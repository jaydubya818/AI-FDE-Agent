# ADR 0005: Represent the Business Twin as a Relational Graph First

**Status:** Accepted
**Date:** 2026-08-08

## Context

The operating model is graph-shaped, but V1 queries are bounded and require transactions, temporal history, review states, and strong integrity.

## Decision

Use typed relational tables plus versioned node and edge records in PostgreSQL. Do not introduce a graph database in V1.

## Consequences

- Transactions, migrations, row isolation, and audit joins stay simple.
- Graph traversal depth must be bounded and measured.
- A storage interface preserves a later migration path if real queries justify it.
