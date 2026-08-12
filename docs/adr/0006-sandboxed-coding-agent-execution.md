# ADR 0006: Prove Coding-Agent Orchestration in a Sandbox

**Status:** Accepted for post-V1; not implemented
**Date:** 2026-08-08

## Context

After V1 proves the evidence-to-specification lifecycle, AI-FDE may prove that an approved
engineering specification can become bounded implementation work. Production deployment is not
part of this future coding-agent milestone.

## Decision

If the post-V1 phase is approved, AI-FDE will generate structured WorkOrders and dispatch them
through a provider-neutral interface. Execution will occur in an isolated sandbox against a
dedicated example repository.

## Consequences

- The sandbox has explicit repository, command, network, secret, time, and cost limits.
- Outputs include a diff, test results, logs, and a completion status.
- Production credentials, deployment rights, and customer repositories remain unavailable.
- V1 does not implement or simulate this capability.
