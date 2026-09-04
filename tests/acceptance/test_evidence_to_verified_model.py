from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import select

from ai_fde.adapters.storage import InMemoryEvidenceStore
from ai_fde.db import operator_session
from ai_fde.models import CandidateClaim, EvidenceAsset, Job, Operator
from ai_fde.modules.engagements.service import create_engagement, get_engagement_counts
from ai_fde.modules.evidence.service import create_evidence_asset
from ai_fde.modules.knowledge.jobs import lease_next_job, process_job
from ai_fde.modules.knowledge.review import evidence_for_claim, review_claim
from ai_fde.modules.operating_model.service import list_entities, list_verified_assertions
from tests.conftest import OperatorFixture


@pytest.mark.integration
def test_complete_evidence_to_verified_model_lifecycle(
    test_operator: OperatorFixture,
) -> None:
    store = InMemoryEvidenceStore()
    source = Path("fixtures/acme/evidence/01-accounts-payable-sop.md").read_bytes()

    with operator_session(test_operator.id) as session:
        operator = session.get_one(Operator, test_operator.id)
        engagement = create_engagement(
            session,
            operator=operator,
            name="Acceptance Manufacturing",
            primary_outcome="Prove the trustworthy invoice-approval discovery lifecycle.",
        )
        engagement_id = engagement.id
        asset = create_evidence_asset(
            session,
            store,
            engagement_id=engagement_id,
            operator=operator,
            file_name="accounts-payable-sop.md",
            content_type="text/markdown",
            content=source,
            source_type="fixture",
        )
        asset_id = asset.id
        assert asset.status == "queued"

    with operator_session(test_operator.id) as session:
        job = lease_next_job(session, engagement_id, lease_seconds=30)
        assert job is not None
        process_job(session, store, job)
        assert job.status == "completed"

    with operator_session(test_operator.id) as session:
        claim = session.scalar(
            select(CandidateClaim).where(
                CandidateClaim.engagement_id == engagement_id,
                CandidateClaim.predicate == "REQUIRES_APPROVAL",
            )
        )
        assert claim is not None
        evidence = evidence_for_claim(session, claim.id)
        assert len(evidence) == 1
        assert evidence[0]["quote"] == "Invoices over $50,000 require CFO approval."
        assert evidence[0]["file_name"] == "accounts-payable-sop.md"

        operator = session.get_one(Operator, test_operator.id)
        assertion = review_claim(
            session,
            engagement_id=engagement_id,
            claim_id=claim.id,
            operator=operator,
            decision="accepted",
            reason="Confirmed against the supplied policy.",
        )
        assert assertion is not None
        assertion_id = assertion.id
        assert session.get_one(EvidenceAsset, asset_id).status == "needs_review"

        remaining_claims = list(
            session.scalars(
                select(CandidateClaim).where(
                    CandidateClaim.engagement_id == engagement_id,
                    CandidateClaim.status == "candidate",
                )
            )
        )
        assert remaining_claims
        for remaining_claim in remaining_claims:
            review_claim(
                session,
                engagement_id=engagement_id,
                claim_id=remaining_claim.id,
                operator=operator,
                decision="rejected",
                reason="Non-material candidate closed in the acceptance lifecycle.",
            )
        assert session.get_one(EvidenceAsset, asset_id).status == "complete"

    with operator_session(test_operator.id) as session:
        counts = get_engagement_counts(session, engagement_id)
        assert counts["evidence"] == 1
        assert counts["verified_assertions"] == 1

        entities = list_entities(session, engagement_id)
        assert {(item.entity_type, item.display_name) for item in entities} >= {
            ("process", "Invoice approval"),
            ("role", "CFO"),
        }

        [verified] = [
            item
            for item in list_verified_assertions(session, engagement_id)
            if item["id"] == assertion_id
        ]
        assert verified["predicate"] == "REQUIRES_APPROVAL"
        assert verified["subject"] == "Invoice approval"
        assert verified["object"] == "CFO"
        verified_evidence = cast(dict[str, object], verified["evidence"])
        assert verified_evidence["quote"] == "Invoices over $50,000 require CFO approval."

        completed_job = session.scalar(select(Job).where(Job.engagement_id == engagement_id))
        assert completed_job is not None
        assert completed_job.status == "completed"
