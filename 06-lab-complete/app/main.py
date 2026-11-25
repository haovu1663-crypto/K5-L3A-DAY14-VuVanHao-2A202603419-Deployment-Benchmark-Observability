"""
Production AI Agent — Part 6 Final Project

Chạy:      uvicorn app.main:app --workers 2
Kiểm tra:  python check_production_ready.py

Luồng của POST /ask:
    verify_api_key (401) → check_rate_limit (429) → check_budget (402)
    → gọi LLM → record_cost
"""
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, estimate_tokens, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import redis_healthy
from utils.mock_llm import ask as llm_ask


# ──────────────────────────────────────────────────────────
# Structured logging: mỗi dòng log là 1 JSON object trên một dòng
# ──────────────────────────────────────────────────────────
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "lvl": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Các field thêm qua logger.info(..., extra={"event": ..., "path": ...})
        for field in ("event", "path", "method", "status", "ms"):
            value = getattr(record, field, None)
            if value is not None:
                entry[field] = value
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        # json.dumps không xuống dòng (kể cả exc: ký tự \n được escape) → luôn 1 dòng
        return json.dumps(entry, ensure_ascii=False)


def _setup_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(settings.log_level)


_setup_logging()
logger = logging.getLogger("agent")

START_TIME = time.time()


# ──────────────────────────────────────────────────────────
# Lifecycle / graceful shutdown
# ──────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Graceful shutdown: KHÔNG tự đăng ký handler SIGTERM. uvicorn đã bắt SIGTERM, ngừng nhận
    kết nối mới, chờ request đang chạy xong rồi chạy phần sau `yield` bên dưới và thoát
    với exit code 0. Nếu tự gắn signal.signal(SIGTERM, ...) mà không gọi lại handler cũ thì
    process sẽ không bao giờ tắt.
    """
    app.state.shutting_down = False
    logger.info("startup", extra={"event": "startup"})
    yield
    # Từ lúc này /ready trả 503 để load balancer ngừng gửi request mới tới instance này.
    app.state.shutting_down = True
    logger.info("shutdown", extra={"event": "shutdown"})


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


@app.middleware("http")
async def access_log(request: Request, call_next):
    start = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        logger.info(
            "request",
            extra={
                "event": "request",
                "method": request.method,
                "path": request.url.path,
                "status": status,
                "ms": round((time.perf_counter() - start) * 1000, 1),
            },
        )


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = None  # cho phép client gửi kèm, hiện không dùng


# ──────────────────────────────────────────────────────────
# Health checks
# ──────────────────────────────────────────────────────────
@app.get("/health")
def health():
    """Liveness: luôn 200 khi process còn chạy, KHÔNG phụ thuộc Redis."""
    return {
        "status": "ok",
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "environment": settings.environment,
    }


@app.get("/ready")
def ready():
    """Readiness: 200 khi nhận được traffic; 503 khi đang tắt hoặc Redis không kết nối được."""
    if getattr(app.state, "shutting_down", False):
        raise HTTPException(status_code=503, detail="Shutting down")
    if not redis_healthy():
        raise HTTPException(status_code=503, detail="Redis unavailable")
    return {"ready": True}


# ──────────────────────────────────────────────────────────
# Agent endpoint
# ──────────────────────────────────────────────────────────
@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)  # → 429 (rate limit tính theo API key)
    check_budget()             # → 402 (trước khi tốn tiền gọi LLM)

    answer = llm_ask(body.question)

    record_cost(estimate_tokens(body.question), estimate_tokens(answer))
    return {"question": body.question, "answer": answer}
