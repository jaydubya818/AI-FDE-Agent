from __future__ import annotations

import hashlib
from typing import Any, cast
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

ARTIFACT_TYPES = (
    "prd",
    "architecture",
    "business_rules",
    "integration_requirements",
    "approval_controls",
    "evaluation_plan",
    "implementation_spec",
)


class ArtifactStageGateError(ValueError):
    pass


def get_latest_artifact(session: Session, engagement_id: UUID) -> ImplementationArtifact | None:
    """Return the latest implementation specification for legacy API compatibility."""
    return session.scalar(
        select(ImplementationArtifact)
        .where(
            ImplementationArtifact.engagement_id == engagement_id,
            ImplementationArtifact.artifact_type == "implementation_spec",
        )
        .order_by(ImplementationArtifact.version_number.desc())
        .limit(1)
    )


def list_current_artifacts(session: Session, engagement_id: UUID) -> list[ImplementationArtifact]:
    artifacts = list(
        session.scalars(
            select(ImplementationArtifact).where(
                ImplementationArtifact.engagement_id == engagement_id,
                ImplementationArtifact.status == "current",
            )
        )
    )
    order = {artifact_type: position for position, artifact_type in enumerate(ARTIFACT_TYPES)}
    return sorted(artifacts, key=lambda artifact: order[artifact.artifact_type])


def generate_implementation_specification(
    session: Session,
    *,
    engagement_id: UUID,
    operator: Operator,
) -> ImplementationArtifact:
    """Generate the complete packet and return its implementation specification."""
    packet = generate_implementation_packet(
        session,
        engagement_id=engagement_id,
        operator=operator,
    )
    return next(artifact for artifact in packet if artifact.artifact_type == "implementation_spec")


def generate_implementation_packet(
    session: Session,
    *,
    engagement_id: UUID,
    operator: Operator,
) -> list[ImplementationArtifact]:
    engagement = session.get(Engagement, engagement_id)
    if engagement is None:
        raise ArtifactStageGateError("The engagement is not available.")
    current, target, economics = _approved_dependencies(session, engagement_id)

    existing = list_current_artifacts(session, engagement_id)
    if (
        {artifact.artifact_type for artifact in existing} == set(ARTIFACT_TYPES)
        and len({artifact.packet_version for artifact in existing}) == 1
        and all(
            artifact.source_current_workflow_id == current.id
            and artifact.source_target_workflow_id == target.id
            and artifact.economic_case_id == economics.id
            for artifact in existing
        )
    ):
        return existing

    assertions = list_verified_assertions(session, engagement_id)
    current_steps = list_workflow_steps(session, current.id)
    target_steps = list_workflow_steps(session, target.id)
    render_context: dict[str, Any] = {
        "engagement": engagement,
        "assertions": assertions,
        "current": current,
        "current_steps": current_steps,
        "target": target,
        "target_steps": target_steps,
        "economics": economics,
    }
    contents = {
        "prd": _render_prd(**render_context),
        "architecture": _render_architecture(**render_context),
        "business_rules": _render_business_rules(**render_context),
        "integration_requirements": _render_integrations(**render_context),
        "approval_controls": _render_approval_controls(**render_context),
        "evaluation_plan": _render_evaluation_plan(**render_context),
        "implementation_spec": _render_implementation_spec(**render_context),
    }
    packet_version = (
        session.scalar(
            select(func.max(ImplementationArtifact.packet_version)).where(
                ImplementationArtifact.engagement_id == engagement_id
            )
        )
        or 0
    ) + 1
    versions = {
        artifact_type: (
            session.scalar(
                select(func.max(ImplementationArtifact.version_number)).where(
                    ImplementationArtifact.engagement_id == engagement_id,
                    ImplementationArtifact.artifact_type == artifact_type,
                )
            )
            or 0
        )
        + 1
        for artifact_type in ARTIFACT_TYPES
    }
    session.execute(
        update(ImplementationArtifact)
        .where(
            ImplementationArtifact.engagement_id == engagement_id,
            ImplementationArtifact.status == "current",
        )
        .values(status="stale")
    )

    source_assertion_ids = [str(item["id"]) for item in assertions]
    artifacts = []
    for artifact_type in ARTIFACT_TYPES:
        content = contents[artifact_type]
        artifact = ImplementationArtifact(
            engagement_id=engagement_id,
            artifact_type=artifact_type,
            packet_version=packet_version,
            version_number=versions[artifact_type],
            status="current",
            title=_artifact_title(engagement, artifact_type),
            content=content,
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            source_current_workflow_id=current.id,
            source_target_workflow_id=target.id,
            economic_case_id=economics.id,
            source_assertion_ids=source_assertion_ids,
            generated_by_id=operator.id,
        )
        session.add(artifact)
        artifacts.append(artifact)
    session.flush()

    implementation_spec = artifacts[-1]
    engagement.lifecycle_stage = "specify"
    detail = {
        "packet_version": packet_version,
        "artifact_count": len(artifacts),
        "artifact_hashes": {
            artifact.artifact_type: artifact.content_hash for artifact in artifacts
        },
    }
    record_audit(
        session,
        engagement_id=engagement_id,
        actor_id=operator.id,
        action="implementation_packet.generated",
        target_type="implementation_artifact",
        target_id=implementation_spec.id,
        detail=detail,
    )
    publish_domain_event(
        session,
        engagement_id=engagement_id,
        event_type="implementation_packet.generated",
        aggregate_type="implementation_artifact",
        aggregate_id=implementation_spec.id,
        payload=detail,
    )
    return artifacts


def _approved_dependencies(
    session: Session, engagement_id: UUID
) -> tuple[WorkflowVersion, WorkflowVersion, EconomicCase]:
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
            "generating the implementation packet."
        )
    if target.source_workflow_id != current.id:
        raise ArtifactStageGateError(
            "The approved target no longer depends on the current workflow."
        )
    if economics.source_target_workflow_id != target.id:
        raise ArtifactStageGateError(
            "The approved economic case no longer depends on the target workflow."
        )
    return current, target, economics


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


def _artifact_title(engagement: Engagement, artifact_type: str) -> str:
    labels = {
        "prd": "Product Requirements",
        "architecture": "Architecture",
        "business_rules": "Business Rules",
        "integration_requirements": "Integration Requirements",
        "approval_controls": "Approval and Control Matrix",
        "evaluation_plan": "Evaluation Plan",
        "implementation_spec": "Implementation Specification",
    }
    return f"{engagement.name} {engagement.workflow_name} {labels[artifact_type]}"


def _pins(current: WorkflowVersion, target: WorkflowVersion, economics: EconomicCase) -> list[str]:
    return [
        "## Version pins",
        "",
        f"- Current workflow: `{current.id}` (v{current.version_number})",
        f"- Target workflow: `{target.id}` (v{target.version_number})",
        f"- Economic case: `{economics.id}` (v{economics.version_number})",
        f"- Formula version: `{economics.formula_version}`",
    ]


def _header(
    title: str,
    current: WorkflowVersion,
    target: WorkflowVersion,
    economics: EconomicCase,
) -> list[str]:
    return [f"# {title}", "", *_pins(current, target, economics), ""]


def _render_prd(
    *,
    engagement: Engagement,
    assertions: list[dict[str, object]],
    current: WorkflowVersion,
    current_steps: list[WorkflowStep],
    target: WorkflowVersion,
    target_steps: list[WorkflowStep],
    economics: EconomicCase,
) -> str:
    del assertions, current_steps
    lines = _header(_artifact_title(engagement, "prd"), current, target, economics)
    lines.extend(
        [
            "## Problem and outcome",
            "",
            engagement.primary_outcome,
            "",
            "## V1 scope",
            "",
            f"Implement the approved target state for **{engagement.workflow_name}** with "
            "explicit human authority, deterministic system behavior, and evidence-linked "
            "decisions.",
            "",
            "## Required capabilities",
            "",
        ]
    )
    lines.extend(f"- {step.name}: {step.description}" for step in target_steps)
    lines.extend(
        [
            "",
            "## V1 boundaries",
            "",
            "- No autonomous approval, coding-agent execution, or remediation.",
            "- No workflow behavior may be inferred from unverified evidence.",
            "- Unsupported relationship types remain visible in the operating model only.",
            "",
            "## Success criteria",
            "",
            "- Every approved target step and control has an implemented acceptance test.",
            "- Cross-engagement reads and writes fail closed.",
            "- Economic outputs reproduce from the versioned scenario inputs.",
            "",
        ]
    )
    return "\n".join(lines)


def _render_architecture(
    *,
    engagement: Engagement,
    assertions: list[dict[str, object]],
    current: WorkflowVersion,
    current_steps: list[WorkflowStep],
    target: WorkflowVersion,
    target_steps: list[WorkflowStep],
    economics: EconomicCase,
) -> str:
    del assertions, current_steps, target_steps
    lines = _header(_artifact_title(engagement, "architecture"), current, target, economics)
    lines.extend(
        [
            "## Runtime boundaries",
            "",
            "- Web client authenticates human operators through OIDC authorization code + PKCE.",
            "- API enforces engagement membership and PostgreSQL row-level security.",
            "- Worker uses a separate service identity and explicit engagement memberships.",
            "- Evidence objects remain private and are addressed by immutable content hash.",
            "- Extraction uses a provider-neutral contract; production is configured for Bedrock.",
            "",
            "## Data flow",
            "",
            "1. Validate evidence type and bounds before durable storage.",
            "2. Parse content into source-addressable segments.",
            "3. Extract bounded structured claims from untrusted content.",
            "4. Require human verification before assertions affect workflows.",
            "5. Generate version-pinned workflows, scenarios, and this artifact packet.",
            "",
            "## Failure posture",
            "",
            "- Provider, schema, provenance, authorization, and isolation failures fail closed.",
            "- Production extraction never falls back to fixture rules.",
            "- Sanitized data remains disabled until the deployment validation gate is recorded.",
            "",
        ]
    )
    return "\n".join(lines)


def _render_business_rules(
    *,
    engagement: Engagement,
    assertions: list[dict[str, object]],
    current: WorkflowVersion,
    current_steps: list[WorkflowStep],
    target: WorkflowVersion,
    target_steps: list[WorkflowStep],
    economics: EconomicCase,
) -> str:
    del current_steps, target_steps
    lines = _header(_artifact_title(engagement, "business_rules"), current, target, economics)
    lines.extend(["## Verified rules", ""])
    lines.extend(_render_assertions(assertions))
    lines.extend(
        [
            "",
            "## Enforcement requirements",
            "",
            "- Preserve assertion identifiers with each implemented rule.",
            "- Route ambiguous, contradictory, or unsupported rules to human review.",
            "- Stale downstream artifacts after any verified model change.",
            "",
        ]
    )
    return "\n".join(lines)


def _render_integrations(
    *,
    engagement: Engagement,
    assertions: list[dict[str, object]],
    current: WorkflowVersion,
    current_steps: list[WorkflowStep],
    target: WorkflowVersion,
    target_steps: list[WorkflowStep],
    economics: EconomicCase,
) -> str:
    del assertions, current_steps
    lines = _header(
        _artifact_title(engagement, "integration_requirements"), current, target, economics
    )
    systems = sorted({step.system_label for step in target_steps if step.system_label})
    lines.extend(["## Named systems", ""])
    if systems:
        lines.extend(f"- **{system}** remains a system of record." for system in systems)
    else:
        lines.append("- No external system has been verified for this workflow.")
    lines.extend(
        [
            "",
            "## Contract requirements",
            "",
            "- Define authentication, authorization, ownership, and data classification "
            "per system.",
            "- Specify idempotency keys, retry limits, timeouts, and human-visible failure states.",
            "- Record request correlation without persisting secrets or unredacted provider "
            "payloads.",
            "- Reconcile writes against the source system before reporting completion.",
            "",
        ]
    )
    return "\n".join(lines)


def _render_approval_controls(
    *,
    engagement: Engagement,
    assertions: list[dict[str, object]],
    current: WorkflowVersion,
    current_steps: list[WorkflowStep],
    target: WorkflowVersion,
    target_steps: list[WorkflowStep],
    economics: EconomicCase,
) -> str:
    del assertions, current_steps
    lines = _header(_artifact_title(engagement, "approval_controls"), current, target, economics)
    lines.extend(["## Control matrix", ""])
    for step in target_steps:
        lines.extend(
            [
                f"### {step.position}. {step.name}",
                "",
                f"- Allocation: **{step.allocation}**",
                f"- Accountable actor: {step.actor_label or 'Unassigned; resolve before build'}",
                f"- Rationale: {step.rationale}",
                f"- Controls: {', '.join(step.controls) or 'None; resolve before build'}",
                f"- Source assertion: `{step.source_assertion_id or 'none'}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Global controls",
            "",
            "- Material decisions require an authenticated human actor and recorded reason.",
            "- AI may recommend but may not approve, execute code, or remediate autonomously "
            "in V1.",
            "- Every state transition records actor, timestamp, target, and correlation "
            "identifier.",
            "",
        ]
    )
    return "\n".join(lines)


def _render_evaluation_plan(
    *,
    engagement: Engagement,
    assertions: list[dict[str, object]],
    current: WorkflowVersion,
    current_steps: list[WorkflowStep],
    target: WorkflowVersion,
    target_steps: list[WorkflowStep],
    economics: EconomicCase,
) -> str:
    del assertions, current_steps, target_steps
    lines = _header(_artifact_title(engagement, "evaluation_plan"), current, target, economics)
    lines.extend(
        [
            "## Economic sensitivity",
            "",
            "| Scenario | Annual hours saved | Annual net benefit | Payback months |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for scenario_name in ("low", "base", "high"):
        scenario = cast(dict[str, Any], economics.scenarios[scenario_name])
        outputs = cast(dict[str, dict[str, Any]], scenario["outputs"])
        payback = outputs["payback_months"]["value"]
        lines.append(
            f"| {scenario['label']} | {outputs['annual_hours_saved']['value']} | "
            f"{outputs['annual_net_benefit']['value']} | "
            f"{payback if payback is not None else 'not achievable'} |"
        )
    lines.extend(
        [
            "",
            "## Quality gates",
            "",
            "- Extraction: exact-source provenance for every accepted claim; invalid schemas fail.",
            "- Workflow: every target step traces to an approved current workflow and assertion.",
            "- Security: tenant isolation, least privilege, and data lifecycle tests pass.",
            "- Operations: failed jobs expose bounded result codes without evidence content.",
            "- UX: loading, empty, error, success, and stale states are verified.",
            "",
            "## Go/no-go rule",
            "",
            "Do not enable sanitized customer data until the live Auth0, AWS identity, storage, "
            "database, extraction, rollback, and deletion checks all pass and a deployment "
            "validation identifier is recorded.",
            "",
        ]
    )
    return "\n".join(lines)


def _render_implementation_spec(
    *,
    engagement: Engagement,
    assertions: list[dict[str, object]],
    current: WorkflowVersion,
    current_steps: list[WorkflowStep],
    target: WorkflowVersion,
    target_steps: list[WorkflowStep],
    economics: EconomicCase,
) -> str:
    lines = _header(_artifact_title(engagement, "implementation_spec"), current, target, economics)
    lines.extend(
        [
            "## Business outcome",
            "",
            engagement.primary_outcome,
            "",
            "## Verified operating assertions",
            "",
            *_render_assertions(assertions),
            "",
            "## Approved current workflow",
            "",
            *_render_steps(current_steps, include_allocation=False),
            "",
            "## Approved target workflow and allocation",
            "",
            *_render_steps(target_steps, include_allocation=True),
            "",
            "## Deterministic economic case",
            "",
            "### Base inputs",
            "",
        ]
    )
    for key, raw_input in economics.inputs.items():
        input_value = cast(dict[str, object], raw_input)
        lines.append(
            f"- `{key}`: {input_value['value']} {input_value['unit']} "
            f"(**{input_value['classification']}**)"
        )
    lines.extend(["", "### Base calculated outputs", ""])
    for key, raw_output in economics.outputs.items():
        output = cast(dict[str, object], raw_output)
        display_value = output["value"] if output["value"] is not None else "not achievable"
        lines.extend(
            [
                f"- `{key}`: {display_value} {output['unit']} (**calculated**)",
                f"  - Formula: `{output['formula']}`",
            ]
        )
    lines.extend(["", "### Sensitivity scenarios", ""])
    for scenario_name in ("low", "base", "high"):
        scenario = cast(dict[str, Any], economics.scenarios[scenario_name])
        outputs = cast(dict[str, dict[str, Any]], scenario["outputs"])
        payback = outputs["payback_months"]["value"]
        lines.append(
            f"- **{scenario['label']}**: {outputs['annual_net_benefit']['value']} USD/year net; "
            f"payback: {f'{payback} months' if payback is not None else 'not achievable'}."
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
            "- Treat all external content as untrusted input; it cannot change tool policy.",
            "- Keep engagement-scoped authorization and PostgreSQL row isolation on new records.",
            "",
            "## Acceptance criteria",
            "",
            "- Every target step is implemented with its approved allocation and controls.",
            "- Existing approval exceptions follow the verified operating assertions.",
            "- Economic calculations reproduce from the versioned scenario inputs.",
            "- Tests prove cross-engagement reads and writes fail closed.",
            "- No production deployment, coding-agent execution, or autonomous remediation is "
            "implied by this specification.",
            "",
        ]
    )
    return "\n".join(lines)


def _render_assertions(assertions: list[dict[str, object]]) -> list[str]:
    lines: list[str] = []
    for assertion in assertions:
        evidence = cast(dict[str, object], assertion["evidence"])
        object_text = f" {assertion['object']}" if assertion.get("object") else ""
        lines.extend(
            [
                f"- **{assertion['subject']} {assertion['predicate']}{object_text}**",
                f"  - Evidence: “{evidence['quote']}”",
                f"  - Source: `{evidence['file_name']}` / segment `{evidence['segment_id']}`",
                f"  - Assertion: `{assertion['id']}`",
            ]
        )
    return lines


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
