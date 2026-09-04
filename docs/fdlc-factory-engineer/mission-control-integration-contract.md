---
title: Factory Engineer to Mission Control integration contract
status: proposed-v1
date: 2026-09-04
factory_engineer_commit: 801d4c12e14dd4510d40906d8aeddf357df6edce
mission_control_commit: 07a96ac3623c8a6772455fcf4c9cdf4ca78e6d2f
---

# Factory Engineer to Mission Control integration contract

## Contract decision

The V1 seam is an immutable, schema-validated `FactoryDeploymentPackage` export plus a small authenticated Mission Control importer that creates a Mission draft and Plan draft only. The reverse seam is a curated, read-only status/outcome projection.

No shared database, cross-repository package import, raw Markdown handoff, or bidirectional execution control is allowed. No current Mission Control import endpoint or Factory Deployment Package schema exists; this document proposes that new boundary rather than claiming compatibility.

## Ownership boundary

Factory Engineer is authoritative for:

- package identity/version/digest and upstream approval;
- customer-model, workflow, design, readiness, economics and decision pins;
- source evidence references and customer-scoped provenance;
- proposed objective, constraints, acceptance criteria, capability requirements, authority ceilings, verification requirements, rollout/rollback/observability requirements.

Mission Control is authoritative for:

- workspace/operator/team/repository/code-scope authorization;
- Mission, Plan, WorkOrder, Task and Attempt identity/state;
- current Mission Control execution-workflow/template and runtime Factory Definition Version resolution;
- policy compilation, execution manifests, models/harnesses/tools/sandboxes;
- verification subjects, independent verifiers, evidence envelopes/receipts and gate currentness;
- approvals, waivers, acceptance, GitHub publication, release, deployment, rollback and recovery;
- execution telemetry and native failure records.

Factory Engineer approval means “approved to propose for governed handoff.” It never means Mission Control plan approval, execution authorization, acceptance or release eligibility.

## Forward contract

### Media type and integrity

- Schema: `fdlc.factory-deployment-package/v1`
- Media type: `application/vnd.fdlc.factory-deployment-package+json;version=1`
- Encoding: UTF-8 JSON
- Canonicalization: RFC 8785 JSON Canonicalization Scheme (`jcs`)
- Digest: SHA-256 over the canonical payload with `integrity.sha256` omitted
- Maximum importer envelope: 256 KiB initially, matching Mission Control’s current signed-command envelope ceiling

### Origin and approval authenticity — blocking requirement

A content digest proves byte integrity; it does not prove that Factory Engineer issued the package or that a real authorized person approved it. A write-capable importer must therefore verify a trusted issuer and the exact approval record independently of self-declared JSON.

The joint ADR must choose one V1 trust bootstrap:

1. **Authenticated retrieval (recommended):** the operator supplies a package reference and Mission Control retrieves the immutable package, current freshness, approval decision, and issuer identity from a preconfigured Factory Engineer instance over an authenticated service channel.
2. **Signed portable export:** Mission Control validates a detached signature/attestation against a preconfigured Factory Engineer issuer key, enforces issuance age/key rotation, and obtains a current signed freshness/revocation statement before creating drafts.

Email identity, TLS alone, a copied approval ID, or the uploading operator’s assertion is insufficient. Until this mechanism and its key/credential rotation are approved and implemented, Mission Control may parse and preview a package but must not create a Mission or Plan draft.

### Proposed payload

```json
{
  "schema": "fdlc.factory-deployment-package/v1",
  "packageId": "fdp_01J...",
  "packageVersion": 3,
  "createdAt": "2026-09-04T18:00:00Z",
  "originProof": {
    "issuerId": "factory-engineer-production",
    "method": "AUTHENTICATED_RETRIEVAL",
    "issuedAt": "2026-09-04T18:00:00Z",
    "attestationRef": "fe://package-attestation/..."
  },
  "source": {
    "system": "factory-engineer",
    "instanceRef": "https://factory.example.invalid",
    "engagementId": "uuid",
    "customerFactoryModel": { "id": "uuid", "version": 4, "sha256": "sha256:..." },
    "currentWorkflow": { "id": "uuid", "version": 2, "sha256": "sha256:..." },
    "targetWorkflow": { "id": "uuid", "version": 3, "sha256": "sha256:..." },
    "factoryLine": { "id": "uuid" },
    "factoryDesign": { "id": "uuid", "version": 2, "sha256": "sha256:..." },
    "readinessAssessment": { "id": "uuid", "version": 2, "sha256": "sha256:..." },
    "economicCase": { "id": "uuid", "version": 3, "sha256": "sha256:..." }
  },
  "integrity": {
    "canonicalization": "jcs",
    "sha256": "sha256:..."
  },
  "readiness": {
    "status": "READY",
    "blockingGateCount": 0,
    "evidenceRefs": [
      { "ref": "fe://readiness-evidence/...", "sha256": "sha256:..." }
    ],
    "approvalRefs": [
      {
        "decisionId": "uuid",
        "decisionVersion": 1,
        "decisionDigest": "sha256:...",
        "authorizedByRef": "fe://operator/...",
        "authorityBasisRef": "fe://authority/...",
        "decidedAt": "2026-09-04T17:55:00Z"
      }
    ],
    "waivers": []
  },
  "target": {
    "workspaceRef": "semantic-workspace-ref",
    "repositoryRef": "github:owner/repository",
    "requestedCodeScopes": ["apps/service/**"],
    "workflowRef": "software-change/default",
    "environmentClass": "POLICY_SELECTED"
  },
  "missionDraft": {
    "title": "Modernize supported framework dependencies",
    "objective": "...",
    "context": "...",
    "constraints": ["..."],
    "sourceOfTruthRefs": [
      { "kind": "factory-package-artifact", "ref": "fe://artifact/...", "sha256": "sha256:..." }
    ],
    "stopCondition": "Stop when any non-waivable verification or authority gate cannot be satisfied.",
    "executionEnvironment": "POLICY_SELECTED"
  },
  "planDraft": {
    "summary": "...",
    "rollbackApproach": "...",
    "workOrderBlueprints": [
      {
        "key": "inventory-and-upgrade",
        "title": "...",
        "outcome": "...",
        "requirements": ["..."],
        "acceptanceCriterionRefs": ["criterion-1"],
        "constraints": ["..."],
        "requestedCodeScopes": ["apps/service/**"],
        "capabilityRequirements": ["..."],
        "verificationRequirementRefs": ["verification-1"],
        "authorityCeilingRefs": ["authority-1"]
      }
    ],
    "assertions": [
      { "key": "criterion-1", "statement": "...", "sourceRef": "fe://acceptance-criterion/..." }
    ]
  },
  "requirements": {
    "capabilities": [],
    "tools": [],
    "mcpServers": [],
    "skills": [],
    "models": [],
    "policy": [],
    "authorityBoundaries": [],
    "verification": [],
    "evaluation": [],
    "environment": [],
    "rollback": [],
    "observability": []
  },
  "artifactRefs": [
    { "type": "implementation_spec", "version": 3, "ref": "fe://artifact/...", "sha256": "sha256:..." }
  ]
}
```

### Required semantics

- `packageId`, `packageVersion`, and digest identify one immutable approved version.
- `originProof.issuerId` resolves to a preconfigured trusted Factory Engineer instance/key; origin and the exact approval digest are verified outside the self-declared payload.
- All source version refs are exact and current at approval time.
- `readiness.status` must be `READY`, and at least one current `approvalRef` must be independently authenticated; readiness alone is insufficient.
- `sourceOfTruthRefs` and `artifactRefs` are immutable, authenticated references or embedded bounded projections. They are not executable instructions.
- Customer evidence text is excluded by default. If Mission Control needs bounded context, Factory Engineer exports a purpose-specific, approved, hash-bound context artifact rather than raw uploads.
- `workspaceRef`, `repositoryRef`, code scopes and `workflowRef` are requested semantic references. Here `workflowRef` means a Mission Control execution-workflow/template requirement, not Factory Engineer’s customer current-state workflow. Mission Control resolves and authorizes its own local IDs.
- Capability/tool/MCP-server/skill/model entries are requirements and constraints, not authoritative availability, authorization, or certification claims.
- Omitted budget or cost fields mean unknown/not supplied; `0` is a real zero ceiling, never a placeholder. Mission Control collects and validates any locally required budget before submission.
- Acceptance criteria have stable keys and are measurable; Mission Control independently compiles them into its Quality Contract and verification plan.
- An upstream authority ceiling can only reduce downstream authority. Mission Control may impose stricter policy.

## Import protocol

### Human-mediated V1

1. An authenticated Mission Control operator chooses the target workspace, repository, owner/team and allowed code scopes.
2. The importer validates media type, schema, size, canonical digest, trusted origin, package identity/version, current freshness, readiness status and the exact approval digest/authority binding.
3. It previews unresolved or unsupported semantic references—workflow, capability, environment, verifier and code scope—without writing.
4. The operator confirms the mapping.
5. The importer applies the unique idempotency key `factory-package:<issuerId>:<packageId>:<packageVersion>` and stores the digest. The same digest returns the original receipt; different bytes for the same issuer/ID/version fail as an integrity conflict.
6. It calls only the equivalent of `missions.createDraft` and `missions.savePlanDraft`.
7. It returns Mission and Plan draft references plus a receipt bound to the package digest.
8. Mission Control submission re-resolves the current repository configuration and workflow version.
9. Mission Control plan approval independently validates policy/separation of duties and compiles its immutable Quality Contract and WorkOrders.

The result remains `DRAFT`/`PLANNING`. Import never submits, approves, dispatches, verifies, accepts, merges, deploys or promotes.

### Future machine-to-machine option

If human upload/export becomes an operational bottleneck, add one signed service capability, for example `factory-packages.propose`. Its maximum authority is idempotent Mission/Plan draft creation. Reuse Mission Control’s HMAC-bound service-command model: service identity, capability, company/workspace, timestamp, payload digest, replay receipt and bounded envelope. Do not expose a generic write API.

Human authentication remains Clerk in Mission Control and OIDC/Auth0 in Factory Engineer until a real shared Enterprise identity contract exists. Never map authority by email alone.

## Import response and error model

```json
{
  "schema": "fdlc.factory-package-import-receipt/v1",
  "idempotencyKey": "factory-package:...",
  "issuerId": "factory-engineer-production",
  "packageId": "fdp_01J...",
  "packageVersion": 3,
  "packageDigest": "sha256:...",
  "status": "DRAFT_CREATED",
  "missionRef": "mc://mission/...",
  "planRef": "mc://plan/...",
  "mappingRevision": 1,
  "warnings": [],
  "createdAt": "2026-09-04T18:05:00Z"
}
```

Errors are stable codes with bounded detail and correlation ID:

| Code | Meaning | Retry behavior |
|---|---|---|
| `UNSUPPORTED_CONTRACT_VERSION` | Importer cannot parse schema version | Do not retry unchanged package |
| `DIGEST_MISMATCH` | Canonical payload does not match declared hash | Do not retry; regenerate/export |
| `ORIGIN_UNVERIFIED` | Issuer proof is absent, invalid, expired, revoked, or not trusted | Do not create drafts; establish trusted origin |
| `APPROVAL_UNVERIFIED` | Exact upstream decision or authority binding cannot be authenticated | Resolve upstream; never trust payload alone |
| `PACKAGE_NOT_APPROVED` | Upstream approval/readiness missing or invalid | Resolve upstream |
| `PACKAGE_STALE` | Factory Engineer reports the version stale | Regenerate/reapprove |
| `TARGET_NOT_FOUND` | Workspace/repository semantic ref unresolved | Human remap |
| `TARGET_UNAUTHORIZED` | Operator/service lacks target authority | Do not disclose hidden target details |
| `CODE_SCOPE_REJECTED` | Requested scope is outside local policy | Narrow/remap |
| `CAPABILITY_UNAVAILABLE` | Requirement cannot resolve to eligible local capability | Return explicit missing requirement |
| `POLICY_CONFLICT` | Requirement exceeds local policy | Human decision/new design |
| `IDEMPOTENCY_CONFLICT` | Same issuer/package ID/version carries a different digest | Treat as integrity incident; never create a second draft |
| `TEMPORARY_UNAVAILABLE` | Safe transient failure before/after idempotent boundary | Retry with same key |

An identical retry returns the original receipt. Partial writes are transactional or reconciled to a single receipt.

## Reverse status contract

Factory Engineer consumes a curated projection; it does not read Mission Control tables or infer execution truth from logs.

```json
{
  "schema": "fdlc.mission-control-delivery-status/v1",
  "eventId": "mc_evt_01J...",
  "sourceRevision": 42,
  "packageId": "fdp_01J...",
  "packageVersion": 3,
  "packageDigest": "sha256:...",
  "missionRef": "mc://mission/...",
  "planRef": "mc://plan/...",
  "workOrderRefs": ["mc://work-order/..."],
  "state": "IN_PROGRESS",
  "latestOutcome": {
    "executionCompleted": false,
    "verified": false,
    "eligible": false,
    "accepted": false,
    "merged": false,
    "released": false,
    "productionVerified": false
  },
  "verificationEvidenceRefs": [],
  "failureClass": null,
  "observedMetricRefs": [],
  "asOf": "2026-09-04T18:10:00Z"
}
```

The booleans are deliberately separate. Execution complete, verification pass, gate eligibility, WorkOrder acceptance, merge, release and production verification cannot collapse into one “done.”

Delivery may begin as polling an authenticated read projection. Event delivery can be added only after Factory Engineer’s outbox consumer has idempotency, ordering, cursors, retry/dead-letter and reconciliation. Apply events by `sourceRevision`, deduplicate `eventId`, retain `asOf`, and periodically reconcile authoritative current state.

## Post-export change behavior

When a package dependency changes:

1. Factory Engineer marks the package version stale with dependency/cause.
2. It records a new decision/timeline event and notifies the owner.
3. If not imported, export is blocked until regeneration and approval.
4. If imported but not executing, the UI recommends superseding the Mission/Plan draft.
5. If execution is active, Factory Engineer sends a stale-package advisory or exposes it to Mission Control.
6. Mission Control policy decides whether to continue, hold, supersede or cancel. Factory Engineer never directly changes execution state.
7. Security/authority revocation may map to a high-priority hold request, but MC still authorizes and records the transition.

## Data minimization and privacy

- Package contains stable facts and requirements needed for planning, not a copy of the Customer Factory Model.
- Raw source evidence, interview transcripts, secrets, connector tokens, customer repository content and personal data are excluded.
- References are audience-bound and expire or require authenticated retrieval where necessary.
- Mission Control stores the package digest and minimal upstream lineage. Factory Engineer stores minimal MC refs and curated projections.
- Logs and errors never include source text, credentials, full payloads or signed URLs.
- Export/deletion inventories include package copies, import receipts, context artifacts, status projections and failed outbox payloads.

## Contract compatibility

- Additive optional fields may appear within a major schema version; consumers ignore unknown optional fields.
- Removing, renaming, changing semantics, or making an optional field required creates a new major schema.
- Each side publishes supported schema versions/capabilities during import preview.
- Fixtures and contract tests live in both repositories and are pinned to exact schema examples.
- No compatibility claim is made with FDLC’s public `FactoryDefinition 0.1-draft`; that browser-generated artifact is explicitly non-executable and unstable.
- Mission Control’s internal `mission-plan-candidate/v1` informs vocabulary but is not exposed as this external contract.

## Acceptance tests before integration release

- Valid, origin-authenticated, currently approved package creates exactly one Mission/Plan draft.
- Identical retries return the same receipt; another digest for the same issuer/package ID/version fails without a second draft.
- Invalid schema, digest, unsupported version, stale package and absent approval fail closed.
- Untrusted issuer, invalid/expired origin proof, or unverifiable approval authority remains preview-only and cannot write.
- Unauthorized workspace/repository/code scope is denied without target leakage.
- Semantic workflow/capability references require explicit mapping; no volatile MC IDs are required upstream.
- Import never changes Mission state beyond draft/planning and never creates WorkOrders.
- Plan submission rebinds current local workflow/repository configuration; package data cannot override policy.
- Customer evidence text and secrets are absent from fixtures, logs, errors and telemetry.
- Duplicate/out-of-order reverse events do not regress state; reconciliation repairs a missing event.
- Execution completion does not render as verified, accepted or released.
- A stale imported package creates an advisory and requires policy action; it does not silently cancel or continue work.

## Required Mission Control implementation sequence

Mission Control’s existing schema discipline requires contract changes to land atomically: persisted schema, validators, indexes, generated types and CI must ship together. The repository’s prior solution note, `docs/solutions/build-errors/missing-convex-schema-contracts-ci-20260730.md`, documents this exact failure mode. Do not ship a Factory Engineer consumer or UI ahead of the durable import contract.

## Decisions still requiring joint approval

- Canonical instance/reference URI format and authenticated artifact retrieval.
- Trusted-origin mechanism: authenticated retrieval versus signed portable export, including trust bootstrap, rotation, revocation and maximum attestation age.
- Which readiness/security gates are non-waivable.
- Human upload versus signed service import for the first customer deployment.
- Ownership and retention of the original package bytes.
- Supported maximum payload and whether bounded plan projections are embedded or referenced.
- Stale-package policy after execution has begun.
- Mapping UI ownership and separation-of-duties policy for high-risk imports.
