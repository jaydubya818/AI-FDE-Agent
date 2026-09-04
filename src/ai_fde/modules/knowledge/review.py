from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_fde.models import (
    Assertion,
    AssertionEvidence,
    CandidateClaim,
    ClaimEvidence,
    Engagement,
    EvidenceAsset,
    EvidenceSegment,
    ExtractionRun,
    OperatingEntity,
    Operator,
    ReviewDecision,
)
from ai_fde.modules.lifecycle import stale_after_model_change
from ai_fde.modules.shared import publish_domain_event, record_audit


class ClaimNotFoundError(LookupError):
    pass


class ClaimAlreadyReviewedError(ValueError):
    pass


def list_claims(
    session: Session, engagement_id: UUID, status: str | None = None
) -> list[CandidateClaim]:
    statement = select(CandidateClaim).where(CandidateClaim.engagement_id == engagement_id)
    if status:
        statement = statement.where(CandidateClaim.status == status)
    return list(session.scalars(statement.order_by(CandidateClaim.created_at.desc())))


def review_claim(
    session: Session,
    *,
    engagement_id: UUID,
    claim_id: UUID,
    operator: Operator,
    decision: str,
    reason: str | None = None,
) -> Assertion | None:
    claim = session.scalar(
        select(CandidateClaim)
        .where(
            CandidateClaim.id == claim_id,
            CandidateClaim.engagement_id == engagement_id,
        )
        .with_for_update()
    )
    if claim is None:
        raise ClaimNotFoundError(str(claim_id))
    if claim.status != "candidate":
        raise ClaimAlreadyReviewedError("This claim has already been reviewed.")
    if decision not in {"accepted", "rejected", "deferred"}:
        raise ValueError("Unsupported review decision.")

    claim.status = decision
    session.add(
        ReviewDecision(
            engagement_id=engagement_id,
            candidate_claim_id=claim.id,
            reviewer_id=operator.id,
            decision=decision,
            reason=reason.strip() if reason else None,
        )
    )
    assertion: Assertion | None = None
    if decision == "accepted":
        assertion = _create_verified_assertion(session, claim, operator)
        stale_after_model_change(session, engagement_id)
        engagement = session.get(Engagement, engagement_id)
        if engagement is not None:
            engagement.lifecycle_stage = "model"

    session.flush()
    completed_asset = _complete_evidence_review_if_decided(session, claim)

    record_audit(
        session,
        engagement_id=engagement_id,
        actor_id=operator.id,
        action=f"claim.{decision}",
        target_type="candidate_claim",
        target_id=claim.id,
        detail={"reason": reason, "assertion_id": str(assertion.id) if assertion else None},
    )
    publish_domain_event(
        session,
        engagement_id=engagement_id,
        event_type="claim.reviewed",
        aggregate_type="candidate_claim",
        aggregate_id=claim.id,
        payload={"decision": decision},
    )
    if assertion is not None:
        publish_domain_event(
            session,
            engagement_id=engagement_id,
            event_type="assertion.verified",
            aggregate_type="assertion",
            aggregate_id=assertion.id,
            payload={"candidate_claim_id": str(claim.id)},
        )
    if completed_asset is not None:
        record_audit(
            session,
            engagement_id=engagement_id,
            actor_id=operator.id,
            action="evidence.review_completed",
            target_type="evidence_asset",
            target_id=completed_asset.id,
            detail={},
        )
        publish_domain_event(
            session,
            engagement_id=engagement_id,
            event_type="evidence.review_completed",
            aggregate_type="evidence_asset",
            aggregate_id=completed_asset.id,
        )
    return assertion


def _complete_evidence_review_if_decided(
    session: Session,
    claim: CandidateClaim,
) -> EvidenceAsset | None:
    extraction_run = session.get(ExtractionRun, claim.extraction_run_id)
    if extraction_run is None:
        return None
    asset = session.scalar(
        select(EvidenceAsset)
        .where(
            EvidenceAsset.id == extraction_run.evidence_asset_id,
            EvidenceAsset.status == "needs_review",
        )
        .with_for_update()
    )
    if asset is None:
        return None
    pending_claim = session.scalar(
        select(CandidateClaim.id)
        .join(ExtractionRun, ExtractionRun.id == CandidateClaim.extraction_run_id)
        .where(
            ExtractionRun.evidence_asset_id == asset.id,
            CandidateClaim.status == "candidate",
        )
        .limit(1)
    )
    if pending_claim is not None:
        return None
    asset.status = "complete"
    return asset


def _create_verified_assertion(
    session: Session, claim: CandidateClaim, operator: Operator
) -> Assertion:
    payload = claim.normalized_payload
    subject_spec = payload["subject"]
    subject = _get_or_create_entity(
        session,
        engagement_id=claim.engagement_id,
        entity_type=str(subject_spec["type"]),
        name=str(subject_spec["name"]),
        operator_id=operator.id,
    )
    object_entity: OperatingEntity | None = None
    object_spec = payload.get("object")
    if isinstance(object_spec, dict):
        object_entity = _get_or_create_entity(
            session,
            engagement_id=claim.engagement_id,
            entity_type=str(object_spec["type"]),
            name=str(object_spec["name"]),
            operator_id=operator.id,
        )

    assertion = Assertion(
        engagement_id=claim.engagement_id,
        subject_entity_id=subject.id,
        predicate=claim.predicate,
        object_entity_id=object_entity.id if object_entity else None,
        value={
            "summary": claim.summary,
            "claim_kind": claim.claim_kind,
            "condition": payload.get("condition"),
            "is_exception": payload.get("is_exception", False),
        },
        confidence=claim.confidence,
        candidate_claim_id=claim.id,
        verified_by_id=operator.id,
    )
    session.add(assertion)
    session.flush()

    evidence_links = list(
        session.scalars(select(ClaimEvidence).where(ClaimEvidence.candidate_claim_id == claim.id))
    )
    if not evidence_links:
        raise ValueError("A verified assertion must retain at least one evidence link.")
    for link in evidence_links:
        session.add(
            AssertionEvidence(
                engagement_id=claim.engagement_id,
                assertion_id=assertion.id,
                evidence_segment_id=link.evidence_segment_id,
                claim_evidence_id=link.id,
            )
        )
    return assertion


def _get_or_create_entity(
    session: Session,
    *,
    engagement_id: UUID,
    entity_type: str,
    name: str,
    operator_id: UUID,
) -> OperatingEntity:
    canonical_key = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    entity = session.scalar(
        select(OperatingEntity).where(
            OperatingEntity.engagement_id == engagement_id,
            OperatingEntity.entity_type == entity_type,
            OperatingEntity.canonical_key == canonical_key,
        )
    )
    if entity is None:
        entity = OperatingEntity(
            engagement_id=engagement_id,
            entity_type=entity_type,
            canonical_key=canonical_key,
            display_name=name,
            status="verified",
            verified_by_id=operator_id,
        )
        session.add(entity)
        session.flush()
    return entity


def evidence_for_claim(session: Session, claim_id: UUID) -> list[dict[str, object]]:
    statement = (
        select(ClaimEvidence, EvidenceSegment, EvidenceAsset)
        .join(EvidenceSegment, EvidenceSegment.id == ClaimEvidence.evidence_segment_id)
        .join(EvidenceAsset, EvidenceAsset.id == EvidenceSegment.evidence_asset_id)
        .where(ClaimEvidence.candidate_claim_id == claim_id)
    )
    return [
        {
            "claim_evidence_id": link.id,
            "evidence_segment_id": segment.id,
            "evidence_asset_id": asset.id,
            "file_name": asset.file_name,
            "source_type": asset.source_type,
            "source_timestamp": asset.source_timestamp,
            "locator": segment.locator,
            "quote": link.quote,
            "start_offset": link.start_offset,
            "end_offset": link.end_offset,
        }
        for link, segment, asset in session.execute(statement)
    ]
