from __future__ import annotations

import hashlib
from typing import cast
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ai_fde.models import (
    EconomicCase,
    Engagement,
    ImplementationArtifact,
    Operator,
    WorkflowStep,
    WorkflowVersion,
)
from ai_fde.modules.operating_model.service import list_verified_assertions
from ai_fde.modules.shared import publish_domain_event, record_audit
from ai_fde.modules.workflows.service import list_workflow_steps


class ArtifactStageGateError(ValueError):
    pass


def get_latest_artifact(
    session: Session, engagement_id: UUID
) -> ImplementationArtifact | None:
    return session.scalar(
        select(ImplementationArtifact)
        .where(ImplementationArtifact.engagement_id == engagement_id)
        .order_by(ImplementationArtifact.version_number.desc())
        .limit(1)
    )


def generate_implementation_specification(
    session: Session,
    *,
    engagement_id: UUID,
    operator: Operator,
) -> ImplementationArtifact:
    engagement = session.get(Engagement, engagement_id)
    if engagement is None:
        raise ArtifactStageGateError("The engagement is not available.")
    current = _latest_approved_workflow(session, engagement_id, "current")
    target = _latest_approved_workflow(session, engagement_id, "target")
    economics = session.scalar(
        select(EconomicCase)
        .where(
            EconomicCase.engagement_id == engagement_id,
            EconomicCase.status == "approved",
        )
        .order_by(EconomicCase.version_number.desc())
        .limit(1)
    )
    if current is None or target is None or economics is None:
        raise ArtifactStageGateError(
            "Approve the current workflow, target workflow, and economic case before "
            "generating the specification."
        )
    if target.source_workflow_id != current.id:
        raise ArtifactStageGateError(
            "The approved target no longer depends on the current workflow."
        )
    if economics.source_target_workflow_id != target.id:
        raise ArtifactStageGateError(
            "The approved economic case no longer depends on the target workflow."
        )

    existing = session.scalar(
        select(ImplementationArtifact).where(
            ImplementationArtifact.engagement_id == engagement_id,
            ImplementationArtifact.status == "current",
            ImplementationArtifact.source_current_workflow_id == current.id,
            ImplementationArtifact.source_target_workflow_id == target.id,
            ImplementationArtifact.economic_case_id == economics.id,
        )
    )
    if existing is not None:
        return existing

    assertions = list_verified_assertions(session, engagement_id)
    current_steps = list_workflow_steps(session, current.id)
    target_steps = list_workflow_steps(session, target.id)
    content = _render_markdown(
        company_name=engagement.name,
        objective=engagement.primary_outcome,
        assertions=assertions,
        current=current,
        current_steps=current_steps,
        target=target,
        target_steps=target_steps,
        economics=economics,
    )
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    version = (
        session.scalar(
            select(func.max(ImplementationArtifact.version_number)).where(
                ImplementationArtifact.engagement_id == engagement_id,
                ImplementationArtifact.artifact_type == "implementation_spec",
            )
        )
        or 0
    ) + 1
    session.execute(
        update(ImplementationArtifact)
        .where(
            ImplementationArtifact.engagement_id == engagement_id,
            ImplementationArtifact.status == "current",
        )
        .values(status="stale")
    )
    artifact = ImplementationArtifact(
        engagement_id=engagement_id,
        artifact_type="implementation_spec",
        version_number=version,
        status="current",
        title=f"{engagement.name} Accounts Payable Implementation Specification",
        content=content,
        content_hash=digest,
        source_current_workflow_id=current.id,
        source_target_workflow_id=target.id,
        economic_case_id=economics.id,
        source_assertion_ids=[str(item["id"]) for item in assertions],
        generated_by_id=operator.id,
    )
    session.add(artifact)
    session.flush()
    engagement.lifecycle_stage = "specify"
    record_audit(
        session,
        engagement_id=engagement_id,
        actor_id=operator.id,
        action="implementation_specification.generated",
        target_type="implementation_artifact",
        target_id=artifact.id,
        detail={"version": version, "content_hash": digest},
    )
    publish_domain_event(
        session,
        engagement_id=engagement_id,
        event_type="implementation_specification.generated",
        aggregate_type="implementation_artifact",
        aggregate_id=artifact.id,
        payload={"version": version, "content_hash": digest},
    )
    return artifact


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


def _render_markdown(
    *,
    company_name: str,
    objective: str,
    assertions: list[dict[str, object]],
    current: WorkflowVersion,
    current_steps: list[WorkflowStep],
    target: WorkflowVersion,
    target_steps: list[WorkflowStep],
    economics: EconomicCase,
) -> str:
    lines = [
        f"# {company_name} Accounts Payable Implementation Specification",
        "",
        "## Version pins",
        "",
        f"- Current workflow: `{current.id}` (v{current.version_number})",
        f"- Target workflow: `{target.id}` (v{target.version_number})",
        f"- Economic case: `{economics.id}` (v{economics.version_number})",
        f"- Formula version: `{economics.formula_version}`",
        "",
        "## Business outcome",
        "",
        objective,
        "",
        "## Verified operating assertions",
        "",
    ]
    for assertion in assertions:
        evidence = cast(dict[str, object], assertion["evidence"])
        object_text = f" {assertion['object']}" if assertion.get("object") else ""
        lines.extend(
            [
                f"- **{assertion['subject']} {assertion['predicate']}{object_text}**",
                f"  - Evidence: “{evidence['quote']}”",
                f"  - Source: `{evidence['file_name']}` / segment `{evidence['segment_id']}`",
            ]
        )
    lines.extend(["", "## Approved current workflow", ""])
    lines.extend(_render_steps(current_steps, include_allocation=False))
    lines.extend(["", "## Approved target workflow and allocation", ""])
    lines.extend(_render_steps(target_steps, include_allocation=True))
    lines.extend(["", "## Deterministic economic case", "", "### Inputs", ""])
    for key, raw_input in economics.inputs.items():
        input_value = cast(dict[str, object], raw_input)
        lines.append(
            f"- `{key}`: {input_value['value']} {input_value['unit']} "
            f"(**{input_value['classification']}**)"
        )
    lines.extend(["", "### Calculated outputs", ""])
    for key, raw_output in economics.outputs.items():
        output = cast(dict[str, object], raw_output)
        display_value = output["value"] if output["value"] is not None else "not achievable"
        lines.extend(
            [
                f"- `{key}`: {display_value} {output['unit']} (**calculated**)",
                f"  - Formula: `{output['formula']}`",
            ]
        )
    if economics.assumptions:
        lines.extend(["", "### Assumptions", ""])
        lines.extend(f"- {item}" for item in economics.assumptions)
    lines.extend(
        [
            "",
            "## Implementation requirements",
            "",
            "- Preserve every named system of record in the approved target workflow.",
            "- Enforce every listed human approval and control before completion.",
            "- Record step status, actor, timestamps, exceptions, and approval evidence.",
            "- Treat all external content as untrusted input and never allow it to change "
            "tool policy.",
            "- Keep engagement-scoped authorization and PostgreSQL row isolation on all "
            "new records.",
            "",
            "## Acceptance criteria",
            "",
            "- Every target step is implemented with its approved allocation and controls.",
            "- Existing approval exceptions follow the verified operating assertions.",
            "- Economic calculations reproduce from the versioned inputs above.",
            "- Tests prove cross-engagement reads and writes fail closed.",
            "- No production deployment or autonomous remediation is implied by this "
            "specification.",
            "",
        ]
    )
    return "\n".join(lines)


def _render_steps(steps: list[WorkflowStep], *, include_allocation: bool) -> list[str]:
    output: list[str] = []
    for step in steps:
        output.append(f"{step.position}. **{step.name}** — {step.description}")
        if step.actor_label:
            output.append(f"   - Actor: {step.actor_label}")
        if step.system_label:
            output.append(f"   - System: {step.system_label}")
        if include_allocation:
            output.extend(
                [
                    f"   - Allocation: **{step.allocation}**",
                    f"   - Rationale: {step.rationale}",
                    f"   - Controls: {', '.join(step.controls)}",
                ]
            )
        if step.source_assertion_id:
            output.append(f"   - Source assertion: `{step.source_assertion_id}`")
    return output
