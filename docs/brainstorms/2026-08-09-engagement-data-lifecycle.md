---
date: 2026-08-09
topic: engagement-data-lifecycle
---

# Engagement Data Lifecycle

## What We're Building

Add one owner-controlled lifecycle path for an engagement: set an explicit retention deadline,
download a deterministic portability export, and permanently delete the engagement only after a
current export exists. Deletion removes engagement content and evidence objects while preserving a
content-free deletion receipt.

## Why This Approach

The V1 dataset is bounded, so a synchronous deterministic ZIP is simpler and more trustworthy than
adding another worker identity before service authentication exists. A soft-delete-only design
would retain prohibited customer content. A hard delete without a durable receipt would destroy the
minimum evidence needed to prove the operation completed.

## Key Decisions

- Authority: only the engagement owner can set retention, export, or delete.
- Retention: AI-FDE does not invent a default contractual period. The owner sets an explicit
  `retain_until`; deletion is blocked until that deadline, while an unset deadline permits deletion
  for synthetic V1 workspaces.
- Export: a deterministic ZIP contains versioned JSON and YAML records, Markdown implementation
  specifications, audit history, and original evidence files. Its SHA-256 fingerprint is recorded.
- Freshness: deletion requires a completed export whose business-state fingerprint still matches
  the engagement. Operational job/audit churn does not invalidate an otherwise current export.
- Confirmation: the owner must provide the exact engagement name and the export identifier.
- Execution: the engagement enters a write-blocked deletion state before object removal. Evidence
  object deletion is idempotent; then PostgreSQL cascade-deletes engagement content.
- Receipt: a separate operator-scoped record retains only identifiers, classification, counts,
  export hash, timestamps, status, and a bounded failure code. It has no engagement foreign key and
  stores no customer name, evidence, free-form reason, or source content.
- Scope: legal holds, automated expiry jobs, configurable organization policies, and scheduled
  deletion windows are later capabilities. Sanitized data remains disabled after this slice until
  live Auth0 verification and the complete readiness checklist pass.

## Open Questions

- Production retention periods and legal-hold authority must be agreed with each design partner;
  V1 intentionally records an explicit deadline instead of assuming either.

## Next Steps

Implement the lifecycle schema and isolation policy, deterministic export, two-phase deletion
service, owner-only API, cockpit controls, and an export-then-delete acceptance test.
