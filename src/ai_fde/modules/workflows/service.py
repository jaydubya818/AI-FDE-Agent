from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ai_fde.models import (
    Assertion,
    Contradiction,
    Engagement,
    OperatingEntity,
    Operator,
    WorkflowStep,
    WorkflowVersion,
)
from ai_fde.modules.lifecycle import (
    stale_after_current_workflow_change,
    stale_after_target_workflow_change,
)
from ai_fde.modules.shared import publish_domain_event, record_audit


class WorkflowNotFoundError(LookupError):
    pass


class WorkflowStageGateError(ValueError):
    pass


def list_latest_workflows(
    session: Session, engagement_id: UUID
) -> dict[str, WorkflowVersion | None]:
    return {
        kind: session.scalar(
            select(WorkflowVersion)
            .where(
                WorkflowVersion.engagement_id == engagement_id,
                WorkflowVersion.workflow_kind == kind,
            )
            .order_by(WorkflowVersion.version_number.desc())
            .limit(1)
        )
        for kind in ("current", "target")
    }


def list_workflow_steps(session: Session, workflow_id: UUID) -> list[WorkflowStep]:
    return list(
        session.scalars(
            select(WorkflowStep)
            .where(WorkflowStep.workflow_version_id == workflow_id)
            .order_by(WorkflowStep.position)
        )
    )


def generate_current_workflow(
    session: Session,
    *,
    engagement_id: UUID,
    operator: Operator,
) -> WorkflowVersion:
    engagement = session.get(Engagement, engagement_id)
    if engagement is None:
        raise WorkflowNotFoundError(str(engagement_id))
    existing = session.scalar(
        select(WorkflowVersion)
        .where(
            WorkflowVersion.engagement_id == engagement_id,
            WorkflowVersion.workflow_kind == "current",
            WorkflowVersion.status == "draft",
        )
        .order_by(WorkflowVersion.version_number.desc())
        .limit(1)
    )
    if existing is not None:
        return existing

    assertions = list(
        session.scalars(
            select(Assertion)
            .where(
                Assertion.engagement_id == engagement_id,
                Assertion.status == "verified",
            )
            .order_by(Assertion.recorded_at, Assertion.id)
        )
    )
    projected = [
        item for item in (_project_assertion(session, item) for item in assertions) if item
    ]
    if not projected:
        raise WorkflowStageGateError(
            "Verify at least one workflow relationship, rule, or exception before drafting "
            "the current workflow."
        )

    _stale_workflows(session, engagement_id, "current")
    stale_after_current_workflow_change(session, engagement_id)
    workflow = WorkflowVersion(
        engagement_id=engagement_id,
        workflow_kind="current",
        version_number=_next_workflow_version(session, engagement_id, "current"),
        name=f"{engagement.workflow_name} — Current State",
        objective=(
            f"Represent the verified {engagement.workflow_name.lower()} workflow without "
            "redesigning it."
        ),
        status="draft",
        source_assertion_ids=[str(item.id) for item in assertions],
        generated_by="system",
        created_by_id=operator.id,
    )
    session.add(workflow)
    session.flush()

    for position, step_data in enumerate(projected, start=1):
        session.add(
            WorkflowStep(
                engagement_id=engagement_id,
                workflow_version_id=workflow.id,
                position=position,
                **step_data,
            )
        )
    session.flush()
    _record_workflow_event(session, workflow, operator, "workflow.current_drafted")
    return workflow


def generate_target_workflow(
    session: Session,
    *,
    engagement_id: UUID,
    operator: Operator,
) -> WorkflowVersion:
    engagement = session.get(Engagement, engagement_id)
    if engagement is None:
        raise WorkflowNotFoundError(str(engagement_id))
    current = _latest_approved_workflow(session, engagement_id, "current")
    if current is None:
        raise WorkflowStageGateError(
            "Approve a current-state workflow before designing a target state."
        )

    existing = session.scalar(
        select(WorkflowVersion)
        .where(
            WorkflowVersion.engagement_id == engagement_id,
            WorkflowVersion.workflow_kind == "target",
            WorkflowVersion.source_workflow_id == current.id,
            WorkflowVersion.status == "draft",
        )
        .order_by(WorkflowVersion.version_number.desc())
        .limit(1)
    )
    if existing is not None:
        return existing

    _stale_workflows(session, engagement_id, "target")
    stale_after_target_workflow_change(session, engagement_id)
    workflow = WorkflowVersion(
        engagement_id=engagement_id,
        workflow_kind="target",
        version_number=_next_workflow_version(session, engagement_id, "target"),
        name=f"{engagement.workflow_name} — Target State",
        objective=(
            "Allocate each verified workflow step to the safest effective combination of human "
            "authority and existing software."
        ),
        status="draft",
        source_workflow_id=current.id,
        source_assertion_ids=current.source_assertion_ids,
        generated_by="system",
        created_by_id=operator.id,
    )
    session.add(workflow)
    session.flush()

    for step in list_workflow_steps(session, current.id):
        allocation, rationale, controls = _target_recommendation(step)
        session.add(
            WorkflowStep(
                engagement_id=engagement_id,
                workflow_version_id=workflow.id,
                step_key=step.step_key,
                position=step.position,
                name=step.name,
                description=step.description,
                step_type=step.step_type,
                actor_label=step.actor_label,
                system_label=step.system_label,
                allocation=allocation,
                rationale=rationale,
                controls=controls,
                source_assertion_id=step.source_assertion_id,
            )
        )
    session.flush()
    engagement.lifecycle_stage = "decide"
    _record_workflow_event(session, workflow, operator, "workflow.target_drafted")
    return workflow


def update_workflow_step(
    session: Session,
    *,
    engagement_id: UUID,
    workflow_id: UUID,
    step_id: UUID,
    operator: Operator,
    name: str | None = None,
    description: str | None = None,
    actor_label: str | None = None,
    allocation: str | None = None,
    rationale: str | None = None,
    controls: list[str] | None = None,
) -> WorkflowStep:
    workflow = _get_workflow(session, engagement_id, workflow_id)
    if workflow.status != "draft":
        raise WorkflowStageGateError("Only a draft workflow can be edited.")
    step = session.scalar(
        select(WorkflowStep)
        .where(
            WorkflowStep.id == step_id,
            WorkflowStep.workflow_version_id == workflow_id,
            WorkflowStep.engagement_id == engagement_id,
        )
        .with_for_update()
    )
    if step is None:
        raise WorkflowNotFoundError(str(step_id))
    if allocation is not None:
        if workflow.workflow_kind != "target":
            raise WorkflowStageGateError("Allocation changes belong to the target workflow.")
        if allocation not in {"human", "software", "ai", "ai_human"}:
            raise ValueError("Unsupported allocation.")
        step.allocation = allocation
    if name is not None:
        step.name = name.strip()
    if description is not None:
        step.description = description.strip()
    if actor_label is not None:
        step.actor_label = actor_label.strip() or None
    if rationale is not None:
        step.rationale = rationale.strip()
    if controls is not None:
        step.controls = [item.strip() for item in controls if item.strip()]
    record_audit(
        session,
        engagement_id=engagement_id,
        actor_id=operator.id,
        action="workflow.step_updated",
        target_type="workflow_step",
        target_id=step.id,
        detail={"workflow_id": str(workflow.id), "workflow_kind": workflow.workflow_kind},
    )
    return step


def approve_workflow(
    session: Session,
    *,
    engagement_id: UUID,
    workflow_id: UUID,
    operator: Operator,
    reason: str | None = None,
) -> WorkflowVersion:
    workflow = _get_workflow(session, engagement_id, workflow_id, lock=True)
    if workflow.status != "draft":
        raise WorkflowStageGateError("Only a draft workflow can be approved.")
    if not list_workflow_steps(session, workflow.id):
        raise WorkflowStageGateError("A workflow must contain at least one step before approval.")

    clean_reason = reason.strip() if reason else None
    if workflow.workflow_kind == "current":
        blocking_count = session.scalar(
            select(func.count())
            .select_from(Contradiction)
            .where(
                Contradiction.engagement_id == engagement_id,
                Contradiction.blocking.is_(True),
            )
        )
        if blocking_count and not clean_reason:
            raise WorkflowStageGateError(
                "Resolve blocking contradictions or record an explicit approval override reason."
            )
        stale_after_current_workflow_change(session, engagement_id)
        next_stage = "map"
    else:
        source = session.get(WorkflowVersion, workflow.source_workflow_id)
        if source is None or source.status != "approved":
            raise WorkflowStageGateError(
                "The target workflow's current-state source is no longer approved."
            )
        for step in list_workflow_steps(session, workflow.id):
            if step.allocation in {"ai", "ai_human"} and (
                not step.rationale.strip() or not step.controls
            ):
                raise WorkflowStageGateError(
                    f"{step.name} needs a rationale and at least one control before AI "
                    "allocation approval."
                )
        stale_after_target_workflow_change(session, engagement_id)
        next_stage = "design"

    workflow.status = "approved"
    workflow.approved_by_id = operator.id
    workflow.approved_at = datetime.now(UTC)
    workflow.approval_reason = clean_reason
    engagement = session.get(Engagement, engagement_id)
    if engagement is not None:
        engagement.lifecycle_stage = next_stage
    _record_workflow_event(
        session,
        workflow,
        operator,
        f"workflow.{workflow.workflow_kind}_approved",
        detail={"approval_reason": clean_reason},
    )
    session.flush()
    return workflow


def _get_workflow(
    session: Session, engagement_id: UUID, workflow_id: UUID, *, lock: bool = False
) -> WorkflowVersion:
    statement = select(WorkflowVersion).where(
        WorkflowVersion.id == workflow_id,
        WorkflowVersion.engagement_id == engagement_id,
    )
    if lock:
        statement = statement.with_for_update()
    workflow = session.scalar(statement)
    if workflow is None:
        raise WorkflowNotFoundError(str(workflow_id))
    return workflow


def _latest_approved_workflow(
    session: Session, engagement_id: UUID, kind: str
) -> WorkflowVersion | None:
    return session.scalar(
        select(WorkflowVersion)
        .where(
            WorkflowVersion.engagement_id == engagement_id,
            WorkflowVersion.workflow_kind == kind,
            WorkflowVersion.status == "approved",
        )
        .order_by(WorkflowVersion.version_number.desc())
        .limit(1)
    )


def _next_workflow_version(session: Session, engagement_id: UUID, kind: str) -> int:
    latest = session.scalar(
        select(func.max(WorkflowVersion.version_number)).where(
            WorkflowVersion.engagement_id == engagement_id,
            WorkflowVersion.workflow_kind == kind,
        )
    )
    return (latest or 0) + 1


def _stale_workflows(session: Session, engagement_id: UUID, kind: str) -> None:
    session.execute(
        update(WorkflowVersion)
        .where(
            WorkflowVersion.engagement_id == engagement_id,
            WorkflowVersion.workflow_kind == kind,
            WorkflowVersion.status.in_(["draft", "approved"]),
        )
        .values(status="stale")
    )


def _project_assertion(session: Session, assertion: Assertion) -> dict[str, object] | None:
    subject = session.get(OperatingEntity, assertion.subject_entity_id)
    object_entity = (
        session.get(OperatingEntity, assertion.object_entity_id)
        if assertion.object_entity_id
        else None
    )
    if subject is None:
        return None
    condition = assertion.value.get("condition")
    is_exception = bool(assertion.value.get("is_exception"))
    object_name = object_entity.display_name if object_entity else None
    source_suffix = assertion.id.hex[:10]

    if assertion.predicate == "OWNS" and object_name:
        return {
            "step_key": f"ownership-{source_suffix}",
            "name": f"Oversee {object_name}",
            "description": str(assertion.value.get("summary") or "Verified process ownership."),
            "step_type": "human_task",
            "actor_label": subject.display_name,
            "system_label": None,
            "allocation": "human",
            "rationale": "Verified ownership is currently exercised by a human accountable owner.",
            "controls": ["Named owner remains accountable"],
            "source_assertion_id": assertion.id,
        }
    if assertion.predicate == "USES" and object_name:
        return {
            "step_key": f"system-use-{source_suffix}",
            "name": f"Process work in {object_name}",
            "description": str(assertion.value.get("summary") or "Verified system use."),
            "step_type": "software_task",
            "actor_label": subject.display_name,
            "system_label": object_name,
            "allocation": "software",
            "rationale": "The current workflow already uses this deterministic system.",
            "controls": ["Preserve the existing system of record"],
            "source_assertion_id": assertion.id,
        }
    if assertion.predicate == "REQUIRES_APPROVAL" and object_name:
        qualifier = str(condition) if condition else "qualifying work"
        prefix = "Apply approved exception for" if is_exception else "Approve"
        return {
            "step_key": f"approval-{source_suffix}",
            "name": f"{prefix} {qualifier}",
            "description": str(assertion.value.get("summary") or "Verified approval rule."),
            "step_type": "approval",
            "actor_label": object_name,
            "system_label": None,
            "allocation": "human",
            "rationale": "A material financial approval remains under human authority.",
            "controls": ["Approval actor and decision are recorded"],
            "source_assertion_id": assertion.id,
        }
    if assertion.predicate == "PRECEDES" and object_name:
        return {
            "step_key": f"sequence-{source_suffix}",
            "name": f"Complete {subject.display_name} before {object_name}",
            "description": str(assertion.value.get("summary") or "Verified workflow sequence."),
            "step_type": "decision",
            "actor_label": subject.display_name,
            "system_label": None,
            "allocation": "human",
            "rationale": "The ordering dependency is verified; its execution remains explicit.",
            "controls": [f"Do not begin {object_name} before completion is recorded"],
            "source_assertion_id": assertion.id,
        }
    if assertion.predicate == "HANDS_OFF_TO" and object_name:
        return {
            "step_key": f"handoff-{source_suffix}",
            "name": f"Hand off from {subject.display_name} to {object_name}",
            "description": str(assertion.value.get("summary") or "Verified workflow handoff."),
            "step_type": "handoff",
            "actor_label": object_name,
            "system_label": None,
            "allocation": "human",
            "rationale": "The verified receiving role must acknowledge the transfer of work.",
            "controls": ["Record the sender, recipient, timestamp, and acknowledgement"],
            "source_assertion_id": assertion.id,
        }
    if assertion.predicate == "GOVERNED_BY" and object_name:
        return {
            "step_key": f"governance-{source_suffix}",
            "name": f"Apply {object_name}",
            "description": str(assertion.value.get("summary") or "Verified governing rule."),
            "step_type": "decision",
            "actor_label": subject.display_name,
            "system_label": None,
            "allocation": "human",
            "rationale": "A verified policy or rule must remain an explicit decision control.",
            "controls": [f"Record the applicable version of {object_name}"],
            "source_assertion_id": assertion.id,
        }
    return None


def _target_recommendation(step: WorkflowStep) -> tuple[str, str, list[str]]:
    if step.step_type == "approval":
        return (
            "human",
            "Keep material approval authority with the verified human role.",
            ["Approval actor and decision are recorded", "No autonomous approval"],
        )
    if step.system_label:
        return (
            "software",
            f"Preserve {step.system_label} as the deterministic system of record.",
            ["Existing system of record is preserved", "Failures route to a human owner"],
        )
    return (
        "human",
        "Insufficient verified evidence exists to justify higher autonomy.",
        ["Named human owner remains accountable"],
    )


def _record_workflow_event(
    session: Session,
    workflow: WorkflowVersion,
    operator: Operator,
    event_type: str,
    *,
    detail: dict[str, object] | None = None,
) -> None:
    action = event_type
    record_audit(
        session,
        engagement_id=workflow.engagement_id,
        actor_id=operator.id,
        action=action,
        target_type="workflow_version",
        target_id=workflow.id,
        detail={
            "kind": workflow.workflow_kind,
            "version": workflow.version_number,
            **(detail or {}),
        },
    )
    publish_domain_event(
        session,
        engagement_id=workflow.engagement_id,
        event_type=event_type,
        aggregate_type="workflow_version",
        aggregate_id=workflow.id,
        payload={"kind": workflow.workflow_kind, "version": workflow.version_number},
    )
