# End-to-End Test Strategy

## Purpose

This strategy defines how AI-FDE earns confidence from source evidence through an approved
implementation packet. It gives engineering, FDE, product, security, and release owners one test
contract: what must be proven locally, what must be proven in a deployed environment, what evidence
is retained, and who may make the release decision.

The strategy optimizes for high-value failures. A passing test must show that a material product
invariant holds; it must not merely show that a page rendered or an endpoint returned 200.

## Quality principles

1. Human approval boundaries are product behavior, not optional UI ceremony.
2. Candidate model output never becomes verified truth without an attributable decision.
3. Exact provenance, dependency versions, and staleness are tested with the state they protect.
4. Deterministic code owns arithmetic, ordering, authorization, and lifecycle enforcement.
5. Browser tests cover critical journeys; lower layers cover permutations and failure detail.
6. Every release gate produces reproducible evidence or remains open.
7. Synthetic success cannot authorize sanitized customer data.
8. Model efficiency is measured with quality held constant: rejected output and retries count.

## Scope

### In scope for repository-local validation

- The complete synthetic Acme evidence-to-specification journey and a three-profile internal-alpha
  journey covering exception, handoff, and straight-through workflows.
- API, worker, PostgreSQL, MinIO, and production Next.js integration.
- Evidence provenance, candidate-claim review, contradictions, workflows, allocation, economics,
  artifact generation, audit, export, deletion, and engagement isolation.
- Configuration fail-closed behavior for production identity and sanitized data.
- Static validation of AWS Terraform and provider contracts.
- Accessibility, keyboard operation, and reduced-motion behavior for the golden cockpit flow.
- Token, latency, cost, and provider-run metadata persistence.
- Structured operator/engineering assessments, comparison thresholds, and scorecard derivations.

### Out of scope for a local pass

- Auth0 behavior against a live tenant.
- AWS network, IAM, ECS, RDS, S3, KMS, restore, and rollback behavior in a real account.
- Bedrock quality, latency, token, cost, and inference-profile behavior against a live model.
- Sanitized customer data.
- Realized customer ROI, percentage productivity improvement, or token-cost reduction claims.
- Coding-agent execution, pull-request remediation, and autonomous production changes.

Those items are deployment gates, not assumptions. Their records are required before design-partner
use.

## Test model

| Layer                  | Risk controlled                                          | Examples                                                 | Command                | Cadence                           |
| ---------------------- | -------------------------------------------------------- | -------------------------------------------------------- | ---------------------- | --------------------------------- |
| Unit                   | Incorrect local logic                                    | parsers, schemas, calculations, provider validation      | `make test`            | every change                      |
| Service integration    | Incorrect persistence or provider boundaries             | database transactions, object storage, jobs              | `make test`            | every change                      |
| Domain acceptance      | Broken lifecycle or invariant                            | provenance, approval gates, staleness, export, deletion  | `make acceptance`      | every change                      |
| Isolation              | Cross-engagement disclosure or mutation                  | application authorization and PostgreSQL RLS             | `make acceptance`      | every change                      |
| Browser accessibility  | Inaccessible operator control                            | axe, keyboard order, focus, reduced motion               | `make accessibility`   | every UI change and release       |
| Browser golden path    | Broken runtime integration                               | seed through seven-artifact packet                       | `make demo-rehearsal`  | merge candidate and demo          |
| Browser internal alpha | Workflow-specific coupling or false comparison readiness | three workflow packets, assessments, and locked baseline | `make alpha-rehearsal` | merge candidate and alpha session |
| Clean build            | Environmental drift                                      | empty migration, seed, tests, static checks, build       | `make rehearse`        | merge candidate and release       |
| Infrastructure static  | Invalid or unsafe declared stack                         | Terraform format and validation                          | `make terraform-check` | infrastructure change and release |
| External staging       | Local assumptions fail in reality                        | live Auth0, AWS, Bedrock, restore, deletion, rollback    | go/no-go record        | every deployed release            |

## Requirements-to-test traceability

| Product invariant                          | Primary proof                                | Secondary proof                                   |
| ------------------------------------------ | -------------------------------------------- | ------------------------------------------------- |
| Evidence cannot create verified truth      | claim-review acceptance cases                | browser reviews every candidate                   |
| Every material claim has exact evidence    | provenance acceptance cases                  | browser asserts exact-evidence panels             |
| Human and model confidence are separate    | claim schema and service tests               | packet contains verified assertions only          |
| Blocking conflicts remain visible          | contradiction acceptance cases               | browser supplies reason before resolution         |
| Material stages require approval           | workflow/economics/artifact acceptance cases | browser clicks each public approval control       |
| Approved versions are immutable            | version-history acceptance cases             | packet pins approved dependency IDs               |
| Upstream changes stale downstream work     | staleness acceptance cases                   | packet-current assertions                         |
| Economics reproduce deterministically      | economics unit and acceptance cases          | browser verifies ordered scenarios                |
| Engagements are isolated twice             | authorization and RLS suites                 | dedicated empty database rehearsal                |
| Jobs persist and expose failure state      | worker/job integration cases                 | demo polls completed worker output                |
| Uploaded content cannot change authority   | parser/provider validation cases             | deterministic fixture remains untrusted input     |
| Synthetic state is unmistakable            | fixture/config tests                         | browser asserts Synthetic workspace before action |
| Production claims require live proof       | fail-closed configuration tests              | unchecked external go/no-go record                |
| Comparative claims require matched cohorts | assessment and aggregate scorecard cases     | browser leaves the conventional baseline locked   |

## Critical browser journey

The browser golden path must perform these actions through accessible UI controls and public API
behavior:

1. Open the engagement list and verify the Acme engagement is labeled synthetic.
2. Open the engagement and wait for six worker-produced candidate claims.
3. Inspect exact evidence for every candidate.
4. Accept the four workflow-relevant claims and reject two redundant entity-only claims.
5. Confirm the review queue is clear and four verified assertions exist.
6. Resolve the CFO/Controller contradiction as an accepted exception with a human reason.
7. Construct and approve the four-step current workflow.
8. Design the target workflow and verify CFO approval remains Human while NetSuite work remains
   Software.
9. Approve the target workflow.
10. Calculate low/base/high economics and approve the base case.
11. Generate exactly seven artifacts as one current packet.
12. Verify the implementation specification contains version pins, the CFO rule, deterministic
    economics, and the no-production-deployment boundary.

The test fails on any AI-FDE API response at or above HTTP 400, failed AI-FDE API request, or
error-level browser console event. Playwright retains traces and screenshots on failure. A final
success screenshot is saved locally for human inspection and excluded from Git.

The internal-alpha browser journey repeats the governed lifecycle for Accounts Payable, Employee
Access Onboarding, and Customer Support Triage. It records one AI-FDE operator assessment per
workflow, verifies `3/3` packets, confirms the conventional baseline remains `0/3`, and writes a
reviewed scorecard screenshot for repository orientation. It does not fabricate human usability or
production model results.

## Negative, boundary, and recovery coverage

The critical browser test remains intentionally narrow. The following permutations belong at the
acceptance or service layer so the browser run stays fast and diagnostic:

- Approval is denied while a blocking contradiction is unresolved.
- Economics is unavailable before target approval.
- Artifact generation is unavailable before economic approval.
- Invalid evidence types, sizes, locators, hashes, and provider output fail closed.
- Duplicate and retrying jobs remain idempotent.
- A stale dependency invalidates the complete packet.
- Cross-engagement read and write attempts fail at the application and row-policy layers.
- Export hashes reproduce and deletion leaves only a content-free receipt.
- Production mode rejects development identity and unsafe credential combinations.
- Sanitized data remains disabled unless a current validation record is supplied.
- Provider timeout, refusal, malformed schema, bad provenance, and retry exhaustion are observable.
- Scenario values that violate conservative ordering are rejected.
- A completed AI-FDE assessment is rejected before the seven-artifact packet exists.
- Assessment updates preserve one current record while appending audit history without free-text
  notes.
- Comparison readiness remains false until both methods cover three distinct workflows.
- Readiness validation rejects mutable or mismatched images, disabled ECS rollback/version
  consistency, and incomplete or mismatched Bedrock evaluation jobs.

The rehearsal script separately verifies operational recovery:

- occupied ports fail before infrastructure starts;
- health polling is bounded rather than an indefinite wait;
- a browser or service failure exits nonzero and preserves bounded logs;
- interruption, failure, and success all stop owned processes and remove dedicated volumes;
- a second run starts from empty infrastructure and cannot inherit approval state.

## Test data policy

| Data class                   | Allowed environment               | Rule                                              |
| ---------------------------- | --------------------------------- | ------------------------------------------------- |
| Three synthetic fixtures     | local, CI, internal demo, staging | visibly labeled; safe to commit                   |
| Generated synthetic variants | local, CI, internal demo          | must be reviewed for accidental real identifiers  |
| Sanitized customer data      | deployed staging only after GO    | disabled until every external gate passes         |
| Raw customer data            | none in V1                        | never place in this repository or local rehearsal |

Test output must not contain credentials, cookies, tokens, raw prompts, raw model responses, or real
customer evidence. Failure logs use bounded tails and metadata. Runtime databases, exports,
disposable demo screenshots, Playwright reports, and Terraform state remain ignored. The reviewed
internal-alpha scorecard screenshot is intentionally committed as synthetic product evidence.

## Environment contract

### Developer environment

- Explicit development identity.
- Deterministic extraction provider.
- Synthetic data only.
- Local PostgreSQL and S3-compatible object storage.
- No calls to Auth0, AWS, or Bedrock.

### Clean rehearsal environment

- Dedicated Docker Compose project, database volume, object volume, bucket, and ports.
- Fresh migration and schema-drift check.
- Production Next.js build and server.
- Real API and persistent worker processes.
- Unconditional cleanup.

### External staging environment

- Production-equivalent identity, workload roles, network, database, storage, and extraction
  provider.
- Pinned release commit and image digests.
- Metadata-only telemetry.
- Sanitized data stays disabled until the release owner signs the complete go/no-go record.

## Non-functional strategy

### Security and privacy

- Treat cross-engagement access, raw-content telemetry, or unsafe authorization as P0.
- Run isolation tests for all customer-owned tables and material service operations.
- Validate OIDC, session revocation, allowlists, cookie attributes, workload identity, secret
  rotation, and least privilege in the deployed environment.
- Exercise export, permanent deletion, backup expiry, and recovery as one lifecycle contract.

### Accessibility

- Run automated WCAG checks on the golden flow.
- Verify full keyboard completion, visible focus, semantic names, status announcements, contrast,
  zoom, and reduced motion.
- Use accessible roles and labels in critical browser tests so a selector failure also identifies
  a likely operator-interface regression.

### Performance and resilience

Establish baselines before setting improvement claims. Record at minimum:

- evidence-to-reviewable-claims latency;
- API p50/p95 latency for stage transitions;
- job queue age, attempts, completion, and exhausted retries;
- time from engagement creation to approved packet;
- browser rehearsal duration;
- worker restart and database connection behavior.

Initial release thresholds must be written into the deployed go/no-go record after the first
representative staging run. A local deterministic run is a functional baseline, not a production
SLO.

### Model quality and cost

For each extraction evaluation, record model or inference-profile ID, prompt/schema version, input
and output tokens, retries, latency, dollars, accepted material claims, rejected claims, provenance
validity, and reviewer corrections.

Primary efficiency measures are:

- total model dollars and tokens per accepted material claim;
- total model dollars and tokens per approved current packet;
- end-to-end delivery time and rework for the same quality threshold.

Pull-request token cost is post-V1 because no coding agent is implemented. No percentage reduction
may be claimed until the same task set, quality gate, and measurement window are compared.

## Defect severity and release policy

| Severity | Definition                                                     | Examples                                                      | Decision                            |
| -------- | -------------------------------------------------------------- | ------------------------------------------------------------- | ----------------------------------- |
| P0       | security, privacy, authority, or irreversible data failure     | isolation bypass, raw evidence in logs, unauthorized approval | stop; sanitized processing disabled |
| P1       | critical journey cannot complete or result is materially wrong | worker cannot finish, economics wrong, packet mixes versions  | release blocked                     |
| P2       | important behavior degraded with a safe workaround             | confusing recovery, incomplete noncritical evidence           | owner and dated fix required        |
| P3       | cosmetic or low-risk improvement                               | minor copy or spacing issue                                   | may follow normal backlog           |

Flaky P0/P1 tests are failures. They are not retried into acceptance without a diagnosed cause and
owner. Quarantine requires a written risk decision and cannot remove coverage for an authority,
isolation, provenance, or deletion invariant.

## Release gates

### Merge gate

- Full Python suite passes.
- Ruff, mypy, ESLint, and TypeScript pass.
- Production web build passes.
- Relevant accessibility and browser tests pass.
- Migrations upgrade cleanly and Alembic reports no drift.
- Documentation links and formatting pass.

### Internal-demo gate

- `make demo-rehearsal` passes from empty infrastructure.
- The final screenshot is visually inspected.
- No hidden database edit, skipped decision, console error, or failed API request occurred.
- Demo limitations are stated before the talk track.

### Internal-alpha gate

- `make alpha-rehearsal` passes from empty infrastructure.
- Three workflow packets and three AI-FDE operator assessment records are visible.
- The incomplete conventional cohort prevents comparative output.
- Human alpha sessions follow the separate runbook before staging entry.

### Design-partner gate

Every line in the design-partner go/no-go record passes for the exact commit, image digests,
account, region, Auth0 tenant, and Bedrock profile. Missing evidence is NO-GO. Local proof cannot
waive an external gate.

## Ownership

| Role                   | Accountable for                                                   |
| ---------------------- | ----------------------------------------------------------------- |
| Change author          | relevant tests, reproducibility, and failure evidence             |
| Technical owner        | merge gate, migrations, runtime health, and rollback readiness    |
| Operating FDE          | golden-path usability, business correctness, and demo record      |
| Security/release owner | identity, isolation, telemetry, data lifecycle, and GO/NO-GO      |
| AI platform owner      | live model evaluation, quality threshold, and token/cost baseline |
| Engineering recipient  | packet completeness and kickoff acceptance feedback               |

One person may fill several roles in an early team, but every release record names the accountable
person for each decision.

## Evidence and retention

- CI retains test logs, failing Playwright traces/screenshots, and build results according to the
  repository hosting policy.
- Local success screenshots are disposable and ignored by Git.
- A deployed release record stores commit, image digests, environment identifiers, validation IDs,
  result, owner, date/time, and links to approved metadata-only evidence.
- Never attach secrets, customer content, raw model payloads, or session material to a test record.
- Keep a release record at least as long as the deployed release or engagement retention obligation,
  whichever is longer.

## Operator commands

```bash
make test              # Python unit, integration, acceptance, and isolation suite
make acceptance        # domain golden path and tenant-isolation subset
make accessibility     # browser accessibility and keyboard coverage
make lint              # Ruff, mypy, ESLint, and TypeScript
make terraform-check   # Terraform format and static validation
make rehearse          # fresh infrastructure, migration, tests, static checks, build
make demo-rehearsal     # production-mode synthetic browser golden path
make alpha-rehearsal    # production-mode three-profile internal-alpha journey
```

The sample-demo procedure and actual local rehearsal record are in
[the sample demo runbook](../runbooks/sample-demo.md). Delivery decisions are defined in
[the design-partner delivery plan](../delivery/design-partner-delivery-plan.md).
