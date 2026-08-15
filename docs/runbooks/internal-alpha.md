# Internal Alpha Runbook

## Purpose

The internal alpha tests whether an FDE can repeat the AI-FDE delivery method across materially
different workflows and produce a trustworthy engineering handoff. It is not a production AI
evaluation and does not authorize sanitized customer data.

The repository supplies three synthetic profiles:

| Profile                                       | Workflow shape       | Stress tested                                                      |
| --------------------------------------------- | -------------------- | ------------------------------------------------------------------ |
| Acme Manufacturing / Accounts Payable         | exception-heavy      | approval rules and contradiction resolution                        |
| Northstar Health / Employee Access Onboarding | multi-system handoff | ownership, sequence, approval, and People Operations-to-IT handoff |
| Beacon Logistics / Customer Support Triage    | straight-through     | system of record, ordered work, and governing policy               |

## Entry criteria

- The exact commit passes the clean-environment rehearsal.
- One technical owner and one FDE leader own the alpha window.
- At least two internal FDE evaluators are scheduled for human usability sessions.
- Every session uses synthetic evidence and development authentication.
- P0/P1 defect ownership and a same-day stop decision are available.

## Automated rehearsal

From the repository root, run:

```bash
make alpha-rehearsal
```

The command creates isolated PostgreSQL and MinIO volumes, migrates the schema, seeds all three
profiles, runs the persistent worker, builds and starts the production-mode web application, and
drives every workflow through the browser. It records one AI-FDE operator assessment per workflow
and writes:

```text
output/playwright/internal-alpha/internal-alpha-scorecard.png
```

A pass proves the repository-controlled journey works across all three shapes. It deliberately
leaves the conventional cohort at `0/3`, so comparative improvement stays locked.

## Human evaluation sessions

For each evaluator:

1. Start from the engagement list without implementation-team guidance.
2. Review every candidate against exact evidence.
3. Resolve contradictions with an attributable reason.
4. Approve current and target workflows, sensitivity economics, and the seven-artifact packet.
5. Record an operator assessment for AI-FDE.
6. Complete the same bounded handoff using the team's normal documents, spreadsheets, copilots,
   knowledge bases, and workflow tools.
7. Record the conventional assessment against the same workflow and evidence.
8. Have an engineer who did not participate in discovery review each handoff.

Record duration, usefulness, clarification, rework, workaround, and trust-failure counts in the
product. Free-text assessment notes stay out of audit and domain-event payloads.

## Claim rules

- Use absolute differences only after both methods have three completed operator assessments
  across three distinct workflows.
- Do not publish percentage time, ROI, token, or pull-request cost reduction from the automated
  fixture run.
- Zero fixture tokens means no model call occurred. It is not a production cost result.
- A workflow that is blocked or abandoned remains part of the evidence; do not rewrite it as
  completed.

## Defect triage

| Severity | Definition                                                                          | Response                                    |
| -------- | ----------------------------------------------------------------------------------- | ------------------------------------------- |
| P0       | isolation, authorization, sensitive logging, deletion, or irreversible data failure | stop the alpha immediately                  |
| P1       | incorrect authority, provenance, stage gate, economics, or packet version           | stop the affected workflow; fix before exit |
| P2       | material usability failure or undocumented workaround                               | assign owner and retest in the alpha window |
| P3       | polish or low-impact clarity issue                                                  | backlog with evidence                       |

## Exit decision

The alpha exits only when:

- all three workflows reach a current packet or show a product-visible blocked/abandoned outcome;
- no P0/P1 defect remains open;
- an independent engineer can use the packet without a critical clarification;
- human evaluation records exist for both methods across the three workflows;
- the FDE leader has reviewed the objective scorecard and signed the next decision.

Passing the automated rehearsal alone is **not** sufficient to enter production-equivalent staging.
