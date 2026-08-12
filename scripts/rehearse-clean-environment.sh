#!/usr/bin/env bash
set -euo pipefail

rehearsal_project="ai-fde-rehearsal"
postgres_port="${AI_FDE_REHEARSAL_POSTGRES_PORT:-55433}"
minio_api_port="${AI_FDE_REHEARSAL_MINIO_API_PORT:-59010}"
minio_console_port="${AI_FDE_REHEARSAL_MINIO_CONSOLE_PORT:-59011}"

cleanup() {
  docker compose -p "${rehearsal_project}" down --volumes --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

export AI_FDE_POSTGRES_HOST_PORT="${postgres_port}"
export AI_FDE_MINIO_API_HOST_PORT="${minio_api_port}"
export AI_FDE_MINIO_CONSOLE_HOST_PORT="${minio_console_port}"
export AI_FDE_ENV="development"
export AI_FDE_AUTH_MODE="development"
export AI_FDE_DATABASE_URL="postgresql+psycopg://ai_fde_app:ai_fde_app@localhost:${postgres_port}/ai_fde"
export AI_FDE_MIGRATION_DATABASE_URL="postgresql+psycopg://ai_fde_owner:ai_fde_owner@localhost:${postgres_port}/ai_fde"
export AI_FDE_S3_ENDPOINT_URL="http://localhost:${minio_api_port}"
export AI_FDE_S3_ACCESS_KEY="ai-fde-dev"
export AI_FDE_S3_SECRET_KEY="ai-fde-dev-secret"
export AI_FDE_S3_BUCKET="ai-fde-rehearsal-evidence"
export AI_FDE_S3_REGION="us-east-1"
export AI_FDE_S3_USE_WORKLOAD_IDENTITY="false"

cleanup
docker compose -p "${rehearsal_project}" up -d --wait postgres minio

uv sync --frozen
pnpm install --frozen-lockfile
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic upgrade head
uv run alembic check
PYTHONPATH=src uv run python -m ai_fde.seed
uv run pytest
uv run ruff check .
uv run mypy src tests
pnpm lint
pnpm typecheck
pnpm build

echo "Clean-environment rehearsal passed; temporary containers and volumes will now be removed."
