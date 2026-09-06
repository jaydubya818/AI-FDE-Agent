---
title: Factory Opportunity Portfolio v1
status: implemented-feature-branch
date: 2026-09-04
---

# Factory Opportunity Portfolio v1

## Purpose

The portfolio compares candidate factory lines using an inspectable rubric, then records one explicit human selection. It supports “no suitable opportunity” and does not turn an ordinal assessment into fabricated financial precision.

## Candidate record

Each opportunity version contains:

- stable `opportunity_key`, name, and description;
- an exact approved current-workflow reference;
- an exact economic/provenance reference;
- evidence references and explicit blockers;
- raw 0–5 factor values;
- derived value, verifiability, readiness, risk, autonomy, and priority scores;
- rubric/version, calculation detail, rationale, and recommendation;
- lifecycle state and human selection decision.

Lifecycle states are `CANDIDATE`, `ASSESSED`, `RECOMMENDED`, `SELECTED`, `REJECTED`, and `STALE`.

## Deterministic rubric

V1 scores these named inputs:

- workflow frequency, human effort, and cycle time;
- repeatability and standardization;
- evidence quality and deterministic verifiability;
- blast radius and data sensitivity;
- system accessibility and implementation complexity;
- expected economic value and autonomy potential.

Each raw factor is an integer ordinal from 0 through 5. Positive and risk weights are stored with the result. The calculation is deterministic integer arithmetic, produces bounded 0–100 dimensions, and preserves the exact rubric version. The UI shows the inputs and rationale rather than only the composite.

Hard blockers remain visible and can prevent a recommendation regardless of score. A high autonomy-potential score is a design input, not execution authority.

## Selection and freshness

- A human selects the lighthouse opportunity after an approved Customer Factory Model, approved current workflow, and baseline/economics source exist.
- Only one current `SELECTED` opportunity is permitted per engagement.
- Selecting a different opportunity stales dependent readiness and packages from the old selection.
- Upstream source changes stale the affected candidate versions.
- Selection does not create Mission Control work and does not authorize execution.

## Synthetic portfolio

The deterministic fixtures cover three distinct shapes:

| Candidate | Primary value shape | Dominant risk shape |
|---|---|---|
| Dependency modernization | repeatable repository maintenance and reduced upgrade drag | broad dependency blast radius |
| Test remediation | deterministic failing-test reproduction and verification | flaky or incomplete test evidence |
| Security remediation | bounded vulnerability correction with explicit verification | sensitive code and authority requirements |

The fixtures demonstrate rubric generality; they are synthetic and are not customer recommendations.

## Implementation boundary

Scoring, persistence, concurrency controls, and fixtures are implemented in the Factory Engineer module. Actual reusable agent/tool availability remains a Mission Control resolution concern and is never inferred from a portfolio score.
