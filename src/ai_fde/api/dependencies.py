from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ai_fde.adapters.storage import EvidenceStore
from ai_fde.config import Settings, get_settings
from ai_fde.db import operator_session
from ai_fde.models import EngagementMember, Operator
from ai_fde.modules.identity.service import (
    EngagementAccessNotFoundError,
    EngagementPermission,
    EngagementPermissionDeniedError,
    authorize_engagement,
)


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    operator_id: UUID
    auth_mode: str
    sanitized_data_allowed: bool


def get_principal(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthenticatedPrincipal:
    if settings.auth_mode == "development":
        return AuthenticatedPrincipal(
            operator_id=settings.operator_id,
            auth_mode="development",
            sanitized_data_allowed=False,
        )
    raise HTTPException(
        status_code=503,
        detail="OIDC authentication is configured but its provider adapter is not active.",
    )


def get_session(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_principal)],
) -> Iterator[Session]:
    with operator_session(principal.operator_id) as session:
        yield session


def get_operator(
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_principal)],
) -> Operator:
    operator = session.get(Operator, principal.operator_id)
    if operator is None:
        raise HTTPException(status_code=401, detail="The authenticated operator is not active.")
    return operator


def require_engagement_read(
    engagement_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_principal)],
) -> EngagementMember:
    return _authorize_engagement(session, engagement_id, principal, "read")


def require_engagement_write(
    engagement_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_principal)],
) -> EngagementMember:
    return _authorize_engagement(session, engagement_id, principal, "write")


def _authorize_engagement(
    session: Session,
    engagement_id: UUID,
    principal: AuthenticatedPrincipal,
    permission: EngagementPermission,
) -> EngagementMember:
    try:
        return authorize_engagement(
            session,
            engagement_id=engagement_id,
            operator_id=principal.operator_id,
            permission=permission,
            sanitized_data_allowed=principal.sanitized_data_allowed,
        )
    except EngagementAccessNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Engagement not found.") from exc
    except EngagementPermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def get_evidence_store(request: Request) -> EvidenceStore:
    store: EvidenceStore = request.app.state.evidence_store
    return store


SessionDependency = Annotated[Session, Depends(get_session)]
OperatorDependency = Annotated[Operator, Depends(get_operator)]
PrincipalDependency = Annotated[AuthenticatedPrincipal, Depends(get_principal)]
EngagementReadDependency = Annotated[EngagementMember, Depends(require_engagement_read)]
EngagementWriteDependency = Annotated[EngagementMember, Depends(require_engagement_write)]
EvidenceStoreDependency = Annotated[EvidenceStore, Depends(get_evidence_store)]
