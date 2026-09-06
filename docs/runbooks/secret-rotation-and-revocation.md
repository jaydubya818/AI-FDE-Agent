# Secret Rotation and Revocation

## Scope and current constraint

Rotate every controlled design-partner credential at least every 90 days and immediately after
suspected exposure, privileged recovery use, owner departure, or scope change. Every rotation is a
release operation with a named security owner, technical owner, rollback decision, prior-version
rejection proof, and `runtime-secret-rotation` evidence record.

Terraform creates distinct API and migration runtime secrets plus a dedicated immutable
qualification-record secret. The API password rotates through the migration secret. The production
worker has no stored database password: each `(deployment_id, release_revision)` pair gets a new
task-role identity, short-lived RDS IAM tokens, and the exact `rds-db:connect` DB-user boundary.

## Inventory

| Store | Keys / authority | Consumer | Owner |
| --- | --- | --- | --- |
| RDS-managed master secret | RDS owner login | migration/bootstrap and emergency recovery only | Cloud/DB owner |
| `${project}-${environment}/api` Secrets Manager JSON | `AI_FDE_DATABASE_URL`, `AI_FDE_OIDC_CLIENT_SECRET` | API execution role | Security owner |
| `${project}-${environment}/migration` Secrets Manager JSON | `AI_FDE_MIGRATION_DATABASE_URL`, `AI_FDE_APP_DATABASE_PASSWORD` | migration execution role | Cloud/DB owner |
| `${project}-${environment}/qualification` Secrets Manager versions | strict qualification JSON; writes denied outside qualifier role | Python execution roles read one exact version | Independent qualifier |
| Federated deployment role | short-lived STS authority, no stored key | reviewed delivery automation | Release owner |
| ECS task IAM roles | S3/Bedrock permissions, no stored key | API or worker task only | Cloud owner |
| Auth0 application | OIDC client secret | API through its secret | Auth0 owner |
| Existing Mission Control receiving secret | current package-retrieval bearer | one engagement-bound Mission Control importer identity; migration task may only update this exact ARN | Integration + security owner |
| Package retrieval grant | opaque bearer; only digest stored by Factory Engineer | one engagement-bound Mission Control importer identity | Integration + security owner |

Secret ARNs and last-rotated timestamps may enter evidence. Values, database URLs, Auth0 secrets,
session tokens, and STS credentials may not enter Terraform variables/state, source control,
commands, tickets, logs, screenshots, or JSON evidence.

ECS JSON-key selectors include the exact signed VersionId (`ARN:json-key::version-id`) for both API
keys and both migration keys. After rotation, update the signed evidence and the corresponding
Terraform VersionId input together; moving `AWSCURRENT` never silently repoints a task definition.

## Application password and worker workload-identity rotation

1. Open a maintenance window and pause new pilot work. Record exact release revision, deployment ID,
   current ECS task definitions, secret ARNs, and current health without recording values.
2. For API rotation, generate a strong replacement in the approved secret-management process and
   prepare the API URL plus migration `AI_FDE_APP_DATABASE_PASSWORD`. Worker rotation changes the
   reviewed release revision (and normally the deployment ID), which creates a new task role and
   database login even if an operator accidentally reuses the deployment label. There is no worker
   password to copy.
3. Update the API and migration secrets under change control. ECS tasks do not
   automatically reload a new `AWSCURRENT`; do not assume rotation is complete.
4. Start the Terraform-owned migration state machine once through the migration-caller role. The
   caller has no direct `ecs:RunTask` or `iam:PassRole` permission; the broker hardcodes the exact
   task revision, private subnets, migration security group, disabled public IP, and disabled ECS
   Exec. It updates the application login and reasserts
   `NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS` before applying the already-reviewed
   migration revision.
5. Replace the affected API tasks. For worker-identity rotation, complete the quarantine/state
   handoff below, then qualify the new release-scoped role and roll the worker only after its exact
   RDS DB-user authorization is present. Never delete the old role merely because ECS tasks stopped.
6. Prove the old API password cannot open a new connection. For a worker compromise, prove the old
   task role is denied the current deployment's exact `rds-db:connect` ARN, S3 read/write prefix,
   KMS decrypt/data-key context, and Bedrock model. Enumerate both services and standalone ECS tasks;
   no old deployment task or task revision may remain. Re-run the exact-tuple heartbeat negative
   gate; a copied database password alone must be unusable because bootstrap keeps the production
   worker privilege group `NOLOGIN` and gives only the current derived login `rds_iam`.
7. Inspect metadata-only logs/alarms for leakage and unexpected denial volume. Record only bounded
   outcome codes.
8. Seal and independently review the rotation JSON. If any consumer still uses the prior version,
   the rotation failed; keep sanitized data disabled.

Existing API pooled sessions can remain usable briefly while old tasks drain. Worker database
connections use fresh IAM tokens only at connection creation; quarantine the superseded role and
require a new qualification and activation record.

## Prior worker-role quarantine and Terraform handoff

The Terraform task roles have `prevent_destroy = true`. That is deliberate: an ordinary release
rotation must fail instead of destroying a role while previously issued STS credentials can still
be valid. The worker role and database login suffix is
`sha256(deployment_id + ":" + release_revision)[:12]`, so repeating a deployment label does not
reuse the old release credential.

For the first deployment, set `prior_worker_task_role_arns = []`, pass
`--no-prior-worker-task-roles` to both readiness verifiers, and seal a
`prior-worker-session-revocation` observation with `{"roles": []}`. No state handoff is needed.

For every later release:

1. Capture a short-lived session from the currently running worker before rotation solely for the
   bounded denial probes. Record its issue time but never record its credentials.
2. Run `scripts.quarantine_prior_worker_role.py quarantine` under the dedicated role-lifecycle
   operator. Name the exact prior role ARN, prior deployment ID, and prior 40-character revision.
   The command must derive the Terraform suffix, replace the trust policy with deny-all assumption,
   remove instance-profile bindings, permission boundary, managed policies, and all non-quarantine
   inline policies, then install and re-read the exact `AWSRevokeOlderSessions` token-cutoff deny.
   Any AccessDenied, pagination failure, name mismatch, or incomplete cleanup is a stop condition.
3. Wait through the recorded IAM propagation boundary. Using only the captured pre-rotation
   session, probe the current release's exact RDS DB-user ARN, S3 Get/Put prefix, KMS Decrypt and
   GenerateDataKey with the regional-S3/bucket context, and Bedrock model ARN. Every request must
   be denied. Seal those typed observations with
   `scripts.seal_prior_worker_revocation_observations`; retain the exact role ARN, prior
   release/deployment, quarantine application/cutoff, maximum session duration, propagation wait,
   exact `session_expiry_not_before`, captured-session issue/actual-expiry/probe times, targets, and
   outcomes. The probe must occur after propagation while that credential is still temporally
   valid; an expired-token denial is not revocation evidence.
4. Run `scripts.quarantine_prior_worker_role.py verify-state-rm` against that KMS-authenticated
   evidence. It must re-read the exact live role, trust policy, sole inline cutoff deny, and absence
   of grants before producing a state-handoff authorization. The command never invokes Terraform.
5. Back up remote state under the approved change, then remove only the exact address
   `aws_iam_role.task["worker"]` from Terraform state. If step 4 did not authorize this exact role,
   stop. Keep the now-unmanaged AWS role quarantined and listed in
   `prior_worker_task_role_arns`; never leave an unmanaged role without the verified quarantine.
6. Apply the new release, bootstrap its release-scoped database login, drain every old/standalone
   ECS task, and run candidate plus post-activation verification with the exact signed prior-role
   evidence.

Deletion is optional and never immediate. `scripts.quarantine_prior_worker_role.py cleanup` must
authenticate the signed evidence, recheck the live quarantine, refuse until the recorded maximum
session TTL plus propagation (`session_expiry_not_before`) has elapsed, and require all six denied
captured-session probes. It must distinguish AccessDenied/API failure from NoSuchEntity. Seal the
resulting `deleted-after-ttl` observation; a `GetRole` NoSuchEntity response by itself never proves
stolen STS credentials were revoked.

## Auth0 client-secret rotation

1. Confirm exact callback/logout/web-origin configuration and current live validation evidence.
2. Rotate using the Auth0 tenant's approved process, update only the API Secrets Manager resource,
   and replace API tasks. Keep the overlap as short as the provider supports.
3. Prove successful login, PKCE callback, session creation, logout, and server-side revocation on the
   new secret; prove the old client credential is rejected through a controlled non-logging check.
4. Review `auth.denied` events for expected test volume and no credential material. A new
   `auth0-live-validation` record is required because the external configuration changed.

## Master, migration, and federation rotation

- Rotate the RDS-managed master secret after any bootstrap/recovery use and at least every 90 days.
  Re-run no application on that credential. Prove the migration role remains the only consumer.
- Rotate the migration owner URL and application-password field together under maintenance. Ensure
  no migration task remains running and old owner credentials fail before closing the change.
- Federated deployment uses short-lived STS credentials. On incident, revoke/disable the identity
  provider trust or deployment-role assumption path, terminate active automation, inspect CloudTrail,
  and require a new reviewed deployment identity before resuming.
- Task-role permissions are credentials by authority even without a secret value. On over-broad or
  compromised access, narrow/revoke the IAM policy and replace tasks. The worker must retain only
  `GetObject`/`GetObjectVersion` for one `engagements/<uuid>/evidence/*` prefix, evidence-key decrypt through regional S3, and
  invocation of one exact Bedrock model ARN; it must not enumerate the bucket.

## Package retrieval grant rotation

Retrieval grants are one-engagement, viewer-only, requester-bound credentials with a server-enforced
maximum lifetime of 24 hours. Expiry must be an ISO-8601 timestamp with a timezone; the command
rejects past, timezone-naive, and over-limit values. The deployed HTTP API deliberately refuses
issuance. A separately reviewed fixed-command admin broker uses the migration database role to
verify the named human owns the engagement, provision or reuse one
engagement-scoped viewer identity, revoke every prior active grant for that identity, issue one
replacement atomically, and deliver it directly to an existing Secrets Manager ARN:

```sh
ai-fde-admin rotate-package-retrieval-grant \
  --engagement-id <engagement-uuid> \
  --owner-operator-id <human-owner-uuid> \
  --requester-identity <bound-importer-identity> \
  --requester-system mission-control \
  --expires-at <ISO8601-timestamp-with-timezone-within-24-hours> \
  --target-secret-arn <configured-receiving-secret-arn>
```

Set Terraform `package_retrieval_target_secret_arn` to that exact existing ARN before running the
operation. The bootstrap state machine does not accept command overrides; direct `ecs:RunTask` is a
NO-GO. This grants the migration task only `secretsmanager:PutSecretValue` on that resource; it does
not grant create, read, list, or delete. If the secret uses a customer-managed key, also set the
exact `package_retrieval_target_kms_key_arn`; its encrypt/decrypt data-key authority is constrained
to Secrets Manager and that secret's encryption context. The command uses the grant UUID as the
Secrets Manager client request token, promotes the value to `AWSCURRENT`, and prints metadata only.
It never emits the bearer or target ARN. Do not put the ARN argument or command output into public
build logs.

Database rotation commits before secret delivery. If delivery fails, the replacement remains
unknown and retrieval is fail-closed; fix permissions or the receiving secret, then rerun the
command to revoke that undelivered grant and issue another. Never attempt to recover it from
CloudWatch. Prove the replacement retrieves the exact immutable package/digest with its bound
requester identity, then prove the old grant returns `REVOKED_TOKEN` and telemetry contains only
metadata. Rotation never changes, republishes, approves, or dispatches the package.

## Failure and rollback

Do not restore a known compromised credential as rollback. If new credentials fail before the old
version is revoked and exposure is not suspected, restore service configuration to the prior
Secrets Manager version only under the incident owner's explicit decision, replace tasks, diagnose,
and issue an entirely new credential for the next attempt. If exposure is possible, keep services
paused and recover forward.

Rotation completion requires:

- [ ] all consumers use the intended new version;
- [ ] prior credentials fail new authentication;
- [ ] API readiness and worker progress pass;
- [ ] database role/RLS and IAM scope remain least privilege;
- [ ] the Mission Control retrieval grant is current, expiry-bounded, engagement-specific, and all
      prior grants are revoked;
- [ ] no secret appeared in telemetry or evidence;
- [ ] `runtime-secret-rotation` JSON matches the exact revision/deployment and all checks pass;
- [ ] `prior-worker-session-revocation` JSON is signed and proves the exact quarantine/session
      boundary, or explicitly contains an empty role list on the first deployment;
- [ ] independent security/release reviewer approves the access-controlled record.
