.PHONY: setup infrastructure migrate dev seed test lint format acceptance accessibility auth0-contract auth0-readiness terraform-check rehearse demo-rehearsal alpha-rehearsal

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

accessibility: infrastructure migrate seed
	pnpm --dir apps/web test:a11y

auth0-contract: infrastructure migrate
	uv run pytest tests/unit/test_authentication_config.py tests/unit/test_oidc_provider.py tests/isolation/test_oidc_sessions.py

auth0-readiness:
	PYTHONPATH=src uv run python scripts/verify_auth0_configuration.py

terraform-check:
	terraform fmt -check -recursive infrastructure/terraform/design-partner
	terraform -chdir=infrastructure/terraform/design-partner validate

rehearse:
	./scripts/rehearse-clean-environment.sh

demo-rehearsal:
	./scripts/rehearse-sample-demo.sh

alpha-rehearsal:
	AI_FDE_DEMO_TEST_SCRIPT=test:e2e:alpha \
	AI_FDE_DEMO_EVIDENCE_NAME=internal-alpha \
	AI_FDE_ALPHA_SCREENSHOT="$(CURDIR)/output/playwright/internal-alpha/internal-alpha-scorecard.png" \
	./scripts/rehearse-sample-demo.sh
