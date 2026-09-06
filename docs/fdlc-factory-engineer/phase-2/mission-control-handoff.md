---
title: Mission Control trusted handoff
status: implemented-feature-branch
date: 2026-09-04
---

# Mission Control trusted handoff

## Boundary

Factory Engineer establishes customer truth and approved deployment intent before execution. Mission Control establishes execution and verification truth after handoff.

Factory Engineer never creates WorkOrders, Tasks, Attempts, sandboxes, verification receipts, approvals, releases, or deployment state. The package is a proposal for Mission Control's governed Plan path, not an executable manifest.

## Import sequence

1. An authenticated Clerk operator chooses the local workspace, repository, owner/team, and allowed code scopes.
2. Mission Control retrieves the exact package from a preconfigured HTTPS Factory Engineer base URL with its server-held bearer credential.
3. The adapter enforces response size/media type, supported schema, trusted issuer, immutable/current `PUBLISHED` states, approval binding, freshness, required fields, and canonical digest.
4. Mission Control resolves semantic target references to its own authorized IDs and requires delivery update/assignment authority.
5. Preview returns the exact proposed mapping and warnings without writing.
6. After explicit confirmation, one internal Convex mutation atomically creates an import receipt, Mission draft, Plan draft, and audit records.
7. The result remains Mission `PLANNING` with Plan `DRAFT`.
8. Existing Mission Control submission, Plan approval, Quality Contract compilation, WorkOrder creation, independent verification, acceptance, and release paths remain authoritative.

## Fail-closed governance

The adapter never bypasses local feature flags or Mission Spec governance:

- disabled Plan release returns `PLAN_RELEASE_DISABLED`;
- an enabled spec-intake contract requiring a finalized Mission Spec returns `SPEC_INTAKE_REQUIRED` for a new imported Mission;
- no synthetic spec, active constitution, workflow ID, policy decision, approval, or execution record is fabricated;
- preview remains available only to the extent existing authorization and trust checks permit it.

## Idempotency

External identity is:

```text
issuer_id + package_id + package_version
```

The receipt also stores package digest and the confirmed local target. An identical retry for the same digest and target returns the existing receipt. Different bytes or a different target for the same external identity returns an idempotency conflict and creates nothing.

## Package-to-Plan mapping

| Factory Engineer package | Mission Control draft |
|---|---|
| `mission_title` | Mission title |
| `mission_context` + `intent` | Mission context; the authenticated package URL is the sole Mission source-of-truth reference |
| `objective` | Mission objective |
| `stop_condition` | Mission stop condition |
| semantic target | locally resolved project/repository/code scopes/workflow requirement |
| `plan_summary` | Plan summary |
| `rollback_approach` | Plan rollback approach |
| `plan_assertions[]` | draft Plan assertions |
| `work_order_blueprints[]` | draft blueprint inputs only |
| `acceptance_criteria[]` | Plan-level criteria, each referenced by at least one blueprint |
| constraints/environment/policy/approval/authority statements | bounded Mission constraints and Plan blueprint constraints |
| selected capability/acceptance/verification IDs | bounded Plan lineage fields; complete upstream reference objects remain in Factory Engineer |
| issuer/package/version/digest + mapping/correlation IDs | bounded import metadata and immutable receipt fields |

Customer source documents and claim excerpts are not copied. Mission Control validates the complete
package in memory, then persists only the mapped draft content, authenticated package URL, selected
requirement IDs, and bounded receipt/import metadata described above.

## Validation errors

Stable failures include authentication/retrieval failure, unsupported schema, untrusted issuer, oversized response, bad digest, stale/revoked/not-published status, incomplete approval/authority/verification, target not found or unauthorized, rejected code scope, disabled Plan release, required Mission Spec, and idempotency conflict. All fail before an executable object is created.

## Demo behavior

The hosted Factory Engineer demo simulates successful retrieval and a governed-draft preview in browser-local synthetic state. It is labeled simulated, makes zero API requests, and never writes to Mission Control. The real adapter runs only inside Mission Control with explicit server configuration and authenticated operator confirmation.
