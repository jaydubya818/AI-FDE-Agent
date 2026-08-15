# Design-Partner AWS Deployment

This stack implements the accepted one-region AWS boundary for AI-FDE. It creates private Fargate
services, private Multi-AZ RDS PostgreSQL, an unversioned KMS-encrypted evidence bucket, HTTPS ALB,
ECR, Secrets Manager, metadata-only CloudWatch log groups, and distinct web/API/worker/migration
roles. It does not make the product sanitized-data ready by itself.

## Safety defaults

- `services_enabled=false` prevents tasks from starting before secrets and database roles exist.
- `sanitized_data_enabled=false` remains the default after services start.
- Enabling sanitized data without `deployment_validation_id` fails Terraform planning.
- S3 and RDS have `prevent_destroy`; RDS and the ALB have deletion protection.
- S3 versioning and Bedrock invocation logging are intentionally not configured. The live
  readiness command fails if Bedrock invocation logging is enabled out of band.
- Image inputs must be immutable ECR URIs with digests, not mutable tags.
- Every task definition enables ECS version consistency, and every long-running service enables
  deployment-circuit-breaker rollback.

## Bootstrap and deploy

1. Create a separate encrypted S3 state bucket and DynamoDB lock table using your platform
   bootstrap process. They are intentionally outside this stack's lifecycle.
2. Build and push the three images. Build the web image with
   `NEXT_PUBLIC_AI_FDE_API_URL=https://<domain>/api`.
3. Copy `terraform.tfvars.example` to an untracked environment file and replace every placeholder.
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

5. Populate the three role-specific runtime secrets out of band. Use TLS-verifying PostgreSQL
   URLs and different owner/application passwords:

   - API secret: `AI_FDE_DATABASE_URL`, `AI_FDE_OIDC_CLIENT_SECRET`
   - Worker secret: `AI_FDE_DATABASE_URL`
   - Migration secret: `AI_FDE_MIGRATION_DATABASE_URL`, `AI_FDE_APP_DATABASE_PASSWORD`

6. Run the migration task once. It idempotently creates/locks down `ai_fde_app`, installs pgvector,
   and applies Alembic migrations. Then run the same task definition with a command override of
   `ai-fde-admin provision-worker`.
7. Set `services_enabled=true`, plan, and apply. Confirm web and API health before onboarding an
   engagement.
8. For each engagement, run a migration-task command override of
   `ai-fde-admin grant-worker --engagement-id <uuid>`. The worker has no global database bypass.

## Sanitized-data release gate

Keep the application fail-closed until the Auth0 record, restore rehearsal, deletion rehearsal,
and secret rotation are complete. Then run:

```sh
PYTHONPATH=src uv run python scripts/verify_design_partner_readiness.py \
  --region <region> \
  --application-url https://<domain> \
  --bucket <evidence-bucket> \
  --db-instance <db-identifier> \
  --cluster <cluster> \
  --migration-family <migration-task-family> \
  --git-commit <40-character-commit> \
  --web-image <web-image@sha256:digest> \
  --api-image <api-image@sha256:digest> \
  --worker-image <worker-image@sha256:digest> \
  --bedrock-evaluation-job <completed-job-id-or-arn> \
  --bedrock-model-id <evaluated-model-or-inference-profile-id> \
  --api-secret <api-secret-arn> \
  --worker-secret <worker-secret-arn> \
  --migration-secret <migration-secret-arn> \
  --auth0-validation-id <record-id> \
  --restore-rehearsal-id <record-id> \
  --deletion-rehearsal-id <record-id> \
  --secret-rotation-id <record-id> \
  --output <approved-record-path>
```

Review and sign the record. Only then set both `deployment_validation_id` to its emitted ID and
`sanitized_data_enabled=true`. A failed or missing check remains a no-go.
