from __future__ import annotations

from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_fde.models import Engagement, EngagementMember

EngagementPermission = Literal["read", "write"]
WRITE_ROLES = {"owner", "operator"}


class EngagementAccessNotFoundError(LookupError):
    """The engagement is not visible to this operator."""


class EngagementPermissionDeniedError(PermissionError):
    """The operator is a member but lacks the requested capability."""


def authorize_engagement(
    session: Session,
    *,
    engagement_id: UUID,
    operator_id: UUID,
    permission: EngagementPermission,
    sanitized_data_allowed: bool,
) -> EngagementMember:
    engagement = session.get(Engagement, engagement_id)
    if engagement is None:
        raise EngagementAccessNotFoundError(str(engagement_id))
    if engagement.data_classification == "sanitized" and not sanitized_data_allowed:
        raise EngagementPermissionDeniedError(
            "Sanitized engagements require production OIDC authentication."
        )

    membership = session.scalar(
        select(EngagementMember).where(
            EngagementMember.engagement_id == engagement_id,
            EngagementMember.operator_id == operator_id,
        )
    )
    if membership is None:
        raise EngagementAccessNotFoundError(str(engagement_id))
    if permission == "write" and membership.role not in WRITE_ROLES:
        raise EngagementPermissionDeniedError("This engagement membership is read-only.")
    return membership
