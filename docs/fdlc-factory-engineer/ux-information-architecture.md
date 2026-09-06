---
title: Factory Engineer UX information architecture
status: proposed
date: 2026-09-04
---

# Factory Engineer UX information architecture

## UX direction

Preserve the operator cockpit and evolve it into a persistent engagement workspace. Do not make Factory Engineer a marketing page, a generic chat surface, or a linear setup wizard. The primary UX question is: **where should the human FDE spend scarce judgment today?**

The interface should feel like an enterprise engineering control room: calm, dense when useful, explicit about authority and evidence, and boring in the best way.

## Navigation model

### Global

- Engagements
- Daily attention
- Capability candidates
- Product documentation
- FDLC Framework, Guide, and Mission Control links
- Operator/session and data-classification context

### Within an engagement

1. Overview
2. Source Evidence
3. Claims
4. Customer Model
5. Current State
6. Factory Opportunities
7. Factory Lines
8. Economics
9. FDLC Readiness
10. Deployment Packages
11. Deployment
12. Outcomes
13. Learning
14. Observability
15. Timeline & Decisions
16. Data Lifecycle

This is an information architecture, not a demand for 15 top-level tabs on day one. Use grouped navigation and contextual subroutes:

```text
Understand     Overview · Source Evidence · Claims · Customer Model · Current State
Design         Opportunities · Factory Lines · Target/Factory Design · Economics
Deploy         Readiness · Deployment Packages · Mission Control
Operate        Outcomes · Learning · Observability
Govern         Timeline & Decisions · Data Lifecycle
```

## Existing-to-target screen map

| Existing screen/section | Target home | Change |
|---|---|---|
| Engagement list and internal-alpha scorecard | Engagements | Preserve; add administration status, factory-line summary, and stable demo banner |
| Cockpit stage summary | Overview | Recast as derived attention/readiness projection, not one canonical lifecycle |
| Evidence upload/list/operator note | Source Evidence | Rename in product copy; add freshness, source versions, connectors and processing recovery |
| Candidate claim review | Claims | Preserve review mechanics; add support/human/freshness axes, unknowns, contradiction inbox and concurrency |
| Verified model | Customer Model | Preserve flat projection initially; add version selector, typed relationships and provenance coverage |
| Current workflow | Current State | Preserve approval gate; add graph/swimlane, exceptions, handoffs, queues, time/cost/rework |
| Target workflow | Factory Line › Design | Preserve allocation; add capabilities, authority, verifier, fallback, environment and rollback |
| Economics | Economics | Preserve formulas/scenarios; add baseline evidence, intervention/compute cost, sensitivity and observed results |
| Specification / seven artifacts | Deployment Packages | Keep seven artifact views inside a package; add traceability/readiness/approval/handoff preview |
| Delivery proof | Outcomes and internal evaluation | Keep internal-alpha evaluation distinct from customer outcomes |
| Data lifecycle | Data Lifecycle | Preserve export/delete; expand new-aggregate and linked-MC semantics |
| No current screen | Factory Opportunities | Add eligibility-first, explainable ordinal portfolio |
| No current screen | FDLC Readiness | Add stage heatmap/table, blockers, evidence, owner, decision and next action |
| No current screen | Deployment | Add read-only Mission Control projection and reconciliation state |
| No current screen | Learning | Add customer-local field signals and reviewed capability candidates |
| Audit rows not exposed | Timeline & Decisions | Add linked event history and consequential decision records |

## Engagement overview

The overview is the default daily operating page, not a vanity dashboard.

### Header

- customer/engagement name and objective;
- synthetic/sanitized classification;
- administration status;
- last meaningful update and data freshness;
- owner and current decision authorities;
- clear production/demo distinction.

### Attention queue

Ordered, explainable cards for:

- material claims awaiting human review;
- blocking contradictions and unknowns;
- customer questions;
- stale evidence and artifacts;
- factory designs blocked on capability or authority;
- readiness gates and expiring waivers;
- package approvals;
- degraded MC synchronization or deployment state;
- outcomes whose observation window has completed;
- field signals awaiting privacy/product review.

Every recommendation says **why it is here**, the evidence/record that triggered it, impact, owner, and safest next action. It never mutates state automatically.

### Portfolio summary

Show each factory line with owner, objective, lifecycle state, FDLC readiness, autonomy level, risk, economics band, deployed version, MC link, and outcome health. Do not collapse the portfolio to one engagement phase.

## Signature trust affordances

### “Why do you believe this?”

Available on every material claim, workflow node, recommendation, opportunity, assumption, risk, readiness result, and design decision. The disclosure shows:

1. authoritative statement or recommendation;
2. exact source citations;
3. labeled inference and model/version;
4. support and contradiction state;
5. human decision and authority basis;
6. freshness and version;
7. downstream dependents and impact if changed.

Absence is explicit: “No supporting source evidence,” “Inference only,” or “Unknown.”

### “Ask the Customer Model”

This is a read-only cited query interface, not a generic RAG chat or mutation path. Every answer contains:

- direct answer when supported;
- citations the operator can open;
- labels for verified fact, approved assumption, inference, contradiction, or unknown;
- model/customer-model version and freshness;
- the user’s evidence-access boundary;
- suggested follow-up question when material ambiguity remains.

It must be impossible for a query response to approve a claim, modify a workflow, invoke MC, or widen connector permissions.

## Core workspace behavior

### Source Evidence

List source, version, provenance, classification, acquisition/observation time, freshness, processing state and dependent claims. Connector cards show scopes, last successful sync, cursor, revocation and bounded errors. Upload/interview/connector actions create new source records; they never overwrite reviewed history.

Failure states distinguish unsupported type, size limit, quarantine, parse failure, extraction failure, retry scheduled, exhausted retry, deleted-during-processing and connector authorization loss.

### Claims

Use separate filters for support, human disposition, freshness and impact. A contradiction inbox is first-class. The review action requires a reason for material verification/rejection and shows exact citations before submission. Concurrent updates use an expected version; a `409` shows the newer decision and offers reload/reapply, never silent last-write-wins.

### Customer Model

Default to a readable typed inventory and relationship table. Add a graph only where relationships materially help. Every graph has a keyboard-navigable tabular equivalent. Operators can compare approved versions, inspect provenance coverage, see stale elements, and start a new draft without editing the approved snapshot.

### Current State

Show how work actually happens, including exceptions and variance from documentation. Prefer swimlanes for actor/system handoffs, with a table alternative. Expose steps, decisions, queues, exceptions, time, cost, rework and risk. Conflicting documented/observed behavior remains visible.

### Opportunities

Run eligibility gates before ranking. Show explainable bands—value, frequency, standardization, evidence quality, verifiability, risk, system access, sensitivity and autonomy potential—with citations and assumptions. For eligible opportunities, show any versioned factory-line template fit, mismatch, required customization/validation, and customer-local extensions. Do not show fabricated “94/100” precision. “No suitable opportunity yet” is a successful, trustworthy result.

### Factory line and Designer

The factory-line workspace owns objective, selected current workflow, target design, capabilities, authority, validation, deployment linkage and outcomes. The Designer visually classifies nodes as human, deterministic software, agent, verifier, approval or system event. Selecting a node exposes inputs/outputs, capability, model, tool, MCP-server and skill requirements, permissions, context, retry/timeout, sandbox, verification, escalation and fallback.

A required agent/skill/tool/MCP server is labeled `REQUIRED`, `CANDIDATE`, `AVAILABLE`, `QUALIFIED`, or `UNAVAILABLE` based on an authoritative source. Factory Engineer does not imply certification or authorization merely because it generated a requirement.

### Economics

Separate baseline, projected, measured and realized views. Every input shows value, unit/currency, classification, source, observation period, owner, freshness and uncertainty. Sensitivity controls show formulas and justified ranges. Missing evidence renders as “insufficient evidence,” not `$0`.

### Readiness

Use a stage heatmap paired with a detailed table for Discover, Design, Assemble, Validate, Deploy, Operate and Improve. Each stage shows categorical status, evidence coverage, blockers, decisions, artifacts, owner and next action. Blocking gates stay prominent even if a future summary score is high. Waivers show scope, impact and expiry.

### Deployment package

The package page shows exact version pins, digest, readiness gate, seven existing artifact views, structured authority/verification/deployment sections, stale impact, approver, and MC handoff preview. The approval button is unavailable when required gates fail and explains each blocker. Once approved, fields are read-only; “Create new version” is the edit path.

### Deployment

Show only MC-projected facts: handoff/reconciliation health, Mission and Plan refs, WorkOrder summaries, verification, human acceptance, release, production verification and outcome links. Attempt completion never renders as accepted or deployed. A stale FE package displays an alert and policy action; FE does not directly cancel MC execution.

### Outcomes and Learning

Outcomes compare metric definition, baseline, projection and measured/realized observation by exact deployed version and window. Explain attribution limits. Learning begins engagement-local. The operator reviews a sanitized generalized form before any signal contributes to a cross-customer capability candidate.

### Observability

Provide an FDE-facing engagement view for source freshness, claim/review flow, agent/model/tool activity, tokens, latency, failures/retries, decisions, package/handoff health, MC-projected deployment activity and costs. Keep the engineering telemetry view separate. Both views label source system and “as of” time, link to governed records, omit raw customer content, and never treat telemetry as verification or acceptance proof.

## Durable feedback states

Every workspace and consequential action handles:

| State | Required behavior |
|---|---|
| Loading | Preserve page structure, identify what is loading, avoid false zeroes |
| Empty—not started | Explain the prerequisite and one safe next action |
| Empty—none found | Say what ran, over what scope, and that absence is not proof |
| Not applicable | Show the policy/decision that made it N/A |
| Error | Bounded message, correlation ID, retry only when safe, no raw customer content |
| Partial | Show completed/failed items and whether retry is idempotent |
| Stale | Show cause, affected version, dependents and required reapproval |
| Conflict | Show newer state and offer explicit reload/reapply |
| Permission denied | Name required authority without exposing sensitive configuration |
| Success | Persist a receipt/version/decision in the page; do not rely on a toast |
| Sync degraded | Show last successful reconciliation and whether displayed MC state may be old |

## Demo journey

Preserve the existing three fixtures. Extend the browser-local simulation incrementally to show:

1. start/resume engagement;
2. review source evidence;
3. verify claims;
4. resolve a contradiction;
5. approve current workflow;
6. assess opportunities and select a lighthouse line;
7. design target workflow and allocation;
8. review economics and readiness;
9. generate/approve a simulated deployment package;
10. preview a clearly simulated MC handoff;
11. record outcome assessment and field signal.

Add modernization, security remediation and test engineering fixtures without replacing the current three. Every simulated downstream state must say `SIMULATED`; demo hashes/approvals are not cryptographic or production proof. Demo mode never falls through to network APIs.

## Responsive and accessibility requirements

- Desktop-first graph/design editing; mobile supports reading, review, decisions and notifications.
- Every graph, heatmap and swimlane has an equivalent semantic table/list.
- Keyboard operation covers disclosures, graph-node selection, claim decisions, contradiction resolution and package approval.
- Focus moves to errors/receipts and returns predictably when dialogs/disclosures close.
- Status never depends on color alone; synthetic/simulated/stale/blocking states use text.
- Reduced motion continues to disable meaningful transitions.
- Axe WCAG A/AA checks remain release gates, supplemented by manual screen-reader and contrast review before customer launch.

## Navigation migration

1. Phase 1 changes only public identity, ecosystem links and terminology while retaining existing anchors and tests.
2. Add Overview as a projection over current data, then Claims/Source Evidence naming aliases.
3. Introduce route-level modules for Opportunities, Factory Lines and Readiness; do not expand the existing 1,000-line cockpit components.
4. Wrap Specification in Deployment Packages only after the package aggregate exists.
5. Add Deployment/Outcomes/Learning only after their contracts and data exist—no placeholder claims of live integration.
