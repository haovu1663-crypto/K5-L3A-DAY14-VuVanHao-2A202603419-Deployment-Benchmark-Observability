"""
Cost guard (tiêu chí 8).

  • Cộng dồn chi phí LLM (tính theo token) vào Redis, theo ngày và theo tháng.
  • Tổng chi phí vượt DAILY_BUDGET_USD hoặc MONTHLY_BUDGET_USD → HTTP 402.
  • Fail closed: không đọc được Redis thì trả 503, không để request đi qua mà không đếm tiền.

Lưu ý: check_budget() chạy trước, record_cost() chạy sau khi gọi LLM, nên request đang
chạy song song có thể làm tổng vượt budget một chút. Muốn chặt hơn thì cần "đặt trước"
(reserve) chi phí ước tính trước khi gọi — đánh đổi cho bài này, ghi ở đây cho rõ.
"""
import logging
import time

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

logger = logging.getLogger("agent.cost")

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006

_DAY_TTL = 2 * 24 * 3600
_MONTH_TTL = 35 * 24 * 3600


def _keys() -> tuple[str, str]:
    now = time.gmtime()
    return (
        f"cost:day:{time.strftime('%Y-%m-%d', now)}",
        f"cost:month:{time.strftime('%Y-%m', now)}",
    )


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    day_key, month_key = _keys()
    try:
        day_used = float(r.get(day_key) or 0.0)
        month_used = float(r.get(month_key) or 0.0)
    except Exception as exc:
        logger.error("cost guard: Redis không khả dụng: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable") from exc

    if day_used >= settings.daily_budget_usd:
        raise HTTPException(
            status_code=402,
            detail={"error": "Daily budget exceeded", "used_usd": round(day_used, 6),
                    "budget_usd": settings.daily_budget_usd},
        )
    if month_used >= settings.monthly_budget_usd:
        raise HTTPException(
            status_code=402,
            detail={"error": "Monthly budget exceeded", "used_usd": round(month_used, 6),
                    "budget_usd": settings.monthly_budget_usd},
        )


def estimate_tokens(text: str) -> int:
    """Ước lượng thô ~4 ký tự / token (mock LLM không trả số token thật)."""
    return max(1, len(text) // 4)


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng, trả về chi phí request."""
    cost = (input_tokens / 1000) * PRICE_INPUT_PER_1K + (output_tokens / 1000) * PRICE_OUTPUT_PER_1K
    day_key, month_key = _keys()
    try:
        pipe = r.pipeline()
        pipe.incrbyfloat(day_key, cost)
        pipe.expire(day_key, _DAY_TTL)
        pipe.incrbyfloat(month_key, cost)
        pipe.expire(month_key, _MONTH_TTL)
        pipe.execute()
    except Exception as exc:
        # Request đã phục vụ xong; chỉ ghi log lỗi đếm tiền, không làm hỏng response.
        logger.error("cost guard: không ghi được chi phí: %s", type(exc).__name__)
    return cost
