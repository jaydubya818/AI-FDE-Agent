# ADR 0015: Optimize Verified Value per Token

**Status:** Accepted
**Date:** 2026-08-14

## Context

Internal AI teams need faster delivery and lower model cost. Token reduction alone is a poor goal:
a cheap output that is wrong, rejected, or expensive to repair destroys value. Model usage must be
connected to an accepted delivery outcome and its quality.

## Decision

Optimize for verified value per token across the complete engagement. Count all model input and
output tokens, including retrieval, retries, refusals, rejected output, and repair work. Hold
correctness, provenance, security, approval, and required evaluation thresholds as constraints.

V1 will relate extraction usage to accepted claims and approved artifact packets. It will not claim
a reduction until a comparable internal baseline exists. If bounded coding-agent execution is
approved after V1, extend the measure to total planning, generation, repair, and review tokens per
accepted pull request. Required tests, human review, rework, defects, and time-to-merge remain
quality guardrails.

## Consequences

- A lower token count is not a win when correction or rework increases.
- Failed and rejected work remains visible in the cost denominator.
- Structured state and exact evidence retrieval are preferred over repeatedly sending raw history.
- Model and prompt comparisons require the same evaluation set and accepted-outcome definition.
- Pull-request token-cost reduction remains a post-V1 metric, not a current product claim.
