from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from ai_fde.models import AuditEvent, OutboxEvent


def record_audit(
    session: Session,
    *,
    engagement_id: UUID,
    actor_id: UUID,
    action: str,
    target_type: str,
    target_id: UUID,
    detail: dict[str, Any] | None = None,
    actor_type: str = "operator",
) -> AuditEvent:
    event = AuditEvent(
        engagement_id=engagement_id,
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail or {},
    )
    session.add(event)
    return event


def publish_domain_event(
    session: Session,
    *,
    engagement_id: UUID,
    event_type: str,
    aggregate_type: str,
    aggregate_id: UUID,
    payload: dict[str, Any] | None = None,
) -> OutboxEvent:
    event = OutboxEvent(
        engagement_id=engagement_id,
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload=payload or {},
    )
    session.add(event)
    return event
