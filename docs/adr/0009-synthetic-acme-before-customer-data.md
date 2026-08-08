# ADR 0009: Prove the Model with Synthetic Acme Data First

**Status:** Accepted
**Date:** 2026-08-08

## Context

The first proof needs realistic enterprise context without exposing customer information before access, retention, and deletion controls are ready.

## Decision

Start with a synthetic Acme Manufacturing engagement. Its evidence includes organization data, transcripts, messages, SOPs, policies, diagrams, workflow documents, exceptions, and business metrics. The next engagement may use sanitized customer data without changing the domain model.

## Consequences

- Fixtures must be realistic, deterministic, license-safe, and clearly synthetic.
- Security and isolation are built before the design-partner release, not postponed until live data.
- Synthetic results cannot be presented as customer outcomes.
