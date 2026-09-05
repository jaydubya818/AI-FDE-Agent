FROM ghcr.io/astral-sh/uv:0.8.15 AS uv
FROM python:3.13.7-slim-bookworm AS builder

COPY --from=uv /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_DEV=1
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --locked --no-editable

FROM python:3.13.7-slim-bookworm AS rds-ca
ARG AWS_RDS_GLOBAL_BUNDLE_SHA256=e5bb2084ccf45087bda1c9bffdea0eb15ee67f0b91646106e466714f9de3c7e3
RUN python -c "import urllib.request; urllib.request.urlretrieve('https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem', '/tmp/aws-rds-global-bundle.pem')" \
    && echo "${AWS_RDS_GLOBAL_BUNDLE_SHA256}  /tmp/aws-rds-global-bundle.pem" | sha256sum --check --strict

FROM python:3.13.7-slim-bookworm AS runtime
RUN groupadd --system --gid 10001 ai-fde \
    && useradd --system --uid 10001 --gid ai-fde --home-dir /app ai-fde \
    && install -d --mode=0555 /opt/ai-fde/certs
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    AI_FDE_RDS_CA_BUNDLE_PATH=/opt/ai-fde/certs/aws-rds-global-bundle.pem \
    AI_FDE_RDS_CA_BUNDLE_SHA256=sha256:e5bb2084ccf45087bda1c9bffdea0eb15ee67f0b91646106e466714f9de3c7e3
COPY --from=rds-ca --chmod=0444 /tmp/aws-rds-global-bundle.pem /opt/ai-fde/certs/aws-rds-global-bundle.pem
COPY --from=builder --chown=ai-fde:ai-fde /app/.venv /app/.venv
COPY --chown=ai-fde:ai-fde src ./src
USER ai-fde
CMD ["ai-fde-worker"]
