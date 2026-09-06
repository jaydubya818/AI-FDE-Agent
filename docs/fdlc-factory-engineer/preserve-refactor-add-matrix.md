---
title: Factory Engineer preserve, refactor, and add matrix
status: complete
date: 2026-09-04
audit_commit: 801d4c12e14dd4510d40906d8aeddf357df6edce
---

# Factory Engineer preserve, refactor, and add matrix

## Rating key

- **Yes** means the capability is safe to use within its stated production boundary and has direct test evidence.
- **Conditional** means the implementation is sound but depends on live infrastructure, operations, scale, or customer qualification that has not been proven.
- **No** means the capability is missing, materially incomplete, synthetic-only, or unsafe to present as production-ready.
- **Reusable as-is** is intentionally stricter than “code exists.” A capability can be worth preserving while still needing hardening.

## Existing application capabilities

| Capability | Current implementation | Production-ready? | Reusable as-is? | Needs extension? | FDLC role |
|---|---|---:|---:|---|---|
| Modular monolith | Next.js web, FastAPI API, shared Python domain, separate persistent worker | Yes, as a topology | Yes | Split only after measured need | Factory Engineer runtime |
| Engagement-scoped workspaces | Durable `Engagement` plus owner/operator/viewer membership | Conditional | Yes | Add customer identity, administration state, objectives, authorities | Discover and govern customer context |
| PostgreSQL persistence | SQLAlchemy, PostgreSQL, six Alembic migrations | Conditional | Yes | Add new aggregates through migrations | Authoritative FE record |
| Row-level isolation | Engagement RLS, non-bypass app role, denial tests | Conditional | Yes | Add composite tenant integrity and new-table policies | Customer isolation |
| Object-store isolation | Engagement-prefixed keys behind S3/MinIO adapter | Conditional | Yes | Orphan reconciliation, malware/quarantine, connector objects | Source-evidence storage |
| Evidence ingestion | Upload and operator-note routes; hash/dedup per engagement | No | Mostly | Stream/body limits, source versions, quarantine, deletion races | Discover customer reality |
| Evidence parsing | Bounded TXT, MD, CSV, EML, PDF, DOCX, PNG, JPEG parsers | Conditional | Mostly | Per-job/provider budgets; visual-region provenance | Normalize source evidence |
| Evidence provenance | Asset → segment → exact quote/offset/locator links | Yes | Yes | Add source identity, freshness, polarity, quality | Explain “why” |
| Candidate claim extraction | Deterministic fixture and constrained Bedrock providers | Conditional | Yes | Evaluation corpus, source-quality/support semantics, job budgets | Propose inference |
| Prompt-injection boundary | Untrusted-input prompt plus strict schema and offset checks | No | No | Adversarial evaluations and file scanning | Trust control |
| Human claim verification | Accept/reject/defer; acceptance creates verified assertions | Conditional | Mostly | Required reasons for material claims, corrections, concurrency, re-review | Human authority over understanding |
| Claim state | `candidate`, `accepted`, `rejected`, `deferred` | No | No | Split inference support, human disposition, freshness, materiality | Customer fact governance |
| Model confidence | One numeric claim `confidence` | No | No | Rename/record model confidence separately from human status and model version | Advisory inference signal |
| Multi-source support | Schema permits multiple claim/assertion evidence links | No | No | Correct singular API projection; corroboration and contradiction semantics | Evidence strength |
| Contradiction records | Blocking record, explicit resolution, audit event | No | Concept only | General detection, winner/supersession semantics, impact and dependencies | Surface ambiguity |
| Contradiction detection | Only conflicting `REQUIRES_APPROVAL` objects for same subject | No | No | General rules, temporal conflicts, scope, exceptions, evaluations | Trust/readiness gate |
| Unresolved unknowns | Mentioned in docs; no model or route | No | No | Add owner, materiality, blocker, due date, resolution evidence | Explicit uncertainty |
| Assumptions | Untyped strings on economic case | No | No | First-class identity, owner, evidence, expiry, approval, dependencies | Explainable economics/design |
| Operating-model construction | Accepted claims create typed entities and assertions | Conditional | Yes as substrate | Add relation semantics, aliases, owners, estate, decisions | Model customer reality |
| Typed operating model | Ten entity types and assertions | No | Partly | Add engineering estate types and schema/version contracts | Customer Factory Model content |
| Versioned operating model | No model-version aggregate; assertions mutate status independently | No | No | Add immutable `CustomerFactoryModelVersion` snapshots | Authoritative customer model |
| Current workflow | Generated version from verified projected assertions | Conditional | Partly | Real graph, branches, queues, exceptions, time/cost/rework | Baseline current state |
| Target workflow | Versioned design derived from approved current workflow | Conditional | Partly | Capabilities, fallbacks, escalation, graph and validation | Proposed factory operation |
| Human/software/AI allocation | Per-step `human`, `software`, `ai`, `ai_human` | Conditional | Concept | Evidence-backed feasibility, risk, authority, reversibility | Work classification |
| Workflow approval | Draft/approved/stale gate with operator, time, reason | Conditional | Mostly | Separation of duties, DB immutability, rejection/supersession | Consequential human decision |
| Staleness propagation | Conservative model → workflow → economics → artifact SQL updates | Conditional | Yes | Dependency/cause graph before selective invalidation | Prevent obsolete approvals |
| Economics model | `labor-capacity-sensitivity-v2` deterministic formulas | Conditional | Yes | Add error/rework, intervention, compute cost and observations | Business case |
| Low/base/high scenarios | Fixed, monotonic, reproducible sensitivity transformations | Yes | Yes | Per-input sensitivity and configurable justified ranges | Uncertainty communication |
| Input classifications | measured/calculated/estimated/synthetic/simulated | Conditional | Yes | Evidence link, observation window, verifier, freshness, “assumed” | Economic provenance |
| Reproducible formulas | Stored formula version, inputs, outputs and transforms | Yes | Yes | Pricing/version records for model costs | Auditability |
| Realized economics | Not implemented | No | No | Outcome and observation aggregates | Measure value |
| Seven artifact renderers | PRD, architecture, rules, integrations, controls, evaluation, implementation spec | Conditional | Yes | Map into package views; add structured contracts only when distinct | Implementation intent |
| Version-pinned artifacts | Content hash and pins to workflows/economics/assertions | Conditional | Yes | Package identity, schema/template versions, approval | Immutable handoff inputs |
| Acceptance criteria | Generic Markdown criteria inside artifacts | No | No | Identified, measurable, verifier-bound structured records | Verification contract input |
| Delivery assessment | Structured operator/engineering assessment | Yes for alpha | Yes | Customer outcome and deployment evaluations later | Product validation |
| Internal-alpha scorecard | Objective multi-profile gates and minimum comparative cohort | Yes for alpha | Yes | Fix recovered-run readiness and add labeled evaluation sets | Internal evidence, not customer proof |
| Provider token tracking | Extraction run input/output tokens | Conditional | Yes | Broader agent/tool runs and trace correlation | Technical telemetry |
| Model latency tracking | Extraction latency in milliseconds | Conditional | Yes | Histograms, SLOs, dashboards, worker health | Technical telemetry |
| Model cost tracking | Not implemented despite README wording | No | No | Pricing source/version and billed/estimated cost | Economics and operations |
| HTTP telemetry privacy | Metadata-only access logging with tests | Conditional | Yes | Trace propagation, backend/export, redaction verification | Technical observability |
| Audit events | Consequential domain actions persisted with actor and detail | Conditional | Yes as seed | Append-only grants, shared correlation/causation, timeline/decision projections | Engagement audit trail |
| Transactional outbox | Events written in domain transactions | No | Schema only | Publisher, versioned events, delivery attempts, cursors, dead letter | Integration reliability |
| Persistent worker | DB jobs, attempts, lease, `SKIP LOCKED`, retry/backoff | Conditional | Mostly | Lease ownership checks, heartbeat, dead letter, queue health | Source processing only |
| Worker service identity | Dedicated service operator and per-engagement membership | Conditional | Yes | Scalable assignment/admission and liveness | Least-privilege processing |
| OIDC identity | Auth-code/PKCE/state/nonce, allowlist, opaque hashed sessions | Conditional | Yes | Live tenant proof, provisioning, assurance/MFA policy | Human operator identity |
| Fail-closed production settings | Production requires OIDC, Bedrock, workload S3, service worker; sanitized data needs validation ID | Yes as config | Yes | Replace weak external-record string checks with verifiable attestations | Production gate |
| Data export | Versioned archive, hash, source fingerprint and receipt | Conditional | Yes | New aggregates, MC references, field-signal policies | Customer control |
| Permanent deletion | Export-bound confirmation and durable deletion receipt | Conditional | Yes | Derived signals, active handoffs, backups and legal holds | Customer control |
| Static health endpoint | Returns application OK | No | No | DB/object store/migration/worker/queue readiness | Operations |
| Synthetic hosted-demo adapter | Deterministic browser-local state; no live calls | Yes for demo | Yes in boundary | Contract parity, later simulated stages, reset/story improvements | Safe evaluation |
| Hosted-demo contract parity | Demo uses values invalid in backend schema | No | No | Shared/generated contract tests | Prevent narrative drift |
| Hosted-demo release configuration | Manual Vercel `--build-env` flags | No | No | Fail-fast Vercel invariant and post-deploy alias gate | Safe public demo |
| Golden-path browser test | Full evidence-to-seven-artifact Acme flow | Yes for synthetic | Yes | Gate every public alias; add new target flows incrementally | Release regression proof |
| Internal-alpha browser test | Three workflow shapes and objective scorecard | Yes for synthetic | Yes | Add engineering factory-line fixtures | Breadth proof |
| Accessibility tests | Axe WCAG A/AA, keyboard focus, landmarks, reduced motion | Yes for tested screens | Yes | Table alternatives for future graphs; CI enforcement | Inclusive operator UX |
| CI enforcement | No checked-in workflow | No | No | Start PostgreSQL, fail on skipped trust tests, run web suites/build | Release discipline |
| API type safety | Pydantic server models and handwritten TS types | Conditional | No | Generated/shared contract and demo parity test | Stable product contract |
| Pagination/concurrency | Unpaginated lists, N+1 provenance reads, `max + 1` version allocation | No at scale | No | Pagination, ETags/optimistic locking, aggregate locks | Multi-operator reliability |

## Target capabilities

| Capability | Current implementation | Production-ready? | Reusable as-is? | Needs extension? | FDLC role |
|---|---|---:|---:|---|---|
| Public Factory Engineer identity | AI-FDE/Operator Cockpit copy only | No | Internal names only | Centralize public name, description, links, tokens | FDLC product alignment |
| Curated Guide links | None | No | No | Stable topic-key registry and link health check | Contextual methodology |
| FDLC general-knowledge retrieval | Public search index exists outside FE but lacks revision/hash/provenance | No | No | Upstream content manifest, bounded advisory retrieval | General guidance, never customer truth |
| Structured interview | Operator note only | No | No | Session/question/response evidence with attribution and unresolved items | Discover |
| Connector capability | None | No | No | Read-only contract: identity, scopes, cursor, freshness, revocation, provenance | Discover |
| Customer Factory Model | Flat operating projection | No | Substrate only | Typed/versioned aggregate and relationships | Model |
| Evidence graph / “Why?” | Claim citations exist in review cards | No | Data base only | General trace view across recommendations, economics, risks and decisions | Explainability |
| “Ask the Customer Model” | None | No | No | Read-only cited query with explicit inference/unknown | Operator insight |
| Factory opportunities | None | No | No | Eligibility gates and explainable ordinal dimensions | Assess |
| Opportunity portfolio | None | No | No | Candidate/assessed/selected decision and comparison | Select lighthouse |
| Factory line | None | No | No | Independent aggregate, owner, risk, readiness, lifecycle, MC linkage | Long-lived unit of deployment |
| Factory Designer | Current/target list and allocation only | No | Workflow base | Graph, capability requirements, authority, verification, fallback | Design/configure |
| MCP requirement mapping | None | No | No | Semantic server/protocol version, scopes, data boundary, trust state and MC authorization mapping | Governed integration design |
| Autonomy model | No explicit model | No | No | Adopt Guide L0–L5 plus separate action authorities after ADR | Bounded autonomy |
| FDLC readiness | No evidence-backed stage assessment | No | No | Stage gates, evidence, blockers, owners, actions, waivers | Validate/deploy |
| Composite readiness score | None; public FDLC quiz is educational only | No | No | Defer until validated; use categorical gate status first | Portfolio summary only |
| Decision log | Audit rows only | No | Seed only | Alternatives, rationale, evidence, approver, expiry and dependencies | Human judgment |
| Engagement timeline | Audit/outbox rows only | No | Seed only | Durable event projection with actor, object and links | Audit/storytelling |
| Engagement observability | Run/model metrics and delivery scorecard are fragmented | No | Partial | Privacy-safe source/claim/agent/model/tool/decision/deployment/cost read models; keep technical telemetry separate | Operate and improve |
| Factory deployment package | Seven artifact rows only | No | Renderers only | Immutable aggregate, approval, readiness and schema digest | Governed handoff |
| Mission Control handoff | README link only | No | No | Versioned export/import preview; draft creation only | Deploy through control plane |
| Mission Control status projection | None | No | No | Ordered, reconcilable, read-only outcome/status contract | Deployment visibility |
| Outcome measurement | Assessments and projected economics only | No | No | Metric definition, window, source, baseline and deployment version | Measure |
| Shared failure taxonomy | Bounded worker codes only | No | Partial | Versioned cross-product taxonomy without collapsing native states | Learn |
| Field signals | None | No | No | Engagement-local observations and privacy-reviewed generalization | Learn/productize |
| Capability candidate library | None | No | No | Discovery/candidate layer; Agent Factory remains certification authority | Reuse |
| Reusable factory-line template fit | None | No | No | Versioned template reference, fit rationale, required customization/validation and customer-local extensions | Reuse without erasing local reality |
| Daily FDE attention view | Stage list and blockers distributed across cockpit | No | Data base only | Explainable, read-only priority projection | Human force multiplier |
| Reusable engineering fixtures | Three business workflow fixtures | No | Preserve current three | Add modernization, security remediation, test engineering | Generalization evidence |

## Disposition summary

### Preserve

The modular monolith, PostgreSQL/RLS foundation, evidence provenance, candidate-before-truth boundary, human review, workflow approvals, deterministic economics, seven artifact renderers, broad stale-on-change behavior, identity abstraction, worker separation, data lifecycle controls, demo isolation, and existing browser/accessibility suites.

### Refactor incrementally

Claim state, contradiction semantics, operating-model projection, workflow graph depth, authority/approval roles, dependency tracking, economics inputs, artifact aggregation, audit/outbox delivery, worker lease safety, API contracts, and demo/backend parity.

### Replace only at the concept edge

Replace the single mutable engagement progress label as the canonical lifecycle; do not replace the engagement record. Replace unqualified product use of “Evidence” with `SourceEvidence`; do not rename tables in Phase 1. Replace manual public-demo configuration with a build invariant; retain the adapter.

### Add after decisions and contracts

Customer Factory Model versions, unknowns/assumptions, interviews/connectors, opportunities, factory lines, readiness, Factory Designer, structured decisions, deployment packages, MC projections, outcomes, field signals, and capability candidates.

Nothing in this matrix supports a rewrite, a graph database, a new agent framework, or a shared database with Mission Control.
