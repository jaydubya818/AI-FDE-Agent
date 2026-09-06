from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from ai_fde.adapters.storage import InMemoryEvidenceStore
from ai_fde.db import operator_session
from ai_fde.models import AuditEvent, CandidateClaim, Contradiction, EngagementAssessment, Operator
from ai_fde.modules.artifacts.service import (
    ARTIFACT_TYPES,
    generate_implementation_packet,
    generate_implementation_specification,
    get_latest_artifact,
)
from ai_fde.modules.economics.service import (
    approve_economic_case,
    calculate_economic_case,
)
from ai_fde.modules.engagements.evaluation import (
    AssessmentStageGateError,
    engagement_delivery_scorecard,
    record_assessment,
)
from ai_fde.modules.engagements.service import create_engagement
from ai_fde.modules.evidence.service import create_evidence_asset
from ai_fde.modules.knowledge.contradictions import resolve_contradiction
from ai_fde.modules.knowledge.jobs import lease_next_job, process_job
from ai_fde.modules.knowledge.review import review_claim
from ai_fde.modules.workflows.service import (
    WorkflowStageGateError,
    approve_workflow,
    generate_current_workflow,
    generate_target_workflow,
    list_workflow_steps,
)
from tests.conftest import OperatorFixture


@pytest.mark.integration
def test_verified_model_to_implementation_specification_lifecycle(
    test_operator: OperatorFixture,
) -> None:
    store = InMemoryEvidenceStore()
    fixture_root = Path("fixtures/acme/evidence")

    with operator_session(test_operator.id) as session:
        operator = session.get_one(Operator, test_operator.id)
        engagement = create_engagement(
            session,
            operator=operator,
            name="Lifecycle Manufacturing",
            workflow_name="Vendor onboarding",
            primary_outcome="Prove an evidence-backed implementation specification lifecycle.",
        )
        engagement_id = engagement.id
        for path in sorted(fixture_root.glob("*.md")):
            create_evidence_asset(
                session,
                store,
                engagement_id=engagement_id,
                operator=operator,
                file_name=path.name,
                content_type="text/markdown",
                content=path.read_bytes(),
                source_type="fixture",
            )

    with operator_session(test_operator.id) as session:
        while job := lease_next_job(session, engagement_id, lease_seconds=30):
            assert job.lease_token is not None
            process_job(session, store, job, lease_token=job.lease_token)

    with operator_session(test_operator.id) as session:
        operator = session.get_one(Operator, test_operator.id)
        with pytest.raises(AssessmentStageGateError, match="seven-artifact"):
            record_assessment(
                session,
                engagement_id=engagement_id,
                evaluator=operator,
                delivery_method="ai_fde",
                perspective="operator",
                outcome="completed",
                duration_minutes=90,
                usefulness_score=5,
                clarification_count=1,
                rework_count=0,
                workaround_count=0,
                trust_failure_count=0,
                notes="This must not be persisted before the stage gate is satisfied.",
            )
        actionable_claims = list(
            session.scalars(
                select(CandidateClaim).where(
                    CandidateClaim.engagement_id == engagement_id,
                    CandidateClaim.predicate.in_(["OWNS", "USES", "REQUIRES_APPROVAL"]),
                )
            )
        )
        assert len(actionable_claims) == 4
        for claim in actionable_claims:
            review_claim(
                session,
                engagement_id=engagement_id,
                claim_id=claim.id,
                operator=operator,
                decision="accepted",
                reason="Verified for the lifecycle acceptance case.",
            )

        current = generate_current_workflow(session, engagement_id=engagement_id, operator=operator)
        assert len(list_workflow_steps(session, current.id)) == 4
        with pytest.raises(WorkflowStageGateError, match="blocking contradictions"):
            approve_workflow(
                session,
                engagement_id=engagement_id,
                workflow_id=current.id,
                operator=operator,
            )

        contradiction = session.scalar(
            select(Contradiction).where(Contradiction.engagement_id == engagement_id)
        )
        assert contradiction is not None
        resolve_contradiction(
            session,
            engagement_id=engagement_id,
            contradiction_id=contradiction.id,
            operator=operator,
            resolution_type="accepted_exception",
            reason="The Controller path is a documented exception to the CFO rule.",
        )
        approve_workflow(
            session,
            engagement_id=engagement_id,
            workflow_id=current.id,
            operator=operator,
        )

        target = generate_target_workflow(session, engagement_id=engagement_id, operator=operator)
        target_steps = list_workflow_steps(session, target.id)
        assert target.name == "Vendor onboarding — Target State"
        assert len(target_steps) == 4
        assert {step.allocation for step in target_steps} <= {"human", "software"}
        approve_workflow(
            session,
            engagement_id=engagement_id,
            workflow_id=target.id,
            operator=operator,
        )

        values = {
            "annual_volume": Decimal("24000"),
            "current_minutes_per_item": Decimal("18"),
            "target_minutes_per_item": Decimal("8"),
            "loaded_hourly_cost": Decimal("42"),
            "implementation_cost": Decimal("85000"),
            "annual_operating_cost": Decimal("18000"),
        }
        classifications = {key: "synthetic" for key in values}
        economic_case = calculate_economic_case(
            session,
            engagement_id=engagement_id,
            operator=operator,
            values=values,
            classifications=classifications,
            assumptions=["Synthetic fixture values for architecture validation only."],
        )
        assert economic_case.outputs["annual_hours_saved"]["value"] == "4000.00"
        assert economic_case.outputs["annual_net_benefit"]["value"] == "150000.00"
        assert list(economic_case.scenarios) == ["low", "base", "high"]
        assert (
            Decimal(economic_case.scenarios["low"]["outputs"]["annual_net_benefit"]["value"])
            < Decimal(economic_case.scenarios["base"]["outputs"]["annual_net_benefit"]["value"])
            < Decimal(economic_case.scenarios["high"]["outputs"]["annual_net_benefit"]["value"])
        )
        approve_economic_case(
            session,
            engagement_id=engagement_id,
            economic_case_id=economic_case.id,
            operator=operator,
        )

        artifact = generate_implementation_specification(
            session, engagement_id=engagement_id, operator=operator
        )
        assert artifact.status == "current"
        assert "## Verified operating assertions" in artifact.content
        assert "Invoices over $50,000 require CFO approval." in artifact.content
        assert "annual_net_benefit" in artifact.content
        assert "No production deployment" in artifact.content
        packet = generate_implementation_packet(
            session, engagement_id=engagement_id, operator=operator
        )
        assert [item.artifact_type for item in packet] == list(ARTIFACT_TYPES)
        assert len({item.packet_version for item in packet}) == 1
        assert len({item.source_current_workflow_id for item in packet}) == 1
        assert all("Accounts Payable" not in item.title for item in packet)
        assert "## Runtime boundaries" in next(
            item.content for item in packet if item.artifact_type == "architecture"
        )

        assessment = record_assessment(
            session,
            engagement_id=engagement_id,
            evaluator=operator,
            delivery_method="ai_fde",
            perspective="operator",
            outcome="completed",
            duration_minutes=90,
            usefulness_score=5,
            clarification_count=1,
            rework_count=0,
            workaround_count=0,
            trust_failure_count=0,
            notes="Evaluator note that must never be copied into the audit event.",
        )
        updated = record_assessment(
            session,
            engagement_id=engagement_id,
            evaluator=operator,
            delivery_method="ai_fde",
            perspective="operator",
            outcome="completed",
            duration_minutes=82,
            usefulness_score=5,
            clarification_count=0,
            rework_count=0,
            workaround_count=0,
            trust_failure_count=0,
            notes="Updated evaluator note.",
        )
        assert updated.id == assessment.id
        assert (
            session.scalar(
                select(func.count())
                .select_from(EngagementAssessment)
                .where(EngagementAssessment.engagement_id == engagement_id)
            )
            == 1
        )
        audit = session.scalar(
            select(AuditEvent)
            .where(
                AuditEvent.engagement_id == engagement_id,
                AuditEvent.action == "engagement.assessment_recorded",
            )
            .order_by(AuditEvent.created_at.desc())
        )
        assert audit is not None
        assert audit.detail["notes_present"] is True
        assert "notes" not in audit.detail
        scorecard = engagement_delivery_scorecard(session, engagement_id)
        assert scorecard["packet"]["complete"] is True
        assert scorecard["claims"]["material_accepted"] == 4
        assert scorecard["provider"]["run_count"] == 2
        assert scorecard["assessments"][0]["duration_minutes"] == 82

        remaining_entity_claim = session.scalar(
            select(CandidateClaim).where(
                CandidateClaim.engagement_id == engagement_id,
                CandidateClaim.status == "candidate",
                CandidateClaim.predicate == "IDENTIFIED_AS",
            )
        )
        assert remaining_entity_claim is not None
        review_claim(
            session,
            engagement_id=engagement_id,
            claim_id=remaining_entity_claim.id,
            operator=operator,
            decision="accepted",
            reason="New verified model state must stale downstream artifacts.",
        )

    with operator_session(test_operator.id) as session:
        latest = get_latest_artifact(session, engagement_id)
        assert latest is not None
        assert latest.status == "stale"
