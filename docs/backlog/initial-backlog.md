# Initial V1 Backlog

**Status:** Active
**Rule:** P0 items are required for the design-partner milestone. P1 items may be cut in the order defined by the roadmap. P2 is post-V1.

## Implementation Snapshot — 2026-08-08

- Complete: FND-01 through FND-05, PLT-01/03/04/05/06/07/09, EVD-02/03/05/06/08, KNO-03/05/07, COM-02, and the initial SEC-02/03 row-isolation foundation.
- Narrow V1 implementation: text and Markdown only; deterministic Acme extraction only; local development identity only.
- Next product slice: complete review semantics and model history, then construct the evidence-backed current workflow.
- Deferred post-V1 by product decision: ART-04 and Epic 8 coding-agent execution.

## Epic 0: Foundation Decisions

| ID | Priority | Item | Acceptance |
| --- | --- | --- | --- |
| FND-01 | P0 | Review and approve the V1 PRD | Product owner accepts outcome, non-goals, and release criteria |
| FND-02 | P0 | Resolve ADR 0004 | Runtime and modular-monolith choice is accepted or replaced |
| FND-03 | P0 | Resolve ADR 0005 | PostgreSQL relational-graph approach is accepted or replaced |
| FND-04 | P0 | Resolve ADR 0007 | Engagement-isolation strategy is accepted or replaced |
| FND-05 | P0 | Resolve ADR 0008 | Persistent-job strategy is accepted or replaced |
| FND-06 | P0 | Select deployment, OIDC, and production extraction providers | Each selection has a short ADR or amendment and a verified development path |

## Epic 1: Platform Spine

| ID | Priority | Item | Depends on | Acceptance |
| --- | --- | --- | --- | --- |
| PLT-01 | P0 | Create repository tooling and local environment | FND-02 | One documented command starts required local services |
| PLT-02 | P0 | Add API, worker, and web health paths | PLT-01 | Health status is visible and tested |
| PLT-03 | P0 | Add migrations and test database workflow | PLT-01 | Clean migrate, rollback where safe, and test setup pass |
| PLT-04 | P0 | Implement engagement aggregate and API | PLT-03 | Acme engagement can be created and retrieved |
| PLT-05 | P0 | Implement persistent jobs and outbox | PLT-03, FND-05 | A leased job survives worker restart without duplicate effect |
| PLT-06 | P0 | Implement audit-event foundation | PLT-04 | Engagement mutations create correlated audit events |
| PLT-07 | P0 | Build engagement overview shell | PLT-04 | Loading, empty, error, and success states work |
| PLT-08 | P0 | Add CI for lint, types, tests, and migrations | PLT-01 | Pull-request-equivalent command fails on a known defect |
| PLT-09 | P0 | Add engagement row-policy test harness | PLT-03, FND-04 | Each engagement-owned migration must add a passing default-deny test |

## Epic 2: Acme Evidence

| ID | Priority | Item | Depends on | Acceptance |
| --- | --- | --- | --- | --- |
| EVD-01 | P0 | Define Acme fixture manifest and expected truth | FND-01 | Each fixture has purpose, source date, and expected facts or conflicts |
| EVD-02 | P0 | Implement evidence metadata and object storage | PLT-04 | Original asset is immutable, hashed, and engagement-scoped |
| EVD-03 | P0 | Implement parser interface and addressable segments | EVD-02 | A segment links back to an exact source locator |
| EVD-04 | P0 | Add required PDF, DOCX, text, Markdown, CSV, and diagram parsers | EVD-03 | Acme fixtures parse with deterministic segment identifiers |
| EVD-05 | P0 | Implement idempotent ingestion job | PLT-05, EVD-04 | Retry creates no duplicate asset or segment |
| EVD-06 | P0 | Build evidence upload and status UI | EVD-05 | Operator sees progress, failure reason, retry, and completion |
| EVD-07 | P0 | Add malicious and malformed-file tests | EVD-04 | Unsupported or unsafe files fail without executing content |
| EVD-08 | P0 | Add immutable operator notes as evidence | EVD-02 | A discovery note is timestamped, attributable, citable, and versioned |

## Epic 3: Claims and Review

| ID | Priority | Item | Depends on | Acceptance |
| --- | --- | --- | --- | --- |
| KNO-01 | P0 | Define versioned extraction schemas | EVD-01 | People, systems, rules, exceptions, metrics, and relationships validate |
| KNO-02 | P0 | Implement provider-neutral structured extraction | KNO-01, EVD-05 | Invalid provider output is rejected and observable |
| KNO-03 | P0 | Store candidate claims and evidence links | KNO-02 | Every claim resolves to an exact evidence segment |
| KNO-04 | P0 | Implement review commands and materiality policy | KNO-03 | Accept, edit, reject, and defer are audited; material claims cannot auto-verify |
| KNO-05 | P0 | Build review inbox | KNO-04 | Operator can filter, inspect evidence, decide, and resume |
| KNO-06 | P0 | Implement identity candidates without auto-merge | KNO-03 | Ambiguous Sarah identities remain separate pending review |
| KNO-07 | P0 | Implement contradiction and unknown records | KNO-04 | Seeded CFO/controller case creates a blocking record |
| KNO-08 | P0 | Add extraction and citation evaluation harness | KNO-02 | Golden and edge cases produce reproducible scored results |
| KNO-09 | P0 | Add indirect prompt-injection acceptance cases | KNO-02 | Evidence content cannot change tool policy, grant authority, or auto-verify a material claim |

## Epic 4: Company Operating Model

| ID | Priority | Item | Depends on | Acceptance |
| --- | --- | --- | --- | --- |
| COM-01 | P0 | Implement entity, version, alias, relationship, and assertion migrations | KNO-04, FND-03, PLT-09 | Temporal, row-policy, and engagement invariants pass database tests |
| COM-02 | P0 | Apply reviewed claims transactionally | COM-01 | Accepted claim creates assertion and model-change event once |
| COM-03 | P0 | Implement current and historical projections | COM-02 | Query by valid and recorded time returns expected Acme history |
| COM-04 | P0 | Implement bounded model query services for agents and UI | COM-03 | Results cannot cross engagement or bypass review state |
| COM-05 | P0 | Build model search and detail views | COM-04 | Operator can inspect provenance and history without chat |
| COM-06 | P1 | Build bounded graph exploration | COM-04 | Operator can traverse supported relationships with accessible fallback list |
| COM-07 | P0 | Implement stale-dependency event | COM-02 | A model change marks dependent drafts and artifacts stale |
| COM-08 | P0 | Correct verified assertions through reviewed versions | COM-02 | Correction preserves prior history, evidence, actor, and reason |

## Epic 5: Current Workflow

| ID | Priority | Item | Depends on | Acceptance |
| --- | --- | --- | --- | --- |
| WFL-01 | P0 | Implement process and workflow version model | COM-01 | Approved versions are immutable |
| WFL-02 | P0 | Implement step, transition, rule, exception, and evidence model | WFL-01 | AP happy and exception paths validate |
| WFL-03 | P0 | Generate a current-workflow draft from approved model state | COM-04, WFL-02 | Draft pins a model snapshot and preserves source links |
| WFL-04 | P0 | Build current-workflow editor and evidence panel | WFL-03 | Operator edits structure and sees AI-generated versus manual changes |
| WFL-05 | P0 | Implement workflow validation and approval gate | KNO-07, WFL-04 | Blocking contradiction prevents approval without audited override |
| WFL-06 | P1 | Add accessible visual workflow layout | WFL-04 | Graph and list forms represent the same workflow |

## Epic 6: Allocation, Target State, and Economics

| ID | Priority | Item | Depends on | Acceptance |
| --- | --- | --- | --- | --- |
| DEC-01 | P0 | Implement deterministic allocation-factor model | WFL-05 | Each step records all required factor values |
| DEC-02 | P0 | Add explainable recommendation adapter | DEC-01 | Recommendation, rationale, risk, controls, and confidence validate |
| DEC-03 | P0 | Build allocation review UI | DEC-02 | Operator decides every step and changes remain audited |
| DEC-04 | P0 | Implement target-workflow version and comparison | DEC-03 | Current state remains immutable and delta is inspectable |
| DEC-05 | P0 | Add existing-system and unsafe-autonomy validators | DEC-04 | Acme target keeps existing systems and required approvals |
| ECO-01 | P0 | Implement baseline and input-evidence model | COM-02 | Inputs label measured, customer-estimated, AI-estimated, or simulated |
| ECO-02 | P0 | Implement versioned deterministic formulas | ECO-01 | Stored inputs reproduce all results exactly |
| ECO-03 | P0 | Add sensitivity scenarios and missing-input gate | ECO-02 | Low/base/high values display and required unknowns block approval |
| ECO-04 | P0 | Build business-case review UI | ECO-03 | Operator sees formulas, evidence, assumptions, and approval state |

## Epic 7: Specifications

| ID | Priority | Item | Depends on | Acceptance |
| --- | --- | --- | --- | --- |
| ART-01 | P0 | Define artifact and dependency model | DEC-04, ECO-04 | Artifact versions pin model, workflow, formula, and template versions |
| ART-02 | P0 | Implement PRD and architecture generators | ART-01 | Outputs are schema-checked and cite approved upstream versions |
| ART-03 | P0 | Implement business-rule, integration, control, and eval-plan generators | ART-01 | Required implementation packet is complete or explicitly blocked |
| ART-04 | P2 | Define and generate structured WorkOrders | ART-01 | Each WorkOrder has scope, constraints, acceptance, and required evidence |
| ART-05 | P0 | Implement stale artifact behavior | COM-07, ART-01 | Upstream change marks current outputs stale without deleting them |
| ART-06 | P0 | Export Markdown, YAML, and JSON | ART-02, ART-03, ART-04 | Export round-trip preserves identifiers and labels |

## Epic 8: Coding-Agent Sandbox — Post-V1

| ID | Priority | Item | Depends on | Acceptance |
| --- | --- | --- | --- | --- |
| ORC-01 | P2 | Define provider and sandbox interfaces | ART-04, FND-06 | A fake adapter and policy contract pass contract tests |
| ORC-02 | P2 | Create dedicated example target repository | ORC-01 | Repository has deterministic setup, task, and tests |
| ORC-03 | P2 | Implement one real coding-agent provider | ORC-01, ORC-02 | Approved WorkOrder produces captured output in sandbox |
| ORC-04 | P2 | Enforce filesystem, command, network, secret, time, and budget policy | ORC-03 | Escape and policy-violation tests stop and quarantine the run |
| ORC-05 | P2 | Implement run checkpoints, cancellation, and explicit completion | PLT-05, ORC-03 | Interrupted run ends or resumes without false success |
| ORC-06 | P2 | Capture diff, tests, logs, cost, and evaluation | ORC-03 | Required evidence is viewable and tied to the run |
| ORC-07 | P2 | Build WorkOrder approval and result UI | ORC-04, ORC-06 | Operator can approve, monitor, cancel, and inspect every terminal state |
| ORC-08 | P2 | Add a second provider | ORC-03 | Same contract suite passes without provider-specific domain logic |

## Epic 9: Design-Partner Readiness

| ID | Priority | Item | Depends on | Acceptance |
| --- | --- | --- | --- | --- |
| SEC-01 | P0 | Add OIDC and operator role | FND-06 | Unauthenticated access fails; operator flow succeeds |
| SEC-02 | P0 | Add application authorization and PostgreSQL row policies | SEC-01, FND-04 | Default-deny policies protect all engagement-owned tables |
| SEC-03 | P0 | Add cross-engagement isolation suite | SEC-02 | Read, write, job, export, search, and agent-tool attacks fail |
| SEC-04 | P0 | Implement retention, export, and deletion state | EVD-02, SEC-02 | A test engagement can be exported and deleted per policy |
| QLT-01 | P0 | Add full golden-path acceptance suite | All P0 | Clean environment passes the PRD release criteria |
| QLT-02 | P0 | Run accessibility and keyboard pass | All cockpit UI | Core flow meets documented WCAG 2.2 AA checks |
| QLT-03 | P0 | Review telemetry for sensitive content | All runtime work | Normal logs contain references, not raw evidence or secrets |
| QLT-04 | P0 | Write operator and sanitized-data onboarding guides | SEC-04, QLT-01 | A new operator can run the golden path and prepare safe data |

## P2: Explicitly Deferred

- Live Slack, email, Microsoft 365, ERP, or CRM connectors.
- Real customer pilot and production execution.
- Adoption, realized ROI, and production trust scores.
- Multi-customer pattern mining and platform promotion.
- Autonomous workflow or production changes.
- Graph database, Temporal migration, Redis, or microservices without a measured trigger.
