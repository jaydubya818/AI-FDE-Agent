from __future__ import annotations

from uuid import UUID

from sqlalchemy import update
from sqlalchemy.orm import Session

from ai_fde.models import EconomicCase, ImplementationArtifact, WorkflowVersion
from ai_fde.modules.factory_engineer.service import (
    stale_all_after_current_workflow_change,
    stale_all_after_economic_change,
    stale_all_after_target_workflow_change,
    stale_all_customer_models,
    stale_all_packages_after_artifact_change,
)


def stale_after_model_change(
    session: Session, engagement_id: UUID, *, actor_id: UUID | None = None
) -> None:
    session.execute(
        update(WorkflowVersion)
        .where(
            WorkflowVersion.engagement_id == engagement_id,
            WorkflowVersion.status.in_(["draft", "approved"]),
        )
        .values(status="stale")
    )
    _stale_economics_and_artifacts(session, engagement_id, actor_id=actor_id)
    stale_all_customer_models(
        session,
        engagement_id=engagement_id,
        reason="Verified customer truth changed; regenerate and reapprove the customer model.",
        actor_id=actor_id,
    )


def stale_after_current_workflow_change(
    session: Session, engagement_id: UUID, *, actor_id: UUID | None = None
) -> None:
    session.execute(
        update(WorkflowVersion)
        .where(
            WorkflowVersion.engagement_id == engagement_id,
            WorkflowVersion.workflow_kind == "target",
            WorkflowVersion.status.in_(["draft", "approved"]),
        )
        .values(status="stale")
    )
    _stale_economics_and_artifacts(session, engagement_id, actor_id=actor_id)
    stale_all_after_current_workflow_change(
        session,
        engagement_id=engagement_id,
        reason="The approved current workflow changed.",
        actor_id=actor_id,
    )


def stale_after_target_workflow_change(
    session: Session, engagement_id: UUID, *, actor_id: UUID | None = None
) -> None:
    _stale_economics_and_artifacts(session, engagement_id, actor_id=actor_id)
    stale_all_after_target_workflow_change(
        session,
        engagement_id=engagement_id,
        reason="The approved target workflow changed.",
        actor_id=actor_id,
    )


def stale_after_economic_change(
    session: Session, engagement_id: UUID, *, actor_id: UUID | None = None
) -> None:
    session.execute(
        update(ImplementationArtifact)
        .where(
            ImplementationArtifact.engagement_id == engagement_id,
            ImplementationArtifact.status == "current",
        )
        .values(status="stale")
    )
    stale_all_after_economic_change(
        session,
        engagement_id=engagement_id,
        reason="The approved economic case changed.",
        actor_id=actor_id,
    )


def stale_after_artifact_change(
    session: Session, engagement_id: UUID, *, actor_id: UUID | None = None
) -> None:
    stale_all_packages_after_artifact_change(
        session,
        engagement_id=engagement_id,
        reason="An implementation artifact version changed.",
        actor_id=actor_id,
    )


def _stale_economics_and_artifacts(
    session: Session, engagement_id: UUID, *, actor_id: UUID | None = None
) -> None:
    session.execute(
        update(EconomicCase)
        .where(
            EconomicCase.engagement_id == engagement_id,
            EconomicCase.status.in_(["draft", "approved"]),
        )
        .values(status="stale")
    )
    stale_after_economic_change(session, engagement_id, actor_id=actor_id)
