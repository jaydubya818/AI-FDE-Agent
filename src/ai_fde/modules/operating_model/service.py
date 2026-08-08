from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_fde.models import (
    Assertion,
    AssertionEvidence,
    ClaimEvidence,
    EvidenceAsset,
    EvidenceSegment,
    OperatingEntity,
)


def list_entities(session: Session, engagement_id: UUID) -> list[OperatingEntity]:
    return list(
        session.scalars(
            select(OperatingEntity)
            .where(OperatingEntity.engagement_id == engagement_id)
            .order_by(OperatingEntity.entity_type, OperatingEntity.display_name)
        )
    )


def list_verified_assertions(session: Session, engagement_id: UUID) -> list[dict[str, object]]:
    statement = (
        select(
            Assertion,
            OperatingEntity,
            AssertionEvidence,
            ClaimEvidence,
            EvidenceSegment,
            EvidenceAsset,
        )
        .join(OperatingEntity, OperatingEntity.id == Assertion.subject_entity_id)
        .join(AssertionEvidence, AssertionEvidence.assertion_id == Assertion.id)
        .join(ClaimEvidence, ClaimEvidence.id == AssertionEvidence.claim_evidence_id)
        .join(EvidenceSegment, EvidenceSegment.id == AssertionEvidence.evidence_segment_id)
        .join(EvidenceAsset, EvidenceAsset.id == EvidenceSegment.evidence_asset_id)
        .where(
            Assertion.engagement_id == engagement_id,
            Assertion.status == "verified",
        )
        .order_by(Assertion.recorded_at.desc())
    )
    rows = session.execute(statement).all()
    object_ids = {row[0].object_entity_id for row in rows if row[0].object_entity_id is not None}
    object_names = {
        entity.id: entity.display_name
        for entity in session.scalars(
            select(OperatingEntity).where(OperatingEntity.id.in_(object_ids))
        )
    }
    return [
        {
            "id": assertion.id,
            "subject": subject.display_name,
            "subject_entity_id": subject.id,
            "predicate": assertion.predicate,
            "object": object_names.get(assertion.object_entity_id),
            "object_entity_id": assertion.object_entity_id,
            "value": assertion.value,
            "status": assertion.status,
            "confidence": assertion.confidence,
            "recorded_at": assertion.recorded_at,
            "evidence": {
                "file_name": asset.file_name,
                "source_type": asset.source_type,
                "source_timestamp": asset.source_timestamp,
                "locator": segment.locator,
                "quote": claim_evidence.quote,
                "segment_id": segment.id,
            },
        }
        for assertion, subject, assertion_evidence, claim_evidence, segment, asset in rows
    ]
