# ADR 0006: Prove Coding-Agent Orchestration in a Sandbox

**Status:** Accepted
**Date:** 2026-08-08

## Context

AI-FDE must prove that an approved engineering specification can become bounded implementation work. Production deployment is not required for the first milestone.

## Decision

AI-FDE generates structured WorkOrders and dispatches them through a provider-neutral interface to Codex or Claude Code. Execution occurs in an isolated sandbox against a dedicated example repository.

## Consequences

- The sandbox has explicit repository, command, network, secret, time, and cost limits.
- Outputs include a diff, test results, logs, and a completion status.
- Production credentials, deployment rights, and customer repositories remain unavailable.
