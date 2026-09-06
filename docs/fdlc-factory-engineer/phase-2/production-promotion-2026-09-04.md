# Factory Engineer Phase 2 production promotion

## Release decision

**GO — promoted and verified on 2026-09-04.**

The public Factory Engineer hosted demonstration runs the exact approved Phase 2 source revision.
The deployed behavior matches the protected preview, all production acceptance checks passed, and
no release-blocking findings remain. This decision applies only to the browser-local synthetic
demonstration. It is not approval for customer data or the live FastAPI/cloud-service path.

## Release identity

| Field                          | Recorded value                                                                                                       |
| ------------------------------ | -------------------------------------------------------------------------------------------------------------------- |
| Factory Engineer revision      | `196ab3ad7b1114bcbce2ed141bec188505909043` (`196ab3a`)                                                               |
| Factory Engineer branch        | `codex/factory-engineer-evolution`                                                                                   |
| Exact-revision CI              | [Factory Engineer CI run 33924029301](https://github.com/jaydubya818/AI-FDE-Agent/actions/runs/33924029301) — passed |
| Vercel project                 | `ai-fde-agent` / `prj_zLus8PiiOABhesDLkn1Y4HfAdRgS`                                                                  |
| Production deployment          | `dpl_Mm1hRiJWrtcxJRaVdoWyjfCd9Pty`                                                                                   |
| Production build               | `bld_qrivehstr` — READY, Next.js, Turbopack, Node.js 24.x                                                            |
| Production URL                 | <https://ai-fde-agent.vercel.app>                                                                                    |
| Secondary production alias     | <https://ai-fde-agent-jaydubya818.vercel.app>                                                                        |
| Immutable deployment URL       | <https://ai-fde-agent-6i943r544-jaydubya818.vercel.app>                                                              |
| Deployment inspector           | <https://vercel.com/jaydubya818/ai-fde-agent/Mm1hRiJWrtcxJRaVdoWyjfCd9Pty>                                           |
| Artifact created               | `2026-09-04T22:33:21Z` (`2026-09-04 15:33:21 PDT`)                                                                   |
| Primary alias promoted         | `2026-09-04T22:37:41Z` (`2026-09-04 15:37:41 PDT`)                                                                   |
| Vercel output digest           | `prj_zLus8PiiOABhesDLkn1Y4HfAdRgS/3639120bde8f2339f739614749ba80e151f89575f6e5af3bcc3fa7e6fe9d81b1`                  |
| Previous production revision   | `4c97374724dddf183e5266ec70e8561e2317fcb9`                                                                           |
| Previous production deployment | `dpl_EJ3bfZ9tz3Tk3TTFev7DmJAufFY3`                                                                                   |
| Previous immutable URL         | <https://ai-fde-agent-98hn8fuir-jaydubya818.vercel.app>                                                              |
| Mission Control revision       | `59378cbe7773b228c5acace555b0cbd918bbd9d5` (`59378cb`)                                                               |

## Configuration and integrity attestation

The artifact was built from a clean worktree whose `HEAD`, upstream, and GitHub branch all resolved
to `196ab3ad7b1114bcbce2ed141bec188505909043`. Vercel deployment metadata records the same
`gitCommitSha`, `releaseCommit`, and release branch. The Vercel project root is `apps/web`; the
framework is Next.js and the configured runtime is Node.js 24.x.

The production build received exactly these public build settings:

```text
NEXT_PUBLIC_AI_FDE_HOSTED_DEMO=true
NEXT_PUBLIC_AI_FDE_API_URL=https://api.ai-fde.invalid/api
```

The SHA-256 configuration fingerprint over those two lines in that order, newline-delimited and
with a final newline, is
`sha256:17d744a056985e415514e22684c7159872752f2494fbd935946d2e43dadbba5e`.

Vercel exposed both build-setting keys on the artifact but not their secret-redacted value fields.
The values above are bound by the recorded deployment command and by `apps/web/next.config.ts`,
which aborts every Vercel build unless hosted-demo mode is exactly `true` and the API URL is exactly
the invalid sentinel. The successful remote build, rendered safety copy, and zero-API production
tests provide independent runtime confirmation.

The project has zero persistent environment-variable entries. This is intentional for this
artifact: the two public values were supplied only to the exact build. No password protection,
authentication setting, live API address, service credential, or customer-data capability changed.
The protected preview and automatic branch aliases retain their existing protection behavior;
alias protection settings were not reconfigured, and the established primary production URL
remains publicly accessible.

The deployment-package fixture remained byte-identical across the verified Phase 2 checkpoints:

- raw fixture SHA-256:
  `119182c45eaa57b78f4c99335cbbbec117c57d69e48836668cc8e3a583d51e90`;
- canonical package digest:
  `sha256:5a27aaeb78ffe078dbae41146caf1e8884c9621790e6df903dc62e561a127c37`.

## Pre-promotion verification

- Factory Engineer and Mission Control worktrees were clean and matched their remote branches.
- The exact Factory Engineer revision passed CI migrations/check, generated-contract validation,
  Ruff, mypy, Python trust tests, Prettier, TypeScript, ESLint, the fail-closed production build,
  golden-path, internal-alpha, and accessibility gates.
- Protected preview `dpl_8iddgeLFs6gSnQJrhJSW4N9ieUeo` at
  <https://ai-fde-agent-kwa19m2jw-jaydubya818.vercel.app> reported the exact release revision and
  remained READY.
- Vercel project inventory contained no accidental `ai-fde-worktree` project. The five known
  project aliases were present, with no custom or accidental alias.
- The temporary automation bypass used for protected-preview testing was revoked before production
  deployment. The project reported `protectionBypassCount: 0` before and after promotion.
- Mission Control's fixture matched Factory Engineer byte-for-byte and its draft-only importer
  remained pushed, unapplied, authenticated, scoped, and fail closed.

## Manual protected-preview acceptance

**PASS.** The final walkthrough completed the full synthetic Acme story:

`Source Evidence → candidate claims → human verification → verified customer reality → approved
current workflow → factory opportunity portfolio → selected factory line → seven-stage FDLC
readiness → target workflow/factory design → approved immutable deployment package → governed
Mission Control handoff preview`.

The walkthrough confirmed the following trust boundaries:

- source evidence, inference, accepted claims, rejected claims, and contradictions remain distinct;
- opportunity Value, Verifiability, Readiness, Risk, and Priority scores expose their rationale;
- Discover, Design, Assemble, Validate, Deploy, Operate, and Improve each expose evidence-backed
  readiness and blockers;
- Human, Software, and Agent allocation, authority ceilings, verification requirements, and
  consequential human gates are explicit;
- package version, approval, source-version pins, provenance, digest, publication, immutability,
  stale/revoked semantics, and verification basis remain visible;
- Mission Control handoff is authenticated governed ingestion with draft authority only; it does
  not create or claim authority over WorkOrders, Attempts, verification, acceptance, merge,
  release, or deployment.

The preview browser reported no console errors and captured no `/api/` requests during the story.

## Live production acceptance

The browser suites ran against <https://ai-fde-agent.vercel.app>, never localhost or preview:

| Gate           | Result                    | Coverage                                                                                          |
| -------------- | ------------------------- | ------------------------------------------------------------------------------------------------- |
| Golden path    | 1/1 passed in 5.1 seconds | Complete Acme package and governed Mission Control draft preview                                  |
| Internal alpha | 1/1 passed in 8.0 seconds | Three synthetic workflow shapes and program scorecard                                             |
| Accessibility  | 6/6 passed in 4.8 seconds | WCAG A/AA axe checks, mobile navigation, keyboard focus, landmarks/scroll regions, reduced motion |
| Aggregate      | **8/8 passed**            | No application assertion failure                                                                  |

Golden-path and internal-alpha tests each captured browser console errors, every `/api/` request,
failed API responses, and failed API requests. All four collections were empty. This confirms the
hosted-demo zero-live-API invariant for both primary production stories.

The supplemental isolated-browser smoke also passed:

- the canonical URL loaded publicly without an authentication redirect;
- title `Factory Engineer · FDLC`, production heading, `Hosted Demo FDE · synthetic browser demo`,
  and the no-customer-data/no-live-identity/no-cloud-worker/no-model-call boundary rendered;
- the direct Acme engagement URL returned HTTP 200 before and after hard refresh;
- client navigation home and browser-back restoration worked;
- the deliberate missing route returned the expected HTTP 404 page without a runtime exception;
- the document, CSS, nine JavaScript resources, fonts, icon, and RSC resources returned HTTP 200;
- all ten JS/CSS PerformanceResourceTiming entries reported HTTP 200;
- DOM readiness reached `complete`, scripts loaded, an interactive control was enabled, and
  client-side navigation proved the hydrated runtime was functional;
- browser console messages, page errors, `/api/` requests, unexpected 4xx responses, and 5xx
  responses were empty. The only 4xx was the deliberate 404 probe;
- measured vitals were TTFB 35.4 ms, FCP 88 ms, LCP 88 ms, and CLS 0.001.

Vercel error-level and HTTP 500 log queries for the deployment returned no entries after release
traffic. An initial local Playwright launch was denied by the macOS sandbox before navigation; the
identical authorized retry passed all eight product checks. This was verifier infrastructure, not a
production application failure.

## Production state change

Before promotion, both canonical production aliases resolved to the previous Phase 1 deployment.
The production-targeted build automatically assigned the team-scoped alias while `--skip-domain`
kept the primary alias on Phase 1. After artifact attestation, `vercel promote` moved the primary
alias without rebuilding. The final alias inventory contains the same five known aliases; only the
two intended production aliases now resolve to `dpl_Mm1hRiJWrtcxJRaVdoWyjfCd9Pty`. Automatic
branch aliases are unchanged. No accidental project or alias was created.

## Rollback

Rollback target: Phase 1 deployment `dpl_EJ3bfZ9tz3Tk3TTFev7DmJAufFY3`, exact revision
`4c97374724dddf183e5266ec70e8561e2317fcb9`, created at `2026-09-04T18:24:59Z`.

If a release-significant regression is found, stop further changes, preserve browser/network/log
evidence, and run:

```bash
vercel rollback dpl_EJ3bfZ9tz3Tk3TTFev7DmJAufFY3 --yes
```

No rollback was required for this release.

## Mission Control production state

Mission Control importer revision `59378cb` remained pushed and was not applied to a live Convex
environment during this release. Only an automatic frontend preview was built. No Convex deploy,
migration, action, package import, or production-state mutation was executed by this release.

The importer contract remains compatible with the production Factory Engineer package contract.
Import is authenticated, fail closed, idempotent, target-scoped, and draft-only. It cannot create
WorkOrders or claim execution, verification, approval, acceptance, merge, release, or deployment
authority.

## Known limitations

- This production URL is a public synthetic demonstration with browser-local state. It accepts no
  customer evidence and makes no live identity, backend API, cloud worker, or model call.
- The live FastAPI/customer-data path remains unqualified and fail closed pending its external
  identity, workload isolation, model, restore, deletion, secret-rotation, observability, and
  rollback evidence.
- Mission Control retrieval/import is simulated in the public Factory Engineer demo. The compatible
  importer revision is not active in live Convex.
- Vercel has no persistent project environment entries. Every future hosted-demo artifact must
  receive both exact build settings; the checked-in build invariant prevents a silent unsafe
  fallback.
- Automated accessibility gates passed. Manual assistive-technology and contrast review remains a
  customer-launch activity rather than a blocker for this synthetic demonstration.

## Next recommended phase

Do not begin Phase 3 from this release task. The next product-owner decision should be whether to
qualify one controlled design-partner path: production Factory Engineer identity and service
deployment, managed secret rotation, operational monitoring/backups, explicit Mission Control
rollout/spec governance, and draft-only package ingestion. Preserve Mission Control as the sole
owner of Plan approval, WorkOrders, execution, verification, acceptance, merge, release, and
deployment. Do not add autonomous execution or broaden authority in that tranche.
