# Engagement Data Lifecycle

Only the engagement owner can set retention, generate a portability export, or permanently delete
an engagement. Operators and viewers may inspect lifecycle status but cannot perform these actions.

## Retention

AI-FDE does not choose a contractual retention duration. The owner records an explicit, timezone-
aware `retain until` deadline agreed for the engagement. V1 permits extending that deadline and
rejects attempts to shorten it. Once a design-partner qualification is provisioned, its absolute
`retention_expires_at` is immutable and becomes the maximum authorized deadline; neither an owner
nor a direct runtime database write can extend the engagement past that ceiling. Upload,
worker-processing, package-publication, and package-retrieval gates recheck both deadlines and fail
closed if either is expired or the engagement exceeds the qualification ceiling. A future deadline
blocks deletion.

An unset deadline permits deletion for synthetic V1 workspaces. Legal holds, organization-wide
policy templates, and automated expiry jobs are not implemented and must not be implied.

## Portability export

Select **Generate & download export** in the Data stewardship section. AI-FDE reads each evidence
asset's persisted object version, verifies its SHA-256 hash, and downloads a deterministic ZIP
containing:

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
engagement name and acknowledge that the application will not restore the engagement.
Infrastructure recovery copies remain subject to the bounded backup lifecycle below; do not
describe the operation as immediate physical erasure.

The operation first write-blocks the engagement, then paginates every object version and delete
marker under that engagement's exact S3 evidence prefix. It deletes each exact version, re-lists the
prefix, and refuses success unless the prefix is physically empty. Only then does it cascade-delete
engagement-owned PostgreSQL rows. A successful response displays a receipt containing only
identifiers, classification, counts, export hash, status, and timestamps. Customer name, outcome,
evidence, model content, free-form reasons, and detailed audit payloads do not survive.

If object or database removal fails, the receipt records a bounded failure code and the engagement
remains write-blocked. Resolve the infrastructure failure and use **Retry permanent deletion**. Do
not create new business state in a failed-deletion engagement.

The production stack enables S3 versioning for recovery while an engagement is active. Successful
permanent deletion removes current, noncurrent, untracked, and delete-marker versions from the
engagement prefix; an earlier VersionId must no longer be retrievable. The configured noncurrent
lifecycle remains defense in depth for an interrupted operation, not the successful deletion
boundary. Deleted PostgreSQL rows remain recoverable through the 7-day RDS automated-backup/PITR
window. The deletion rehearsal must prove zero remaining application rows, object versions, and
delete markers and emit a digest-bound `deletion-boundary-rehearsal` JSON for the release; contract
and UI language must match it.

## Current readiness boundary

Sanitized customer data remains disabled. This lifecycle is necessary but not sufficient for a
design partner; live Auth0 verification, accessibility, sensitive-telemetry review, and a clean-
environment rehearsal must also pass.
