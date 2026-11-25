"""
Rate limiting (tiêu chí 7).

  • Mỗi API key tối đa RATE_LIMIT_PER_MINUTE request trong 60 giây (sliding window log).
  • Vượt giới hạn → HTTP 429 kèm header Retry-After.
  • State nằm trong Redis (sorted set) nên mọi worker / instance dùng chung và vẫn còn
    sau khi restart agent.

Các bước ZREMRANGEBYSCORE → ZCARD → ZADD → EXPIRE chạy trong MỘT script Lua để
atomic: nếu chạy rời từng lệnh thì 2 worker có thể cùng thấy "còn chỗ" và cùng thêm
request, làm vượt giới hạn.
"""
import hashlib
import logging
import uuid

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

logger = logging.getLogger("agent.ratelimit")

WINDOW_SECONDS = 60

# KEYS[1] = sorted set của key; ARGV = limit, window(s), member
# Dùng TIME của Redis để mọi worker cùng một đồng hồ.
_LUA = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local window = tonumber(ARGV[2]) * 1000
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, now - window)
local count = redis.call('ZCARD', KEYS[1])
if count >= tonumber(ARGV[1]) then
  local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
  local retry = math.ceil((tonumber(oldest[2]) + window - now) / 1000)
  if retry < 1 then retry = 1 end
  return {0, retry}
end
redis.call('ZADD', KEYS[1], now, ARGV[3])
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]) + 1)
return {1, tonumber(ARGV[1]) - count - 1}
"""

_script = r.register_script(_LUA)


def check_rate_limit(key: str) -> None:
    """Raise 429 nếu `key` vượt giới hạn; raise 503 nếu không nói chuyện được với Redis."""
    # Băm key để secret không nằm trong tên key Redis hay log.
    redis_key = "ratelimit:" + hashlib.sha256(key.encode()).hexdigest()[:32]
    try:
        allowed, value = _script(
            keys=[redis_key],
            args=[settings.rate_limit_per_minute, WINDOW_SECONDS, uuid.uuid4().hex],
        )
    except Exception as exc:
        # Fail closed: không kiểm soát được tốc độ thì không cho đi qua.
        logger.error("rate limiter: Redis không khả dụng: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable") from exc

    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: {settings.rate_limit_per_minute} requests/minute",
            headers={"Retry-After": str(value)},
        )
