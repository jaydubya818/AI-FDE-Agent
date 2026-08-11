# ADR 0013: Deploy the Design-Partner Stack on AWS

**Status:** Proposed
**Date:** 2026-08-11

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
- Amazon S3 with block-public-access and a customer-managed KMS key for evidence and generated
  exports;
- ECR for images, Secrets Manager for runtime secrets, CloudWatch for metadata-only logs, and
  distinct least-privilege IAM task roles;
- Auth0 remains the human OIDC provider selected in ADR 0011.

Use private subnets for application and database tasks. Infrastructure is defined in Terraform,
and deployment automation uses short-lived federated credentials. Staging may begin with a
single-AZ database for cost control; sanitized customer data requires Multi-AZ, tested restore,
point-in-time recovery, and a documented backup-expiry deletion boundary.

S3 versioning remains off until the deletion implementation can enumerate and remove every object
version. Model invocation logging and raw HTTP access logging remain off. Load balancer logs, if
enabled, must be verified not to capture sensitive callback query strings.

## Consequences

- One provider supplies compute, database, evidence storage, workload identity, encryption, and
  the proposed extraction API.
- Fargate costs and Terraform setup are higher than a platform-as-a-service deployment.
- RDS backups can retain deleted data until their configured expiry; customer terms and retention
  UX must state that boundary accurately.
- The modular monolith remains three runtime processes, not a distributed domain architecture.

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
