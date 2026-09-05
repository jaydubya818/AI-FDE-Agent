# ADR 0013: Deploy the Design-Partner Stack on AWS

**Status:** Accepted
**Date:** 2026-08-11
**Accepted:** 2026-08-12
**Amended:** 2026-09-04 — enable bounded S3 version recovery and a dedicated evidence CMK boundary

## Context

The design-partner environment needs a persistent API, web server, worker, PostgreSQL, immutable
evidence storage, workload identities, and a coherent security boundary. Splitting these across a
frontend host, application host, database vendor, and object-storage vendor would reduce initial
setup work but increase incident response, data-processing agreements, egress paths, and secrets
for a single founder.

## Decision

Use one AWS region and account boundary for the first design-partner deployment:

- ECS on Fargate for separate Next.js web, FastAPI API, and persistent-worker task definitions;
- an Application Load Balancer with HTTPS for web and API routing;
- Amazon RDS for PostgreSQL with encryption, automated backups, TLS verification, and no public
  endpoint;
- Amazon S3 with block-public-access and a dedicated customer-managed KMS key for evidence and
  generated exports;
- ECR for images, Secrets Manager for runtime secrets, CloudWatch for metadata-only logs, and
  distinct least-privilege IAM task roles;
- Auth0 remains the human OIDC provider selected in ADR 0011.

Use private subnets for application and database tasks. Infrastructure is defined in Terraform,
and deployment automation uses short-lived federated credentials. Staging may begin with a
single-AZ database for cost control; sanitized customer data requires Multi-AZ, tested restore,
point-in-time recovery, and a documented backup-expiry deletion boundary.

S3 versioning is enabled with KMS encryption and lifecycle expiry for noncurrent versions (30 days
by default, constrained to 7–90 days). Permanent application deletion paginates and deletes every
object version and delete marker under the exact engagement prefix, then re-lists and fails unless
that prefix is empty. The lifecycle remains defense in depth for interrupted cleanup; customer terms
must disclose only the remaining RDS PITR recovery boundary after successful deletion. Model
invocation logging and raw HTTP access logging remain off. Load balancer logs, if enabled, must be
verified not to capture sensitive callback query strings.

The evidence CMK is separate from the keys used for RDS, Secrets Manager, and ECR. S3 Bucket Keys
are enabled, so IAM constrains evidence cryptographic operations to regional S3 and the exact bucket
ARN encryption context. The bucket policy denies non-TLS requests and rejects every object write
that does not explicitly name both `aws:kms` and the exact evidence key ARN.

The controlled pilot runs a worker bound to one canonical engagement UUID. Its task role can read
only `engagements/<uuid>/*`, cannot enumerate the evidence bucket, and can decrypt the evidence key
only through regional S3. Bedrock invocation is restricted to one concrete foundation-model or
regional accountless foundation-model ARN. A second concurrent engagement requires a separately scoped worker task and
role rather than a shared wildcard policy.

The database owner separately binds the worker login to the exact service operator, engagement,
release revision, deployment ID, and verifier-emitted validation digest. PostgreSQL rejects
heartbeats that do not match that complete binding, and API readiness selects only the same identity.
The validation identifier is an immutable SHA-256 digest, not a free-form approval label.

## Consequences

- One provider supplies compute, database, evidence storage, workload identity, encryption, and
  the selected extraction API.
- Fargate costs and Terraform setup are higher than a platform-as-a-service deployment.
- RDS backups can retain deleted data until their configured expiry; customer terms and retention
  UX must state that boundary accurately.
- The modular monolith remains three runtime processes, not a distributed domain architecture.

## Implementation status

Implemented as production Dockerfiles and validated Terraform under
`infrastructure/terraform/design-partner`. The stack remains unvalidated in a live AWS account;
sanitized data stays disabled until the deployment readiness record passes.

## Alternatives

- Vercel plus Render/Railway plus a separate database and object store is faster to click together
  but creates more data processors and operational boundaries.
- Kubernetes adds control-plane and deployment complexity without a V1 requirement.
- A single VM weakens workload isolation, recovery, and credential separation.

## References

- [Amazon ECS task IAM roles](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-iam-roles.html)
- [RDS for PostgreSQL TLS](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/PostgreSQL.Concepts.General.SSL.html)
- [RDS encryption at rest](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Overview.Encryption.html)
- [S3 default encryption](https://docs.aws.amazon.com/AmazonS3/latest/userguide/default-bucket-encryption.html)
