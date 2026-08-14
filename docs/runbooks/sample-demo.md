# Synthetic Sample Demo Runbook

## Purpose

This runbook proves the complete AI-FDE V1 journey in a disposable local environment. It starts
empty PostgreSQL and MinIO volumes, applies migrations, seeds the synthetic Acme engagement, starts
the API, persistent worker, and optimized web application, drives the cockpit through the real
browser, verifies the final packet, and removes the temporary runtime.

Use this run before an internal demo, for a merge candidate, or when reproducing an integration
failure. It is not a production-readiness or sanitized-data approval.

## What the demo proves

- The UI, API, worker, database, and object store operate together.
- Worker-produced candidate claims can be reviewed through the public cockpit.
- Exact evidence, human authority, contradiction resolution, and stage gates are enforced.
- Current workflow, target allocation, and deterministic sensitivity economics can be approved.
- Exactly seven dependency-pinned artifacts are generated as the engineering handoff.
- Unexpected API failures and browser console errors fail the run.
- A fresh run cannot inherit data or approval state from a previous run.
- Owned processes, containers, networks, and volumes are removed after success or failure.

## What the demo does not prove

- Auth0 against a live tenant.
- AWS deployment, network, workload identity, restore, rollback, or secret rotation.
- Bedrock extraction quality, latency, or cost.
- Sanitized or raw customer data handling.
- Realized ROI, percentage token savings, or pull-request cost reduction.
- Coding-agent execution or autonomous remediation.

The demo uses the deterministic synthetic Acme extraction fixture and an explicit local development
identity. Keep `AI_FDE_SANITIZED_DATA_ENABLED` false.

## Prerequisites

- macOS with Docker Desktop running.
- Python 3.13 and `uv`.
- Node.js 20.9 or newer and pnpm 10.
- `curl`, `lsof`, and Chromium installed by Playwright.
- Repository dependencies installed with `make setup`.
- No real customer data or production credentials in the environment.

The script checks required commands and ports before starting infrastructure.

## One-command automated rehearsal

From the repository root:

```bash
make demo-rehearsal
```

Expected terminal result:

```text
Running 1 test using 1 worker
  1 passed
Sample demo rehearsal passed in <duration> seconds.
Final browser evidence: output/playwright/demo/demo-complete.png
```

Success means the command exits zero. The screenshot is local evidence for visual inspection and is
intentionally ignored by Git.

## Automated journey

The browser test performs the following sequence without direct database mutation:

1. Confirms one synthetic Acme engagement is available.
2. Waits for the persistent worker to expose six claims.
3. Opens exact evidence for each claim.
4. Accepts four workflow-relevant claims.
5. Rejects two redundant entity-only claims.
6. Resolves the CFO/Controller evidence as a documented strategic-vendor exception.
7. Constructs and approves the current workflow.
8. Designs the target workflow.
9. Verifies the over-$50,000 approval remains Human and NetSuite processing remains Software.
10. Approves the target workflow.
11. Calculates and approves low/base/high economics.
12. Generates exactly seven current artifacts.
13. Inspects the implementation specification for dependency pins, the CFO rule,
    `annual_net_benefit`, and the V1 no-production-deployment boundary.
14. Fails if an AI-FDE API call returns an error, an AI-FDE request fails, or the browser logs an
    error-level console event.

## Presenter setup

For a live, human-operated walkthrough, use the normal local stack:

```bash
cp .env.example .env
make setup
make infrastructure
make migrate
make seed
make dev
```

Open [http://localhost:3000](http://localhost:3000). Before presenting, run the automated rehearsal
once on the same commit. Do not reuse the automated rehearsal's runtime: it intentionally cleans up
when the test completes.

## Talk track

### 1. Frame the problem

Say:

> Internal AI teams lose time and trust between discovery and implementation. AI-FDE preserves the
> chain from exact evidence to human-approved implementation intent.

State the limitations immediately: this is synthetic data, deterministic local extraction, and a
human-authoritative V1 ending at a Markdown implementation packet.

### 2. Select the engagement

**Action:** Open Acme Manufacturing.

**Show:** The Synthetic workspace label, named Accounts Payable workflow, and gated lifecycle.

**Point:** Synthetic and production state must not be visually ambiguous.

### 3. Review candidate claims

**Action:** Open exact evidence, accept workflow-relevant claims, and reject redundant entity-only
claims.

**Show:** Source excerpt, locator, confidence, decision note, and remaining review count.

**Point:** The model proposes. A human verifies. Evidence and verified truth remain distinct.

### 4. Resolve the contradiction

**Action:** Explain that invoices over $50,000 normally require CFO approval while approved annual
contracts permit a Controller exception. Enter a reason and resolve it as an accepted exception.

**Show:** The blocker cannot disappear without classification and an attributable reason.

**Point:** AI-FDE preserves the exception path instead of flattening conflicting evidence.

### 5. Approve the current workflow

**Action:** Construct and inspect the current-state steps, then approve.

**Show:** Ownership, sequence, systems, and approval authority derived from verified state.

**Point:** Workflow design starts from approved reality, not a generic best practice.

### 6. Review target allocation

**Action:** Design the target workflow and inspect the allocation controls.

**Show:** CFO approval remains Human; deterministic NetSuite processing remains Software.

**Point:** AI is one allocation option, not the default. Authority and control survive redesign.

### 7. Approve sensitivity economics

**Action:** Calculate low/base/high scenarios and approve the case.

**Show:** Labeled inputs, explicit transforms, formula version, and conservative ordering.

**Point:** The LLM does not perform the arithmetic. The result is a forecast, not realized ROI.

### 8. Inspect the engineering packet

**Action:** Generate the packet and move across all seven tabs.

**Show:** PRD, architecture, business rules, integration requirements, approval controls, evaluation
plan, and implementation specification. Open the implementation specification last.

**Point:** Every artifact shares one approved dependency set. Engineering receives rules, controls,
economics, evaluation, and provenance together.

### 9. Close with the business case

Connect the workflow to the intended measures:

- faster evidence-to-approved-packet time;
- fewer missed rules, contradictions, and rework loops;
- fewer engineering clarification requests;
- reproducible forecast and, later, realized value;
- model tokens and dollars per accepted material claim and approved packet.

Do not claim a percentage reduction until a comparable baseline and quality guardrail exist.

## Expected observations

| Checkpoint          | Expected result                                        |
| ------------------- | ------------------------------------------------------ |
| Engagement list     | Acme Manufacturing is visibly synthetic                |
| Candidate review    | six reviewable claims with exact evidence              |
| Verified state      | four accepted material assertions                      |
| Contradiction       | resolved as accepted exception with a reason           |
| Current workflow    | four steps and approved state                          |
| Target allocation   | CFO Human; NetSuite Software                           |
| Economics           | ordered low/base/high scenarios and approved base case |
| Packet              | exactly seven tabs, current and version-pinned         |
| Implementation spec | rule, economics, pins, and V1 boundary present         |
| Browser/runtime     | no console error or failed API call                    |
| Cleanup             | no demo containers, volumes, or listeners remain       |

## Ports and isolation

Defaults:

| Runtime          | Port  |
| ---------------- | ----- |
| PostgreSQL       | 55435 |
| MinIO API        | 59030 |
| MinIO console    | 59031 |
| AI-FDE API       | 8101  |
| Operator Cockpit | 3101  |

Override an occupied port for one run:

```bash
AI_FDE_DEMO_API_PORT=8201 AI_FDE_DEMO_WEB_PORT=3201 make demo-rehearsal
```

Available variables are `AI_FDE_DEMO_POSTGRES_PORT`, `AI_FDE_DEMO_MINIO_API_PORT`,
`AI_FDE_DEMO_MINIO_CONSOLE_PORT`, `AI_FDE_DEMO_API_PORT`, and `AI_FDE_DEMO_WEB_PORT`.

The Docker Compose project is `ai-fde-demo-rehearsal`; it is separate from normal development and
the clean static rehearsal.

## Failure diagnosis

On failure, the script:

1. exits nonzero;
2. stops only the child processes it started;
3. removes the dedicated Docker project and volumes;
4. prints the last 40 lines of bounded service logs;
5. leaves the temporary log directory path in the terminal;
6. retains Playwright failure traces/screenshots under the ignored test output paths.

Investigate in this order:

1. Read the first failing Playwright assertion or startup check.
2. Inspect the API, worker, web, and build log tails printed by the script.
3. Open the retained Playwright trace if the browser reached the cockpit.
4. Confirm no expected port was taken between preflight and process startup.
5. Re-run once only after identifying or changing the suspected cause.

A retry without diagnosis does not turn a flaky authority, isolation, or packet failure into a
pass.

## Manual cleanup verification

Cleanup is automatic. To verify after an interrupted host session:

```bash
docker compose -p ai-fde-demo-rehearsal ps -a
lsof -nP -iTCP:8101 -sTCP:LISTEN
lsof -nP -iTCP:3101 -sTCP:LISTEN
```

The Compose command should show no services and the listener commands should return no rows. If a
leftover demo project exists, inspect it before running the bounded cleanup:

```bash
docker compose -p ai-fde-demo-rehearsal down --volumes --remove-orphans
```

Do not remove the normal development project or broad Docker volumes.

## Rehearsal record

| Field                 | Value                                                                             |
| --------------------- | --------------------------------------------------------------------------------- |
| Date                  | 2026-08-14                                                                        |
| Tested implementation | `f9a2c82` (`test: add end-to-end delivery rehearsal`)                             |
| Host                  | Local macOS / Docker Desktop                                                      |
| Web mode              | Optimized Next.js build served with `next start`                                  |
| Data/provider         | Synthetic Acme / deterministic extraction                                         |
| Result                | Passed                                                                            |
| Browser result        | 1 passed in 2.3 seconds                                                           |
| Complete rehearsal    | 16 seconds                                                                        |
| Final evidence        | `output/playwright/demo/demo-complete.png` inspected                              |
| Console/API failures  | None                                                                              |
| Cleanup               | Containers, volumes, API, and web listeners removed                               |
| Exceptions            | None recorded                                                                     |
| External gates        | Auth0, AWS, Bedrock, recovery, deletion boundary, and secret rotation remain open |

The authoritative production decision remains the
[design-partner go/no-go record](design-partner-go-no-go.md).
