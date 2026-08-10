---
title: "feat: Build AI-FDE Operator Cockpit vertical slice"
type: feat
status: active
date: 2026-08-08
---

# Build the AI-FDE Operator Cockpit Vertical Slice

## Overview

Build a design-partner-ready internal cockpit that helps one human FDE transform Acme Manufacturing evidence into a reviewed Company Operating Model, approved current and target AP workflows, a quantified business case, and implementation-ready artifacts.

This plan deliberately stops before coding-agent execution, a real pilot, or production deployment. The milestone proves trusted understanding and an implementation-ready handoff.

## Problem Statement

Enterprise process knowledge is fragmented, contradictory, and temporal. Chat and retrieval systems can summarize it but do not maintain an accountable source of business truth. Starting implementation from raw documents risks automating the stated process, missing hidden rules, and creating a polished but unsafe demo.

## Proposed Solution

Build one modular system around four durable distinctions:

1. evidence is not truth;
2. candidate claims are not verified assertions;
3. current workflows are not target workflows;
4. estimated value is not realized value.

The human FDE reviews material state transitions. Agents operate through bounded domain tools over versioned structured context. Coding-agent execution remains a later phase.

## Stakeholders

- **Primary user:** Internal human FDE.
- **Product owner:** Founder.
- **Later stakeholder:** Sanitized design partner.
- **Engineering and operations:** One founder using AI coding agents.

## Research Findings

### Repository

The repository was empty at planning time. It had no code, conventions, issue templates, or institutional solution records. The architecture and conventions in this documentation are therefore new and must be reviewed explicitly.

### External Guidance

- NIST AI RMF guidance supports explicit human roles, risk mapping, measurement, and governed operation.
- OWASP agentic guidance supports least privilege, bounded tools, sandboxing, approval, and auditable actions.
- W3C PROV concepts support separating evidence, activity, agent responsibility, and derivation.
- PostgreSQL row security can provide default-deny engagement filtering but must be paired with correct runtime roles and application tests.
- OpenTelemetry provides a stable base for common traces and logs. Generative-AI conventions are still evolving and must be version-pinned.

See [standards and external guidance](../references/standards.md).

## Technical Approach

### Architecture

- Next.js cockpit.
- FastAPI API and Python worker sharing one application package.
- PostgreSQL for transactional, temporal, graph-shaped, job, and audit state.
- pgvector for candidate retrieval only.
- S3-compatible object storage for immutable evidence.
- PostgreSQL-backed persistent jobs and transactional outbox.
- Provider-neutral extraction-model adapters.
- OpenTelemetry instrumentation with sensitive payload controls.

The approved technical shape is governed by ADRs. Proposed ADRs must be accepted before their implementation begins.

### Primary Data Path

```text
Evidence asset
  -> evidence segment
  -> extraction run
  -> candidate claim
  -> review decision
  -> verified assertion
  -> operating-model snapshot
  -> current workflow
  -> allocation decision
  -> target workflow
  -> economic scenario
  -> versioned artifact
  -> implementation-ready specification
```

### Security Model

- Every customer-owned record has an engagement identifier.
- The application and database both enforce engagement access.
- Ingested content is untrusted and cannot alter system or tool policy.
- Material claim acceptance, workflow approval, and economic approval are explicit operator actions.

## Implementation Phases

### Phase 0: Approve Foundation

Review the PRD, ADRs, schema, roadmap, and backlog. Select the deployment, OIDC, and production extraction providers when each becomes necessary.

**Exit:** No P0 item depends on an unresolved architectural decision.

### Phase 1: Establish the Runnable Spine

Create the repository tooling, applications, database migrations, persistent jobs, engagement model, audit foundation, and Acme seed.

**Exit:** A clean environment can create Acme, run a restart-safe job, and display its audit record.

### Phase 2: Build Evidence and Review

Implement immutable uploaded evidence and operator notes, supported document and diagram parsers, exact locators, structured extraction, candidate claims, identity candidates, review decisions, contradictions, and unknowns.

**Exit:** The seeded AP conflict is surfaced with both sources and cannot become truth silently.

### Phase 3: Build the Business Twin and Current Workflow

Implement versioned entities, relationships, assertions, projections, process versions, workflow structure, evidence links, and approval gates.

**Exit:** The operator approves an evidence-backed current AP workflow only after resolving or overriding material blockers.

### Phase 4: Build Target Design and Economics

Implement allocation factors, explainable recommendations, target workflow versions, system-preservation controls, baseline inputs, deterministic formulas, and sensitivity.

**Exit:** The operator approves a target workflow and reproducible business case.

### Phase 5: Generate Implementation Artifacts

Generate versioned PRD, architecture, rules, controls, and evaluation plan. Implement dependency and stale-state tracking.

**Exit:** The packet is complete, internally consistent, and tied to approved upstream versions.

### Phase 6: Harden for a Design Partner

Complete OIDC, row isolation, retention, deletion, accessibility, telemetry review, acceptance testing, and operator documentation.

**Progress:** Auth0-backed opaque sessions, application/row authorization, and the bounded
retention/export/deletion path are implemented. Live Auth0 verification, accessibility, telemetry,
and clean-environment rehearsal remain.

**Exit:** All PRD release criteria pass from a clean environment.

## Flow Analysis

### Happy Path

The operator creates Acme, uploads evidence, reviews candidate claims, resolves identities and conflicts, approves the current workflow, reviews the allocation, approves the target workflow and business case, and generates implementation-ready artifacts.

### Required Recovery Paths

- Duplicate upload links to existing evidence.
- Parser failure retains the asset and supports safe retry.
- Invalid extraction output fails validation before claims are created.
- Interrupted review resumes at the prior position.
- New evidence may move the lifecycle backward and mark outputs stale.
- Blocking unknowns explain what evidence is missing.
- Export or deletion failure remains retryable and auditable.

### Permission Paths

V1 has one operator role, but every command still requires authenticated engagement membership. System workers use service identities and explicit engagement context. Future roles must not require changing record ownership.

## Alternative Approaches Considered

### Document Retrieval as the Product

Rejected. It is faster to build but cannot establish reviewed truth, preserve contradictions, or support safe downstream decisions.

### Graph Database First

Rejected for V1. It adds operational and modeling complexity before query needs are proven. Typed relational state with versioned edges is sufficient.

### Microservices and Temporal First

Rejected for V1. Both solve scaling and orchestration problems the first engagement does not yet have. Interfaces preserve later migration paths.

### TypeScript-Only Application

Not selected. It would reduce runtime count but give up the preferred Python path for document, evaluation, and AI workflows. ADR 0004 records the accepted modular-monolith decision.

### Coding-Agent Execution in V1

Deferred. V1 ends at an implementation-ready specification and does not simulate dispatch, execution, or sandbox evidence.

## Functional Acceptance Criteria

- [x] Create and resume the Acme engagement.
- [x] Ingest the currently supported text and Markdown evidence without duplicate effects.
- [x] Cite exact source locations for candidate and verified material claims.
- [x] Detect and preserve the seeded approval rule and exception.
- [x] Prevent a blocking contradiction from being silently bypassed.
- [ ] Inspect current and historical operating-model state.
- [x] Approve an immutable current workflow version.
- [x] Review every current-slice step allocation and require a control for AI allocation.
- [x] Approve a separate target workflow version.
- [x] Reproduce base economic results from labeled, versioned inputs.
- [x] Generate a current versioned Markdown implementation specification.
- [x] Mark downstream workflows, economics, and artifacts stale after a relevant upstream assertion changes.

## Non-Functional Acceptance Criteria

- [x] Strict typing and schema validation cover the implemented API and model boundaries.
- [x] Migrations and local setup are automated and tested for the implemented slice.
- [ ] Long operations expose progress, cancellation, retry, failure, and completion.
- [x] Cross-engagement reads of implemented engagement-owned records fail closed in database tests.
- [ ] Consequential mutations have complete audit records.
- [ ] Sensitive evidence and secrets do not appear in routine telemetry.
- [ ] Core flow is keyboard-operable and targets WCAG 2.2 AA.
- [x] The repository is runnable after the current vertical slice.

## Success Metrics

- 100% of accepted material assertions have inspectable evidence.
- 100% of seeded critical rules and exceptions are surfaced.
- 100% of consequential mutations appear in the audit trail.
- Zero silent conflicts and zero successful cross-engagement access in tests.
- One FDE completes the golden path without manual database or artifact editing.
- The final implementation packet is judged usable for engineering kickoff.

## Dependencies

- Product-owner approval of proposed ADRs.
- License-safe synthetic Acme evidence.
- Development credentials for the selected extraction model when deterministic fixtures are replaced.
- OIDC and object-storage development configurations before sanitized data.

## Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| Eight-week scope expands | P0 backlog and documented cut order |
| Extraction is persuasive but wrong | Candidate layer, exact citations, material review, evaluation |
| Generic model loses domain meaning | Typed core schema and controlled relation types |
| Upstream changes produce stale specs | Version pins and automatic staleness |
| Future execution work leaks into V1 | Keep WorkOrders, dispatch, and sandbox behavior post-V1 |
| Security is postponed because data is synthetic | Isolation, retention, and auth before design-partner release |
| AI-generated code grows complexity | Small WorkOrders, tests, review, and phase gates |

## Resource Plan

One founder owns product decisions, architecture, acceptance, and integration. Coding agents may implement bounded backlog items but do not approve requirements, ADRs, security boundaries, migrations, or release gates.

Plan for eight weeks. Six weeks is a credible internal-alpha target through artifact generation. It is not a credible design-partner target because identity, data handling, accessibility, and readiness controls would remain incomplete.

## Documentation Plan

Update the PRD, affected ADRs, schema, backlog status, and operator documentation in the same change as behavior. Generated customer artifacts are versioned outputs, not replacements for product documentation.

## Definition of Done

The milestone is done when every PRD release criterion passes in a clean environment, the product visibly distinguishes working, estimated, synthetic, and deferred capabilities, and the founder would use the resulting packet to start a real engineering engagement.
