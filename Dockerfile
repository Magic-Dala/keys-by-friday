FROM ghcr.io/astral-sh/uv:0.11.24 AS uv

FROM python:3.12-slim

COPY --from=uv /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    PATH="/app/.venv/bin:$PATH" \
    HOME=/tmp \
    PORT=8080

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY backend ./backend
COPY rental_agent ./rental_agent

RUN uv sync --frozen --no-dev --extra backend \
    && useradd --system --uid 10001 --no-create-home appuser

USER appuser

CMD ["/bin/sh", "-c", "exec uvicorn backend.app.main:app --host 0.0.0.0 --port \"${PORT:-8080}\""]
