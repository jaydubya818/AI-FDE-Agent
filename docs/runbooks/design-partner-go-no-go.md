# Design-Partner Go/No-Go Record

**Current repository state (2026-08-12): NO-GO for sanitized customer data.**

Use one copy of this record per deployed release. A local test, Terraform validation, or unchecked
record cannot be interpreted as approval. Never record credentials, tokens, customer evidence, or
raw model requests/responses here.

## Release identity

| Field | Value |
| --- | --- |
| Environment | |
| Git commit | |
| Web/API/worker image digests | |
| AWS account and region | |
| Bedrock model/inference-profile ID | |
| FDE owner | |
| Validation date/time | |

## Implemented-code gates

- [ ] Full Python tests, RLS/isolation tests, Ruff, and mypy pass.
- [ ] Frontend lint, clean typecheck, production build, and accessibility checks pass.
- [ ] Alembic clean upgrade, safe downgrade, re-upgrade, and `alembic check` pass.
- [ ] Terraform formatting and validation pass for the release commit.
- [ ] Images are built from the release commit and referenced by digest.
- [ ] Coding-agent execution and autonomous remediation remain disabled.

## Live identity and deployment gates

- [ ] Auth0 live-tenant record is complete; ID: `________________`.
- [ ] HTTPS, callback, cookie, allowlist, logout, revocation, and unauthenticated behavior pass.
- [ ] Web, API, worker, migration, and deployment roles are distinct and least privilege.
- [ ] Worker is an active service identity with only explicit operator memberships.
- [ ] ECS tasks have no public IP; RDS is private, encrypted, TLS-forced, Multi-AZ, and PITR-ready.
- [ ] S3 blocks public access, uses the expected KMS key, and has versioning disabled.
- [ ] Bedrock invocation logging is disabled and the selected model passed the fixed evaluation.
- [ ] Runtime secrets were rotated and the prior version was invalidated; ID: `________________`.

## Recovery and deletion gates

- [ ] RDS restore rehearsal passed with row counts and RLS verified; ID: `________________`.
- [ ] Evidence restore/reconciliation passed without cross-engagement access.
- [ ] Sanitized golden-path export and deletion passed; ID: `________________`.
- [ ] The RDS backup-expiry and S3 deletion boundaries match customer-facing retention language.
- [ ] Rollback to the previous image digests was rehearsed without schema or data loss.

## Automated readiness record

Run `scripts/verify_design_partner_readiness.py` with the record IDs above.

| Field | Value |
| --- | --- |
| Readiness validation ID | |
| Signed record location | |
| Machine-check result | Pass / Fail |
| Reviewer | |

## Decision

- [ ] **GO:** every gate passed; set the emitted validation ID and enable sanitized data through a
      reviewed Terraform change.
- [ ] **NO-GO:** one or more gates are incomplete or failed; keep sanitized data disabled.

Decision owner: `________________`  Date/time: `________________`

Notes or linked tickets (no sensitive content):
