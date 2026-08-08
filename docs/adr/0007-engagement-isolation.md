# ADR 0007: Isolate Data by Engagement from Day One

**Status:** Accepted
**Date:** 2026-08-08

## Context

The synthetic V1 is followed by sanitized customer data. Retrofitting tenant boundaries after data exists is unsafe.

## Decision

Every customer-owned record carries an engagement identifier. Authorization is enforced in application services and PostgreSQL row-level policies. Object storage uses engagement-scoped paths and access controls.

## Consequences

- Tests must prove that cross-engagement reads and writes fail.
- Background jobs and agent tools must carry an explicit engagement context.
- Single-customer deployment remains possible without changing the model.
