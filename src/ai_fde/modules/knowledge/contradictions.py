from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_fde.models import Contradiction, Operator
from ai_fde.modules.factory_engineer.service import stale_all_customer_models
from ai_fde.modules.shared import publish_domain_event, record_audit


class ContradictionNotFoundError(LookupError):
    pass


class ContradictionAlreadyResolvedError(ValueError):
    pass


RESOLUTION_STATUSES = {
    "accepted_exception": "accepted_exception",
    "not_a_conflict": "not_a_conflict",
    "superseded": "resolved",
    "override": "resolved",
}


def list_contradictions(session: Session, engagement_id: UUID) -> list[Contradiction]:
    return list(
        session.scalars(
            select(Contradiction)
            .where(Contradiction.engagement_id == engagement_id)
            .order_by(Contradiction.created_at.desc())
        )
    )


def resolve_contradiction(
    session: Session,
    *,
    engagement_id: UUID,
    contradiction_id: UUID,
    operator: Operator,
    resolution_type: str,
    reason: str,
) -> Contradiction:
    contradiction = session.scalar(
        select(Contradiction)
        .where(
            Contradiction.id == contradiction_id,
            Contradiction.engagement_id == engagement_id,
        )
        .with_for_update()
    )
    if contradiction is None:
        raise ContradictionNotFoundError(str(contradiction_id))
    if not contradiction.blocking:
        raise ContradictionAlreadyResolvedError("This contradiction is already resolved.")
    if resolution_type not in RESOLUTION_STATUSES:
        raise ValueError("Unsupported contradiction resolution.")

    clean_reason = reason.strip()
    if len(clean_reason) < 5:
        raise ValueError("A contradiction resolution requires a meaningful reason.")

    contradiction.resolution_type = resolution_type
    contradiction.resolution_reason = clean_reason
    contradiction.status = RESOLUTION_STATUSES[resolution_type]
    contradiction.blocking = False
    contradiction.resolved_by_id = operator.id
    contradiction.resolved_at = datetime.now(UTC)
    stale_all_customer_models(
        session,
        engagement_id=engagement_id,
        reason="A material contradiction resolution changed the verified customer truth basis.",
        actor_id=operator.id,
    )
    record_audit(
        session,
        engagement_id=engagement_id,
        actor_id=operator.id,
        action="contradiction.resolved",
        target_type="contradiction",
        target_id=contradiction.id,
        detail={"resolution_type": resolution_type, "reason": clean_reason},
    )
    publish_domain_event(
        session,
        engagement_id=engagement_id,
        event_type="contradiction.resolved",
        aggregate_type="contradiction",
        aggregate_id=contradiction.id,
        payload={"resolution_type": resolution_type},
    )
    session.flush()
    return contradiction
