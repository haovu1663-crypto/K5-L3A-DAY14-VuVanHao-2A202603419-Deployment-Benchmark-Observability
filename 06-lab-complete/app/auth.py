"""
API Key authentication (tiêu chí 6).

  • Client gửi header  X-API-Key: <key>
  • Key phải trùng biến môi trường AGENT_API_KEY
  • Thiếu hoặc sai key → HTTP 401 (không phải 403 hay 422)

Dùng auto_error=False rồi tự raise 401: nếu để FastAPI tự xử lý header bắt buộc,
nó sẽ trả 403/422 khi thiếu header.
"""
import secrets

from fastapi import HTTPException, Security
from fastapi.security.api_key import APIKeyHeader

from app.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: str | None = Security(api_key_header)) -> str:
    """Dependency cho FastAPI — dùng trong /ask: Depends(verify_api_key)."""
    # Nếu server chưa cấu hình AGENT_API_KEY thì từ chối tất cả (không bao giờ mở toang).
    # compare_digest: so sánh thời gian không đổi, tránh lộ key qua timing.
    if (
        not api_key
        or not settings.agent_api_key
        or not secrets.compare_digest(api_key.encode(), settings.agent_api_key.encode())
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Send header: X-API-Key: <key>",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return api_key
