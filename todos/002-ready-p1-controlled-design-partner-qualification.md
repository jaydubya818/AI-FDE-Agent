---
status: ready
priority: p1
issue_id: "002"
tags: [factory-engineer, phase-3, design-partner, security, operations, mission-control]
dependencies: []
---

# Qualify one controlled design-partner production path

## Problem Statement

Phase 2 proves the public synthetic application experience and the immutable Factory Engineer to
Mission Control draft contract. It does not prove that one real design partner can safely use the
actual authenticated service with bounded customer data, operational monitoring, recovery, secret
rotation, and a human-mediated Mission Control import.

## Findings

- The Vercel production deployment is intentionally browser-local and synthetic; it is not the
  customer-data service path.
- The real FastAPI path already has OIDC sessions, engagement membership/RLS, bounded uploads,
  worker identity, persistent PostgreSQL state, S3 storage, and an AWS ECS design-partner template.
- `Engagement` is the existing customer isolation boundary, but it does not carry an explicit
  qualification policy, four-level information classification, or authorized source/workflow list.
- Health is static, telemetry is not structured, and restore/rotation evidence is caller-supplied
  rather than produced by a bounded drill.
- Mission Control revision `0f8267e` validates and imports the v1 package through an authenticated,
  default-off preview/confirm UI as Mission `PLANNING` and Plan `DRAFT`; it has not been applied live.

## Proposed Solutions

### Option 1: Add a qualification envelope to the existing engagement boundary

Add one 1:1 qualification policy, keep direct document upload as the sole customer-data path, and
reuse the existing package/retrieval/import contract.

**Pros:** Smallest data-model change, preserves isolation and trust invariants, avoids a new tenant
platform, and keeps Mission Control authoritative for execution.

**Cons:** Deliberately supports only one bounded qualification shape.

**Effort:** Large

**Risk:** Medium

### Option 2: Build a generalized customer/organization/connector platform

Introduce organizations, arbitrary connectors, repository credentials, and a generic ingestion
gateway.

**Pros:** Broader future flexibility.

**Cons:** Excessive Phase 3 scope, substantially larger attack surface, and no evidence it is needed
for the first partner.

**Effort:** Very large

**Risk:** High

## Recommended Action

Use Option 1. Keep the Vercel demo unchanged; qualify the separate real-service path. Represent the
design partner as a policy bound 1:1 to an existing engagement and its server-derived memberships.
Permit only manifest-authorized document uploads and the existing pull-based Mission Control v1
handoff. Fail closed unless qualification mode, partner state, workflow, source, information class,
identity, and retention policy all agree.

## Technical Details

**Factory Engineer:** qualification models/migration/service/API, access audit, classification
policy, auth/origin hardening, service health/readiness/version, structured telemetry, operational
alarms, rotation/restore drill tooling, real-service UI and browser tests, evidence/runbooks.

**Mission Control:** gated human preview/confirm UI, complete no-authority regression proof, focused
authorization/idempotency coverage, and rollout documentation. No new execution abstraction.

## Acceptance Criteria

- [x] Existing Phase 2 production behavior remains unchanged and regression suites stay green.
- [x] One engagement can be provisioned as an explicit design-partner qualification boundary.
- [x] Authorized users, sources, repository refs, workflow classes, retention, classification, and
      qualification state are server-enforced.
- [x] PUBLIC, INTERNAL, CONFIDENTIAL, and RESTRICTED influence provider, artifact, Mission Control,
      retention, export, persistence, and logging policy.
- [x] Missing, expired, tampered, cross-partner, wrong-workflow, and wrong-source requests fail
      closed with deterministic tests.
- [x] The only customer-data path is bounded document upload with attributable access audit.
- [x] Service liveness, dependency readiness, revision, environment, resource/time bounds, and
      deployment provenance are observable without secret leakage.
- [x] Structured logs and minimum useful metrics/alerts have documented signal, threshold, owner,
      and response.
- [ ] A production-equivalent credential rotation proves new works, old is revoked, old fails, and
      no credential appears in logs/artifacts.
- [ ] An isolated backup/restore drill verifies a known durable record and artifact without touching
      production.
- [x] Mission Control preview/confirm is human initiated, authenticated, gated, idempotent, and
      visibly machine-generated.
- [x] Mission Control import creates only one Mission `PLANNING` and one Plan `DRAFT`; it creates no
      WorkOrder, Task, Attempt, dispatch, publication, PR, merge, release, or deployment state.
- [x] Local static, migration, unit, integration/isolation, contract, browser, accessibility,
      Terraform, and production-build gates pass.
- [ ] An immutable Phase 3 candidate evidence package records exact revisions and honest remaining
      live gates without secret values.
- [ ] Both repository branches are committed and pushed; Preview is verified.
- [x] Production remains on the Phase 2 revision unless the exact Phase 3 candidate receives a
      separate explicit promotion authorization.

## Work Log

### 2026-09-04 - Audit and authorized implementation

**By:** Codex

**Actions:**

- Audited Factory Engineer application, web, identity, storage, infrastructure, operations, tests,
  and the narrow Mission Control importer at exact revision `59378cb` before changing code.
- Ran the focused Mission Control contract/import audit suites: 43/43 passed.
- Selected the existing engagement boundary, bounded upload path, and pull-based package v1 import
  as the smallest safe Phase 3 architecture.
- Created isolated Phase 3 branches in both repositories.

**Learnings:**

- Most trust primitives already exist; the gap is a qualification envelope plus operational proof.
- The public Vercel demo and the real design-partner service must remain separate release claims.
- Mission Control needs usability and proof, not broader service authority.

### 2026-09-04 - Controlled qualification implementation and adversarial hardening

**By:** Codex

**Actions:**

- Implemented engagement-bound qualification, classification, retention, authorized-source and
  workflow enforcement, bounded upload, attributable audit, package retrieval, and human-mediated
  Mission Control handoff.
- Added transaction-safe S3 writes with exact VersionId compensation, pinned reads and SHA-256
  verification, version-complete permanent deletion, pinned portability export, and portable ZIP
  entry hardening.
- Added database-clock heartbeats, deployment-scoped RDS IAM worker identities, lease fencing,
  late authorization checks, exact expiry handling, and deterministic PostgreSQL race tests.
- Added KMS-signed typed evidence envelopes, offline runtime signature and semantic validation,
  exact Auth0/RDS/secret/version bindings, two-party IAM proof, and a 64 KiB qualification-record
  ceiling.
- Added exact cluster task inventory, task/execution-role binding, no-NAT worker networking,
  endpoint/security-group verification, dedicated evidence KMS encryption, a fixed-network Step
  Functions migration broker, and fail-closed prior-role quarantine/cleanup tooling.
- Added liveness/readiness/version endpoints, structured metadata-only telemetry, CloudWatch
  signals/alarms/dashboard, operational runbooks, Terraform validation in CI, and non-root
  container trust-bundle verification.
- Committed and pushed Mission Control revision `0f8267e1ba210c03c35082848b1d7bb7cebf8d83`.

**Verification:**

- Factory Engineer: 352/352 Python tests passed with required PostgreSQL coverage; Ruff, generated
  contract, and mypy across 129 files passed.
- Infrastructure: Alembic sole head `b7e2c5d4a901`, schema drift check, Terraform init/format/
  validate, actionlint, and both non-root container builds/checksums passed.
- Web: production-equivalent Next.js build and all 9 golden, internal-alpha, accessibility, and
  design-partner browser tests passed; the default development stack also stayed healthy.
- Secret-pattern scan found no high-confidence credential material in changed or untracked files.

**Remaining live gates:**

- Run and KMS-seal the real Auth0 browser, credential rotation/revocation, deletion-boundary, and
  isolated restore procedures against the exact AWS release.
- Run candidate readiness, the fixed broker binding migration, post-activation verification, and
  the live Mission Control receipt before claiming design-partner production qualification.

## Notes

- Do not apply Mission Control to live Convex or promote a new Factory Engineer production artifact
  without exact-candidate authorization.
- The supplied Phase 3 brief ends mid-sentence after “Broader”; all complete requirements preceding
  that truncation are in scope.
