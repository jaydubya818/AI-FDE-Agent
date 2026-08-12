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
COPY --chown=ai-fde:ai-fde src ./src
USER ai-fde
CMD ["ai-fde-worker"]
