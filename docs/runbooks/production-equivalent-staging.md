# Production-Equivalent Staging Runbook

## Purpose

Replace proposed Auth0, AWS, workload-identity, deployment, recovery, deletion, and Bedrock
decisions with release-bound live evidence. Sanitized data remains disabled throughout staging.

## Required owners and inputs

- Security/release owner with stop authority.
- Cloud owner using short-lived federated AWS credentials.
- Auth0 tenant owner.
- AI platform owner for the fixed Bedrock evaluation.
- Exact 40-character Git commit and immutable web/API/worker image digests.
- Previous known-good image digests and a schema-compatible rollback decision.
- Completed Auth0, restore, deletion, and secret-rotation evidence identifiers.

Do not put credentials, access tokens, model payloads, customer evidence, or raw prompts in the
readiness record.

## Execution order

1. Run the clean local rehearsal on the release commit.
2. Build each image from that commit and publish by digest, never by mutable tag.
3. Apply reviewed Terraform with `sanitized_data_enabled = false`.
4. Run the migration as the migration identity and verify the Alembic revision.
5. Validate the live Auth0 tenant using the Auth0 runbook and retain its signed record ID.
6. Run the fixed synthetic Bedrock evaluation and retain the completed evaluation job ARN or ID.
7. Exercise RDS restore, evidence reconciliation, deletion boundary, secret rotation, and rollback.
8. Run the machine verifier below.
9. Have a reviewer other than the deployer compare the JSON record with the live console and
   external records.
10. Complete the design-partner go/no-go record. Any empty or failed item is NO-GO.

## Machine readiness gate

```bash
PYTHONPATH=src uv run python scripts/verify_design_partner_readiness.py \
  --region us-east-1 \
  --application-url https://staging.example.com \
  --bucket <evidence-bucket> \
  --db-instance <rds-instance> \
  --cluster <ecs-cluster> \
  --web-service web \
  --api-service api \
  --worker-service worker \
  --migration-family <migration-task-family> \
  --git-commit <40-character-commit> \
  --web-image <registry/web@sha256:digest> \
  --api-image <registry/api@sha256:digest> \
  --worker-image <registry/worker@sha256:digest> \
  --bedrock-evaluation-job <completed-job-id-or-arn> \
  --bedrock-model-id <evaluated-model-or-inference-profile-id> \
  --api-secret <api-secret-arn> \
  --worker-secret <worker-secret-arn> \
  --migration-secret <migration-secret-arn> \
  --auth0-validation-id <signed-record-id> \
  --restore-rehearsal-id <signed-record-id> \
  --deletion-rehearsal-id <signed-record-id> \
  --secret-rotation-id <signed-record-id> \
  --output <controlled-record-path>/design-partner-readiness.json
```

The verifier fails unless the release commit is exact, images are immutable and match every ECS
task definition, deployment rollback and ECS version consistency are enabled, the Bedrock
evaluation is completed for the configured model, and existing infrastructure and external record
gates pass.

## Live scenarios

- Successful and denied Auth0 login; allowlist; expiry; logout; revocation; callback validation.
- Worker-only S3 and Bedrock access; denied access from web/API roles where not required.
- Rolling replacement and automatic circuit-breaker rollback.
- Failed worker job, provider outage, and exhausted retry alert.
- RDS restore with RLS and engagement counts checked.
- Export and permanent deletion with the documented backup-expiry boundary.
- Secret rotation with prior secret rejection.
- Metadata-only logs reviewed for evidence, prompt, credential, cookie, and token leakage.

## Stop conditions

Stop immediately for cross-engagement access, raw-content telemetry, unauthorized approval,
provider fallback, image mismatch, disabled rollback, incomplete restore/deletion, or a Bedrock model
that differs from the completed evaluation. Keep sanitized data disabled and issue a new readiness
record after remediation.

## Exit evidence

- `design-partner-readiness-v2` JSON tied to the release commit and image digests.
- Signed Auth0, restore, deletion, secret-rotation, and Bedrock evaluation records.
- Completed independent review and go/no-go record.
- Previous-image rollback target and accountable incident contacts.
