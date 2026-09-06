# Design-Partner Go/No-Go Record

**Current repository state (2026-09-04): NO-GO for sanitized customer data.**

Use one copy of this record per deployed release. A local test, Terraform validation, or unchecked
record cannot be interpreted as approval. Never record credentials, tokens, customer evidence, or
raw model requests/responses here.

## Release identity

| Field                              | Value |
| ---------------------------------- | ----- |
| Environment                        |       |
| Git commit                         |       |
| Deployment ID / qualification mode |       |
| Web/API/worker image digests       |       |
| AWS account and region             |       |
| Worker engagement UUID             |       |
| Accountless regional Bedrock foundation-model ID and exact ARN |       |
| FDE owner                          |       |
| Validation date/time               |       |

## Implemented-code gates

- [ ] Full Python tests, RLS/isolation tests, Ruff, and mypy pass.
- [ ] Frontend lint, clean typecheck, production build, and accessibility checks pass.
- [ ] Alembic clean upgrade, safe downgrade, re-upgrade, and `alembic check` pass.
- [ ] Terraform formatting and validation pass for the release commit.
- [ ] Images are built from the release commit and referenced by digest.
- [ ] Every task reports the exact release revision, deployment ID, and
      `controlled-design-partner` qualification mode.
- [ ] ECS task definitions match those digests, enforce version consistency, and enable automatic
      deployment rollback.
- [ ] Coding-agent execution and autonomous remediation remain disabled.

## Live identity and deployment gates

- [ ] Auth0 live-tenant JSON is current and digest-bound; path/digest: `________________`.
- [ ] HTTPS, callback, cookie, allowlist, logout, revocation, and unauthenticated behavior pass.
- [ ] Web, API, worker, migration, and deployment roles are distinct and least privilege.
- [ ] The migration caller has only `states:StartExecution` on the exact Terraform-owned broker;
      the broker hardcodes the migration task-definition revision, cluster, private subnets,
      migration security group, disabled public IP, disabled ECS Exec, and no container overrides.
      Its execution role alone owns the exact `ecs:RunTask`/`iam:PassRole` boundary and the
      execution must finish with container exit code zero.
- [ ] Worker is an active service identity with only explicit operator memberships.
- [ ] Worker startup proves `session_user = current_user =
      ai_fde_worker_<first-12-hex-of-sha256(deployment-id:release-revision)>`, membership in the
      NOLOGIN `ai_fde_worker` privilege group, rejection of the API/shared-password login, and matches the
      owner-bound operator, engagement, release revision, deployment ID, and
      validation digest to one active operator membership. The bootstrap's null binding cannot
      publish a `RUNNING` heartbeat.
- [ ] Every `RUNNING` heartbeat rechecks that database-bound authority; deactivation, a null or
      mismatched binding, or membership removal stops fresh readiness heartbeats.
- [ ] API, worker, and migration carry the same nonzero canonical engagement UUID; web does not.
      Worker IAM simulation
      allows `GetObject` only under that engagement, denies a different engagement plus
      `ListBucket`/`GetBucketLocation`, and permits evidence-key decrypt only through regional S3
      with the exact evidence-bucket ARN encryption context.
- [ ] ECS tasks have no public IP; RDS is private, encrypted, TLS-forced, Multi-AZ, and PITR-ready.
- [ ] Worker AWS traffic uses only the reviewed private endpoints/security groups; worker HTTPS has
      no `0.0.0.0/0` egress. API readiness reports the exact pinned AWS RDS CA path and digest.
- [ ] Complete cluster-wide `RUNNING` and `STOPPED` enumeration proves that every active task is one
      healthy current web/API/worker service task and the migration family has no active task.
      Fully stopped migration, prior-revision, and other history is classified in the record; a
      desired-`STOPPED` task whose task or container is not actually stopped is NO-GO.
- [ ] Every listed superseded worker role is denied the current RDS login, S3 read/write prefix,
      evidence-key decrypt/data-key context, and Bedrock model ARN.
- [ ] Every superseded role is either retained under an exact verified assumption-deny,
      grant-stripped `AWSRevokeOlderSessions` quarantine or deleted only after its maximum STS
      session TTL plus IAM propagation. Signed evidence retains the exact prior ARN/release,
      cutoff, session-expiry boundary, propagation timestamps, and six captured-session denials.
      A missing role alone is not proof that previously issued credentials are revoked.
- [ ] S3 blocks public access and non-TLS requests; every object write must explicitly name
      `aws:kms` and the exact dedicated rotating evidence CMK. Default encryption uses that same
      key, versioning is enabled, and noncurrent evidence expires within the approved 7–90 day
      boundary.
- [ ] Bedrock invocation logging is disabled and the selected model passed the fixed evaluation.
- [ ] The completed Bedrock evaluation job references the exact configured regional foundation model.
- [ ] Worker IAM simulation allows `bedrock:InvokeModel` for exactly the configured concrete ARN and
      denies a concrete alternate ARN; the Terraform input contains no wildcard.
- [ ] Runtime secrets were rotated and the prior version was invalidated; JSON path/digest:
      `________________`.
- [ ] API and migration each have exactly one `AWSCURRENT` version matching the signed rotation
      record; settled task definitions were registered after those exact versions. Activation
      re-lists and compares the same version inventory.
- [ ] The qualification secret resource policy exactly matches the Terraform digest. Live qualifier,
      evidence-issuer, and deployer roles match their exact trust/inline-policy digests, carry no
      extra attached/inline policy, profile, or boundary, and simulations prove only the evidence
      issuer can sign while only the qualifier can publish the immutable version.

## Recovery and deletion gates

- [ ] Isolated RDS restore passed with RLS, a known audit record, and package/artifact digest;
      JSON path/digest: `________________`.
- [ ] Evidence restore/reconciliation passed without cross-engagement access.
- [ ] Sanitized golden-path export and deletion passed; JSON path/digest: `________________`.
- [ ] The RDS backup-expiry and S3 deletion boundaries match customer-facing retention language.
- [ ] Rollback to the previous image digests was rehearsed without schema or data loss.
- [ ] Dashboard and every availability, 5xx, auth-denial, dependency, Mission Control ingestion,
      and backup/recovery route were injected, received, and acknowledged by named owners.
- [ ] PostgreSQL latest restorable time and isolated drill meet the 15-minute RPO / 4-hour RTO.

## Automated readiness record

Run `scripts/verify_design_partner_readiness.py` with the release commit/deployment ID, immutable
image digests, worker engagement UUID, completed Bedrock evaluation job, configured model ID and
exact ARN, worker-network and ECS-role Terraform outputs, and five JSON paths above. A first deployment must
explicitly supply an empty prior-role set and an empty signed prior-worker role list.
Each external record must match the strict per-type
`fdlc.production-qualification-evidence/v2` schema and carry a valid signature from the configured
asymmetric AWS KMS key and evidence-issuer role; a digest-only file or free-form ID is not evidence.
Follow the
[production-equivalent staging runbook](production-equivalent-staging.md) for the exact command.

| Field                   | Value       |
| ----------------------- | ----------- |
| Qualification secret VersionId (64 hex) |             |
| Readiness + activation record locations |             |
| Machine-check result    | Pass / Fail |
| Reviewer                |             |

## Decision

- [ ] **GO:** every gate passed; bind the exact immutable qualification version while disabled,
      update the owner-managed database binding, enable sanitized data, and pass post-activation
      ECS/HTTPS verification.
- [ ] **NO-GO:** one or more gates are incomplete or failed; keep sanitized data disabled.

Decision owner: `________________` Date/time: `________________`

Notes or linked tickets (no sensitive content):
