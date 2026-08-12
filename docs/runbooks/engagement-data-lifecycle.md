# Engagement Data Lifecycle

Only the engagement owner can set retention, generate a portability export, or permanently delete
an engagement. Operators and viewers may inspect lifecycle status but cannot perform these actions.

## Retention

AI-FDE does not choose a contractual retention duration. The owner records an explicit, timezone-
aware `retain until` deadline agreed for the engagement. V1 permits extending that deadline and
rejects attempts to shorten it. A future deadline blocks deletion.

An unset deadline permits deletion for synthetic V1 workspaces. Legal holds, organization-wide
policy templates, and automated expiry jobs are not implemented and must not be implied.

## Portability export

Select **Generate & download export** in the Data stewardship section. AI-FDE verifies each
evidence object's SHA-256 hash and downloads a deterministic ZIP containing:

- `manifest.json` with the schema version, export identifier, fingerprint, and counts;
- `records.json` and `records.yaml` with the engagement's structured state;
- every current Markdown implementation-packet artifact;
- audit history available at export time; and
- original evidence files under engagement-scoped paths.

AI-FDE records the archive hash, source fingerprint, byte count, record count, and evidence-object
count. Any later business-state change makes the export stale and requires a fresh download before
deletion. Job and export-audit churn do not invalidate unchanged business state.

## Permanent deletion

Deletion is enabled only when the authenticated operator is the owner, retention does not block the
operation, and the latest export matches current business state. The owner must type the exact
engagement name and acknowledge that content cannot be restored.

The operation first write-blocks the engagement, then removes evidence objects idempotently, and
finally cascade-deletes engagement-owned PostgreSQL rows. A successful response displays a receipt
containing only identifiers, classification, counts, export hash, status, and timestamps. Customer
name, outcome, evidence, model content, free-form reasons, and detailed audit payloads do not survive.

If object or database removal fails, the receipt records a bounded failure code and the engagement
remains write-blocked. Resolve the infrastructure failure and use **Retry permanent deletion**. Do
not create new business state in a failed-deletion engagement.

## Current readiness boundary

Sanitized customer data remains disabled. This lifecycle is necessary but not sufficient for a
design partner; live Auth0 verification, accessibility, sensitive-telemetry review, and a clean-
environment rehearsal must also pass.
