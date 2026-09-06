# Production-Equivalent Staging Runbook

## Purpose

Replace proposed Auth0, AWS, workload-identity, deployment, recovery, deletion, and Bedrock
decisions with release-bound live evidence. Sanitized data remains disabled throughout staging.

## Required owners and inputs

- Security/release owner with stop authority.
- Cloud owner using short-lived federated AWS credentials.
- Auth0 tenant owner.
- AI platform owner for the fixed Bedrock evaluation.
- Exact 40-character Git commit, immutable web/API/worker image digests, one canonical nonzero
  worker engagement UUID, and one canonical accountless regional Bedrock `foundation-model` ARN.
- Previous known-good image digests and a schema-compatible rollback decision.
- Completed Auth0, restore, deletion, secret-rotation, and prior-worker-session-revocation JSON
  records conforming to KMS-signed `fdlc.production-qualification-evidence/v2`.
- Exact evidence-issuer role/signing-key ARNs and the sorted complete list of superseded
  release-scoped worker task-role ARNs. The first deployment uses an explicit empty list.

Do not put credentials, access tokens, model payloads, customer evidence, or raw prompts in the
readiness record.

## Execution order

1. Run the clean local rehearsal on the release commit.
2. Build each image from that commit and publish by digest, never by mutable tag.
3. Apply reviewed Terraform with `sanitized_data_enabled = false`.
4. Run the migration as the migration identity and verify the Alembic revision. With a configured
   worker engagement, bootstrap must grant the service operator membership before binding that exact
   engagement. Without one, bootstrap retains a null pre-onboarding binding and the worker must not
   report `RUNNING`.
5. Validate the live Auth0 tenant using the Auth0 runbook and retain its controlled JSON record.
6. Run the fixed synthetic Bedrock evaluation and retain the completed evaluation job ARN or ID.
7. Exercise the isolated RDS restore, evidence reconciliation, deletion boundary, secret rotation,
   alarms/dashboard, and rollback using the production operations runbooks.
8. Run the machine verifier below.
9. Confirm `api_runtime_secret_version_id` and `migration_runtime_secret_version_id` still equal
   the signed rotation envelope and the sole `AWSCURRENT` versions. Set only
   `pending_qualification_record_version_id` to the emitted immutable VersionId while
   sanitized data remains false. Run the fixed migration broker to persist the derived validation
   ID. Then set the same VersionId as `active_qualification_record_version_id` and enable sanitized
   data in a second change; pending and active must match at final activation.
10. Run the post-activation verifier. It must find a fully stopped, exit-zero migration using the
    exact pending migration task-definition revision, while independently rejecting any active
    standalone or stale task. Have the independent qualifier review both records.
11. Complete the design-partner go/no-go record. Any empty or failed item is NO-GO.

## Machine readiness gate

```bash
PYTHONPATH=src uv run python -m scripts.verify_design_partner_readiness \
  --region us-east-1 \
  --application-url https://staging.example.com \
  --bucket <evidence-bucket> \
  --evidence-kms-key-arn <evidence-kms-key-arn> \
  --evidence-bucket-policy-sha256 <evidence-bucket-policy-sha256> \
  --db-instance <rds-instance> \
  --rds-boundary <terraform-output-rds-boundary.json> \
  --cluster <ecs-cluster> \
  --ecs-role-boundary <terraform-output-ecs-role-boundary.json> \
  --web-service web \
  --api-service api \
  --worker-service worker \
  --migration-task-definition-arn <terraform-output-migration-task-definition-arn> \
  --git-commit <40-character-commit> \
  --deployment-id <deployment-record-id> \
  --web-image <registry/web@sha256:digest> \
  --api-image <registry/api@sha256:digest> \
  --worker-image <registry/worker@sha256:digest> \
  --worker-operator-id <canonical-worker-operator-uuid> \
  --worker-engagement-id <canonical-engagement-uuid> \
  --bedrock-evaluation-job <completed-job-id-or-arn> \
  --bedrock-model-id <evaluated-foundation-model-id> \
  --bedrock-model-arn <exact-accountless-regional-foundation-model-arn> \
  --api-secret <api-secret-arn> \
  --migration-secret <migration-secret-arn> \
  --qualification-secret <qualification-secret-arn> \
  --qualification-secret-policy-sha256 <terraform-output-policy-sha256> \
  --qualification-control-boundary <terraform-output-qualification-control-boundary.json> \
  --qualifier-role-arn <qualifier-role-arn> \
  --deployment-role-arn <deployment-role-arn> \
  --worker-task-role-arn <release-scoped-worker-role-arn> \
  --worker-network-boundary <terraform-output-worker-network-boundary.json> \
  --prior-worker-task-role-arn <superseded-worker-role-arn> \
  --evidence-issuer-role-arn <evidence-issuer-role-arn> \
  --evidence-signing-key-arn <evidence-signing-key-arn> \
  --oidc-issuer-url https://<tenant>/ \
  --oidc-client-id <oidc-client-id> \
  --oidc-allowed-email <allowlisted-operator-email> \
  --auth0-validation-record <controlled-path>/auth0.json \
  --restore-rehearsal-record <controlled-path>/restore.json \
  --deletion-rehearsal-record <controlled-path>/deletion.json \
  --secret-rotation-record <controlled-path>/rotation.json \
  --prior-worker-revocation-record <controlled-path>/prior-worker-revocation.json \
  --output <controlled-record-path>/design-partner-readiness.json
```

Replace the prior-role argument with `--no-prior-worker-task-roles` for a first deployment. Repeat
it in sorted order on rotation. Candidate and activation both consume the raw worker-network,
RDS, qualification-control, and ECS-role Terraform outputs. The ECS-role output pins all four task
and execution role ARNs and the exact live-verifiable API/migration IAM policy inventories.
Both passes also receive the exact `qualification_secret_policy_sha256` and must agree on every
boundary.

The verifier fails unless the release commit/deployment/qualification mode exactly match every ECS
task, images are immutable, deployment rollback and version consistency are enabled, S3 versioning
has bounded noncurrent expiry, the Bedrock evaluation is complete for the configured model, API,
worker, and migration tasks share the exact engagement boundary while web receives none, and every
external JSON record has the expected type-specific schema, KMS signature, issuer/key,
revision/deployment/freshness, and digest. Live IAM simulation must also prove exact-prefix S3,
exact-ARN Bedrock, exact RDS DB-user allow/deny boundaries, and denial of all current authority to
every listed prior worker role. The qualifier also verifies exact trust and inline-policy digests
for the qualifier, evidence issuer, and deployer; rejects any managed policy, instance profile,
permissions boundary, or extra inline policy; and proves that only the issuer can KMS-sign while
only the qualifier can publish a version. Cluster-wide `RUNNING` and `STOPPED` enumeration must be
complete. Fully stopped history is classified; any task that is still active, including a
desired-`STOPPED` task whose task or container is not actually stopped, is NO-GO.
The verifier must run as the separate qualifier role and writes the strict record to its dedicated,
write-restricted Secrets Manager secret.

## Live scenarios

- Successful and denied Auth0 login; allowlist; expiry; logout; revocation; callback validation.
- Worker startup succeeds only through RDS IAM as the release-scoped worker task role, matching
  operator GUC, active
  service operator, exact configured engagement binding, release revision, deployment ID,
  validation digest, and operator membership. Attempt forged release/deployment/digest heartbeats
  with the worker login, then repeat with the API login and after deactivation; all must be rejected.
- Worker `GetObject` and `GetObjectVersion` allowed for its assigned
  `engagements/<uuid>/evidence/*` prefix; a different engagement,
  `ListBucket`, and `GetBucketLocation` denied; KMS decrypt allowed through regional S3 and denied
  without that service context.
- Worker `bedrock:InvokeModel` allowed for the one configured ARN and denied for a concrete alternate
  model ARN; denied access from web/API roles where not required.
- Rolling replacement and automatic circuit-breaker rollback.
- Failed worker job, provider outage, and exhausted retry alert.
- Isolated RDS restore with RLS, a known audit record, and published package/artifact digest checked.
- Export and permanent deletion with the documented backup-expiry boundary.
- API/owner secret rotation and worker workload-role revocation with prior authority rejection.
- Metadata-only logs reviewed for evidence, prompt, credential, cookie, and token leakage.

## Stop conditions

Stop immediately for cross-engagement access, raw-content telemetry, unauthorized approval,
provider fallback, image mismatch, disabled rollback, incomplete restore/deletion, or a Bedrock model
that differs from the completed evaluation. Keep sanitized data disabled and issue a new readiness
record after remediation.

## Exit evidence

- Immutable `design-partner-readiness-v5` JSON tied to the release commit, deployment ID, runtime
  environment, image digests, and all five complete signed evidence envelopes, plus a passing
  post-activation record proving the enabled ECS/HTTPS configuration uses that exact secret
  version. The payload must remain at or below the Secrets Manager 64 KiB ceiling.
- Access-controlled, independently reviewed Auth0, restore, deletion, secret-rotation,
  prior-worker-revocation, and Bedrock evaluation records.
- Completed independent review and go/no-go record.
- Previous-image rollback target and accountable incident contacts.

Use [controlled production operations](design-partner-production-operations.md),
[isolated restore drill](isolated-restore-drill.md), [secret rotation](secret-rotation-and-revocation.md),
and [qualification evidence records](qualification-evidence-records.md). Code and local tests do not
satisfy any live external gate.
