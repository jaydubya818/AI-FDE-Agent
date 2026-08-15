# Bounded Design-Partner Pilot Runbook

## Purpose

Test one real FDE delivery outcome without turning the first customer engagement into an open-ended
production launch. This runbook begins only after production-equivalent staging has a signed GO.

## Pilot contract

Before ingestion, record outside the repository:

| Boundary       | Required decision                                                          |
| -------------- | -------------------------------------------------------------------------- |
| Customer       | one named design partner and process owner                                 |
| Workflow       | one primary workflow with explicit start and end                           |
| Operator       | one lead FDE and one backup                                                |
| Evidence       | approved, sanitized, minimum necessary set                                 |
| Retention      | exact deadline and backup-expiry language                                  |
| Baseline       | conventional time, clarifications, rework, workarounds, and trust failures |
| Outcome        | packet acceptance criteria and forecast measures                           |
| Incident       | customer, FDE, security, and technical contacts                            |
| Stop authority | named security/release owner                                               |

Do not accept raw production data, broaden to a second workflow, add source-system connectors, or
enable coding-agent execution during the pilot.

## Admission gate

- The exact deployed release has a current signed GO and readiness validation ID.
- Sanitization was completed through the approved external procedure.
- Contractual data classification, subprocessors, retention, deletion, and incident terms are
  accepted.
- The conventional baseline was captured before AI-FDE work begins.
- The process owner understands that model output is candidate state until human review.
- The previous release and rollback procedure are current.

## Operating sequence

1. Enable sanitized data through a reviewed release-specific change.
2. Create one engagement and confirm membership before evidence upload.
3. Ingest only the approved evidence manifest and reconcile hashes/counts.
4. Review every candidate and contradiction; never bulk-accept model output.
5. Have the process owner approve the current workflow and business rules.
6. Review target allocation and preserve Human authority for material approvals.
7. Calculate low/base/high economics from labeled inputs; do not present forecast as realized ROI.
8. Generate one seven-artifact packet and have an independent engineer review it.
9. Record AI-FDE operator and engineering assessments.
10. Monitor continuously during material actions and daily for the first 72 hours.

## Measures

- Evidence receipt to approved packet, with stage durations.
- Accepted material claims and reviewer corrections.
- Contradictions found, missed critical rules, and approval-control defects.
- Engineering clarification and rework events.
- Operator workarounds, usefulness, and trust failures.
- Provider tokens, latency, retries, and cost per accepted material claim and packet.
- Reproducibility and sponsor acceptance of the economic scenarios.

Compare against the pre-recorded conventional baseline using absolute values first. A percentage is
permitted only when denominators, windows, quality guardrails, and exclusions are documented.

## Stop and rollback

Pause ingestion and worker processing immediately if any staging stop condition occurs, the data
manifest expands without approval, a critical rule lacks provenance, the packet mixes dependency
versions, or a customer asks to withdraw. Preserve metadata-only incident evidence, follow the
release rollback decision, and notify all named contacts. Resumption requires a new explicit GO.

## Closeout

1. Record the final AI-FDE and conventional assessments.
2. Export or permanently delete the engagement according to the agreed retention decision.
3. Verify the content-free receipt and communicate the backup-expiry boundary.
4. Separate product benefit from model, infrastructure, FDE review, and change-management cost.
5. Decide **continue**, **correct**, **narrow**, or **stop** with the customer process owner.
6. Do not generalize a one-workflow result into a portfolio-wide claim.
