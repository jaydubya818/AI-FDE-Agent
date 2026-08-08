from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from ai_fde.adapters.storage import InMemoryEvidenceStore
from ai_fde.db import operator_session
from ai_fde.models import CandidateClaim, Contradiction, Operator
from ai_fde.modules.artifacts.service import (
    generate_implementation_specification,
    get_latest_artifact,
)
from ai_fde.modules.economics.service import (
    approve_economic_case,
    calculate_economic_case,
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
            process_job(session, store, job)

    with operator_session(test_operator.id) as session:
        operator = session.get_one(Operator, test_operator.id)
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
