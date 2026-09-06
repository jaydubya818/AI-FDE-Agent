---
title: Customer Factory Model v1
status: implemented-feature-branch
date: 2026-09-04
---

# Customer Factory Model v1

## Purpose

The Customer Factory Model is the approved, customer-scoped projection of engineering reality that Factory Engineer may use for opportunity assessment and deployment intent. It is not raw source evidence, an execution manifest, or a replacement for the existing Company Operating Model compatibility view.

## V1 record

Each immutable version contains:

- organization;
- systems, repositories, and environments;
- workflows and policies;
- authority boundaries and constraints;
- risks and baselines;
- evidence, verified-claim, approved-input, and explicit-assumption references;
- downstream factory-opportunity references when known.

Every material `TraceableFact` has a stable key, label, description, typed attributes, and at least one typed provenance reference. The model itself requires both customer evidence and a verified claim. A model cannot manufacture missing customer truth from general FDLC guidance.

## Provenance

V1 source references use this shape:

```json
{
  "kind": "EVIDENCE | VERIFIED_CLAIM | APPROVED_INPUT | ASSUMPTION",
  "ref": "bounded semantic or product reference",
  "version": 1,
  "sha256": "sha256:<64 lowercase hexadecimal characters>"
}
```

`VERIFIED_CLAIM` and `APPROVED_INPUT` references must pin an immutable version. Evidence and assumptions still require an integrity digest. Customer data remains under `engagement_id`; cross-engagement references fail closed.

## Lifecycle and concurrency

```text
DRAFT → APPROVED → STALE
```

- Editing approved content is forbidden. A change creates a new version.
- Only one current approved model may exist per engagement.
- Version allocation and approval transitions serialize on the engagement aggregate.
- Approval requires a human identity; a service identity may retrieve published packages but cannot approve truth.
- Database constraints and privileges protect immutable approved rows independently of service code.

## Staleness

A changed or superseded material claim, contradiction decision, current workflow, target workflow, economic case, or package source dependency causes the narrowest safe downstream versions to become stale. Staleness preserves history and records its cause; it never rewrites an approved version.

The first implementation deliberately over-invalidates where dependency precision is unavailable. That is safer than allowing a current-looking package to retain obsolete customer truth.

## Compatibility

The existing `OperatingEntity` and `Assertion` records remain the current Company Operating Model projection. V1 adds the versioned Customer Factory Model beside them. It does not physically rename legacy tables or force a data rewrite.

## Implementation boundary

Implemented in `src/ai_fde/modules/factory_engineer/` with PostgreSQL persistence and acceptance tests. The public hosted demo uses deterministic browser-local synthetic equivalents. It does not represent customer data, production authorization, or Mission Control execution.
