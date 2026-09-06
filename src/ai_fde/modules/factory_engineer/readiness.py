from __future__ import annotations

from datetime import UTC, datetime

from ai_fde.modules.factory_engineer.schemas import (
    FDLCStage,
    ReadinessAssessmentInput,
    ReadinessStageInput,
    ReadinessStageSnapshot,
    ReadinessStatus,
    SourceReference,
)

READINESS_CRITERIA: dict[FDLCStage, tuple[str, ...]] = {
    FDLCStage.DISCOVER: (
        "desired_outcome",
        "owner",
        "workflow_scope",
        "baseline_evidence",
        "evidence_sufficiency",
        "material_unknowns",
    ),
    FDLCStage.DESIGN: (
        "current_state_approved",
        "target_state_defined",
        "acceptance_criteria",
        "work_allocation",
        "autonomy_boundary",
        "authority_boundary",
    ),
    FDLCStage.ASSEMBLE: (
        "agents",
        "skills",
        "tools",
        "models",
        "context_sources",
        "environment",
    ),
    FDLCStage.VALIDATE: (
        "verification_strategy",
        "evaluation_requirements",
        "security_requirements",
        "failure_handling",
        "rollback",
        "permission_model",
        "unresolved_blockers",
    ),
    FDLCStage.DEPLOY: (
        "deployment_scope",
        "rollout_plan",
        "approval_requirements",
        "deployment_package",
        "production_target",
    ),
    FDLCStage.OPERATE: (
        "ownership",
        "observability",
        "incident_response",
        "cost_monitoring",
        "human_escalation",
    ),
    FDLCStage.IMPROVE: (
        "outcome_metrics",
        "baseline",
        "learning_signals",
        "failure_taxonomy",
        "improvement_owner",
    ),
}


class ReadinessCriteriaError(ValueError):
    """The assessment omitted or invented a required FDLC criterion."""


def evaluate_readiness(
    assessment: ReadinessAssessmentInput, *, now: datetime | None = None
) -> tuple[ReadinessStatus, list[ReadinessStageSnapshot]]:
    timestamp = now or datetime.now(UTC)
    snapshots = [_evaluate_stage(stage, now=timestamp) for stage in assessment.stages]
    statuses = {snapshot.status for snapshot in snapshots}
    if ReadinessStatus.STALE in statuses:
        overall = ReadinessStatus.STALE
    elif ReadinessStatus.BLOCKED in statuses:
        overall = ReadinessStatus.BLOCKED
    elif statuses == {ReadinessStatus.READY}:
        overall = ReadinessStatus.READY
    elif ReadinessStatus.NOT_READY in statuses:
        overall = ReadinessStatus.NOT_READY
    elif statuses <= {ReadinessStatus.READY, ReadinessStatus.CONDITIONALLY_READY}:
        overall = ReadinessStatus.CONDITIONALLY_READY
    elif statuses == {ReadinessStatus.NOT_STARTED}:
        overall = ReadinessStatus.NOT_STARTED
    else:
        overall = ReadinessStatus.IN_PROGRESS
    return overall, snapshots


def _evaluate_stage(stage: ReadinessStageInput, *, now: datetime) -> ReadinessStageSnapshot:
    expected = set(READINESS_CRITERIA[stage.stage])
    actual = {criterion.key for criterion in stage.criteria}
    if len(actual) != len(stage.criteria) or actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise ReadinessCriteriaError(
            f"{stage.stage} readiness criteria mismatch; missing={missing}, unknown={unknown}"
        )

    satisfied_count = sum(criterion.satisfied for criterion in stage.criteria)
    score = (satisfied_count * 100 + len(stage.criteria) // 2) // len(stage.criteria)
    blockers = [
        f"{criterion.label}: {criterion.explanation}"
        for criterion in stage.criteria
        if not criterion.satisfied and criterion.blocking
    ]
    next_actions = [
        criterion.next_action
        for criterion in stage.criteria
        if not criterion.satisfied and criterion.next_action is not None
    ]
    evidence_refs = _unique_refs(
        [ref for criterion in stage.criteria if criterion.satisfied for ref in criterion.basis_refs]
    )
    if blockers:
        status = ReadinessStatus.BLOCKED
        explanation = f"{len(blockers)} blocking criterion/criteria remain unresolved."
    elif satisfied_count == 0:
        status = ReadinessStatus.NOT_STARTED
        explanation = "No readiness criterion has a verified basis yet."
    elif satisfied_count == len(stage.criteria):
        status = ReadinessStatus.READY
        explanation = "Every required criterion is satisfied with a recorded basis."
    elif score >= 70:
        status = ReadinessStatus.CONDITIONALLY_READY
        explanation = "No blocking criterion remains, but non-blocking conditions are open."
    elif score < 50:
        status = ReadinessStatus.NOT_READY
        explanation = "Fewer than half of the required criteria are currently satisfied."
    else:
        status = ReadinessStatus.IN_PROGRESS
        explanation = "Readiness work is underway and no blocking criterion is marked."
    return ReadinessStageSnapshot(
        stage=stage.stage,
        status=status,
        score=score,
        evidence_refs=evidence_refs,
        blockers=blockers,
        risks=stage.risks,
        decisions=stage.decisions,
        required_artifacts=stage.required_artifacts,
        owner=stage.owner,
        next_actions=next_actions,
        criteria=stage.criteria,
        explanation=explanation,
        updated_at=now,
    )


def _unique_refs(refs: list[SourceReference]) -> list[SourceReference]:
    seen: set[tuple[str, str, int | None, str]] = set()
    unique: list[SourceReference] = []
    for ref in refs:
        identity = (ref.kind, ref.ref, ref.version, ref.sha256)
        if identity not in seen:
            seen.add(identity)
            unique.append(ref)
    return unique
