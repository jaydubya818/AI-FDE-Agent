from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import UTC, datetime
from statistics import fmean
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ai_fde.models import (
    CandidateClaim,
    Contradiction,
    EconomicCase,
    Engagement,
    EngagementAssessment,
    EvidenceAsset,
    ExtractionRun,
    ImplementationArtifact,
    Operator,
    WorkflowVersion,
)
from ai_fde.modules.artifacts.service import ARTIFACT_TYPES
from ai_fde.modules.shared import publish_domain_event, record_audit

ALPHA_PROFILE_SLUGS = ("acme-manufacturing", "northstar-health", "beacon-logistics")


class AssessmentStageGateError(ValueError):
    pass


def list_assessments(session: Session, engagement_id: UUID) -> list[EngagementAssessment]:
    return list(
        session.scalars(
            select(EngagementAssessment)
            .where(EngagementAssessment.engagement_id == engagement_id)
            .order_by(
                EngagementAssessment.delivery_method,
                EngagementAssessment.perspective,
                EngagementAssessment.updated_at.desc(),
            )
        )
    )


def record_assessment(
    session: Session,
    *,
    engagement_id: UUID,
    evaluator: Operator,
    delivery_method: str,
    perspective: str,
    outcome: str,
    duration_minutes: int,
    usefulness_score: int,
    clarification_count: int,
    rework_count: int,
    workaround_count: int,
    trust_failure_count: int,
    notes: str | None,
) -> EngagementAssessment:
    if delivery_method == "ai_fde" and outcome == "completed":
        packet = _packet_snapshot(session, engagement_id)
        if not packet["complete"]:
            raise AssessmentStageGateError(
                "AI-FDE delivery cannot be marked completed until one current seven-artifact "
                "implementation packet exists."
            )

    lock_identity = f"{engagement_id}:{evaluator.id}:{delivery_method}:{perspective}".encode()
    lock_key = int.from_bytes(hashlib.sha256(lock_identity).digest()[:8], signed=True)
    session.execute(select(func.pg_advisory_xact_lock(lock_key)))
    assessment = session.scalar(
        select(EngagementAssessment)
        .where(
            EngagementAssessment.engagement_id == engagement_id,
            EngagementAssessment.evaluator_id == evaluator.id,
            EngagementAssessment.delivery_method == delivery_method,
            EngagementAssessment.perspective == perspective,
        )
        .with_for_update()
    )
    created = assessment is None
    if assessment is None:
        assessment = EngagementAssessment(
            engagement_id=engagement_id,
            evaluator_id=evaluator.id,
            delivery_method=delivery_method,
            perspective=perspective,
        )
        session.add(assessment)

    assessment.outcome = outcome
    assessment.duration_minutes = duration_minutes
    assessment.usefulness_score = usefulness_score
    assessment.clarification_count = clarification_count
    assessment.rework_count = rework_count
    assessment.workaround_count = workaround_count
    assessment.trust_failure_count = trust_failure_count
    assessment.notes = notes.strip() if notes and notes.strip() else None
    assessment.updated_at = datetime.now(UTC)
    session.flush()

    safe_detail = {
        "created": created,
        "delivery_method": delivery_method,
        "perspective": perspective,
        "outcome": outcome,
        "duration_minutes": duration_minutes,
        "usefulness_score": usefulness_score,
        "clarification_count": clarification_count,
        "rework_count": rework_count,
        "workaround_count": workaround_count,
        "trust_failure_count": trust_failure_count,
        "notes_present": assessment.notes is not None,
    }
    record_audit(
        session,
        engagement_id=engagement_id,
        actor_id=evaluator.id,
        action="engagement.assessment_recorded",
        target_type="engagement_assessment",
        target_id=assessment.id,
        detail=safe_detail,
    )
    publish_domain_event(
        session,
        engagement_id=engagement_id,
        event_type="engagement.assessment_recorded",
        aggregate_type="engagement_assessment",
        aggregate_id=assessment.id,
        payload=safe_detail,
    )
    return assessment


def engagement_delivery_scorecard(session: Session, engagement_id: UUID) -> dict[str, Any]:
    engagement = session.get(Engagement, engagement_id)
    if engagement is None:
        raise LookupError("Engagement not found.")

    claim_rows = session.execute(
        select(CandidateClaim.status, CandidateClaim.materiality, func.count(CandidateClaim.id))
        .where(CandidateClaim.engagement_id == engagement_id)
        .group_by(CandidateClaim.status, CandidateClaim.materiality)
    ).all()
    claim_counts: defaultdict[str, int] = defaultdict(int)
    material_accepted = 0
    for claim_status, materiality, count in claim_rows:
        claim_counts[claim_status] += count
        if claim_status == "accepted" and materiality == "material":
            material_accepted += count

    contradiction_rows = session.execute(
        select(Contradiction.status, Contradiction.blocking, func.count(Contradiction.id))
        .where(Contradiction.engagement_id == engagement_id)
        .group_by(Contradiction.status, Contradiction.blocking)
    ).all()
    contradiction_total = sum(row[2] for row in contradiction_rows)
    contradiction_resolved = sum(
        row[2] for row in contradiction_rows if row[0] not in {"open", "investigating"}
    )
    blocking_open = sum(
        row[2] for row in contradiction_rows if row[1] and row[0] in {"open", "investigating"}
    )

    run_rows = list(
        session.scalars(
            select(ExtractionRun)
            .where(ExtractionRun.engagement_id == engagement_id)
            .order_by(ExtractionRun.created_at, ExtractionRun.id)
        )
    )
    input_tokens = sum(item.input_tokens for item in run_rows)
    output_tokens = sum(item.output_tokens for item in run_rows)
    total_tokens = input_tokens + output_tokens
    packet = _packet_snapshot(session, engagement_id)

    evidence_statuses = list(
        session.scalars(
            select(EvidenceAsset.status).where(EvidenceAsset.engagement_id == engagement_id)
        )
    )
    workflows = list(
        session.scalars(
            select(WorkflowVersion).where(WorkflowVersion.engagement_id == engagement_id)
        )
    )
    approved_workflow_kinds = {
        workflow.workflow_kind for workflow in workflows if workflow.status == "approved"
    }
    approved_economic_case = session.scalar(
        select(EconomicCase.id)
        .where(
            EconomicCase.engagement_id == engagement_id,
            EconomicCase.status == "approved",
        )
        .limit(1)
    )
    latest_runs_by_asset = {item.evidence_asset_id: item for item in run_rows}
    run_ready = len(latest_runs_by_asset) == len(evidence_statuses) and all(
        item.status == "complete" for item in latest_runs_by_asset.values()
    )
    evidence_ready = (
        bool(evidence_statuses)
        and all(status not in {"queued", "processing", "failed"} for status in evidence_statuses)
        and run_ready
    )

    return {
        "engagement": {
            "id": str(engagement.id),
            "name": engagement.name,
            "slug": engagement.slug,
            "workflow_name": engagement.workflow_name,
        },
        "milestones": {
            "engagement_created": True,
            "evidence_ready": evidence_ready,
            "review_completed": bool(claim_counts) and claim_counts["candidate"] == 0,
            "workflows_approved": approved_workflow_kinds == {"current", "target"},
            "economics_approved": approved_economic_case is not None,
            "implementation_packet_completed": packet["complete"],
        },
        "claims": {
            "total": sum(claim_counts.values()),
            "candidate": claim_counts["candidate"],
            "accepted": claim_counts["accepted"],
            "rejected": claim_counts["rejected"],
            "deferred": claim_counts["deferred"],
            "material_accepted": material_accepted,
        },
        "contradictions": {
            "total": contradiction_total,
            "resolved": contradiction_resolved,
            "blocking_open": blocking_open,
        },
        "packet": packet,
        "provider": {
            "run_count": len(run_rows),
            "providers": sorted({item.provider_name for item in run_rows}),
            "model_ids": sorted({item.model_id for item in run_rows if item.model_id}),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "latency_ms": sum(item.latency_ms for item in run_rows),
            "tokens_per_accepted_material_claim": (
                round(total_tokens / material_accepted, 2) if material_accepted else None
            ),
        },
        "assessments": [
            _assessment_dict(item) for item in list_assessments(session, engagement_id)
        ],
    }


def internal_alpha_scorecard(session: Session) -> dict[str, Any]:
    engagements = list(
        session.scalars(
            select(Engagement)
            .where(
                Engagement.data_classification == "synthetic",
                Engagement.slug.in_(ALPHA_PROFILE_SLUGS),
            )
            .order_by(Engagement.created_at, Engagement.slug)
        )
    )
    engagement_cards = [engagement_delivery_scorecard(session, item.id) for item in engagements]
    assessments = [
        assessment
        for card in engagement_cards
        for assessment in card["assessments"]
        if assessment["perspective"] == "operator" and assessment["outcome"] == "completed"
    ]
    by_method: dict[str, list[dict[str, Any]]] = {
        method: [item for item in assessments if item["delivery_method"] == method]
        for method in ("ai_fde", "conventional")
    }
    comparison_ready = all(
        len(items) >= 3 and len({item["engagement_id"] for item in items}) >= 3
        for items in by_method.values()
    )

    comparison: dict[str, Any] = {
        "ready": comparison_ready,
        "minimum_completed_operator_assessments_per_method": 3,
        "methods": {method: _method_summary(items) for method, items in by_method.items()},
        "absolute_difference": None,
        "reason": None,
    }
    if comparison_ready:
        ai_fde = comparison["methods"]["ai_fde"]
        conventional = comparison["methods"]["conventional"]
        comparison["absolute_difference"] = {
            "duration_minutes": round(
                conventional["average_duration_minutes"] - ai_fde["average_duration_minutes"],
                2,
            ),
            "rework_count": round(
                conventional["average_rework_count"] - ai_fde["average_rework_count"], 2
            ),
            "trust_failure_count": round(
                conventional["average_trust_failure_count"] - ai_fde["average_trust_failure_count"],
                2,
            ),
            "usefulness_score": round(
                ai_fde["average_usefulness_score"] - conventional["average_usefulness_score"],
                2,
            ),
        }
    else:
        comparison["reason"] = (
            "Collect at least three completed operator assessments across three workflows for "
            "both AI-FDE and the conventional baseline before making comparative claims."
        )

    return {
        "program": "internal-alpha",
        "profile_count": len(engagement_cards),
        "packet_complete_count": sum(1 for item in engagement_cards if item["packet"]["complete"]),
        "accepted_material_claim_count": sum(
            item["claims"]["material_accepted"] for item in engagement_cards
        ),
        "total_provider_tokens": sum(item["provider"]["total_tokens"] for item in engagement_cards),
        "engagements": engagement_cards,
        "comparison": comparison,
    }


def _packet_snapshot(session: Session, engagement_id: UUID) -> dict[str, Any]:
    artifacts = list(
        session.scalars(
            select(ImplementationArtifact).where(
                ImplementationArtifact.engagement_id == engagement_id,
                ImplementationArtifact.status == "current",
            )
        )
    )
    packet_versions = {item.packet_version for item in artifacts}
    artifact_types = {item.artifact_type for item in artifacts}
    complete = (
        len(artifacts) == len(ARTIFACT_TYPES)
        and artifact_types == set(ARTIFACT_TYPES)
        and len(packet_versions) == 1
    )
    completed_at = max((item.generated_at for item in artifacts), default=None)
    return {
        "complete": complete,
        "artifact_count": len(artifacts),
        "expected_artifact_count": len(ARTIFACT_TYPES),
        "packet_version": next(iter(packet_versions)) if len(packet_versions) == 1 else None,
        "completed_at": completed_at.isoformat() if complete and completed_at else None,
    }


def _assessment_dict(assessment: EngagementAssessment) -> dict[str, Any]:
    return {
        "id": str(assessment.id),
        "engagement_id": str(assessment.engagement_id),
        "evaluator_id": str(assessment.evaluator_id),
        "delivery_method": assessment.delivery_method,
        "perspective": assessment.perspective,
        "outcome": assessment.outcome,
        "duration_minutes": assessment.duration_minutes,
        "usefulness_score": assessment.usefulness_score,
        "clarification_count": assessment.clarification_count,
        "rework_count": assessment.rework_count,
        "workaround_count": assessment.workaround_count,
        "trust_failure_count": assessment.trust_failure_count,
        "notes": assessment.notes,
        "created_at": assessment.created_at.isoformat(),
        "updated_at": assessment.updated_at.isoformat(),
    }


def _method_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "completed_operator_assessment_count": len(items),
        "distinct_workflow_count": len({item["engagement_id"] for item in items}),
        "average_duration_minutes": None,
        "average_usefulness_score": None,
        "average_clarification_count": None,
        "average_rework_count": None,
        "average_workaround_count": None,
        "average_trust_failure_count": None,
    }
    if not items:
        return summary
    for source, target in (
        ("duration_minutes", "average_duration_minutes"),
        ("usefulness_score", "average_usefulness_score"),
        ("clarification_count", "average_clarification_count"),
        ("rework_count", "average_rework_count"),
        ("workaround_count", "average_workaround_count"),
        ("trust_failure_count", "average_trust_failure_count"),
    ):
        summary[target] = round(fmean(item[source] for item in items), 2)
    return summary
