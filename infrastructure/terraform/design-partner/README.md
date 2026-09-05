# Design-Partner AWS Deployment

This stack implements the accepted one-region AWS boundary for AI-FDE. It creates private Fargate
services, private Multi-AZ RDS PostgreSQL, a versioned KMS-encrypted evidence bucket, HTTPS ALB,
ECR, Secrets Manager, metadata-only CloudWatch logs/metrics/alarms/dashboard, and distinct
web/API/worker/migration IAM and network identities. The worker reaches AWS services through
private, policy-bounded VPC endpoints and has no public HTTPS egress. Separate deployment,
migration-caller, migration-broker, qualifier, and evidence-issuer principals keep release,
owner-database, approval, and evidence-signing authority apart. This stack does not make the
product sanitized-data ready by itself.

## Safety defaults

- `services_enabled=false` prevents tasks from starting before secrets and database roles exist.
- `sanitized_data_enabled=false` remains the default after services start.
- `api_runtime_secret_version_id` and `migration_runtime_secret_version_id` pin every ECS JSON-key
  selector to the exact VersionIds in signed rotation evidence. Moving `AWSCURRENT` alone never
  changes credentials in a settled task or a later task launch.
- `pending_qualification_record_version_id` is migration-only;
  `active_qualification_record_version_id` is API/worker-only. Each must be the verifier-emitted
  64-character immutable Secrets Manager version, and final activation requires equality. The
  runtime recomputes its validation ID from the strict record; free-form hashes are never accepted.
- S3, RDS, and ECS task roles have `prevent_destroy`; RDS and the ALB have deletion protection.
  Release rotation cannot silently destroy a superseded workload identity. Follow the explicit
  quarantine/state-handoff procedure below before Terraform may create its replacement.
- S3 versioning is enabled. A dedicated rotating evidence CMK is separate from database, secret,
  and image encryption. The bucket policy denies non-TLS traffic and every object write that omits
  the explicit `aws:kms` algorithm or exact evidence-key ARN. Noncurrent evidence expires after 30
  days by default and the input is constrained to 7–90 days. Delete markers are immediate logical
  deletion, not immediate erasure of prior versions. Bedrock invocation logging remains off and the
  live gate fails if it is enabled.
- Image inputs must be immutable ECR URIs with digests, not mutable tags.
- Every task definition enables ECS version consistency, and every long-running service enables
  deployment-circuit-breaker rollback.
- `release_revision`, `deployment_id`, and the fixed `controlled-design-partner` qualification mode
  are propagated to every task and checked live. The API, worker, and migration tasks also receive
  the non-secret worker engagement UUID; the web task receives neither. Once activated, Python
  runtimes receive the exact qualification secret version rather than a caller-supplied digest.
  Qualification mode is informational provenance, never authorization.
- Alarm notifications are opt-in through an existing `alarm_topic_arn`; routine RDS backup events
  use the separate optional non-paging `backup_event_topic_arn`. The external topics, restrictive
  publish policies, confirmed subscriptions, encryption, and delivery tests remain platform-owner
  responsibilities.
- The Mission Control ingestion alarm reads a dedicated integration log group. It remains dormant
  until Mission Control forwards metadata-only importer outcomes under separately reviewed
  least-privilege access; AI-FDE retrieval denials are not ingestion failures.
- `worker_engagement_id=null` gives the worker no S3 evidence policy. When one canonical, nonzero
  engagement UUID is set, the worker may `GetObject`/`GetObjectVersion` only under
  `engagements/<uuid>/evidence/*`; it cannot
  list the bucket or read its location, and KMS decrypt is usable only through regional S3 with the
  exact bucket-ARN encryption context. The worker cannot write or delete evidence. It has no network
  ingress; API, web, worker, and migration use separate security groups.
- Worker Bedrock authority is one canonical, accountless regional `foundation-model` ARN. Inference
  profiles, cross-region resources, wildcards, and account-qualified model ARNs are rejected.
- The migration task receives `secretsmanager:PutSecretValue` only when an exact existing
  `package_retrieval_target_secret_arn` is configured. It cannot create, read, list, or delete
  secrets through that policy. For a customer-managed receiving key, configure its exact ARN in
  `package_retrieval_target_kms_key_arn`; KMS use is then restricted to Secrets Manager and that
  secret's encryption context.

## Bootstrap and deploy

1. Create a separate encrypted S3 state bucket and DynamoDB lock table using your platform
   bootstrap process. They are intentionally outside this stack's lifecycle.
2. Build and push the three images. Build the web image with
   `NEXT_PUBLIC_AI_FDE_API_URL=https://<domain>/api`.
3. Copy `terraform.tfvars.example` to an untracked environment file and replace every placeholder,
   including the exact 40-character `release_revision`, stable `deployment_id`, canonical nonzero
   worker operator UUID, and the single pilot `worker_engagement_id`. Keep the worker engagement
   null until that boundary is approved; sanitized data cannot be enabled while it is null. Keep
   Bedrock classifications at `PUBLIC`/`INTERNAL` unless an explicit data review authorizes
   `CONFIDENTIAL`; `RESTRICTED` is rejected. Supply one concrete Bedrock ARN, never a wildcard.
4. Initialize remote state, then validate and plan:

   ```sh
   terraform init \
     -backend-config="bucket=<state-bucket>" \
     -backend-config="key=ai-fde/design-partner.tfstate" \
     -backend-config="region=<region>" \
     -backend-config="dynamodb_table=<lock-table>" \
     -backend-config="encrypt=true"
   terraform validate
   terraform plan
   terraform apply
   ```

5. Populate the two role-specific runtime secrets out of band. Use TLS-verifying PostgreSQL
   URLs for owner and API credentials. Set `api_runtime_secret_version_id` and
   `migration_runtime_secret_version_id` to their exact signed `AWSCURRENT` VersionIds before
   starting tasks. The worker uses short-lived RDS IAM authentication:

   - API secret: `AI_FDE_DATABASE_URL`, `AI_FDE_OIDC_CLIENT_SECRET`
   - Migration secret: `AI_FDE_MIGRATION_DATABASE_URL`, `AI_FDE_APP_DATABASE_PASSWORD`

6. Assume only the separate `migration_runner_role_arn`, then start the exact
   `migration_state_machine_arn` once with an empty JSON input:

   ```sh
   aws stepfunctions start-execution \
     --state-machine-arn <migration_state_machine_arn> \
     --name <unique-reviewed-execution-name> \
     --input '{}'
   ```

   The caller can only start this state machine. It cannot call `ecs:RunTask`, pass roles, register
   task definitions, or choose a task revision, cluster, subnet, security group, public-IP setting,
   execute-command setting, or container override. The Step Functions execution role owns the
   exact ECS launch and completion-event permissions; the state machine hardcodes the current
   Terraform task revision and private network boundary. Independently confirm that the execution
   reached `SUCCEEDED` and that the migration task exited zero. The task idempotently locks down
   `ai_fde_app`, creates the release-scoped RDS IAM worker login, retires prior worker
   logins/sessions, installs pgvector, and applies Alembic migrations.
7. Set `services_enabled=true`, plan, and apply. Confirm `/api/live`, `/api/ready`, and
   `/api/version` before onboarding an engagement.
8. The fixed bootstrap reads the approved `AI_FDE_WORKER_ENGAGEMENT_ID`, grants that service
   operator membership, and binds the exact deployment identity in the same owner-controlled run.
   Do not rerun it with a caller-supplied command override. The worker has neither a global database
   bypass nor S3 access to another engagement. Supporting another concurrently active engagement
   requires a separately scoped worker task/role, not broadening this one.
9. Before a Mission Control import, configure the exact existing receiving secret ARN. Retrieval
   grant rotation is an owner-only admin operation and is deliberately not accepted as input to the
   bootstrap broker. Run it only through a separately reviewed, fixed-command broker that retains
   the same exact task revision, private network, migration roles, and typed business-argument
   validation (the grant value is never printed):

   ```sh
   ai-fde-admin rotate-package-retrieval-grant \
     --engagement-id <engagement-uuid> \
     --owner-operator-id <human-owner-uuid> \
     --requester-identity <bound-importer-identity> \
     --requester-system mission-control \
     --expires-at <ISO8601-timestamp-with-timezone-within-24-hours> \
     --target-secret-arn <configured-receiving-secret-arn>
   ```

   A direct `ecs:RunTask` or bootstrap-broker command override is a NO-GO. The command atomically
   revokes prior grants and commits the replacement before direct `PutSecretValue` delivery. A
   delivery failure is fail-closed: do not recover the token from logs; correct delivery and rerun
   through its reviewed broker to rotate again.

## Sanitized-data release gate

Keep the application fail-closed until the Auth0, restore, deletion, secret-rotation, and
prior-worker-session-revocation procedures produce current strict, release-bound JSON records
signed by the independent evidence issuer's AWS KMS key. The first deployment still requires an
explicit signed prior-worker record with an empty `roles` list. Then run:

```sh
PYTHONPATH=src uv run python -m scripts.verify_design_partner_readiness \
  --region <region> \
  --application-url https://<domain> \
  --bucket <evidence-bucket> \
  --evidence-kms-key-arn <evidence-kms-key-arn> \
  --evidence-bucket-policy-sha256 <evidence-bucket-policy-sha256> \
  --db-instance <db-identifier> \
  --rds-boundary <terraform-output-rds-boundary.json> \
  --cluster <cluster> \
  --ecs-role-boundary <terraform-output-ecs-role-boundary.json> \
  --migration-task-definition-arn <terraform-output-migration-task-definition-arn> \
  --git-commit <40-character-commit> \
  --deployment-id <deployment-record-id> \
  --web-image <web-image@sha256:digest> \
  --api-image <api-image@sha256:digest> \
  --worker-image <worker-image@sha256:digest> \
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
  --worker-task-role-arn <release-scoped-worker-task-role-arn> \
  --worker-network-boundary <terraform-output-worker-network-boundary.json> \
  --prior-worker-task-role-arn <superseded-worker-task-role-arn> \
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
  --output <approved-record-path>
```

For the first deployment, replace `--prior-worker-task-role-arn ...` with
`--no-prior-worker-task-roles`. On rotation, repeat the role argument in sorted order for every
superseded release role and keep the signed evidence list identical.

The verifier also requires KMS-authenticated external evidence, the exact dedicated evidence CMK,
the bucket's TLS and explicit SSE-KMS/key-ID deny policy, S3 versioning/bounded noncurrent expiry,
an exact duplicate-free ECS environment/secret inventory, no active stale service or standalone
tasks,
private healthy services, the pinned RDS CA bundle, RDS PITR, role-separated secrets, and the
evaluated regional foundation model. It also requires every task definition to use the exact
Terraform task and execution role and re-reads the API and migration roles' exact trust, inline,
managed-policy, permissions-boundary, and instance-profile inventories. Cluster enumeration is
complete for both `RUNNING` and
`STOPPED`: every active task must be one healthy current service task, while fully stopped migration,
prior-revision, and other history is classified and retained in the record without treating bounded
historical volume as active authority. A desired-`STOPPED` task that is not fully stopped remains
NO-GO. IAM simulation must prove every explicitly supplied prior worker role is
denied the current deployment's exact RDS login, S3 prefix and KMS context, and Bedrock model. It
also proves the current worker can read only its exact S3 engagement prefix, cannot list the bucket,
can decrypt the evidence key only through S3, and can invoke only the exact Bedrock ARN. The verifier
deterministically derives `validation_id` as a SHA-256 digest over the passed record before adding
`validation_id` and `content_digest`; this avoids a circular self-hash while making the enablement
identity independently recomputable. The v5 record embeds all five complete signed envelopes and
their pinned public-key fingerprint, and publishing fails above the Secrets Manager 64 KiB limit.
Review the final `design-partner-readiness-v5` record. The
qualifier writes it as an immutable secret version whose VersionId is derived from the strict
claims. First set only `pending_qualification_record_version_id` to that exact version while
sanitized data remains disabled; this changes only the migration task/broker. Start a new execution
of the fixed migration state machine so the database binding stores the derived validation ID. Then
set the same value as `active_qualification_record_version_id`, enable sanitized data, and update
the services without changing the pending binding. Run
`scripts.verify_design_partner_activation` under the qualifier role; it must prove the settled ECS
tasks and HTTPS readiness response use `sanitized_data_enabled=true` and the same exact record
version. It independently validates the new stopped-task history and requires an exit-zero stopped
migration on the exact pending migration task-definition revision; dynamic task ARNs and history
are not byte-compared to the pre-bind candidate snapshot. A failed, stale, mismatched, or missing
check remains NO-GO. Run activation while ECS still returns that stopped task; if it has aged out of
the API's stopped-task history, rerun the idempotent fixed broker and verify the new successful task.

```sh
PYTHONPATH=src uv run python -m scripts.verify_design_partner_activation \
  --region <region> \
  --application-url https://<domain> \
  --cluster <cluster> \
  --ecs-role-boundary <terraform-output-ecs-role-boundary.json> \
  --db-instance <db-identifier> \
  --rds-boundary <terraform-output-rds-boundary.json> \
  --migration-task-definition-arn <terraform-output-migration-task-definition-arn> \
  --qualification-secret <qualification-secret-arn> \
  --qualification-secret-policy-sha256 <terraform-output-policy-sha256> \
  --qualification-control-boundary <terraform-output-qualification-control-boundary.json> \
  --qualification-version-id <64-character-version-id> \
  --pending-qualification-version-id <same-64-character-version-id> \
  --qualifier-role-arn <qualifier-role-arn> \
  --deployment-role-arn <deployment-role-arn> \
  --evidence-kms-key-arn <evidence-kms-key-arn> \
  --evidence-bucket-policy-sha256 <evidence-bucket-policy-sha256> \
  --worker-network-boundary <terraform-output-worker-network-boundary.json> \
  --prior-worker-task-role-arn <superseded-worker-task-role-arn> \
  --oidc-issuer-url https://<tenant>/ \
  --oidc-client-id <oidc-client-id> \
  --oidc-allowed-email <allowlisted-operator-email> \
  --output <approved-activation-record-path>
```

Use `--no-prior-worker-task-roles` instead on the first deployment. Candidate and activation must
receive the same raw `terraform output -json worker_network_boundary`, `rds_boundary`, and
`qualification_control_boundary` files, plus the same raw
`terraform output -json ecs_role_boundary`, qualification-secret policy digest, and prior-role
choice. Activation re-lists every runtime secret version, re-runs RDS and worker IAM simulations,
and re-reads the exact qualification policy, control-role inventories, and API/migration role
inventories. Any role substitution or authority drift requires a new candidate record.

## Release-scoped worker-role rotation

The worker IAM role and RDS login suffix is the first 12 hex characters of
`sha256(deployment_id + ":" + release_revision)`. Reusing a deployment label therefore cannot
reuse the prior release credential. The task-role `prevent_destroy` lifecycle intentionally makes
an ordinary rotation plan fail.

Before removing the exact worker role address from Terraform state, use
`scripts.quarantine_prior_worker_role.py` to disable all new assumptions, strip every grant and
instance-profile binding, install and re-read the exact `AWSRevokeOlderSessions` cutoff deny, and
wait for its propagation boundary. With credentials captured before rotation, probe the exact RDS,
S3 read/write, KMS decrypt/data-key, and Bedrock targets; all must be denied. Seal the complete role
observation, including prior release/deployment, cutoff, maximum session duration, captured
session issue/actual-expiry, conservative cleanup expiry, propagation timestamps, and pre-expiry
probe outcomes, with the independent evidence issuer. The
tool's `verify-state-rm` action must authenticate that signed record and recheck live IAM state
before it emits authorization for an operator to remove only
`aws_iam_role.task["worker"]` from state. It never runs Terraform itself.

Retain the quarantined role ARN in `prior_worker_task_role_arns`. Cleanup is allowed only after the
maximum STS session TTL plus propagation has elapsed and the signed captured-session probes remain
denied; the cleanup action rechecks those facts before deleting. Never leave a role unmanaged
without a verified deny-all quarantine. See the rotation runbook for the exact stop conditions.

See [controlled production operations](../../../docs/runbooks/design-partner-production-operations.md),
[isolated restore drill](../../../docs/runbooks/isolated-restore-drill.md),
[secret rotation](../../../docs/runbooks/secret-rotation-and-revocation.md), and
[qualification evidence records](../../../docs/runbooks/qualification-evidence-records.md). This
repository change performs no live AWS action and supplies no production qualification evidence.
