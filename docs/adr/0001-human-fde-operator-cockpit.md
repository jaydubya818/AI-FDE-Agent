# ADR 0001: Build for a Human FDE First

**Status:** Accepted
**Date:** 2026-08-08

## Context

The product could begin as an autonomous FDE, a customer self-service product, or an internal tool for a human FDE. Autonomy would expand risk and hide gaps in the operating model.

## Decision

The first user is an internal FDE. AI-FDE augments discovery, analysis, workflow design, documentation, implementation planning, engineering orchestration, and learning. The human FDE owns the customer relationship and material decisions.

## Consequences

- Operator speed, evidence review, and decision quality are primary UX goals.
- Customer self-service and unattended production changes are out of V1.
- Every consequential recommendation remains inspectable and overridable.
