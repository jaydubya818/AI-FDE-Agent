# ADR 0004: Start with a Modular Monolith and PostgreSQL

**Status:** Accepted
**Date:** 2026-08-08

## Context

A single founder needs fast iteration and strong boundaries. Microservices, several databases, and a workflow platform would increase operating cost before product fit.

## Decision

Start with a modular monolith: a Next.js operator web app, a FastAPI application API, and a Python worker. Use PostgreSQL as the transactional store and pgvector only where semantic retrieval is required. Use S3-compatible object storage for evidence.

## Consequences

- The project has two language runtimes but keeps AI and data workflows in Python.
- Modules communicate through explicit services and contracts, not network services.
- Services may be extracted later only with measured operational need.
