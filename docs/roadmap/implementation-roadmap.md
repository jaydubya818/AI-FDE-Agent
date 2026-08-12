# V1 Implementation Roadmap

**Target:** Internal alpha at Week 6; design-partner candidate at Week 8
**Team:** One founder using AI coding agents
**Planning assumption:** Eight weeks. Six weeks may produce an internal alpha through implementation-ready artifacts, but it is not design-partner-ready. Compress only by reducing polish or provider breadth, not trust controls.

**Implementation snapshot — 2026-08-12:** The repository now implements multi-format bounded
evidence, a provider-neutral Bedrock production path, named primary workflows, low/base/high
economics, a seven-artifact packet, a dedicated service worker, production images, and validated
AWS Terraform. Sanitized-data readiness remains **NO-GO** until live Auth0/AWS/model, restore,
deletion-boundary, and secret-rotation evidence is signed.

## Delivery Rule

Every week ends with a runnable repository, a short golden-path demonstration, automated tests for completed behavior, and updated documentation. Incomplete capabilities remain behind a disabled route or feature flag. No placeholder page counts as progress.

## Phase 0: Product and Architecture Foundation

**Status:** Approved and implemented

Deliverables:

- Product vision and V1 PRD.
- FDE doctrine and lifecycle gates.
- System architecture and domain model.
- Company Operating Model schema.
- ADRs, repository structure, roadmap, and backlog.

Exit gate:

- Product owner approves the V1 boundary and proposed ADRs.
- No critical implementation decision is hidden in a prompt or backlog item.

## Week 1: Runnable Platform Spine

Build:

- Monorepo tooling and documented local setup.
- Web, API, worker, PostgreSQL, object-store emulator, migrations, and CI.
- Engagement creation and overview.
- Persistent job and transactional outbox foundations.
- Audit event foundation.
- Row-level policy test harness for engagement-owned tables.
- Acme seed command and a minimal fixture manifest.

Demonstration:

Create the Acme engagement, run a background job, restart the worker, and see the completed job and audit record in the cockpit.

Exit gate:

- Clean setup, migration, seed, test, lint, and dev commands work.
- Engagement scope is mandatory in application commands and jobs.

## Week 2: Evidence and Provenance

Build:

- Evidence upload, hashing, metadata, object storage, and supported parser interface.
- PDF, DOCX, text/Markdown, CSV, and diagram parsing needed by Acme.
- Timestamped operator notes as first-class evidence.
- Addressable evidence segments and locators.
- Idempotent ingestion state machine with retry and cancellation.
- Evidence list, detail, progress, failure, and empty states.
- Initial Acme transcripts, SOPs, policies, messages, and metrics.

Demonstration:

Upload the Acme evidence set, inspect exact segments, retry a forced parser failure, and prove that no duplicate asset or segment is created.

Exit gate:

- Original evidence remains immutable.
- Every parsed segment resolves to its source locator.

## Week 3: Extraction and Review Inbox

Build:

- Schema-constrained extraction runs.
- Candidate claims with exact evidence links.
- Review inbox with accept, edit, reject, defer, and bulk low-risk review.
- Candidate identity resolution and human merge decision.
- Contradiction and unknown creation.
- Prompt, model, schema, cost, and validation telemetry.
- Indirect prompt-injection cases for evidence and retrieved context.

Demonstration:

Extract Acme claims, review them, find the seeded approval-rule conflict, and preserve both sources without updating canonical truth automatically.

Exit gate:

- Material claims always require review.
- Invalid model output cannot enter the operating model.
- The critical AP rule and exception appear in the acceptance dataset.

## Week 4: Company Model and Current Workflow

Build:

- Operating entities, aliases, versioned relationships, assertions, and model snapshots.
- Current and historical projections.
- Searchable model list/detail and a bounded graph view.
- Process and workflow versions, steps, transitions, rules, exception paths, and evidence.
- Current-state workflow editor and approval gate.
- Staleness events when accepted model state changes.

Demonstration:

Navigate from the Acme company model to the AP workflow, inspect evidence for each material rule, and show that the unresolved conflict blocks approval.

Exit gate:

- Approved workflow versions are immutable.
- Material workflow elements have provenance.
- The operator can leave and resume without losing state.

## Week 5: Allocation, Target Workflow, and Economics

Build:

- Deterministic allocation factor model and explainable AI-assisted recommendation.
- Human, Software, AI, and AI + Human decisions with controls.
- Target workflow drafting, comparison, review, and approval.
- Baseline inputs, evidence quality labels, formulas, scenario, sensitivity, and business-case view.
- Existing-system preservation check and unsafe-autonomy check.

Demonstration:

Review every AP step, approve a target workflow around Acme's existing systems, and reproduce the business-case calculations from stored inputs.

Exit gate:

- Every step has a reviewed allocation.
- No arithmetic depends on unstructured model output.
- Missing required baseline inputs block final approval.

## Week 6: Implementation-Ready Artifacts

Build:

- Versioned artifact generator and templates.
- PRD, architecture brief, business rules, integration needs, approval model, and evaluation plan.
- Artifact dependency graph and stale-state behavior.
- Markdown, YAML, and JSON export.

Demonstration:

Generate a coherent implementation packet from the approved Acme model and workflow, change one upstream rule, and show the packet becomes stale.

Exit gate:

- Artifacts cite model and workflow versions.
- The implementation packet is usable for engineering kickoff.

## Week 7: Trust and Security Hardening

**Status:** Code complete; live validation open — explicit principals, application authorization,
Auth0-backed opaque sessions, service-worker identity, route/RLS isolation, bounded data lifecycle,
and metadata-only telemetry are implemented. Live Auth0 and deployed-worker evidence remain open.

Build:

- Verify the implemented OIDC/operator flow against the deployment Auth0 tenant.
- Complete application authorization and PostgreSQL row-policy coverage.
- Cross-engagement isolation across all V1 data paths.
- Rehearse the implemented retention, export, deletion, and failure-retry workflow.
- Sensitive telemetry review and operational failure states.

Demonstration:

Authenticate as the operator, run cross-engagement attack cases, and export then delete a test engagement according to policy.

Exit gate:

- Unauthenticated access fails and all engagement-owned records fail closed.
- The sanitized-data handling path is documented and testable.

## Week 8: Trust, Security, and Design-Partner Hardening

**Status:** Code complete; sanitized-data no-go — accessibility, clean-environment tooling,
onboarding, ADRs 0012–0014, production images, Terraform, Bedrock adapter, and automated readiness
checks are complete. The required live records remain release gates.

Build:

- Accessibility and keyboard pass for the golden path.
- Observability dashboards and sensitive telemetry review.
- Golden-path acceptance suite and clean-environment rehearsal.
- Operator guide and design-partner data checklist.

Demonstration:

Run the full workflow from a clean environment, pass the release criteria, and export then delete a test engagement according to policy.

Exit gate:

- All PRD release criteria pass.
- Proposed ADRs used by the implementation are accepted.
- Known limitations and simulations are visible in the product and documentation.

## Scope Protection

The Week 6 checkpoint is an internal alpha. The Week 8 checkpoint is the design-partner candidate. If Weeks 7–8 are not complete, the product must not claim sanitized-customer readiness.

Do not cut:

- Evidence provenance.
- Human review of material claims.
- Contradictions and unknowns.
- Versioned current and target workflows.
- Deterministic economics.
- Engagement isolation.
- Acceptance tests for the seeded hidden rule.

Cut first if time is constrained:

1. graph visualization polish beyond bounded exploration;
2. server-sent live updates;
3. bulk review optimization;
4. advanced identity matching;
5. nonessential file formats;
6. optional dashboard summaries.

Do not replace a cut capability with a fake simulation. Mark it deferred.

## Post-V1 Sequence

1. Sandboxed coding-agent WorkOrders and execution evidence.
2. Sanitized design-partner engagement.
3. One live read-only connector justified by that engagement.
4. Real workflow evaluation and shadow mode.
5. Pilot operations and incident handling.
6. Measured adoption and realized ROI.
7. Pattern promotion only after repeated evidence across engagements.
