from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ai_fde.adapters.storage import InMemoryEvidenceStore
from ai_fde.db import operator_session
from ai_fde.models import EngagementAssessment, ExtractionRun, Operator
from ai_fde.modules.engagements.evaluation import (
    engagement_delivery_scorecard,
    internal_alpha_scorecard,
)
from ai_fde.modules.engagements.service import create_engagement
from ai_fde.modules.evidence.service import create_evidence_asset
from tests.conftest import OperatorFixture


@pytest.mark.integration
def test_internal_alpha_comparison_requires_both_three_workflow_cohorts(
    test_operator: OperatorFixture,
) -> None:
    profiles = (
        ("Acme Manufacturing", "Accounts Payable"),
        ("Northstar Health", "Employee Access Onboarding"),
        ("Beacon Logistics", "Customer Support Triage"),
    )
    with operator_session(test_operator.id) as session:
        operator = session.get_one(Operator, test_operator.id)
        engagement_ids = []
        for name, workflow_name in profiles:
            engagement = create_engagement(
                session,
                operator=operator,
                name=name,
                workflow_name=workflow_name,
                primary_outcome=(
                    "Measure delivery quality without making unsupported percentage claims."
                ),
            )
            engagement_ids.append(engagement.id)
            session.add(
                EngagementAssessment(
                    engagement_id=engagement.id,
                    evaluator_id=operator.id,
                    delivery_method="ai_fde",
                    perspective="operator",
                    outcome="completed",
                    duration_minutes=60,
                    usefulness_score=5,
                    clarification_count=1,
                    rework_count=0,
                    workaround_count=0,
                    trust_failure_count=0,
                )
            )
        session.flush()

        incomplete = internal_alpha_scorecard(session)
        assert incomplete["comparison"]["ready"] is False
        assert incomplete["comparison"]["absolute_difference"] is None
        assert (
            incomplete["comparison"]["methods"]["ai_fde"]["completed_operator_assessment_count"]
            == 3
        )
        assert (
            incomplete["comparison"]["methods"]["conventional"][
                "completed_operator_assessment_count"
            ]
            == 0
        )

        for engagement_id in engagement_ids:
            session.add(
                EngagementAssessment(
                    engagement_id=engagement_id,
                    evaluator_id=operator.id,
                    delivery_method="conventional",
                    perspective="operator",
                    outcome="completed",
                    duration_minutes=120,
                    usefulness_score=3,
                    clarification_count=4,
                    rework_count=2,
                    workaround_count=1,
                    trust_failure_count=1,
                )
            )
        session.flush()

        complete = internal_alpha_scorecard(session)
        assert complete["comparison"]["ready"] is True
        assert complete["comparison"]["absolute_difference"] == {
            "duration_minutes": 60.0,
            "rework_count": 2.0,
            "trust_failure_count": 1.0,
            "usefulness_score": 2.0,
        }


@pytest.mark.integration
def test_delivery_scorecard_uses_latest_run_after_successful_recovery(
    test_operator: OperatorFixture,
) -> None:
    store = InMemoryEvidenceStore()
    recovered_at = datetime.now(UTC)
    with operator_session(test_operator.id) as session:
        operator = session.get_one(Operator, test_operator.id)
        engagement = create_engagement(
            session,
            operator=operator,
            name="Recovered Extraction Manufacturing",
            primary_outcome="Show readiness after a failed extraction attempt recovers.",
        )
        asset = create_evidence_asset(
            session,
            store,
            engagement_id=engagement.id,
            operator=operator,
            file_name="recovered.md",
            content_type="text/markdown",
            content=b"Meeting agenda with no operating claim.",
        )
        asset.status = "complete"
        common = {
            "engagement_id": engagement.id,
            "evidence_asset_id": asset.id,
            "extractor_name": "test-extractor",
            "extractor_version": "1",
            "schema_version": "claim-v1",
            "provider_name": "test-provider",
            "model_id": "test-model",
            "prompt_version": "test-prompt",
            "input_hash": asset.content_hash,
        }
        session.add(
            ExtractionRun(
                **common,
                status="failed",
                result_code="provider_transport_error",
                created_at=recovered_at - timedelta(seconds=1),
                completed_at=recovered_at - timedelta(seconds=1),
            )
        )
        session.add(
            ExtractionRun(
                **common,
                status="complete",
                result_code="complete",
                created_at=recovered_at,
                completed_at=recovered_at,
            )
        )
        session.flush()

        scorecard = engagement_delivery_scorecard(session, engagement.id)

        assert scorecard["milestones"]["evidence_ready"] is True
        assert scorecard["provider"]["run_count"] == 2
