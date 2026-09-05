# Controlled Design-Partner Production Operations

**Implementation status:** code-defined, not live-qualified. This runbook does not authorize
sanitized data. A release remains NO-GO until every external gate below has a release-bound passing
record and the independent release owner approves it.

## Operating boundary and owners

This is a single-region, single-account controlled design-partner service. It is not a general
customer production tier. `AI_FDE_DEPLOYMENT_QUALIFICATION_MODE=controlled-design-partner` records
deployment provenance; it is never an authorization bypass or a feature flag.

| Role                | Accountable for                                                       | Stop authority                                             |
| ------------------- | --------------------------------------------------------------------- | ---------------------------------------------------------- |
| Technical on-call   | ECS, ALB, API, worker, database availability, rollback                | outage, unsafe deploy, dependency failure                  |
| Security on-call    | Auth0, denial review, secrets, cross-engagement or telemetry exposure | any identity, isolation, or disclosure concern             |
| Integration on-call | Immutable package retrieval and Mission Control pull/import result    | digest drift, stale/revoked package, non-idempotent import |
| Cloud owner         | AWS account, KMS, RDS recovery, S3 lifecycle, Terraform state         | backup, restore, encryption, or state failure              |
| Release owner       | exact revision/deployment binding, evidence review, GO/NO-GO          | any incomplete or stale qualification record               |

One person may cover multiple on-call roles during the bounded pilot, but the release reviewer must
not be the person who deployed the release. Put current names and paging destinations in the private
incident roster, not in source control.

## Service signals and response contract

Terraform creates the `${project}-${environment}-operations` dashboard and the alarms below. Alarm
actions are absent by default. Set `alarm_topic_arn` only to an existing, access-controlled paging
topic. Set `backup_event_topic_arn` only to a separate non-paging operations topic because routine
RDS backup events are expected. Missing metric data is not treated as healthy evidence; staging must
inject each event and prove the metric, alarm transition, route, and recovery.

| Signal                            | Threshold                                                                                | Owner / severity                                  | First response                                                                                                                                                                                                                                                               |
| --------------------------------- | ---------------------------------------------------------------------------------------- | ------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Web or API unhealthy target       | at least 1 unhealthy target for 2 consecutive 60-second periods                          | Technical / P1                                    | Check `/api/ready`, ECS deployment events, task logs, and dependencies. Roll back the exact task revision if release-related.                                                                                                                                                |
| ALB-generated 5xx                 | at least 5 in each of 2 consecutive 5-minute periods                                     | Technical / P1                                    | Inspect ALB/ECS health and recent infrastructure change. Stop admission if availability is uncertain.                                                                                                                                                                        |
| Web/API target 5xx                | at least 5 target responses in each of 2 consecutive 5-minute periods                    | Application / P1                                  | Identify the failing target/release from ALB and metadata-only runtime logs; roll back if release-related.                                                                                                                                                                   |
| API 5xx                           | at least 5 `http.request.completed` 5xx events in each of 2 consecutive 5-minute periods | Application / P1                                  | Use request/correlation/trace IDs and bounded failure codes. Never copy request content into the incident.                                                                                                                                                                   |
| Repeated authorization denial     | at least 5 `auth.denied` events in each of 2 consecutive 5-minute periods                | Security / P2, P1 if active abuse or IdP outage   | Distinguish expected denied tests from abuse or Auth0 failure; revoke sessions/credentials if needed.                                                                                                                                                                        |
| Workflow or dependency failure    | any `workflow.job.failed` or `workflow.dependency_failed` event in 5 minutes             | Application / P1 for pilot-blocking work          | Stop the affected workflow, preserve its immutable inputs, check dependency health, and retry only under the normal attempt policy.                                                                                                                                          |
| Mission Control ingestion failure | any `mission_control.ingestion_failed` event in 5 minutes                                | Integration / P1                                  | Keep the package immutable, inspect the safe failure class, and retry the pull with the same package identity/idempotency key. Never auto-approve or dispatch. This alarm is dormant until MC forwards metadata-only importer events to the dedicated integration log group. |
| RDS backup/failure/recovery event | every event, routed only when `backup_event_topic_arn` is set                            | Cloud / P2; P1 for failed backup or impaired PITR | Confirm latest restorable time, automated-backup state, and storage health. Open a recovery incident if the RPO target is at risk.                                                                                                                                           |

`http.request.completed`, `auth.denied`, `workflow.dependency_failed`, and
`mission_control.ingestion_failed` are stable metadata-only event names. Changes require matching
Terraform, telemetry tests, alarm-injection evidence, and this table in one release.

Runtime logs carry bounded request/correlation/trace identifiers, durations, routes, outcomes, and
failure codes; CloudWatch filters turn only the stable event names into low-cardinality metrics.
There is no span exporter or distributed-tracing backend in this bounded pilot. `trace_id` is a
correlation value, not proof of an end-to-end sampled trace. That limitation is acceptable only
while the pilot has one application boundary and a named on-call owner; do not claim
X-Ray/OpenTelemetry coverage, and add it before service fan-out makes log correlation insufficient.

Mission Control owns the true human-triggered pull/import boundary. AI-FDE retrieval denials are
authorization outcomes and must not be mislabeled as ingestion failure. Terraform creates
`/integration/${project}-${environment}/mission-control` as the dedicated metadata-only source for
forwarded MC importer events, but does not grant cross-system write access. The MC export/destination,
least-privilege writer, and live alarm injection remain external gates.

### Incident sequence

1. Acknowledge and name the incident owner. For P0/P1, pause new pilot work and customer ingestion.
2. Record exact `AI_FDE_RELEASE_REVISION`, `AI_FDE_DEPLOYMENT_ID`, task-definition ARNs, UTC start
   time, and alarm names. Do not record credentials or customer content.
3. Decide whether the fault is deployment, dependency, identity, data integrity, or provider.
4. Roll back images only when the previous schema is compatible. Never restore production over the
   current database and never bypass qualification or package approval.
5. Verify `/api/live`, `/api/ready`, `/api/version`, worker queue progress, and the failed domain
   flow. Continue only after the signal is normal and the integrity check passes.
6. For cross-engagement access, secret exposure, raw-content telemetry, digest drift, or unexplained
   data loss: treat as P0, revoke access, preserve metadata-only evidence, and keep sanitized data
   disabled until independent review.

## Authoritative, recoverable, and reconstructable state

| Class                                | Examples                                                                                                                                                         | Recovery source                                                                                  | Rule                                                                                                                                                                                                                                |
| ------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Authoritative durable PostgreSQL     | engagements/members, evidence metadata, reviewed claims and immutable versions, decisions/approvals, qualification state, package versions, audit/outbox records | RDS Multi-AZ plus 7-day automated PITR                                                           | Never reconstruct approved truth from model output or logs. Restore and verify exact records.                                                                                                                                       |
| Authoritative durable S3             | acknowledged evidence bytes and generated export objects                                                                                                         | persisted object versions encrypted by the dedicated evidence CMK while the engagement is active | TLS, exact-version reads, and explicit exact-key SSE-KMS headers are mandatory. Permanent deletion paginates and physically purges every version and delete marker under the exact engagement prefix, then proves the prefix empty. |
| Rebuildable but provenance-sensitive | parsed segments, candidates, generated artifacts before approval                                                                                                 | original evidence plus pinned parser/model/revision                                              | Rebuild only as a new run/version. Do not silently replace an approved or published version.                                                                                                                                        |
| Reconstructable runtime              | ECS services/tasks, ALB routing, security groups, alarms, dashboards                                                                                             | reviewed Terraform plus immutable image digests                                                  | Reapply reviewed code; never use console-only configuration as the source of truth.                                                                                                                                                 |
| Non-authoritative operational data   | metadata-only CloudWatch logs/metrics, traces, dashboards                                                                                                        | runtime emission; logs retain 30 days                                                            | Useful for diagnosis, never proof of business approval or package integrity.                                                                                                                                                        |
| External control-plane state         | Terraform backend, DNS/certificate, Auth0 tenant, SNS subscriptions, ECR image retention                                                                         | owner-specific backup/export/process outside this stack                                          | Must have named owner and release evidence. The application stack does not back these up.                                                                                                                                           |

S3 versioning is recovery protection, not immutable archive/WORM storage. Permanent application
deletion physically purges the engagement's historical versions and delete markers; the configured
noncurrent-version lifecycle is defense in depth for interrupted cleanup. RDS-deleted rows remain
recoverable until their backup/PITR expiry. Legal hold and cross-region disaster recovery are not
implemented.

## Recovery objectives

These are pilot objectives, not proven guarantees. A failed or overdue drill is a NO-GO.

| Surface                                              | Target RPO                               | Target RTO                                         | Required proof                                                                                                                       |
| ---------------------------------------------------- | ---------------------------------------- | -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| PostgreSQL business truth                            | no more than 15 minutes                  | no more than 4 hours                               | live `LatestRestorableTime` within target and an isolated PITR drill that verifies a known audit record plus package/artifact digest |
| Acknowledged evidence object, regional failure model | 0 after a successful S3 write            | 2 hours for an approved accidental-delete recovery | versioning/KMS/lifecycle verification plus controlled object-version recovery rehearsal                                              |
| Application release                                  | exact immutable revision; no data replay | 30 minutes                                         | ECS circuit-breaker and previous-digest rollback rehearsal with schema compatibility                                                 |
| Metadata-only telemetry                              | up to 5 minutes                          | 1 hour                                             | dashboard and alarm injection; telemetry is not a source of business truth                                                           |

A regional AWS disaster, KMS loss, or account compromise is outside these objectives because no
cross-region/account backup exists. Do not promise a broader recovery boundary to a design partner.

## Secret inventory and lifecycle

| Secret / credential                 | Owner                        | Runtime scope                                                                                                                                       | Rotation / revocation proof                                                                                                                                                                                                      |
| ----------------------------------- | ---------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| RDS managed master secret           | Cloud owner                  | bootstrap/recovery only; never API or worker                                                                                                        | rotate at least every 90 days and after privileged use; prove old version rejected                                                                                                                                               |
| API `AI_FDE_DATABASE_URL`           | Security + DB owner          | API execution role, application DB role                                                                                                             | rotate at least every 90 days or on suspicion/personnel change; replace task and reject old password                                                                                                                             |
| API `AI_FDE_OIDC_CLIENT_SECRET`     | Auth0 owner                  | API execution role only                                                                                                                             | rotate in Auth0 and Secrets Manager with bounded overlap; revoke old secret and test login/logout                                                                                                                                |
| Worker `AI_FDE_DATABASE_URL`        | Security + DB owner          | passwordless RDS IAM URL for the release-scoped `ai_fde_worker_<12-hex>` login derived from deployment ID plus revision; `ai_fde_worker` is NOLOGIN | bootstrap retires prior database logins/sessions; quarantine prior IAM roles and prove captured credentials denied                                                                                                               |
| Migration URL and API DB password   | Cloud/DB owner               | one-off migration execution role only; never a worker credential                                                                                    | issue for controlled migration/bootstrap, rotate after privileged use, stop all migration tasks                                                                                                                                  |
| Deployment authority                | Release owner                | short-lived federated role; no checked-in access key                                                                                                | revoke federation/session and role assumption on incident; audit CloudTrail principal                                                                                                                                            |
| ECS task credentials for S3/Bedrock | Cloud owner                  | per-task IAM role; no static key                                                                                                                    | replace/revoke role policy and tasks; worker S3 is one exact engagement prefix with no bucket enumeration and evidence-CMK decrypt only via regional S3 plus the exact bucket context; Bedrock invocation is one exact model ARN |
| Restore-verifier URL files          | Cloud/DB owner               | short-lived application-role files on the isolated verifier host                                                                                    | mode `0600`, delete through the approved secure-workstation procedure immediately after drill                                                                                                                                    |
| Mission Control receiving secret    | Integration + security owner | existing secret; migration role has `PutSecretValue` on only its configured ARN                                                                     | access policy/KMS verified, no value in output, Terraform, or logs                                                                                                                                                               |
| Mission Control retrieval grant     | Integration + security owner | one engagement-bound viewer-only importer identity                                                                                                  | server-enforced expiry within 24 hours, direct secret-store delivery, replacement retrieval success, prior grant revoked                                                                                                         |

Secret values never belong in Terraform variables/state, source control, shell history, command-line
arguments, readiness JSON, CloudWatch, tickets, or screenshots. Record only secret ARN, owning role,
rotation timestamp, outcome, and a sanitized evidence reference. Follow
[Secret rotation and revocation](secret-rotation-and-revocation.md) for the executable sequence.

## Deployment and rollback gates

Before deployment, capture read-only baseline counts by qualification status, queued/running jobs,
published packages, and unresolved pilot blockers. Save only counts and identifiers in the release
record. Confirm the migration is backward-compatible with both current and previous image digests.

Within five minutes after deployment:

- `/api/live`, `/api/ready`, and `/api/version` return the intended status, exact revision,
  deployment ID, validation digest, and qualification mode;
- every running task definition uses the expected image digest and release environment values;
- the API, worker, and migration tasks carry the same canonical `AI_FDE_WORKER_ENGAGEMENT_ID`, while
  web does not; IAM
  simulation allows worker reads only within that S3 prefix, denies bucket enumeration and direct
  KMS decrypt, and allows Bedrock invocation only for the configured concrete ARN;
- the migration revision is exact; services are at desired count; the worker advances a synthetic
  job; and no target is unhealthy;
- expected authorization denial and safe failure injections reach the dashboard/alarms;
- one synthetic package retrieval/import preserves digest and idempotency and remains a Mission
  draft, not execution authority.

Rollback means redeploying the previous immutable image digests after proving schema compatibility.
It does not mean reversing approved business state. If database state must be recovered, open a
separate incident and use the isolated restore procedure; never overwrite production in place.

## Remaining external gates — exact NO-GO list

None of these are satisfied by source code or local tests:

- [ ] Dedicated AWS account/region, remote Terraform state durability/locking/versioning, DNS,
      certificate, CloudTrail, budget, and federated deployment authority reviewed live.
- [ ] The platform owner explicitly accepts the stack's single zonal NAT egress dependency for the
      bounded pilot or provisions independently routed per-AZ egress before claiming zonal egress
      resilience.
- [ ] Reviewed Terraform plan applied with exact release revision/deployment ID and sanitized data
      disabled; service, IAM, network, encryption, deletion-protection, lifecycle, and rollback state
      independently inspected.
- [ ] Auth0 live tenant passes login, callback, allowlist denial, cookie, expiry, logout, and session
      revocation; `auth0-live-validation` JSON is current and digest-bound to the release.
- [ ] Exact regional accountless Bedrock foundation model passes the fixed evaluation; invocation logging is off;
      allowed data classification and regional processing terms are approved; IAM simulation allows
      its exact ARN and denies a concrete alternate ARN.
- [ ] One nonzero canonical worker engagement UUID is bound identically in Terraform, API, worker,
      migration, and the owner-managed database binding. That binding also pins the exact release,
      deployment, and validation digest. IAM simulation permits only that evidence prefix, denies
      another engagement and bucket enumeration, and constrains KMS decrypt to regional S3 plus
      the exact evidence-bucket ARN encryption context. Live S3 inspection confirms the dedicated
      key and denies non-TLS, missing/wrong SSE algorithm, and missing/wrong key-ID writes.
- [ ] Isolated RDS PITR drill meets RPO/RTO and produces a passing
      `isolated-restore-rehearsal` JSON; evidence-object version recovery/reconciliation also passes.
- [ ] Export/deletion rehearsal proves the S3 noncurrent-version and RDS backup-expiry customer
      boundary and produces `deletion-boundary-rehearsal` JSON.
- [ ] All runtime and privileged secrets are rotated/revoked and produce a
      `runtime-secret-rotation` JSON; prior credentials demonstrably fail.
- [ ] Every superseded worker IAM role has a signed `prior-worker-session-revocation` record. The
      record proves the exact assumption-deny/grant-stripped cutoff quarantine and captured-session
      denials, or deletion only after maximum session TTL plus propagation. Ordinary Terraform
      rotation must stop at `prevent_destroy` until the deliberate quarantine handoff is complete.
- [ ] Every alarm and both notification routes are injected and acknowledged by named owners;
      latest RDS restorable time remains within 15 minutes.
- [ ] Previous-image rollback and forward recovery meet the 30-minute target without data loss.
- [ ] PostgreSQL acceptance/isolation suites, clean migration upgrade/downgrade/re-upgrade, Python
      static checks, frontend build/browser/accessibility checks, and Terraform validation pass on
      the exact revision with no required test skipped.
- [ ] Mission Control pull/import is validated in its real environment with exact package digest,
      issuer, freshness, idempotency, denial, revocation, and failure evidence; import creates draft
      intent only. A secure production provisioning/rotation path must deliver the one-time grant
      directly to its managed secret store; the deployed HTTP API does not return credentials.
- [ ] Contractual classification, retention, subprocessor, incident contact, and deletion language
      match the implemented regional/backup boundaries; one workflow and accountable FDE are named.
- [ ] An independent qualifier verifies all five external JSON records and publishes one immutable
      `design-partner-readiness-v5` secret version. The record retains all signed envelopes and is
      rejected above 64 KiB. Only then may a reviewed two-stage change bind
      that exact version, bootstrap its derived validation ID, enable sanitized data, and produce a
      passing post-activation ECS/HTTPS record.

Any unchecked item is NO-GO. No live AWS, Auth0, Bedrock, restore, rotation, alert, Mission Control,
or customer-data action was performed by implementing this runbook.
