# ADR 0003: Convert Evidence into Reviewed Claims

**Status:** Accepted
**Date:** 2026-08-08

## Context

Directly merging model output into the operating model would turn extraction errors into business facts. Enterprise sources may also disagree.

## Decision

Ingestion creates candidate claims. Claims cite exact evidence. They become verified assertions only after deterministic validation and human review. Conflicts and unknowns remain explicit records.

## Consequences

- Ingestion is slower than an automatic knowledge-base import.
- The operator gets a review inbox and bulk actions for low-risk claims.
- Material claims cannot silently overwrite existing truth.
- Evidence is immutable while retained. Policy-driven deletion removes prohibited content but preserves permitted audit metadata.
