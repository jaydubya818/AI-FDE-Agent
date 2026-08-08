from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ai_fde.models import (
    Assertion,
    CandidateClaim,
    Engagement,
    EngagementMember,
    EvidenceAsset,
    Operator,
)
from ai_fde.modules.shared import publish_domain_event, record_audit


class EngagementNotFoundError(LookupError):
    pass


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    return slug[:100] or "engagement"


def create_engagement(
    session: Session,
    *,
    operator: Operator,
    name: str,
    primary_outcome: str,
    data_classification: str = "synthetic",
) -> Engagement:
    base_slug = _slugify(name)
    slug = base_slug
    suffix = 2
    while session.scalar(select(Engagement.id).where(Engagement.slug == slug)) is not None:
        slug = f"{base_slug}-{suffix}"
        suffix += 1

    engagement = Engagement(
        name=name.strip(),
        slug=slug,
        primary_outcome=primary_outcome.strip(),
        lifecycle_stage="discover",
        data_classification=data_classification,
        created_by_id=operator.id,
    )
    session.add(engagement)
    session.flush()
    session.add(
        EngagementMember(engagement_id=engagement.id, operator_id=operator.id, role="owner")
    )
    record_audit(
        session,
        engagement_id=engagement.id,
        actor_id=operator.id,
        action="engagement.created",
        target_type="engagement",
        target_id=engagement.id,
        detail={"data_classification": data_classification},
    )
    publish_domain_event(
        session,
        engagement_id=engagement.id,
        event_type="engagement.created",
        aggregate_type="engagement",
        aggregate_id=engagement.id,
    )
    return engagement


def list_engagements(session: Session, operator_id: UUID) -> list[Engagement]:
    statement = (
        select(Engagement)
        .join(EngagementMember, EngagementMember.engagement_id == Engagement.id)
        .where(EngagementMember.operator_id == operator_id)
        .order_by(Engagement.created_at.desc())
    )
    return list(session.scalars(statement))


def get_engagement(session: Session, engagement_id: UUID) -> Engagement:
    engagement = session.get(Engagement, engagement_id)
    if engagement is None:
        raise EngagementNotFoundError(str(engagement_id))
    return engagement


def get_engagement_counts(session: Session, engagement_id: UUID) -> dict[str, int]:
    return {
        "evidence": session.scalar(
            select(func.count())
            .select_from(EvidenceAsset)
            .where(EvidenceAsset.engagement_id == engagement_id)
        )
        or 0,
        "candidate_claims": session.scalar(
            select(func.count())
            .select_from(CandidateClaim)
            .where(
                CandidateClaim.engagement_id == engagement_id,
                CandidateClaim.status == "candidate",
            )
        )
        or 0,
        "verified_assertions": session.scalar(
            select(func.count())
            .select_from(Assertion)
            .where(
                Assertion.engagement_id == engagement_id,
                Assertion.status == "verified",
            )
        )
        or 0,
    }
