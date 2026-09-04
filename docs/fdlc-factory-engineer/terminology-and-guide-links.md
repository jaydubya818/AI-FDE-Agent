---
title: Factory Engineer terminology and Guide link registry
status: partially-implemented
date: 2026-09-04
---

# Factory Engineer terminology and Guide link registry

The public product name, Source Evidence label, ecosystem links, and curated link registry are implemented in the Phase 1 tranche. Lifecycle, autonomy, authority, and target-domain terms remain proposals until their prerequisite ADRs receive product-owner approval.

## Public product language

| Concept | Public term | Internal compatibility |
|---|---|---|
| Product | FDLC Factory Deployed Engineer | Repository/package/env prefixes may remain `AI-FDE` / `ai_fde` |
| Short product name | Factory Engineer | Existing technical metrics such as delivery method `ai_fde` remain historical identifiers |
| Workspace | Engagement cockpit | “Operator Cockpit” may remain a descriptive subtitle during transition |
| Customer material | Source Evidence | Existing `EvidenceAsset` table/API names remain until a compatible migration is justified |
| AI-proposed customer statement | Candidate claim / inference | `CandidateClaim` remains valid |
| Human-authoritative customer statement | Verified assertion | Do not call model-supported text “verified” |
| Customer reality snapshot | Customer Factory Model version | Existing Operating Model endpoint remains a compatibility projection |
| Proposed autonomous delivery unit | Factory line | Not a Mission Control WorkOrder |
| Approved handoff | Factory Deployment Package | Existing seven artifacts remain package views |
| Execution proof | Verification Evidence | Owned by Mission Control, not the Source Evidence store |
| Runtime execution envelope | Mission Control Factory Definition Version | Never synonymize with FE Factory Design |

## Lifecycle language

| Model | Canonical sequence | Use |
|---|---|---|
| FDLC lifecycle | Discover → Design → Assemble → Validate → Deploy → Operate → Improve | Stage readiness of a factory line |
| FDLC runtime lifecycle | Receive → Specify → Plan → Execute → Verify → Approve → Release → Observe → Learn | General protocol/value flow |
| Guide teaching lifecycle | Intent → Plan → Define Agent → Execute through Harness → Apply Skills → Evaluate → Improve → Deliver Software | Explain how factory work is designed and taught |
| FDE field loop | Embed → Observe → Co-build → Productise → Contribute → Reuse → Scale | Field learning/productization |
| FE engagement administration | Draft → Active ↔ Paused → Closed → Archived | Customer engagement administration |
| FE factory line | Candidate → Assessed → Selected → Designing → Validating → Approved → Deployment Ready → Deploying → Active ↔ Paused → Retired | One candidate/deployed factory line |
| Mission Control | Native Mission, WorkOrder, Attempt and release state machines | Governed execution truth; never copied into FE |

## Autonomy and authority

Use the Guide’s L0–L5 operational autonomy model. Do not introduce A0–A5 as a second vocabulary. Persist action authorities separately: observation, recommendation, configuration, execution invocation, publication and production. Permission, authorization, approval, acceptance and capability trust are different facts.

## Curated Guide links

Base: `https://ai-software-factory-mastery.vercel.app`

| Topic key | UI context | Canonical URL | Last reviewed |
|---|---|---|---|
| `autonomy.lowest-ceiling` | Autonomy selection | `/docs/01-understand/03-first-principles-trust-evidence-and-authority#autonomy-is-scoped-and-the-lowest-ceiling-wins` | 2026-09-04 |
| `authority.permission` | Authority matrix | `/docs/02-design/07-governance-policy-and-risk-proportional-approval#permission-is-not-authority` | 2026-09-04 |
| `autonomy.per-action` | Action grants | `/docs/02-design/07-governance-policy-and-risk-proportional-approval#autonomy-per-action-class` | 2026-09-04 |
| `trust.evidence-record` | Claim/source support | `/docs/04-prove/27-quality-and-evidence-architecture#the-evidence-record` | 2026-09-04 |
| `trust.independent-verification` | Verification design | `/docs/04-prove/27-quality-and-evidence-architecture#validation-must-be-independent` | 2026-09-04 |
| `trust.verification-contract` | Package verification | `/docs/04-prove/27-quality-and-evidence-architecture#the-verification-contract` | 2026-09-04 |
| `records.traceability` | Staleness/impact | `/docs/02-design/05-authoritative-records#the-traceability-chain` | 2026-09-04 |
| `capability.agent-definition` | Required capability | `/docs/03-build/11-the-agent-factory#the-agent-definition-is-a-contract-not-a-prompt` | 2026-09-04 |
| `capability.factory-boundary` | Capability productization | `/docs/03-build/11-the-agent-factory#two-factories-one-boundary` | 2026-09-04 |
| `context.retrieval-contract` | Future Guide retrieval | `/docs/03-build/20-context-engineering#the-retrieval-contract` | 2026-09-04 |
| `field.forward-deployed-loop` | Field signals | `/docs/05-operate/38-enterprise-adoption-and-the-infrastructure-landscape#forward-deployed-engineering-and-its-failure-mode` | 2026-09-04 |

The code registry stores stable topic keys and URLs; UI components consume topic keys. Raw anchors are generated from mutable headings, so a scheduled/manual link-health check is required before treating them as durable. Guide content is linked, not copied.

## Product statements

Primary definition:

> The FDLC Factory Deployed Engineer is the evidence-backed operating workspace that turns customer reality into an approved, deployable software-factory design and learns from governed outcomes.

Concise statement:

> Turn enterprise reality into a deployable software factory.

North star:

> Make deploying an AI software factory faster without sacrificing evidence, verification, economics, security, accountability, or human authority.

Internal mantra:

> Discover reality. Prove what is true. Design the factory. Deploy with control. Measure the outcome. Reuse what works.
