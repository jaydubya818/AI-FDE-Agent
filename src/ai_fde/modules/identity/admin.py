from __future__ import annotations

from uuid import UUID

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from ai_fde.models import Engagement, EngagementMember, Operator, WorkerOperatorBinding
from ai_fde.modules.identity.database import (
    WORKER_DATABASE_GROUP,
    is_worker_database_user,
    worker_database_user_for_release,
)


class WorkerProvisioningError(ValueError):
    pass


def validate_worker_runtime_authority(
    session: Session,
    *,
    operator_id: UUID,
    engagement_id: UUID,
    release_revision: str,
    deployment_id: str,
    deployment_validation_id: str | None,
) -> None:
    """Prove the worker's database login and exact deployment authority."""

    session_role, current_role = session.execute(text("SELECT session_user, current_user")).one()
    expected_database_user = worker_database_user_for_release(deployment_id, release_revision)
    if session_role != expected_database_user or current_role != expected_database_user:
        raise WorkerProvisioningError(
            "The worker runtime must connect directly as its release-scoped database login."
        )

    authorized = session.scalar(
        text(
            "SELECT ai_fde_worker_runtime_authorized("
            "CAST(:operator_id AS uuid), CAST(:engagement_id AS uuid), "
            ":release_revision, :deployment_id, :deployment_validation_id)"
        ),
        {
            "operator_id": str(operator_id),
            "engagement_id": str(engagement_id),
            "release_revision": release_revision,
            "deployment_id": deployment_id,
            "deployment_validation_id": deployment_validation_id,
        },
    )
    if authorized is not True:
        raise WorkerProvisioningError(
            "The worker runtime is not authorized for the configured deployment identity."
        )


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


def bind_worker_database_role(
    session: Session,
    *,
    worker: Operator,
    release_revision: str,
    deployment_id: str,
    deployment_validation_id: str | None,
    engagement_id: UUID | None = None,
    database_role: str | None = None,
) -> WorkerOperatorBinding:
    """Rotate the least-privilege login binding to this exact deployment identity."""

    expected_database_role = worker_database_user_for_release(deployment_id, release_revision)
    database_role = database_role or expected_database_role
    if (
        not is_worker_database_user(database_role)
        or database_role != expected_database_role
    ):
        raise WorkerProvisioningError(
            "Only the exact release-scoped worker database login can be bound."
        )
    if worker.identity_kind != "service" or not worker.is_active:
        raise WorkerProvisioningError("The worker identity must be an active service identity.")
    if engagement_id is not None:
        membership = session.scalar(
            select(EngagementMember).where(
                EngagementMember.engagement_id == engagement_id,
                EngagementMember.operator_id == worker.id,
                EngagementMember.role == "operator",
            )
        )
        if membership is None:
            raise WorkerProvisioningError(
                "The database-bound worker needs operator membership in the engagement."
            )
    binding_conflict = or_(
        WorkerOperatorBinding.database_role == database_role,
        WorkerOperatorBinding.operator_id == worker.id,
    )
    if engagement_id is not None:
        binding_conflict = or_(
            binding_conflict,
            WorkerOperatorBinding.engagement_id == engagement_id,
        )
    candidate_bindings = list(
        session.scalars(
            select(WorkerOperatorBinding)
            .where(binding_conflict)
            .with_for_update()
        )
    )
    binding = next(
        (item for item in candidate_bindings if item.database_role == database_role),
        None,
    )
    for previous_binding in candidate_bindings:
        if previous_binding is binding:
            continue
        if previous_binding.operator_id != worker.id:
            raise WorkerProvisioningError(
                "The engagement is already bound to another qualified worker identity."
            )
        session.delete(previous_binding)
    if any(item is not binding for item in candidate_bindings):
        session.flush()
    if binding is None:
        binding = WorkerOperatorBinding(
            database_role=database_role,
            operator_id=worker.id,
            engagement_id=engagement_id,
            release_revision=release_revision,
            deployment_id=deployment_id,
            deployment_validation_id=deployment_validation_id,
        )
        session.add(binding)
    else:
        if binding.operator_id != worker.id:
            raise WorkerProvisioningError(
                "The database role is already bound to a qualified worker identity."
            )
        if (
            engagement_id is not None
            and binding.engagement_id is not None
            and binding.engagement_id != engagement_id
        ):
            raise WorkerProvisioningError(
                "The database role is already bound to another engagement."
            )
        binding.operator_id = worker.id
        binding.engagement_id = engagement_id
        binding.release_revision = release_revision
        binding.deployment_id = deployment_id
        binding.deployment_validation_id = deployment_validation_id
    session.flush()
    return binding


__all__ = [
    "WORKER_DATABASE_GROUP",
    "WorkerProvisioningError",
    "bind_worker_database_role",
    "deactivate_worker_identity",
    "grant_worker_engagement",
    "provision_worker_identity",
    "validate_worker_identity",
    "validate_worker_runtime_authority",
]
