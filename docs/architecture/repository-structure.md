# Repository Structure

**Status:** Accepted for V1
**Date:** 2026-08-08

## Goals

- Keep one founder productive.
- Make domain boundaries visible.
- Share one Python domain package between API and worker.
- Keep generated contracts and fixtures versioned.
- Prevent customer evidence, secrets, and runtime data from entering Git.

## Proposed Layout

```text
ai-fde/
├── README.md
├── AGENTS.md
├── CONTRIBUTING.md
├── Makefile
├── pyproject.toml
├── pnpm-workspace.yaml
├── package.json
├── .env.example
├── .gitignore
│
├── apps/
│   ├── web/                    # Next.js Operator Cockpit
│   ├── api/                    # Thin FastAPI entrypoint
│   └── worker/                 # Thin persistent-worker entrypoint
│
├── src/ai_fde/                 # Shared Python application package
│   ├── domain/                 # Pure entities, value objects, invariants
│   ├── application/            # Commands, queries, jobs, stage gates
│   ├── modules/
│   │   ├── engagements/
│   │   ├── evidence/
│   │   ├── knowledge/
│   │   ├── operating_model/
│   │   ├── processes/
│   │   ├── decisioning/
│   │   ├── economics/
│   │   ├── artifacts/
│   │   ├── orchestration/
│   │   └── audit/
│   ├── agents/                 # Post-V1 runtime, context builders, policies
│   ├── adapters/               # DB, object store, extraction, parsers
│   └── telemetry/
│
├── contracts/                  # OpenAPI, JSON Schema, generated clients
├── prompts/                    # Versioned prompts; no hidden domain rules
├── migrations/                 # Ordered PostgreSQL migrations
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contract/
│   ├── acceptance/
│   └── isolation/
│
├── fixtures/acme/              # Synthetic source evidence and expected truth
├── evals/accounts-payable/     # Golden, edge, adversarial, regression cases
├── examples/work-order-target/ # Post-V1 coding-agent target repository
├── generated/                  # Local generated artifacts; ignored by default
├── docs/
├── infrastructure/             # Local Docker and later deployment definitions
└── scripts/                    # Small, documented developer operations
```

## Dependency Direction

```text
apps -> application -> domain
                    -> module interfaces
adapters ----------> module interfaces
agents ------------> application tools
```

The domain imports no web framework, ORM, model SDK, storage SDK, or UI code. Adapters depend inward on interfaces. Application services are the only mutation path used by the API, worker, UI-backed commands, and agent tools.

## File Rules

- Do not create empty package trees before their phase begins.
- Keep tests beside the repository root by test type for cross-module flows.
- Keep prompt versions and output schemas together by agent capability.
- Generate TypeScript API clients from the OpenAPI contract.
- Never commit `.env`, runtime databases, uploaded evidence, sandbox worktrees, credentials, or real customer exports.
- Synthetic Acme fixtures must be clearly labeled and license-safe.

## Initial Developer Commands

The implementation should converge on these stable commands:

```text
make setup
make dev
make migrate
make seed
make test
make lint
make acceptance
```

Each command must be non-destructive by default and documented before use.
