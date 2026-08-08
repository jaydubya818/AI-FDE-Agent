# ADR 0002: Make the Company Operating Model Canonical

**Status:** Accepted
**Date:** 2026-08-08

## Context

Raw documents are incomplete, stale, and contradictory. Chat history and retrieval results cannot serve as durable enterprise truth.

## Decision

The Company Operating Model, also called the Business Twin, is the canonical representation of the organization. It stores verified entities, relationships, processes, rules, exceptions, unknowns, and decisions with temporal context and provenance.

## Consequences

- Agents reason from the operating model and retrieve source evidence when needed.
- Documents remain immutable evidence, not canonical truth.
- Model changes are versioned, reviewable, and auditable.
