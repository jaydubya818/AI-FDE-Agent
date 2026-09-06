# FDLC Factory Engineer evolution

These artifacts define and implement the evidence-backed evolution of AI-FDE into the FDLC Factory Deployed Engineer. Phase 1 was verified at `af0196f`; Phase 2 is implemented on `codex/factory-engineer-evolution` with the corresponding Mission Control adapter on `codex/factory-engineer-package-import`.

## Required deliverables

1. [Current-state audit](current-state-audit.md)
2. [Preserve / Refactor / Add matrix](preserve-refactor-add-matrix.md)
3. [Target product architecture](target-product-architecture.md)
4. [Target domain model](domain-model.md)
5. [UX information architecture](ux-information-architecture.md)
6. [Mission Control integration contract](mission-control-integration-contract.md)
7. [Incremental migration plan](../plans/2026-09-04-feat-fdlc-factory-engineer-evolution-plan.md)
8. Phase 1 implementation: centralized public identity/links, FDLC-aligned copy/tokens/navigation, Guide-link registry, and hosted-demo build safety.
9. Phase 2 contracts:
   - [Customer Factory Model v1](phase-2/customer-factory-model-v1.md)
   - [FDLC Readiness v1](phase-2/readiness-v1.md)
   - [Factory Opportunity Portfolio v1](phase-2/factory-opportunity-portfolio-v1.md)
   - [Factory Deployment Package v1](phase-2/deployment-package-v1.md)
   - [Authenticated retrieval](phase-2/authenticated-retrieval.md)
   - [Mission Control trusted handoff](phase-2/mission-control-handoff.md)

Supporting reference: [terminology and Guide links](terminology-and-guide-links.md).

## Governing product boundary

```text
FDLC Framework defines the method
AI Software Factory Guide teaches the method
Factory Engineer understands the customer and designs approved deployment intent
Mission Control executes governed autonomous software work
FDLC Enterprise may later govern organization-wide identity, policy and fleets
Factory Engineer measures outcomes and proposes privacy-reviewed reusable capability signals
```

The existing source-evidence → inference → human-verification → approved-workflow → economics → artifact chain remains the foundation. Nothing in these documents authorizes weakening that chain or duplicating Mission Control execution state.

## Capability status

- **Implemented and qualified in Phase 1:** public alignment, shared contract generation, CI trust gates, upload/work budgets, corrected evidence completion/scorecard behavior, synthetic hosted-demo isolation.
- **Implemented on the Phase 2 feature branches:** versioned Customer Factory Model, explainable readiness, deterministic opportunity selection, immutable package/digest, scoped retrieval, Mission Control validation and draft-only import, synthetic proof UI.
- **Deployment configuration still required for customer use:** production Factory Engineer API, managed service secret/rotation, issuer allowlist, Mission Control rollout flags/spec governance, operational monitoring and backups.
- **Not implemented:** package execution, direct WorkOrder creation, automatic approvals, production deployment, generalized connectors/marketplace, enterprise fleet identity, and bidirectional outcome sync.
