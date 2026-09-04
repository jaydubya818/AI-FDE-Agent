---
title: "feat: Evolve AI-FDE into FDLC Factory Engineer"
type: feat
status: active
date: 2026-09-04
owners:
  - product-owner
  - factory-engineer
---

# Evolve AI-FDE into FDLC Factory Engineer

## Overview

Evolve the working AI-FDE internal alpha into the FDLC Factory Deployed Engineer without replacing its evidence-to-decision architecture. The product will become the evidence-backed customer-understanding, factory-design, readiness, deployment-intent and field-learning layer between the FDLC methodology and Mission Control governed execution.

The work is intentionally incremental. Each phase produces a usable vertical slice, migrations are additive, current APIs remain compatible, approved records remain immutable, and new customer data cannot be enabled merely because code exists.

## Problem statement

AI-FDE proves a valuable vertical slice—source evidence → candidate claims → human assertions → workflows → economics → seven artifacts—but its current domain is too narrow for a long-lived FDLC deployment product. It lacks a versioned Customer Factory Model, opportunity/factory-line/readiness aggregates, a package approval/handoff contract, outcomes and privacy-safe field learning. At the same time, Mission Control already owns the downstream execution state that Factory Engineer must not duplicate.

The brief contains two tempting but unsafe shortcuts:

- treating one engagement stage as the lifecycle for every factory line;
- treating uploaded customer “evidence” as the same object as Mission Control verifier evidence.

This plan rejects both. It also uses the Guide’s L0–L5 autonomy model and keeps action authority separate, rather than creating an overlapping A0–A5 scale.

## Product outcome

A human Factory Deployed Engineer can build and approve an evidence-backed Customer Factory Model, select a defensible lighthouse factory line, design and validate it against FDLC gates, approve an immutable deployment package, hand it to Mission Control as a draft proposal, observe governed delivery without owning execution state, measure realized outcomes, and turn reviewed/de-identified field patterns into capability candidates.

## Non-goals

- No rewrite of FastAPI, PostgreSQL, the worker, storage or identity into Next.js.
- No graph database or internal microservice decomposition.
- No generic uncited chat/RAG interface.
- No connector write actions in the initial connector architecture.
- No shared Factory Engineer/Mission Control database or direct execution controls.
- No replication of WorkOrders, Attempts, leases, sandboxes, verification, acceptance or release state.
- No dependency on the proposed FDLC Enterprise product for V1.
- No automatic cross-customer learning or capability publication.
- No mass rename of packages, tables, env vars, telemetry identifiers or persisted historical delivery-method identifiers.
- No new autonomous agent infrastructure until the domain workflows and evaluations are stable.

## Research and constraints

### Local implementation evidence

- Current trust and product boundary: [README.md](../../README.md).
- Durable schema: [models.py](../../src/ai_fde/models.py).
- Exact provenance and job processing: [knowledge/jobs.py](../../src/ai_fde/modules/knowledge/jobs.py).
- Workflow approval/allocation: [workflows/service.py](../../src/ai_fde/modules/workflows/service.py).
- Reproducible economics: [economics/service.py](../../src/ai_fde/modules/economics/service.py).
- Artifact gating/version pins: [artifacts/service.py](../../src/ai_fde/modules/artifacts/service.py).
- Conservative invalidation: [lifecycle.py](../../src/ai_fde/modules/lifecycle.py).
- Production fail-closed settings: [config.py](../../src/ai_fde/config.py).
- Current audit: [current-state-audit.md](../fdlc-factory-engineer/current-state-audit.md).
- Target architecture: [target-product-architecture.md](../fdlc-factory-engineer/target-product-architecture.md).
- Domain model: [domain-model.md](../fdlc-factory-engineer/domain-model.md).
- UX map: [ux-information-architecture.md](../fdlc-factory-engineer/ux-information-architecture.md).
- Mission Control seam: [mission-control-integration-contract.md](../fdlc-factory-engineer/mission-control-integration-contract.md).

### Institutional learning

Mission Control’s `docs/solutions/build-errors/missing-convex-schema-contracts-ci-20260730.md` records that consumer changes without matching persisted schema, validators, indexes, generated types and CI broke builds. Any deployment-package import must land as one coherent Mission Control contract slice. Factory Engineer must not ship an integration UI against a planned-only backend.

### Spec-flow corrections incorporated

- Engagement administration, FDLC readiness, factory-line lifecycle, package lifecycle and MC execution state are separate.
- Source evidence and MC verification evidence use separate names and contracts.
- Claim support, human disposition and freshness are orthogonal.
- Empty states distinguish not assessed, no data, none detected, not applicable and true zero.
- Concurrent decisions use expected versions/ETags and a visible conflict-recovery path.
- Stale packages after handoff create an advisory; MC policy—not FE—decides hold/continue/cancel.
- Outcome values carry metric definition, unit, source, window, scope, version and quality classification.
- Cross-customer signals remain local until generalized, de-identified and human-reviewed.

## Prerequisite ADRs

Create and approve these before the associated schema phase:

1. Product boundaries and canonical identifiers.
2. Source evidence versus execution evidence terminology.
3. Orthogonal claim state model and review correction semantics.
4. Engagement administration versus factory-line/readiness lifecycle.
5. Version dependencies and staleness propagation.
6. Guide L0–L5 autonomy plus per-action authority grants.
7. Deployment package schema, approval, idempotency and MC mapping.
8. Field-signal privacy, generalization and productization authority.

Phase 1 does not require these decisions to be encoded in database schema.

## Delivery phases

### Phase 0 — Audit and baseline

Status: complete in this branch.

Deliverables:

- current-state audit and production-readiness truth;
- preserve/refactor/add matrix;
- ecosystem architecture and domain model;
- UX information architecture;
- Mission Control contract proposal;
- full local baseline with PostgreSQL/MinIO so isolation tests do not skip;
- public deployment observation and deployed acceptance checks.

Exit criteria:

- [x] All four repositories inspected at pinned commits/state.
- [x] Existing trust, persistence, worker, identity, telemetry, lifecycle, demo and tests documented.
- [x] 47 Python tests pass with PostgreSQL-backed tests included.
- [x] Frontend typecheck and lint pass.
- [x] Public alpha, golden and a11y suites have current passing observations; the transient misconfigured build is recorded.
- [ ] Exact default `next build` rerun in an environment where Turbopack process/port creation is permitted.

### Phase 1 — Product alignment and release hardening

Goal: make the existing product clearly belong to FDLC and eliminate avoidable demo/configuration drift without changing domain behavior.

Status in this branch: complete. The public alignment tranche, generated backend/demo contract parity, PostgreSQL-backed CI enforcement, worker/review correctness fixes, bounded upload handling, extraction budgets, and the hosted-demo Vercel build invariant are implemented as one release gate.

Tasks:

- Centralize public product name, concise description, north star and ecosystem URLs in `apps/web/lib/product.ts`.
- Update public metadata, wordmark/copy and minimal FDLC token aliases; retain internal `AI-FDE` identifiers where compatibility matters.
- Add accessible Framework, Guide and Mission Control navigation without converting the cockpit into the marketing site.
- Add a curated Guide topic registry with canonical links and last-reviewed metadata.
- Add explicit Source Evidence terminology in documentation and new UI copy where it is not a breaking API identifier.
- Make a Vercel build fail when hosted-demo mode or its invalid fallback API URL is absent.
- Add backend-versus-hosted-demo contract parity tests before extending demo states.
- Add CI that starts PostgreSQL/MinIO, applies/checks migrations, fails when trust tests skip, and runs lint/type/build/browser/a11y checks.
- Fix the recovered-extraction scorecard and evidence-review completion bugs as separate, tested patches.
- Enforce upload/request size before full buffering and add per-job segment/provider-call/token budgets before sanitized evidence.

Acceptance criteria:

- [x] Public UI says “FDLC Factory Deployed Engineer” / “Factory Engineer”; package names, env vars and persisted historical values remain compatible.
- [x] Ecosystem links are centralized, external-link behavior is accessible, and no Guide text is copied into customer state.
- [x] Vercel production builds without explicit demo safety settings fail before compilation/deployment.
- [x] Demo and backend fixture contracts cannot drift silently.
- [x] CI cannot pass with PostgreSQL isolation tests skipped.
- [x] Existing synthetic golden, alpha and accessibility suites pass unchanged or with intentional public-copy updates.
- [x] No core workflow, approval, economics or artifact behavior changes as part of branding.

Verification on 2026-09-04: actionlint, the generated-contract check, focused Ruff and mypy, frontend typecheck/lint, 10 PostgreSQL-backed hardening tests, and `git diff --check` passed. The production-configured Webpack fallback build passed; the negative build-guard case failed before compilation as intended; golden path passed 1/1; internal-alpha passed 1/1; accessibility passed 6/6 including mobile navigation; and hosted-demo acceptance tests observed zero `/api/` requests. The exact default Turbopack build remains subject to the Phase 0 sandbox limitation recorded above and is enforced in GitHub CI.

Rollback: revert public constants/copy/tokens and the build guard independently. No schema or stored data changes occur.

### Phase 2 — Trust-model and Customer Factory Model foundation

Goal: turn the flat verified projection into a versioned customer model while strengthening source/claim semantics.

Dependencies: ADRs 1–5; Phase 1 contract/CI foundation.

Tasks:

- Add stable source evidence identity/version and freshness while preserving `EvidenceAsset` routes as compatibility views.
- Introduce orthogonal claim support, human disposition and freshness; backfill current accepted/rejected/deferred history.
- Add first-class unknown, assumption, multi-source support and general contradiction records.
- Add correction/supersession decisions; require reasons for material dispositions.
- Add expected-version concurrency to material review operations.
- Add `CustomerFactoryModel` and immutable version snapshots with typed element/relation versions.
- Initially support the engineering types needed by modernization, security and test fixtures; avoid a full universal ontology.
- Continue serving the flat operating-model endpoint as a projection.
- Add explicit artifact dependencies/cause records; keep broad invalidation until parity proves selective behavior.
- Extend export/delete/RLS/object-store/retrieval tests before enabling new records for customer data.

Acceptance criteria:

- [ ] No model assessment can set human verification.
- [ ] Every material model field/relation resolves to verified claims or an explicit approved assumption.
- [ ] Approved model versions reject mutation; changes create a new version and decision.
- [ ] Cross-engagement references fail at service and database boundaries.
- [ ] Contradictions and unknowns remain visible and block configured gates.
- [ ] Existing operating-model clients and golden path remain functional.
- [ ] Change-impact output names every stale dependent and cause.

Rollback: new tables/views are additive. Disable new endpoints/UI and retain old projections; do not destructively down-migrate approved customer records.

#### Phase 2 trusted-handoff release slice (2026-09-04)

The authorized Phase 2 brief deliberately implements a launchable vertical slice across several later target phases without claiming the entire long-range model above is complete.

Implemented in this slice:

- [x] Additive versioned Customer Factory Model snapshots with typed evidence/verified-claim/approved-input/assumption provenance.
- [x] Conservative stale-on-material-change hooks while preserving the existing operating-model projection.
- [x] Explainable deterministic opportunity portfolio with modernization, test-remediation, and security-remediation fixtures plus one human-selected line.
- [x] Seven-stage evidence/blocker/next-action readiness with final readiness pinned to the selected opportunity.
- [x] Explicit immutable package state machine, server-bound issuer, exact source/approval binding, and `fdlc-canonical-json/v1` SHA-256 digest.
- [x] Scoped, expiring, revocable, published-only service retrieval with RLS and audit events.
- [x] Mission Control retrieval/validation/preview/import adapter that creates only governed Mission/Plan drafts and preserves local feature/spec gates.
- [x] Browser-local synthetic proof flow with zero live API or Mission Control calls.

Deliberately deferred from the broader target plan:

- stable `SourceEvidence`/`Claim` identity split and generalized ClaimVersion/Unknown/Assumption/DecisionRecord aggregates;
- selective dependency graph, formal waiver aggregate, and standalone FactoryLine/FactoryDesign aggregates;
- production identity federation/workload identity, automatic secret rotation, connector platform, outcome synchronization, and reusable capability publication.

Release rule: Phase 2 may ship only when both repositories pass their current migration/static/test suites, the shared package fixture/digest agree cross-language, the hosted golden-path and accessibility scripts pass with zero network calls, and the exact commits are pushed before deployment.

### Phase 3 — Structured discovery and read-only connectors

Goal: acquire a more accurate customer model without creating a write-capable integration surface.

Dependencies: versioned source evidence; connector authority/privacy ADR addendum.

Tasks:

- Add structured interview sessions, role templates, attributed responses, follow-up questions, unknowns and claim proposals.
- Define connector/installation/sync/source-version contracts, credential references, consent and revocation.
- Implement one read-only lighthouse connector chosen from customer need—not a generic connector framework for every vendor.
- Add freshness, cursor, partial-sync, rate-limit, revocation and replay behavior.
- Add connector-specific source/provenance evaluation fixtures.

Acceptance criteria:

- [ ] Interview statements remain source evidence, not verified facts.
- [ ] The connector has no write scope or mutation path.
- [ ] Every acquired item preserves external identity/version, sync cursor and source timestamp.
- [ ] Partial/revoked/stale sync states are explicit and downstream claims stale conservatively.
- [ ] Credentials never enter domain JSON, logs, exports or model prompts.

### Phase 4 — Factory opportunity portfolio

Goal: produce explainable, evidence-backed lighthouse options without fake precision.

Dependencies: approved Customer Factory Model/current workflow; decision log.

Tasks:

- Add hard eligibility gates and ordinal assessment dimensions.
- Persist evidence, assumptions and rationale for each dimension.
- Add candidate/assessed/selected/rejected/deferred states.
- Add portfolio comparison and a human selection decision.
- Compare eligible opportunities with versioned reusable factory-line templates; record fit, customization, validation and customer-local extensions without treating a template as customer truth.
- Build labeled expert-FDE evaluation examples; measure agreement, explainability and stability.

Acceptance criteria:

- [ ] Ineligible opportunities never rank above eligible ones.
- [ ] “No suitable opportunity” is supported.
- [ ] No unexplained composite 0–100 score is displayed.
- [ ] Every selection links to the exact model/workflow/evidence and approver.
- [ ] Changed upstream facts stale affected assessments and selections.

### Phase 5 — Factory line, Designer, and autonomy/authority

Goal: turn one selected opportunity into an implementable factory design.

Dependencies: ADRs 4 and 6; opportunity selected; Customer Factory Model version approved.

Tasks:

- Add stable `FactoryLine` and immutable `FactoryDesignVersion`.
- Extend target workflow to a graph with human/software/agent/verifier/approval/system-event nodes.
- Add capability/model/tool/MCP-server/skill/context/environment requirements and availability states.
- Add fallback, escalation, retry/timeout, rollback, observability and learning-signal requirements.
- Store Guide L0–L5 operational autonomy and independent per-action authority ceilings.
- Add decision records for allocation, autonomy, model/capability and verification choices.
- Add current-versus-target diff and accessible graph/table views.

Acceptance criteria:

- [ ] Factory-line state is independent of engagement and FDLC readiness.
- [ ] Required capabilities are not presented as certified without an authoritative registry ref.
- [ ] Template fit never overrides customer evidence; required customization, validation, and customer-local extensions remain explicit.
- [ ] MCP requirements carry semantic version/scopes/data-boundary/trust metadata and remain unavailable until Mission Control authorizes them.
- [ ] Effective autonomy uses the lowest applicable ceiling and never widens downstream policy.
- [ ] Every agent step has bounded authority, fallback, escalation and verification requirements.
- [ ] Approved designs are immutable and all material choices are explainable.

### Phase 6 — Evidence-backed FDLC readiness

Goal: determine whether one factory-line design is eligible for deployment handoff.

Dependencies: design version; structured decisions/dependencies; validated readiness policy.

Tasks:

- Add stage and gate results for Discover, Design, Assemble, Validate, Deploy, Operate and Improve.
- Link evidence, blockers, decisions, required artifacts, owner and next action.
- Add scoped/expiring waivers and non-waivable authority/security gates.
- Build blocker-detection and risk-recall evaluations.
- Add readiness heatmap plus accessible detailed table.
- Defer composite scoring until real FDE/user calibration proves it adds value.

Acceptance criteria:

- [ ] Missing evidence is unknown/fail, never pass.
- [ ] Material contradiction, missing authority, absent verification or rollback blocks high-risk handoff.
- [ ] Waivers identify owner, reason, scope, impact, evidence and expiry.
- [ ] A summary cannot hide a failed gate.

### Phase 7 — Factory Deployment Package

Goal: wrap the seven proven artifact views in one immutable, approved, versioned handoff aggregate.

Dependencies: ADR 7; approved design/readiness/economics; structured acceptance/verification.

Tasks:

- Add package identity/version, pins, canonical digest, readiness state and approval.
- Map and preserve all seven existing renderers.
- Add structured customer-context, authority/policy, verification, environment, rollout, rollback, observability and MC Plan projection only where each adds distinct governing value.
- Reject any stale or “latest” dependency.
- Generate schema fixtures and canonical digest tests.
- Extend export/delete/RLS/audit/timeline behavior.

Acceptance criteria:

- [ ] Package generation names exact approved/current versions and hashes.
- [ ] Package approval is impossible with a failed required gate.
- [ ] Approved package bytes cannot change.
- [ ] Upstream change marks the package stale with cause and blocks export.
- [ ] Existing seven artifacts remain available and traceable.
- [ ] Package contains no secrets or unnecessary raw source evidence.

### Phase 8 — Minimal Mission Control integration

Goal: create governed MC drafts and observe delivery without coupling execution systems.

Dependencies: jointly approved contract, Mission Control atomic schema/API slice, package V1.

Tasks:

- Implement export/download and import preview first.
- In Mission Control, atomically add persisted import receipt/schema, validators, indexes, generated types, tests and an authenticated human importer.
- Resolve semantic workspace/repository/code-scope/workflow/capability refs locally.
- Create only Mission/Plan drafts with package-bound idempotency.
- Store FE link/receipt and expose a read-only status projection.
- Add event ordering/idempotency/reconciliation before optional push delivery.
- Add stale-package advisory; MC policy owns hold/continue/supersede/cancel.

Acceptance criteria: all contract tests in [mission-control-integration-contract.md](../fdlc-factory-engineer/mission-control-integration-contract.md) pass in both repositories.

Rollback: disable importer and projection flags. Imported Mission/Plan drafts remain auditable and can be manually superseded; never delete downstream governed records automatically.

### Phase 9 — Deployment tracking and daily operator view

Goal: make Factory Engineer useful during delivery while preserving MC truth.

Dependencies: stable reverse projection and reconciliation.

Tasks:

- Add deployment workspace with Mission/Plan/WorkOrder refs and non-collapsed status facts.
- Add sync health, last reconciliation and bounded failure classification.
- Build explainable daily attention queue across claims, contradictions, readiness, packages, deployment and outcomes.
- Project audit events into engagement timeline and add structured decision views.
- Add privacy-safe engagement observability for source/claim progress, agent/model/tool activity, tokens/latency/retries, human decisions, MC-projected deployment facts and costs; keep engineering telemetry and MC execution truth separate.

Acceptance criteria:

- [ ] Execution complete never renders as verified, accepted, released or production-verified.
- [ ] Missing/out-of-order events cannot regress displayed state.
- [ ] Every attention item explains trigger, impact, owner and safe next action.
- [ ] Recommendations are read-only until the user invokes an authorized domain action.

### Phase 10 — Outcomes and field learning

Goal: compare baseline/projected/measured/realized outcomes and capture privacy-safe product signals.

Dependencies: deployed-version linkage, outcome definitions, ADR 8.

Tasks:

- Add metric definitions, observation windows, source/quality, deployment pins and attribution confidence.
- Add line-specific measures including cost per verified outcome where the denominator is stable.
- Add engagement-local field signals and outcome/failure links.
- Add explicit generalization, privacy review and product-steward decision.
- Add capability candidates that reference—but do not replace—the authoritative Agent Factory/registry.

Acceptance criteria:

- [ ] Projected results are never labeled realized.
- [ ] Insufficient observation, seasonality, partial rollout and rollback are explicit.
- [ ] Raw text/citations/repository IDs/customer configuration cannot enter cross-customer aggregates.
- [ ] One customer cannot automatically produce a published reusable capability.
- [ ] Productization requires an authoritative external registry/steward reference.

### Phase 11 — Evaluated specialist orchestration

Goal: introduce logical specialist agents only after the underlying domain workflows are stable.

Dependencies: labeled evaluations, versioned inputs/outputs, stable permissions.

Tasks:

- Extract Discovery, Systems Analysis, Claim Assessment, Factory Architecture, Economics, Evaluation, Integration, Deployment Coordination and Product Signal modules where context isolation measurably helps.
- Record specialist/model/prompt/schema/input/output versions and cost/latency.
- Add per-capability evaluation gates and fallback to deterministic or human workflows.
- Keep human decisions and server-side domain transitions outside prompts.

Acceptance criteria:

- [ ] No monolithic prompt owns the end-to-end engagement.
- [ ] Agent output remains a proposal unless an explicit authorized transition accepts it.
- [ ] Each specialist has its own grounding/precision/completeness/authority evaluation.
- [ ] Orchestration failure does not corrupt approved domain state.

## Test strategy

### Required on every relevant change

```bash
.venv/bin/ruff check .
.venv/bin/mypy src tests
.venv/bin/alembic upgrade head
.venv/bin/alembic check
.venv/bin/pytest
pnpm --dir apps/web run typecheck
pnpm --dir apps/web run lint
pnpm --dir apps/web run build
pnpm --dir apps/web run test:e2e:golden
pnpm --dir apps/web run test:e2e:alpha
pnpm --dir apps/web run test:a11y
```

CI must fail if required acceptance/isolation tests skip. Each migration phase also tests downgrade compatibility where safe, cross-engagement denial, export completeness, deletion, concurrent writes and stale dependency behavior.

### Evaluation families

| Capability | Measures |
|---|---|
| Claim extraction | Grounding, exact evidence precision, unsupported assertion rate |
| Contradiction analysis | Precision, recall, temporal/scope handling, false-positive rate |
| Workflow extraction | Step/exception recall, actor/system/decision accuracy |
| Opportunity assessment | Eligibility correctness, expert agreement, explanation quality, stability |
| Target/factory design | Feasibility, completeness, authority and verification correctness |
| Artifact/package | Traceability, cross-artifact consistency, version/digest correctness, criteria quality |
| Readiness | Blocker/risk recall, false-pass rate, waiver correctness |
| MC contract | Schema/digest/idempotency/auth/mapping/ordering/reconciliation |

Do not collapse these into one “AI accuracy” score.

## Security and privacy gates

- New tables receive RLS, explicit grants and cross-engagement denial tests in the same migration.
- Consequential writes require actor, authority, expected version, decision and audit.
- Model/tool prompts get only the minimum source context and never credentials.
- Connector reads require consented scopes; connector writes remain absent.
- Customer source content is excluded from telemetry and cross-customer learning.
- Export and deletion coverage lands with each new aggregate, not afterward.
- Production sanitized data remains disabled until release-bound Auth0/AWS/Bedrock/restore/deletion/rotation/rollback evidence is complete.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Narrative outruns implementation | Capability ledger and UI labels distinguish implemented, qualified, simulated and proposed |
| Schema explosion | Build one vertical slice per aggregate; preserve compatibility projections |
| False confidence in readiness/opportunity scores | Gates and ordinal bands first; calibrate any composite later |
| Duplicate execution state | Package + projection boundary; MC remains sole authority |
| Cross-customer leakage | Engagement-local raw signals, explicit generalization/privacy review |
| Stale approved intent used downstream | Exact pins/digests, dependency graph, fail-closed export/import |
| Multi-operator races | Aggregate locks/unique constraints and expected-version writes |
| Worker/provider cost explosion | Per-job segment/call/token/cost budgets and queue health |
| Demo diverges from backend | Generated contract/parity fixtures and fail-fast Vercel build |
| UI becomes unmaintainable | Route-level focused modules; no continued growth of monolithic cockpit files |
| Mission Control contract lands partially | Atomic schema/validator/index/generated-type/CI slice in MC |

## Success measures

Phase success is operational, not feature-count based:

- proportion of material model facts with current verified source support;
- time and human touches from evidence acquisition to approved model/current workflow;
- readiness false-pass rate and blocker recall;
- expert agreement and stability for opportunity eligibility/ranking;
- package regeneration/reapproval correctness after upstream changes;
- duplicate-free MC draft import and reconciliation health;
- baseline-to-realized outcome coverage by deployed version;
- field-signal privacy review pass rate and reused qualified capability rate;
- human attention spent on consequential decisions rather than status chasing.

## Immediate implementation slice

This branch should stop after the low-risk Phase 1 foundation:

- audit/architecture/plan documents;
- centralized public product and Guide-link registry;
- public naming, ecosystem navigation and minimal FDLC token alignment;
- fail-fast hosted-demo Vercel build invariant;
- corresponding type/lint/build/browser verification.

Do not begin database/domain migrations in the same change. They require the listed ADR decisions and deserve separately reviewable commits.
