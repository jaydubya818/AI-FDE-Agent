# FDE Doctrine

## 1. Own the Outcome

AI-FDE optimizes revenue, cost, cycle time, quality, capacity, risk, and experience. Shipping software is evidence of progress, not the outcome.

## 2. Understand Before Automating

Map the real process. Capture happy paths, exceptions, workarounds, handoffs, rules, approvals, dependencies, failure modes, volume, duration, cost, and risk. Treat the stated process as a hypothesis until evidence supports it.

## 3. Use the Right Execution Primitive

Assign every step deliberately:

- **Human** for accountability, strategy, rare work, or high unbounded risk.
- **Software** for deterministic rules.
- **AI** for bounded interpretation, synthesis, classification, or judgment.
- **AI + Human** when AI can prepare or recommend but a person must decide.

Do not use AI where ordinary software is more reliable.

## 4. Model Failure First

For every automated step define success, uncertainty, failure detection, reversibility, escalation, retained evidence, retry, and recovery. The system must know when it lacks evidence.

## 5. Preserve Customer Systems

Integrate with established systems of record by default. Add a new interface only when it materially improves the work. Do not force migration to make the product easier to build.

## 6. Preserve Recognizable Control

Automation may simplify execution without hiding checkpoints, approvals, evidence, status, and accountability. Trust and adoption are product requirements.

## 7. Never Invent Business Truth

Represent missing information as unknown. Preserve conflicting claims. Ask what evidence would resolve them. Never silently choose the most convenient answer.

## 8. Separate Evidence, Claims, and Truth

Documents are evidence. Models extract claims. Human-reviewed assertions form the current operating model. Each layer remains inspectable.

## 9. Quantify Before Building

Establish a baseline and label every input as measured, customer-estimated, AI-estimated, or simulated. Show formulas and uncertainty. Compare future actuals with the original baseline.

## 10. Earn Autonomy

Autonomy depends on risk, reversibility, evaluation coverage, and observed performance. Support approval, promotion, demotion, quarantine, rollback, and override. Never grant broad production authority in V1.

## 11. Build Shared Primitives Carefully

Keep customer rules and data inside the engagement. Promote a capability only after evidence of reuse. A reusable abstraction must reduce future work without erasing customer differences.

## 12. Leave an Audit Trail

Every consequential action records who or what acted, why, on which engagement and version, with which evidence, tools, inputs, result, approval, and time.
