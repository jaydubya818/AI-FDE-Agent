# Local development environment

AI-FDE is a hybrid repository. Two toolchains are pinned independently and
both must be present before the checks in [CONTRIBUTING.md](../../CONTRIBUTING.md)
can be run.

| Half | Manifests | Pin | Package manager |
| --- | --- | --- | --- |
| Python service, worker, migrations | `pyproject.toml`, `uv.lock` | `requires-python = ">=3.13,<3.14"` | `uv` |
| Operator cockpit (Next.js) | `package.json`, `apps/web/package.json`, `pnpm-lock.yaml` | `packageManager: pnpm@10.32.1` | `pnpm` via `corepack` |

Layout: `src/ai_fde/` holds the modular monolith, `apps/api` and `apps/worker`
are thin Python entrypoints into it, and `apps/web` is the only JavaScript
package. `pnpm-workspace.yaml` covers `apps/web` alone.

## Prerequisites

### Python 3.13 exactly

`requires-python` excludes 3.14. On a machine whose default `python3` is 3.14
or newer, `uv sync` fails to resolve rather than silently building against an
unsupported interpreter. Do not widen the constraint to work around this —
`[tool.mypy] python_version` and `[tool.ruff] target-version` are both pinned
to 3.13 and the lockfile is resolved for it.

`uv` can fetch a suitable interpreter itself:

```sh
uv python install 3.13
uv sync                         # add --python 3.13 if another version is picked
```

`pytest`, `mypy` and `ruff` live in the `dev` dependency group, which `uv sync`
installs by default. `--no-dev` produces a runtime-only environment in which
every command under "Checks" below fails with a missing executable.

### pnpm 10.32.1 via corepack

A system-wide `pnpm` is frequently a different major version than the pinned
one. Let corepack resolve the version recorded in `packageManager`:

```sh
corepack enable
corepack pnpm install --frozen-lockfile
```

Do not run the JavaScript install with `NODE_ENV=production` exported. pnpm
still installs devDependencies in that mode, but `next build` changes
behaviour, so unset it for a development checkout.

## Checks

Run both halves; neither set covers the other.

```sh
# Python
uv run ruff check .
uv run mypy                     # strict; see the py.typed note below
uv run pytest

# JavaScript — all three are thin wrappers around apps/web
corepack pnpm typecheck         # tsc --noEmit
corepack pnpm lint              # eslint . --max-warnings=0
corepack pnpm build             # next build
```

Expected on a clean checkout: ruff clean, mypy clean across 45 source files,
pytest green with the 17 infrastructure-dependent tests skipped, and all
three JavaScript commands exiting 0.

`mypy` is configured with `packages = ["ai_fde"]`, which analyses the
*installed* distribution. That requires the PEP 561 marker at
`src/ai_fde/py.typed`; without it mypy exits 2 having checked nothing rather
than reporting a type error, which is easy to misread as a pass.

## Tests that need infrastructure

The `integration` and `isolation` markers require PostgreSQL and object
storage, provisioned through `testcontainers`, which needs a running Docker
daemon. Without one those tests skip rather than fail, so a green `pytest` on
a laptop does **not** mean the row-level isolation suite ran. Check the
skip count, and see [clean-environment rehearsal](clean-environment-rehearsal.md)
for a full-stack run.

Playwright specs under `apps/web/tests/e2e/` are not part of `pnpm build` and
need both a browser install and a running API. They are invoked explicitly:

```sh
corepack pnpm --dir apps/web exec playwright install
corepack pnpm --dir apps/web test:e2e:golden
```

## Configuration

Copy `.env.example` to `.env`. `Settings` reads the `AI_FDE_` prefix and
defaults to `env=development` / `auth_mode=development`, which trusts a
fixed local operator id and performs no authentication.

Setting `AI_FDE_ENV` to anything other than `development` while leaving
`AI_FDE_AUTH_MODE=development` is rejected at startup, along with a
production deployment that lacks a Bedrock model id, a worker operator id, or
S3 workload identity. Those validators are the only thing standing between a
misconfigured deployment and an unauthenticated API, so treat a
`ValidationError` on boot as a real finding rather than a local annoyance.
