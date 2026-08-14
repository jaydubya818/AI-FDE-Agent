FROM ghcr.io/astral-sh/uv:0.8.15 AS uv
FROM python:3.13.7-slim-bookworm AS builder

COPY --from=uv /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_DEV=1
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --locked --no-editable

FROM python:3.13.7-slim-bookworm AS runtime
RUN groupadd --system --gid 10001 ai-fde \
    && useradd --system --uid 10001 --gid ai-fde --home-dir /app ai-fde
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH=/app PYTHONUNBUFFERED=1
COPY --from=builder --chown=ai-fde:ai-fde /app/.venv /app/.venv
COPY --chown=ai-fde:ai-fde apps/api ./apps/api
COPY --chown=ai-fde:ai-fde alembic.ini ./alembic.ini
COPY --chown=ai-fde:ai-fde migrations ./migrations
COPY --chown=ai-fde:ai-fde scripts/bootstrap_production_database.py ./scripts/bootstrap_production_database.py
COPY --chown=ai-fde:ai-fde src ./src
USER ai-fde
EXPOSE 8000
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--proxy-headers", "--forwarded-allow-ips", "*"]
