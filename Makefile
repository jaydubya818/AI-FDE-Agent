.PHONY: setup infrastructure migrate dev seed test lint format acceptance

setup:
	uv sync
	pnpm install

infrastructure:
	docker compose up -d postgres minio

migrate:
	uv run alembic upgrade head

dev:
	pnpm dev

seed:
	PYTHONPATH=src uv run python -m ai_fde.seed

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run mypy src tests
	pnpm lint
	pnpm typecheck

format:
	uv run ruff format .
	pnpm --dir apps/web exec prettier --write .

acceptance:
	uv run pytest tests/acceptance tests/isolation
