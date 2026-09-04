---
status: ready
priority: p1
issue_id: "001"
tags: [factory-engineer, phase-1, phase-2, trust, mission-control, deployment]
dependencies: []
---

# Ship Phase 1 hardening and trusted deployment handoff

## Problem Statement

Phase 1 is released and the Phase 2 Customer Factory Model, readiness, opportunity,
deployment-package, authenticated-retrieval, and governed Mission Control draft-import paths are
implemented. The remaining work is to record the final repository commits, push both branches,
and verify the deployed Factory Engineer revision.

## Findings

- Phase 1 added CI enforcement, backend/demo contract-parity protection, two trust-state bug fixes, pre-buffer upload limits, and bounded extraction work.
- Phase 2 preserves exact source provenance, human verification, immutable versions, engagement isolation, staleness, and Mission Control’s sole ownership of execution truth.
- Authenticated package retrieval is the approved primary trust bootstrap; portable signed files remain secondary/future.
- The hosted demo must remain deterministic, synthetic, and incapable of live API or Mission Control traffic.

## Proposed Solutions

### Option 1: Incremental vertical slices

Implement and verify Phase 1 hardening first, ship it, then add the Customer Factory Model, readiness, opportunities, package, retrieval, Mission Control adapter, and demo in dependency order.

**Pros:** Small review boundaries, safest migrations, failures localize cleanly.

**Cons:** More commits and two deployment checkpoints.

**Effort:** Large

**Risk:** Medium

### Option 2: One combined implementation

Implement every requirement before the first commit/deployment.

**Pros:** One final release.

**Cons:** Excessive blast radius, poor rollback, difficult review.

**Effort:** Large

**Risk:** High

## Recommended Action

Use incremental vertical slices. Ship the completed Phase 1 foundation and hardening as the first coherent release, then implement Phase 2 on the same feature branch with separate backend, integration, and UI commits. Never merge or deploy a failing intermediate state.

## Technical Details

**Factory Engineer:** models, migrations, services, API routes/schemas, hosted-demo adapter, cockpit UI, CI, tests, and Phase 2 documentation.

**Mission Control:** authenticated retrieval/validation adapter and existing governed Mission/Plan draft mapping only; no new executable abstraction.

## Acceptance Criteria

- [x] Remaining Phase 1 hardening is implemented and fully verified.
- [x] Phase 1 is committed, pushed, deployed to a Vercel preview, and fully verified by local and GitHub release gates.
- [x] Customer Factory Model v1 is versioned, traceable, engagement-scoped, and stale-on-change.
- [x] FDLC Readiness v1 is evidence-backed and blocker-explainable.
- [x] Factory Opportunity Portfolio v1 is deterministic and explainable across three engineering fixtures.
- [x] Factory Deployment Package v1 is approved, immutable, canonicalized, digest-bound, stale/revoked fail-closed, and auditable.
- [x] Authenticated published-only retrieval is scoped, revocable, audited, and production requirements are explicit.
- [x] Mission Control validates the package and maps it idempotently into its existing governed Mission/Plan draft path.
- [x] Hosted demo proves the complete synthetic flow with zero live API calls.
- [x] Documentation reflects actual implementation state.
- [x] All Factory Engineer and touched Mission Control checks pass.
- [ ] Final commits are pushed and the deployed application passes post-release smoke tests.

## Work Log

### 2026-09-04 - Authorized execution

**By:** Codex

**Actions:**
- Parsed the Phase 2 trusted deployment handoff brief.
- Confirmed the existing clean feature worktree and branch.
- Selected incremental vertical slices to preserve rollback and reviewability.

**Learnings:**
- Requirements are explicit; no additional product discovery is required before implementation.
- Authenticated retrieval resolves the highest-risk integration decision from the architecture phase.

### 2026-09-04 - Phase 2 implementation verification

**By:** Codex

**Actions:**
- Implemented and independently reviewed the Factory Engineer model, readiness, opportunity,
  package, authenticated retrieval, and synthetic handoff flow.
- Implemented Mission Control's bounded retrieval, full contract validation, target reauthorization,
  idempotent receipt, and Mission/Plan draft-only mapping.
- Passed both repositories' migration, static, contract, unit/integration, security, production-build,
  golden-path, internal-alpha, and accessibility gates.

**Learnings:**
- Full package provenance is validated at the trust boundary, while Mission Control persists only
  mapped draft intent, selected lineage IDs, the authenticated package URL, and bounded receipt
  metadata.
- Production promotion should remain separate from the requested preview deployment.

## Notes

- Do not modify `/Users/jaywest/Documents/ChatGPT/AI-FDE`.
- Do not expose raw customer evidence or create an executable package abstraction.

### 2026-09-04 - Phase 1 release checkpoint

**By:** Codex

**Actions:**
- Committed Phase 1 as `af0196f` and pushed `codex/factory-engineer-evolution`.
- Verified the exact commit in an isolated worktree and disposable PostgreSQL database: 55 Python tests, migrations/check, Ruff, mypy, generated contract, actionlint, Prettier, TypeScript, ESLint, production Webpack build, golden path, internal alpha, and six accessibility tests all passed.
- Deployed the exact commit to Vercel preview `dpl_Cg4BhqD5Wo8wymL3peSvcZrdz49J`.
- Confirmed GitHub Actions run `33918334562` passed the complete trust, contract, native Turbopack build, browser, and accessibility pipeline.

**Learnings:**
- Local Turbopack cannot bind its internal compiler port in this sandbox; the equivalent Webpack production build passed locally and Vercel's Turbopack build passed remotely.
- Phase 2 migrations require isolated databases when verifying an earlier checkpoint.
