---
status: ready
priority: p1
issue_id: "001"
tags: [factory-engineer, phase-1, phase-2, trust, mission-control, deployment]
dependencies: []
---

# Ship Phase 1 hardening and trusted deployment handoff

## Problem Statement

Factory Engineer has a strong evidence-to-decision foundation and a documented target architecture, but remaining Phase 1 release controls and the Phase 2 Customer Factory Model/readiness/opportunity/package contract are not yet implemented end to end. Mission Control cannot yet retrieve validated deployment intent into its governed Plan-draft path.

## Findings

- Phase 1 still needs CI enforcement, backend/demo contract-parity protection, two trust-state bug fixes, pre-buffer upload limits, and bounded extraction work.
- Phase 2 must preserve exact source provenance, human verification, immutable versions, engagement isolation, staleness, and Mission Control’s sole ownership of execution truth.
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

- [ ] Remaining Phase 1 hardening is implemented and fully verified.
- [ ] Phase 1 is committed, pushed, deployed, and post-deploy verified.
- [ ] Customer Factory Model v1 is versioned, traceable, engagement-scoped, and stale-on-change.
- [ ] FDLC Readiness v1 is evidence-backed and blocker-explainable.
- [ ] Factory Opportunity Portfolio v1 is deterministic and explainable across three engineering fixtures.
- [ ] Factory Deployment Package v1 is approved, immutable, canonicalized, digest-bound, stale/revoked fail-closed, and auditable.
- [ ] Authenticated published-only retrieval is scoped, revocable, audited, and production requirements are explicit.
- [ ] Mission Control validates the package and maps it idempotently into its existing governed Mission/Plan draft path.
- [ ] Hosted demo proves the complete synthetic flow with zero live API calls.
- [ ] Documentation reflects actual implementation state.
- [ ] All Factory Engineer and touched Mission Control checks pass.
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

## Notes

- Do not modify `/Users/jaywest/Documents/ChatGPT/AI-FDE`.
- Do not expose raw customer evidence or create an executable package abstraction.
