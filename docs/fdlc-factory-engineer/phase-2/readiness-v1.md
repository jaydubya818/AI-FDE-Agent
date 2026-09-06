---
title: FDLC Readiness v1
status: implemented-feature-branch
date: 2026-09-04
---

# FDLC Readiness v1

## Purpose

Readiness explains whether a selected factory line is prepared for governed handoff. It is a gate record, not a decorative progress score.

V1 assesses each FDLC stage exactly once:

```text
Discover → Design → Assemble → Validate → Deploy → Operate → Improve
```

## Stage contract

Every stage records:

- categorical status and an explainable 0–100 coverage score;
- criterion-level satisfied/blocking values;
- evidence and decision references;
- blockers, risks, required artifacts, owner, and next actions;
- a plain-language explanation and evaluation timestamp.

Statuses are `NOT_STARTED`, `IN_PROGRESS`, `BLOCKED`, `READY`, `CONDITIONALLY_READY`, `NOT_READY`, and `STALE`.

A satisfied criterion must have a provenance basis. An unsatisfied criterion must have a next action. An unmet blocking criterion produces `BLOCKED` regardless of the numeric score. The score is a transparent coverage summary and never overrides a gate.

## Required criteria

V1 includes named criteria for:

- **Discover:** outcome, owner, scope, baseline evidence, evidence sufficiency, and understood unknowns;
- **Design:** approved current state, target state, measurable acceptance criteria, Human/Software/Agent allocation, autonomy ceiling, and authority boundary;
- **Assemble:** required agents, skills, tools, models, context sources, and environment;
- **Validate:** verification, evaluations, security, failure handling, rollback, permission model, and explicit blockers;
- **Deploy:** deployment scope, rollout, approvals, package generation, and target environment;
- **Operate:** ownership, observability, incident response, cost monitoring, and escalation;
- **Improve:** production metrics, baseline, learning signals, failure taxonomy, and improvement owner.

## Dependency order

Factory opportunity discovery and ranking occur after an approved customer model/current workflow/baseline, but before final readiness. A human selects the opportunity. The final readiness assessment pins that selected opportunity and the approved target workflow. Package creation requires the selected opportunity plus an approved overall `READY` assessment.

This order avoids the circular requirement that a line already be deployment-ready before it can be selected.

## Lifecycle and failure behavior

```text
DRAFT → APPROVED → STALE
```

- Only an all-stage `READY` assessment can be approved for package use.
- Material upstream change marks dependent readiness stale.
- Stale readiness cannot support a new or repeated publish.
- A service identity cannot approve readiness.
- One current approved readiness version is permitted per engagement; history remains queryable.

Waivers are not generalized in V1. If a mandatory criterion is not satisfied, the assessment remains blocked or not ready. A future waiver model must carry explicit scope, authority, rationale, expiry, and non-waivable classifications.

## Implementation boundary

The evaluator and persistence are implemented in the Factory Engineer module and exposed through engagement-scoped APIs. The hosted demo gives the operator deterministic synthetic controls and explanations while keeping all network access disabled.
