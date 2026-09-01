# Nightly backlog

Findings from automated nightly maintenance that were not fixed in the run
that found them, plus research that was ruled out so later runs stop
re-deriving it. Product and delivery work lives in
[docs/backlog/initial-backlog.md](backlog/initial-backlog.md) instead.

## Open

- [ ] 2026-09-01 — No continuous integration of any kind — `.github/workflows/` does not exist, so `ruff`, `mypy`, `pytest`, `tsc`, `eslint` and `next build` only ever run on a contributor's machine, and CONTRIBUTING.md's "make sure the project still builds" is unenforced.
- [ ] 2026-09-01 — The JavaScript half has no unit test runner — `apps/web` ships only Playwright e2e specs, which need a browser install and a running API, so `lib/api.ts` and `lib/hosted-demo.ts` have no test that runs during a normal check cycle.
- [ ] 2026-09-01 — Operator de-authorization is not immediate — `oidc_allowed_emails` is checked in `enroll_operator` at login only, so removing an operator from the allowlist leaves any live session valid for up to `session_ttl_seconds` (12h default). Revoking `OperatorSession` rows on allowlist change would close it.
- [ ] 2026-09-01 — Dead defensive check in `verify_id_token` — `isinstance(subject, str)` is unreachable because joserfc's claims registry already rejects a non-string `sub`. The sibling check on `email` is load-bearing and is now tested. Left in place as defence in depth; remove only alongside a deliberate decision about which layer owns claim typing.
- [ ] 2026-09-01 — Service-layer coverage is gated on Docker — `modules/workflows/service.py` (15%), `knowledge/jobs.py` (16%), `artifacts/service.py` (19%) and `economics/service.py` (25%) are reachable only through the `integration`/`isolation` suites, which skip without a Docker daemon. Their pure helpers could be separated to make the arithmetic testable in isolation; `economics` is money math and is the one worth doing first.

## Closed

Nothing yet. This file was created on 2026-09-01, so there is no prior open
item for this run to have closed.

## Checked, not applicable

- 2026-09-01 — `next` advisories — `apps/web` resolves `next@16.3.0` in `pnpm-lock.yaml`. The highest real floor is 16.2.11 (GHSA-89xv-2m56-2m9x, GHSA-p9j2-gv94-2wf4, GHSA-6gpp-xcg3-4w24, GHSA-m99w-x7hq-7vfj, all 2026-07-22, all confirmed HTTP 200). 16.3.0 clears every one; 64 advisories enumerated, 0 affecting.
- 2026-09-01 — `sharp` advisories — resolves to 0.35.3; the only floor is 0.35.0 (GHSA-f88m-g3jw-g9cj). Clean.
- 2026-09-01 — `postcss` advisories — **the declared range is misleading here.** `apps/web/package.json` declares `^8.5.6`, which is below the 8.5.23 floor (GHSA-fxqj-rqcc-2cmp) and looks vulnerable. `pnpm-lock.yaml` actually resolves 8.5.23 and 8.5.26, both clean. Always read the lockfile, not the manifest.
- 2026-09-01 — `esbuild` GHSA-gv7w-rqvm-qjhr — withdrawn upstream (`withdrawn_at` set). Not actionable in any repo.
- 2026-09-01 — `GHSA-2xp9-vwfh-vxw4` / "CVE-2026-75604" Next.js RCE — does not exist. Authenticated `GET /advisories/GHSA-2xp9-vwfh-vxw4` returns HTTP 404. Reported by automation elsewhere; do not act on it.
- 2026-09-01 — Python dependency sweep — all 29 runtime and dev packages in `uv.lock` enumerated against `ecosystem=pip`. Only `pillow` was affected. `fastapi`, `starlette`, `uvicorn`, `authlib`, `joserfc`, `cryptography`, `pypdf`, `lxml`, `sqlalchemy`, `urllib3`, `requests`, `python-multipart` and `mako` are all above their floors at the resolved versions.
- 2026-09-01 — Route authorization audit — all 36 API routes read with their full signatures. Every one of the 28 routes carrying `{engagement_id}` takes an `EngagementRead`/`Write`/`Owner` dependency; the read/write/owner split matches the mutation each performs. No unguarded engagement route. `GET /internal-alpha/scorecard` and `GET /engagements` are deliberately cross-engagement and rely on row-level security under `operator_session`.
- 2026-09-01 — Committed-credential sweep — every blob across all 32 commits and all refs checked for `.env`/`.pem`/`.key`/`.npmrc`/`.mcp.json` filenames and for AWS, GitHub, OpenAI, Slack, JWT and PEM content patterns. Nothing found. `.env.example` holds only localhost placeholders and the MinIO development credentials that match the `Settings` defaults; it is not a leak.
- 2026-09-01 — Repository hygiene — no `node_modules/`, `.venv/`, `__pycache__/` or `*.tgz` tracked in git. `.gitignore` covers all of them and predates the files it covers.
- 2026-09-01 — Whack-a-mole check — the 32-commit history shows no repeated same-class fix to any file by any author, so no patch in this run was papering over a structural floor.
