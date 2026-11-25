# ============================================================
# Production Dockerfile — multi-stage
#
#   Stage 1 (builder): cài dependencies vào một virtualenv /opt/venv
#   Stage 2 (runtime): chỉ copy virtualenv + code; user non-root; HEALTHCHECK
#
# Build:  docker build -t agent .
# Run:    docker run -p 8000:8000 -e AGENT_API_KEY=... agent
# ============================================================

# ── Stage 1: builder ────────────────────────────────────────
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy requirements TRƯỚC code để tận dụng layer cache:
# sửa code không làm cài lại dependencies.
COPY requirements.txt .
RUN pip install -r requirements.txt


# ── Stage 2: runtime ────────────────────────────────────────
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    PORT=8000

# User non-root
RUN groupadd --system app && useradd --system --gid app --home-dir /app --no-create-home app

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app app/ ./app/
COPY --chown=app:app utils/ ./utils/

USER app

EXPOSE 8000

# Liveness: gọi GET /health (không phụ thuộc Redis nên container không bị
# đánh dấu unhealthy chỉ vì Redis chưa lên)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','8000'), timeout=3)" || exit 1

# `exec` để uvicorn thay thế shell và trở thành PID 1 → nhận SIGTERM trực tiếp khi
# `docker stop` và tắt êm (exit code 0). Port đọc từ biến PORT (Render/Railway cấp).
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2 --timeout-graceful-shutdown 8"]
