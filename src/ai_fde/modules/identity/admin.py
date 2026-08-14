from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_fde.models import Engagement, EngagementMember, Operator


class WorkerProvisioningError(ValueError):
    pass


def provision_worker_identity(
    session: Session,
    *,
    operator_id: UUID,
    environment: str,
    display_name: str,
) -> Operator:
    subject = f"service:worker:{environment}"
    by_id = session.get(Operator, operator_id)
    by_subject = session.scalar(select(Operator).where(Operator.external_subject == subject))
    if by_id is not None and by_id.identity_kind != "service":
        raise WorkerProvisioningError("A human identity cannot be converted into a worker.")
    if by_id is not None and by_id.external_subject != subject:
        raise WorkerProvisioningError("The worker operator ID belongs to another identity.")
    if by_subject is not None and by_subject.id != operator_id:
        raise WorkerProvisioningError("The environment worker subject has another operator ID.")
    worker = by_id or by_subject
    if worker is None:
        worker = Operator(
            id=operator_id,
            external_subject=subject,
            display_name=display_name.strip() or "AI-FDE Worker",
            identity_kind="service",
            is_active=True,
        )
        session.add(worker)
        session.flush()
    else:
        worker.display_name = display_name.strip() or worker.display_name
        worker.is_active = True
    return worker


def grant_worker_engagement(
    session: Session,
    *,
    worker: Operator,
    engagement_id: UUID,
) -> EngagementMember:
    if worker.identity_kind != "service" or not worker.is_active:
        raise WorkerProvisioningError("The worker identity must be an active service identity.")
    if session.get(Engagement, engagement_id) is None:
        raise WorkerProvisioningError("The engagement does not exist.")
    membership = session.scalar(
        select(EngagementMember).where(
            EngagementMember.engagement_id == engagement_id,
            EngagementMember.operator_id == worker.id,
        )
    )
    if membership is None:
        membership = EngagementMember(
            engagement_id=engagement_id,
            operator_id=worker.id,
            role="operator",
        )
        session.add(membership)
        session.flush()
    elif membership.role == "owner":
        raise WorkerProvisioningError("A service identity cannot own an engagement.")
    else:
        membership.role = "operator"
    return membership


def deactivate_worker_identity(session: Session, *, operator_id: UUID) -> Operator:
    worker = session.get(Operator, operator_id)
    if worker is None or worker.identity_kind != "service":
        raise WorkerProvisioningError("The service worker identity does not exist.")
    worker.is_active = False
    return worker


def validate_worker_identity(session: Session, *, operator_id: UUID) -> Operator:
    worker = session.get(Operator, operator_id)
    if worker is None:
        raise WorkerProvisioningError("The configured worker identity is not provisioned.")
    if worker.identity_kind != "service":
        raise WorkerProvisioningError("The configured worker identity is not a service identity.")
    if not worker.is_active:
        raise WorkerProvisioningError("The configured worker identity is inactive.")
    return worker
