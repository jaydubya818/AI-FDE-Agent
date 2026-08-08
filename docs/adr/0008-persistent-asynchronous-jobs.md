# ADR 0008: Use Persistent Jobs Before a Workflow Platform

**Status:** Accepted
**Date:** 2026-08-08

## Context

Ingestion, extraction, document parsing, and agent runs are long-lived and retryable. A full workflow platform adds deployment and debugging overhead to V1.

## Decision

Use PostgreSQL-backed persistent jobs with idempotency keys, leases, retries, checkpoints, and an outbox. Hide this behind a durable job interface.

## Consequences

- Jobs survive process restarts and expose progress to the UI.
- Complex long-running orchestration remains limited in V1.
- Temporal or another workflow platform may replace the implementation without changing domain contracts.
