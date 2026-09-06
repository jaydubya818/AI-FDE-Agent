---
title: Factory Deployment Package v1
status: implemented-feature-branch
date: 2026-09-04
---

# Factory Deployment Package v1

## Product contract

`FactoryDeploymentPackageVersion` is the approved, immutable, data-minimized proposal that crosses from Factory Engineer into Mission Control. It carries implementation intent and exact source lineage. It is not executable, does not contain raw customer documents, and grants no downstream authority.

The retrieval response is:

```json
{
  "package": {
    "schema_version": "fdlc.factory-deployment-package/v1",
    "package_id": "uuid",
    "package_version": 1,
    "status": "PUBLISHED",
    "issuer": {},
    "issued_at": "ISO-8601",
    "approval": {},
    "integrity": {},
    "source": {},
    "target": {},
    "deployment_intent": {}
  },
  "attestation": {
    "package_id": "uuid",
    "package_version": 1,
    "digest": "sha256:<hex>",
    "current_status": "PUBLISHED",
    "issuer": {},
    "approval": {},
    "published_at": "ISO-8601",
    "retrieved_at": "ISO-8601",
    "correlation_id": "uuid"
  }
}
```

The immutable package is digest-covered. The attestation is generated at retrieval and reports current authoritative status. Mission Control requires both `package.status` and `attestation.current_status` to equal `PUBLISHED`.

## Source and target

Source lineage pins exact IDs, versions, and digests for:

- engagement;
- Customer Factory Model;
- approved current and target workflows;
- final readiness assessment;
- selected factory opportunity.

The semantic target carries `workspace_ref`, `repository_ref`, `requested_code_scopes`, `semantic_execution_workflow_ref`, and `environment_class`. Mission Control resolves and authorizes local IDs; Factory Engineer never invents them.

## Deployment intent

The bounded deployment-intent projection includes:

- mission title/context/stop condition;
- plan summary and rollback approach;
- objective, intent, and specification;
- acceptance criteria and constraints;
- capability, agent, skill, tool, model, context, and environment requirements;
- authority, policy, and approval requirements;
- verification, evaluation, rollback, and observability requirements;
- economics baseline, risks, evidence references, decision references, and provenance;
- Plan assertions and WorkOrder blueprints using Mission Control-compatible vocabulary.

References inside the plan graph are unique, resolvable, and acyclic. Every acceptance
criterion is referenced by at least one blueprint; every dependency points to a strictly
earlier blueprint sequence; required approvals resolve to declared approval requirements;
and each blueprint's code scopes exactly equal the package target scopes. Required evidence
is a bounded string. Verification method is one of `COMMAND`, `TEST`, `BROWSER`, `MANUAL`,
or `CHECKLIST`. Blueprint priority is 1–4 and execution role is `WORKER` or `VALIDATOR`.

The full compact UTF-8 retrieval envelope is bounded to 256,000 bytes. General contract
arrays are bounded to 200 items and requested code scopes to 50 items. The producer also
applies a conservative 240,000-byte target-plus-intent cap before draft persistence so the
later immutable metadata has reserved space.

## Approval and issuer

The exact approval binding is:

```json
{
  "decision_ref": {
    "kind": "APPROVED_INPUT",
    "ref": "...",
    "version": 1,
    "sha256": "sha256:<hex>"
  },
  "approved_by": "operator uuid",
  "authorized_by_ref": "...",
  "authority_basis_ref": {
    "kind": "APPROVED_INPUT",
    "ref": "...",
    "version": 1,
    "sha256": "sha256:<hex>"
  },
  "approved_at": "ISO-8601"
}
```

Approval and publication require the active human engagement owner. The authority basis
must pin the package's exact approved Customer Factory Model, and that model must contain
an evidence-backed authority boundary. Issuer identity is server-bound configuration, not
caller-supplied data:

- `issuer_type`: `FDLC_FACTORY_ENGINEER`;
- `authority_scope`: `DEPLOYMENT_PACKAGE_PUBLISH`;
- stable `issuer_id` from server-only `AI_FDE_FACTORY_ENGINEER_ISSUER_ID`;
- deployment environment.

## Lifecycle

```text
DRAFT → READY_FOR_REVIEW → APPROVED → PUBLISHED → SUPERSEDED
                └────────→ REJECTED
PUBLISHED ───────────────→ REVOKED
any dependent current state ─→ STALE
```

- Only approved packages may publish.
- Published bytes and approval/source bindings are immutable.
- A revision creates a new version under the existing package identity.
- Publishing a newer/current package supersedes the prior current published package while retaining history.
- Stale, revoked, superseded, draft, and merely approved packages cannot be retrieved through the integration endpoint.
- Package identity is issuer-scoped externally; reuse across engagements is rejected.

## Canonicalization and digest

Canonicalization is deliberately named `fdlc-canonical-json/v1`, not JCS or RFC 8785.

1. Validate recursively that object keys contain ASCII only.
2. Sort object keys by ASCII/Unicode code-point order.
3. Preserve array order.
4. Encode compact UTF-8 JSON with no insignificant whitespace.
5. Permit strings, booleans, null, safe integers, arrays, and objects.
6. Reject floats and integers outside the cross-language safe range; decimal quantities are strings.
7. Omit only `package.integrity.digest` while calculating.
8. Compute SHA-256 and render `sha256:` plus 64 lowercase hexadecimal characters.

The repository fixture `fixtures/contracts/factory-deployment-package-v1.json` and adjacent `.sha256` are the cross-language interoperability source of truth.

## Implementation boundary

The database and application enforce state transitions, exact version pins, uniqueness, staleness, and immutable published content. This is a V1 contract on the feature branch, not a claim that the service-to-service credential has enterprise secret rotation, workload identity, or fleet management. Those remain deployment responsibilities.
