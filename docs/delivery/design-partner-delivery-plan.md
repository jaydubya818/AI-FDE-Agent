# Design-Partner Delivery Plan

## Objective

Deliver AI-FDE to an internal AI team in controlled stages, prove the complete synthetic journey,
validate every external production assumption, and admit one design-partner engagement only when the
system is operationally ready.

The delivery outcome is not a successful presentation. It is a repeatable operating capability: an
FDE can turn bounded evidence into an approved, version-pinned engineering packet while the team can
explain the provenance, cost, controls, failure state, and rollback path.

## Delivery principles

1. One primary workflow, one named FDE owner, one release record.
2. Synthetic data first; sanitized data is a separate, explicit decision.
3. Local proof validates code. Deployed proof validates production assumptions.
4. Every stage has entry criteria, exit evidence, a decision owner, and stop conditions.
5. The product remains human-authoritative through V1.
6. No delivery claim is expressed as a percentage until a baseline and comparable window exist.
7. Coding-agent execution and autonomous remediation remain outside this plan.

## What is being delivered

### V1 capability

- Evidence ingestion with immutable content hashes and inspectable source locations.
- Persistent provider-neutral extraction into candidate claims.
- Human claim review, contradiction handling, uncertainty, and audit history.
- A verified engagement-isolated Company Operating Model.
- Approved current and target workflow versions with explicit Human / Software / AI allocation.
- Deterministic low/base/high economics with labeled inputs and formulas.
- A current seven-artifact engineering packet with dependency pins.
- OIDC-oriented identity, workload identity, RLS, retention, export, and deletion foundations.
- Token, latency, cost, attempt, and provider-run metadata for efficiency measurement.

### Explicit delivery boundaries

- One named primary workflow per engagement.
- Markdown implementation artifacts.
- Transparent deterministic extraction for three synthetic workflow profiles.
- No customer self-service, live source connectors, OCR, process mining, or multi-workflow ranking.
- No automatic code generation, pull-request creation, remediation, or production changes.
- No claim of realized ROI or token-cost reduction before baseline measurement.

## Workstreams

| Workstream       | Deliverable                            | Accountable owner               | Completion evidence                     |
| ---------------- | -------------------------------------- | ------------------------------- | --------------------------------------- |
| Product workflow | evidence-to-packet lifecycle           | technical owner + operating FDE | browser and acceptance passes           |
| Quality          | layered test and release gates         | technical owner                 | test strategy and clean rehearsal       |
| Identity         | operator and worker identity           | security/release owner          | live Auth0 and workload records         |
| Infrastructure   | production-equivalent AWS runtime      | cloud owner                     | pinned deployment and validation record |
| Model provider   | production extraction and evaluation   | AI platform owner               | fixed Bedrock evaluation report         |
| Data lifecycle   | retention, export, deletion, recovery  | security/release owner          | restore/deletion/expiry records         |
| Operations       | monitoring, incident, rollback         | technical owner                 | dashboard, alerts, rehearsal evidence   |
| Adoption         | FDE onboarding and engineering handoff | FDE leader                      | completed engagement and feedback       |
| Economics        | baseline and outcome measurement       | FDE leader + finance sponsor    | comparable baseline and result record   |

## Stage plan

### Stage 0 — Merge-ready implementation

**Purpose:** Prove the codebase is coherent before involving internal operators.

**Entry criteria**

- The feature branch is based on current main.
- No unrelated or sensitive runtime files are included.
- The implementation and end-to-end test plans are reviewable.

**Activities**

- Run the full Python, acceptance, isolation, lint, type, build, accessibility, and Terraform gates.
- Run migrations from an empty PostgreSQL volume and confirm no Alembic drift.
- Run the production-mode synthetic browser rehearsal.
- Inspect the final packet screenshot and any warning/error output.
- Confirm the dedicated rehearsal resources are deleted.

**Exit evidence**

- All required commands pass on the exact source tree.
- The golden path completes through exactly seven current artifacts.
- No P0/P1 defect remains open.
- Documentation states local limitations without implying production validation.

**Decision owner:** technical owner.

### Stage 1 — Internal scripted demo

**Purpose:** Show internal AI and FDE leaders the actual trust and delivery flow, not a slide-only
concept.

**Entry criteria**

- Stage 0 passed and the commit is on main.
- Demo host meets prerequisites and uses synthetic configuration.
- A presenter and a backup operator have read the runbook.

**Activities**

- State the synthetic-data and deterministic-extraction boundaries before opening the cockpit.
- Run `make demo-rehearsal` once before the session.
- Walk the manual talk track: evidence, exact provenance, decisions, conflict, allocations,
  economics, and packet.
- Demonstrate one intentional gate, such as the unresolved contradiction blocking approval.
- Collect questions against the value proposition: faster discovery, retained context, stronger
  specifications, trustworthy AI output, better handoffs, economics, and token efficiency.

**Exit evidence**

- The operator completes the flow without database edits or undocumented interventions.
- The audience can distinguish candidate output from approved truth.
- Product questions and defects have owners; no P0/P1 issue is deferred.
- The delivery boundary is understood: no sanitized data yet.

**Decision owner:** FDE leader.

### Stage 2 — Internal alpha

**Purpose:** Establish usability and outcome baselines with internal operators before external data
or commitments.

**Entry criteria**

- A named FDE owner and technical owner are available for the alpha window.
- Synthetic or purpose-built fictional evidence covers at least three workflow shapes.
- Telemetry is metadata-only and reviewed for sensitive fields.
- Defect intake, severity, and response ownership are active.

**Activities**

- Have at least two FDEs complete independent engagements without implementation-team help.
- Include a straight-through workflow, an exception-heavy workflow, and a system-handoff workflow.
- Measure time by lifecycle stage, review correction rate, contradictions found, packet completeness,
  clarification requests, and model-run metadata.
- Record structured operator and engineering assessments for AI-FDE and the conventional method.
- Compare the generated packet with a conventional document/spreadsheet handoff for the same task.
- Record usability failures, missing states, and where operators leave the product for another tool.
- Review the packet with an engineer who did not participate in discovery.

**Exit criteria**

- Every alpha engagement reaches a current packet or has a product-visible blocking reason.
- Zero cross-engagement access and zero raw-content telemetry findings.
- The median operator can repeat the flow from the runbook.
- Engineering accepts the packet structure and all critical clarification gaps have owners.
- Baseline metrics exist; the team makes no unsupported percentage claim.
- Comparison readiness has three completed operator assessments per method across three distinct
  workflows; incomplete cohorts remain visible rather than extrapolated.

**Decision owner:** FDE leader with technical owner concurrence.

### Stage 3 — Production-equivalent external staging

**Purpose:** Replace proposed production decisions with live evidence.

**Entry criteria**

- Stage 2 exit criteria passed.
- A dedicated AWS account/region, Auth0 tenant, domain, and Bedrock access are approved.
- Federated deployment credentials and named accountable owners exist.
- The exact commit and image digests are pinned.
- Sanitized data remains disabled.

**Activities and gates**

#### Identity

- Validate Auth0 login, PKCE callback, allowlist, opaque session, expiry, logout, revocation, and
  unauthenticated behavior against the live tenant.
- Verify separate operator, worker, migration, and deployment identities.
- Prove the worker has only explicit engagement memberships and its own audit attribution.

#### Infrastructure

- Deploy the pinned images through reviewed Terraform.
- Verify private ECS tasks, no public task IP, TLS, security groups, RDS encryption/Multi-AZ/PITR,
  S3 public-access block/KMS policy, and least-privilege roles.
- Validate startup, health checks, rolling replacement, and previous-image rollback.
- Confirm the database migration is backward compatible with the rollback window.

#### Extraction

- Run a fixed synthetic evaluation set through the selected Bedrock model or inference profile.
- Measure schema validity, exact provenance, precision/recall for material claims, correction rate,
  latency, tokens, retries, and cost.
- Reject provider fallback or invocation logging that could disclose evidence.

#### Recovery and lifecycle

- Restore RDS and reconcile evidence objects; re-run isolation checks.
- Run export and permanent deletion on a staged engagement.
- Verify the content-free receipt and document RDS backup-expiry and S3 deletion boundaries.
- Rotate runtime secrets and prove the previous versions no longer work.

#### Operations

- Exercise one failed worker job, one API rollback, and one dependency outage.
- Verify metadata-only logs, alerts, dashboards, escalation, and recovery instructions.
- Record API latency, queue age, worker attempts, provider usage, and infrastructure health.

**Exit evidence**

- Every checkbox in the design-partner go/no-go record is complete for the exact release.
- A reviewer other than the implementer verifies identity, isolation, lifecycle, and telemetry.
- Rollback and restore evidence is current.
- Bedrock quality and cost meet the approved threshold.
- No P0/P1 defect remains open.

**Decision owner:** security/release owner. An incomplete field is NO-GO.

### Stage 4 — Sanitized design-partner pilot

**Purpose:** Validate one real delivery outcome under bounded operational conditions.

**Entry criteria**

- Stage 3 has a signed GO decision.
- Contractual data classification, retention, deletion, subprocessors, and incident contacts are
  agreed.
- One workflow and one customer process owner are named.
- Data has been sanitized through an approved procedure outside AI-FDE.
- Success measures and a conventional baseline are documented before ingestion.

**Activities**

- Enable sanitized data through a reviewed, release-specific configuration change.
- Ingest only the approved evidence set.
- Keep every model-created claim in candidate state until the FDE reviews it.
- Hold structured reviews at current workflow, target workflow, economics, and final packet.
- Have the process owner confirm rules, authority, exceptions, and systems of record.
- Have an independent engineer assess packet completeness before implementation begins.
- Monitor the first complete engagement and first 72 hours after deployment.

**Exit measures**

- Time from evidence receipt to approved packet, broken down by stage.
- Accepted material claims, reviewer corrections, missed critical rules, and contradictions found.
- Packet completeness, engineering clarification requests, and implementation rework.
- Low/base/high forecast reproducibility and sponsor acceptance.
- Tokens and model dollars per accepted material claim and approved packet.
- Operator satisfaction, workarounds, and trust failures.

**Decision owner:** FDE leader and customer process owner, with security/release owner retaining stop
authority.

### Stage 5 — Pilot closeout

**Purpose:** Turn one engagement into an evidence-based product decision.

- Export or delete the engagement according to the agreed retention decision.
- Confirm backups and receipts match the stated deletion boundary.
- Compare actual delivery measures with the pre-pilot baseline.
- Separate product benefit from model cost, infrastructure cost, FDE review, and change management.
- Decide whether to continue, correct, narrow, or stop.
- Update the roadmap from measured bottlenecks, not feature requests alone.

## Proposed implementation sequence

The calendar starts only when the named owners and external accounts are available.

| Week | Focus                                    | Exit milestone                                |
| ---- | ---------------------------------------- | --------------------------------------------- |
| 0    | merge-ready local proof                  | main passes clean build and browser rehearsal |
| 1    | internal demo and operator onboarding    | talk track repeated without intervention      |
| 2    | internal alpha engagements               | initial usability and timing baseline         |
| 3    | Auth0, AWS, workload identity            | production-equivalent runtime healthy         |
| 4    | Bedrock evaluation, telemetry, lifecycle | fixed quality/cost and recovery evidence      |
| 5    | rollback, secret rotation, final review  | signed design-partner GO/NO-GO                |
| 6–7  | one sanitized pilot if GO                | approved packet and 72-hour observation       |
| 8    | export/deletion and closeout             | measured continue/correct/stop decision       |

This is an eight-week risk-burn-down sequence, not a date promise. Missing access, owner capacity,
or failed gates moves the pilot; it does not waive the gate.

## Rollout and change control

- Use one release commit and immutable image digests per environment.
- Apply database migrations as a separately attributable deployment step.
- Prefer backward-compatible schema changes across the rollback window.
- Review Terraform changes and production feature flags separately from product code.
- Keep `sanitized_data_enabled` false by default and fail startup if its validation record is
  absent, expired, or mismatched.
- Record configuration, migration revision, provider profile, and formula version with the release.
- Freeze nonessential feature work during the first pilot engagement.

## Stop, rollback, and recovery

### Immediate stop conditions

- Cross-engagement access succeeds at any layer.
- Customer evidence, credentials, cookies, prompts, or raw model payloads appear in normal logs.
- An unauthorized actor can approve a material transition.
- A provider silently falls back to an unevaluated model.
- Deterministic economics cannot be reproduced.
- The packet mixes versions or appears current after an upstream change.
- Export, deletion, restore, or rollback cannot complete as documented.

### Response

1. Disable sanitized ingestion and pause active worker execution.
2. Preserve metadata-only incident evidence and identify affected engagement IDs.
3. Roll application images back to the previous pinned digests when schema compatibility permits.
4. Do not reverse an incompatible migration; use the documented forward-recovery procedure.
5. Notify the named release, security, FDE, and customer contacts.
6. Reopen the relevant go/no-go gate and require new evidence before resuming.

## Monitoring plan

### Healthy signals

- API health and p95 latency remain within the staging baseline.
- Worker queue age drains; retries are bounded; exhausted jobs alert.
- Candidate output has valid schema and provenance.
- Review, contradiction, workflow, economics, and artifact gates remain ordered.
- Packet dependency fingerprints remain current.
- Token, latency, cost, and acceptance metadata reconcile for every provider run.
- RDS, ECS, S3/KMS, and Auth0 show no unexplained denial or restart pattern.

### Review cadence

- During deployment: continuous owner presence through health and smoke checks.
- First 24 hours: check dashboards and job state after each material pilot action.
- First 72 hours: daily technical/FDE review with explicit continue or pause decision.
- Remainder of engagement: weekly outcome and defect review.
- Closeout: signed export/deletion and metric comparison.

## Communication and handoff packet

Each stage produces a small, auditable packet:

- release identity and decision owner;
- completed entry/exit checklist;
- commands or validation IDs used;
- defect list with severity and owner;
- known limitations and explicit no-go items;
- rollback target and recovery contact;
- outcome measures and next decision.

No sensitive content belongs in the delivery packet. Customer evidence remains inside the governed
engagement and approved storage boundary.

## Success decision

The pilot succeeds when AI-FDE improves the quality and repeatability of a real FDE handoff while
preserving human authority and producing attributable cost evidence. The decision is based on the
baseline and quality guardrails, not on a polished demo or raw token reduction.

Use [the end-to-end test strategy](../testing/end-to-end-test-strategy.md) for release evidence,
[the sample demo runbook](../runbooks/sample-demo.md) for the local proof, and
[the go/no-go record](../runbooks/design-partner-go-no-go.md) for the external decision.
