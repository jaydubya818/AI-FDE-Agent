from __future__ import annotations

from uuid import UUID

from sqlalchemy import update
from sqlalchemy.orm import Session

from ai_fde.models import EconomicCase, ImplementationArtifact, WorkflowVersion


def stale_after_model_change(session: Session, engagement_id: UUID) -> None:
    session.execute(
        update(WorkflowVersion)
        .where(
            WorkflowVersion.engagement_id == engagement_id,
            WorkflowVersion.status.in_(["draft", "approved"]),
        )
        .values(status="stale")
    )
    _stale_economics_and_artifacts(session, engagement_id)


def stale_after_current_workflow_change(session: Session, engagement_id: UUID) -> None:
    session.execute(
        update(WorkflowVersion)
        .where(
            WorkflowVersion.engagement_id == engagement_id,
            WorkflowVersion.workflow_kind == "target",
            WorkflowVersion.status.in_(["draft", "approved"]),
        )
        .values(status="stale")
    )
    _stale_economics_and_artifacts(session, engagement_id)


def stale_after_target_workflow_change(session: Session, engagement_id: UUID) -> None:
    _stale_economics_and_artifacts(session, engagement_id)


def stale_after_economic_change(session: Session, engagement_id: UUID) -> None:
    session.execute(
        update(ImplementationArtifact)
        .where(
            ImplementationArtifact.engagement_id == engagement_id,
            ImplementationArtifact.status == "current",
        )
        .values(status="stale")
    )


def _stale_economics_and_artifacts(session: Session, engagement_id: UUID) -> None:
    session.execute(
        update(EconomicCase)
        .where(
            EconomicCase.engagement_id == engagement_id,
            EconomicCase.status.in_(["draft", "approved"]),
        )
        .values(status="stale")
    )
    stale_after_economic_change(session, engagement_id)
