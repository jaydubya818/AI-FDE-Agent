# ADR 0012: Give the Production Worker a Dedicated Service Identity

**Status:** Accepted
**Date:** 2026-08-11
**Accepted:** 2026-08-12

## Context

The local worker runs under the development operator so PostgreSQL row policies can see the Acme
engagement. That identity is development-only, is tied to a human-shaped configuration, excludes
sanitized engagements, and cannot be used in production. A global row-security bypass would make
one compromised worker a cross-engagement data breach.

## Decision

Represent the worker as a dedicated non-human operator per environment, with an immutable internal
ID, `identity_kind=service`, and external subject `service:worker:<environment>`. It never receives
an OIDC login attempt or browser session and never shares a human operator ID.

Provision the service identity through an explicit deployment administration command. Grant it the
existing `operator` membership only on engagements whose evidence it may process. It is never an
engagement owner and cannot manage retention, exports, deletion, membership, or human approval
gates. Worker startup requires `AI_FDE_WORKER_OPERATOR_ID`, verifies the matching active service
identity, and fails closed if provisioning or membership is missing. Production startup must not
call `ensure_local_operator`.

The worker leases only jobs visible through those memberships and processes each job in an
explicit engagement-scoped database transaction. PostgreSQL row policies remain enabled; there is
no superuser, owner connection, or worker-wide bypass role. Sanitized processing is allowed only in
a production environment for a provisioned service identity with explicit engagement membership.

The infrastructure workload identity is separate from the application actor. On the AWS
deployment, an ECS task IAM role grants the worker only its required S3, Bedrock, and secret access.
The stable AI-FDE service-operator ID remains the actor used for row isolation and audit history
when cloud credentials rotate.

## Required implementation

- Add a constrained human/service identity kind to `operators`.
- Separate worker identity configuration from development human identity.
- Add an idempotent administration command to provision/deactivate the service identity and grant
  engagement memberships.
- Record worker-authored audit events as `actor_type=service`.
- Test missing, inactive, human-kind, cross-engagement, owner-only, and sanitized-data cases.
- Preserve the current local development operator only for synthetic development.

## Consequences

- Compromise is limited to explicitly assigned engagements and workload permissions.
- Engagement onboarding gains one explicit worker-membership step.
- A stable application identity and rotating cloud credential can be audited independently.
- The worker cannot silently perform actions reserved for the human FDE.

## Implementation status

Implemented in the application model, worker startup validation, explicit administration command,
audit attribution, membership-scoped job leasing, isolation tests, and the distinct ECS worker task
role. Live deployment validation remains a separate release gate.

## Alternatives

- Reusing the design-partner's human identity destroys attribution and session boundaries.
- A database role that bypasses row security is operationally simple but violates ADR 0007.
- Auth0 client-credentials tokens add an unnecessary browser-identity dependency to an internal
  workload and do not replace database or cloud workload authorization.

## References

- [Amazon ECS task IAM roles](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-iam-roles.html)
- [ADR 0007: engagement isolation](0007-engagement-isolation.md)
