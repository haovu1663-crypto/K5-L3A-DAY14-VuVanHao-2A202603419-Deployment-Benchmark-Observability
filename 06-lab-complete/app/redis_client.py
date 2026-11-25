"""
Kết nối Redis dùng chung cho rate limiter và cost guard.

- Đọc REDIS_URL từ config.
- KHÔNG ping Redis lúc import: `redis.from_url` chỉ tạo client, chưa kết nối, nên app
  vẫn khởi động được khi Redis chưa sẵn sàng (container cần start không có Redis).
- Timeout ngắn để GET /ready không treo khi Redis chết.
"""
import logging

import redis

from app.config import settings

logger = logging.getLogger("agent.redis")

r = redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=1,
    socket_timeout=2,
)


def redis_healthy() -> bool:
    """Dùng cho GET /ready: ping được Redis thì True, mọi lỗi kết nối thì False."""
    try:
        return bool(r.ping())
    except Exception:
        return False
