---
title: "feat: Qualify one controlled design-partner production path"
type: feat
status: active
date: 2026-09-04
---

# Controlled design-partner production qualification plan

## Outcome

Prove one fail-closed, human-governed real-service path from authenticated partner upload through
reviewed Factory Engineer artifacts to Mission Control Mission/Plan drafts. Do not widen autonomy or
change the Phase 2 production deployment claim.

## Vertical slices

1. **Qualification boundary:** add the 1:1 engagement policy, classification decisions, authorized
   source/workflow/repository scope, access records, migration, API, admin provisioning, and
   isolation/negative tests.
2. **Service trust:** add origin/CSRF hardening, revision-aware live/ready responses, structured
   correlation logs, worker/dependency signals, and security headers.
3. **Human workflow:** expose truthful real-service partner state, gate the bounded upload and
   package handoff, and add loading/error/success/expired/denied experiences plus browser coverage.
4. **Mission Control:** add an explicit rollout gate and authenticated preview/confirm UI; strengthen
   runtime authorization/idempotency and structural no-authority tests.
5. **Operations:** add resource/time bounds, CloudWatch metrics/alarms, secret inventory and bounded
   rotation drill, RPO/RTO and isolated restore drill, and fail-closed qualification verification.
6. **Evidence and release:** run all local gates, deploy and verify Preview only, create a
   digest-bound candidate evidence package, commit and push both repositories, and leave production
   promotion blocked on exact-candidate authorization plus any honest external gates.

## Non-goals

- Generalized organizations or multi-tenant SaaS administration.
- Arbitrary data connectors, URLs, repositories, or customer credentials.
- Factory Engineer execution, approval, merge, release, deployment, or infrastructure authority.
- A new Mission Control runtime object or service credential with execution permissions.
- Automatic production promotion or general-customer approval.
