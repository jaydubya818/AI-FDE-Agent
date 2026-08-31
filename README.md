# AI-FDE

## Evidence-to-decision infrastructure for Forward Deployed AI Engineering

AI-FDE is a stateful operating system for internal AI teams and Forward Deployed Engineering leaders. It turns fragmented enterprise evidence into a **verified operating model**, helps a human FDE redesign a workflow, quantifies the business case, and produces a version-pinned implementation packet for engineering.

The project explores a core problem in AI-native delivery:

> Before autonomous agents can safely build or automate a business workflow, the system needs trustworthy implementation intent.

AI-FDE is the governed layer between messy enterprise reality and downstream execution.

```text
Evidence
  → candidate claims
  → human review
  → verified operating model
  → approved current workflow
  → Human / Software / AI allocation
  → approved target workflow
  → reproducible economics
  → implementation-ready artifacts
```

## Why this matters

Enterprise AI projects rarely fail because a model cannot generate code. They fail because implementation begins from incomplete context, undocumented exceptions, weak economics, unclear authority, or requirements that were never verified against how the business actually operates.

AI-FDE is designed to make that discovery-to-delivery path **repeatable, auditable, evidence-backed, and measurable**.

## What the system does

- ingests enterprise evidence into an engagement-scoped workspace
- extracts bounded candidate claims instead of silently promoting generated text to truth
- preserves exact source provenance for human review
- surfaces contradictions, unknowns, rules, approvals, and exception paths
- builds a typed and versioned Company Operating Model / Business Twin
- separates current-state workflow from target-state design
- makes Human / deterministic software / AI allocation explicit
- models low/base/high economics from stored assumptions and formulas
- generates version-pinned implementation artifacts and acceptance criteria
- tracks model tokens, latency, cost, and accepted outcomes
- preserves audit history and human approval boundaries

## Product thesis

A coding agent can implement a precise specification that is precisely wrong.

AI-FDE therefore keeps four things separate:

1. **Evidence** — what source material actually says
2. **Inference** — what AI proposes from that evidence
3. **Approval** — what a human accepts as authoritative
4. **Execution intent** — what downstream engineering systems are allowed to build

That separation creates a safer bridge from enterprise discovery to AI-native engineering execution.

## Trust model

- Evidence may create candidate claims but cannot directly create verified truth.
- Material assertions must resolve to stored evidence.
- Model confidence and human verification are separate.
- Contradictions remain visible until explicitly resolved.
- Approved versions are immutable.
- Upstream changes stale dependent downstream artifacts.
- Economic outputs reproduce from stored inputs and formulas.
- Customer records remain engagement-scoped.
- Long-running work is persistent, retryable, and observable.
- Uploaded content is untrusted input and cannot expand system authority.

## Relationship to autonomous software delivery

AI-FDE and [Mission Control](https://github.com/jaydubya818/MissionControl) solve different layers of the same broader problem.

**AI-FDE** turns uncertain enterprise evidence into governed implementation intent.

**Mission Control** turns governed implementation intent into bounded agent execution, verification, evidence, pull requests, and human decisions.

```text
Enterprise evidence
      ↓
    AI-FDE
      ↓
Verified implementation intent
      ↓
 Mission Control / Software Factory
      ↓
Bounded agent execution
      ↓
Verification + evidence
      ↓
Human-approved delivery
```

## Current status

**Internal-alpha code candidate; synthetic-data only.**

The synthetic evidence-to-specification path is implemented across multiple workflow shapes with structured delivery assessments and an objective program scorecard. External production gates—including live identity/cloud controls, restore/deletion evidence, secret rotation, and model-evaluation evidence—remain intentionally fail-closed.

The repository does not claim production readiness or realized customer ROI. Current economics are scenario-based and reproducible from versioned inputs.

## Live hosted demonstration

[Open the public AI-FDE demonstration](https://ai-fde-agent.vercel.app).

The Vercel production build runs an explicitly labeled, deterministic, synthetic demonstration of the complete operator workflow. It lets an evaluator review claims, resolve contradictions, approve current and target workflows, calculate low/base/high economics, generate seven version-pinned artifacts, and record a delivery assessment.

Demo state is stored in the evaluator's browser. It can be reset by clearing site data. The hosted demo makes no model call, accepts no customer data, and does not claim live PostgreSQL isolation, Auth0 validation, a persistent worker, AWS object storage, Bedrock extraction, or production readiness. Those capabilities remain on the real FastAPI deployment path and fail closed until their external gates are satisfied.

The public build is deployed from the repository root with the Vercel project root configured as `apps/web`:

```bash
vercel link --yes --project ai-fde-agent
vercel deploy . --prod \
  --build-env NEXT_PUBLIC_AI_FDE_HOSTED_DEMO=true \
  --build-env NEXT_PUBLIC_AI_FDE_API_URL=https://api.ai-fde.invalid/api \
  -y
```

The invalid API URL is intentional in hosted-demo mode: browser requests are handled by the synthetic adapter and cannot silently fall through to an unvalidated service.

Run the deployed golden path and accessibility checks directly against the public URL:

```bash
AI_FDE_PLAYWRIGHT_BASE_URL=https://ai-fde-agent.vercel.app \
AI_FDE_PLAYWRIGHT_EXTERNAL_SERVER=true \
pnpm --dir apps/web run test:e2e:golden

AI_FDE_PLAYWRIGHT_BASE_URL=https://ai-fde-agent.vercel.app \
AI_FDE_PLAYWRIGHT_EXTERNAL_SERVER=true \
pnpm --dir apps/web run test:e2e:alpha

AI_FDE_PLAYWRIGHT_BASE_URL=https://ai-fde-agent.vercel.app \
AI_FDE_PLAYWRIGHT_EXTERNAL_SERVER=true \
pnpm --dir apps/web run test:a11y
```

Production browser evidence:

![Three completed synthetic workflow profiles](output/playwright/production/production-internal-alpha-scorecard.png)

![Version-pinned implementation artifact packet](output/playwright/production/production-demo-complete.png)

## Technical themes

- stateful agent workflows
- evidence provenance and human verification
- typed operating models / knowledge graphs
- contradiction and uncertainty management
- deterministic economics
- stage-gated workflow state machines
- durable execution and recovery
- tenant/engagement isolation
- evaluations and outcome-linked model telemetry
- versioned implementation artifacts
- least-privilege authority boundaries

## North Star

Make Forward Deployed AI Engineering faster without making it less trustworthy: preserve the evidence, decisions, economics, controls, and acceptance criteria required to move from discovery to implementation with confidence.
