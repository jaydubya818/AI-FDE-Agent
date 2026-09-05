from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ai_fde.models import Job
from ai_fde.modules.runtime.models import RuntimeHeartbeat


def record_worker_heartbeat(
    session: Session,
    *,
    instance_id: str,
    release_revision: str,
    deployment_id: str,
    deployment_validation_id: str | None,
    qualification_mode: str,
    operator_id: UUID | None,
    engagement_id: UUID | None,
    status: str,
    last_job_completed_at: datetime | None,
    last_failure_code: str | None,
) -> RuntimeHeartbeat:
    """Upsert metadata while PostgreSQL supplies the authoritative seen time."""

    queue_depth, oldest_queued_at = session.execute(
        select(func.count(Job.id), func.min(Job.created_at)).where(Job.status == "queued")
    ).one()
    heartbeat = session.scalar(
        select(RuntimeHeartbeat)
        .where(
            RuntimeHeartbeat.service == "ai-fde-worker",
            RuntimeHeartbeat.instance_id == instance_id,
        )
        .with_for_update()
    )
    if heartbeat is None:
        heartbeat = RuntimeHeartbeat(
            service="ai-fde-worker",
            instance_id=instance_id,
            release_revision=release_revision,
            deployment_id=deployment_id,
            deployment_validation_id=deployment_validation_id,
            qualification_mode=qualification_mode,
            operator_id=operator_id,
            engagement_id=engagement_id,
            status=status,
            queue_depth=int(queue_depth),
            oldest_queued_at=oldest_queued_at,
            last_job_completed_at=last_job_completed_at,
            last_failure_code=last_failure_code,
        )
        session.add(heartbeat)
    else:
        heartbeat.release_revision = release_revision
        heartbeat.deployment_id = deployment_id
        heartbeat.deployment_validation_id = deployment_validation_id
        heartbeat.qualification_mode = qualification_mode
        heartbeat.operator_id = operator_id
        heartbeat.engagement_id = engagement_id
        heartbeat.status = status
        heartbeat.queue_depth = int(queue_depth)
        heartbeat.oldest_queued_at = oldest_queued_at
        heartbeat.last_job_completed_at = last_job_completed_at
        heartbeat.last_failure_code = last_failure_code
    session.flush()
    session.refresh(heartbeat, attribute_names=["last_seen_at"])
    return heartbeat
