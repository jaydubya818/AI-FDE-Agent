from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ai_fde.db import operator_session
from ai_fde.models import Operator
from ai_fde.modules.engagements.service import create_engagement
from ai_fde.modules.factory_engineer.models import PackageRetrievalGrant
from ai_fde.modules.factory_engineer.retrieval import (
    MAX_RETRIEVAL_GRANT_TTL,
    authenticate_retrieval_token,
    issue_retrieval_grant,
    provision_retrieval_service_identity,
    rotate_retrieval_grant,
)
from tests.conftest import OperatorFixture


@pytest.mark.integration
def test_rotation_revokes_the_prior_retrieval_token(
    postgres_available: None,
    test_operator: OperatorFixture,
) -> None:
    timestamp = datetime.now(UTC)
    with operator_session(test_operator.id) as session:
        owner = session.get_one(Operator, test_operator.id)
        engagement = create_engagement(
            session,
            operator=owner,
            name=f"Retrieval rotation {test_operator.id}",
            workflow_name="Mission Control package retrieval",
            primary_outcome="Rotate one service credential without browser exposure.",
        )
        service_operator = provision_retrieval_service_identity(
            session,
            engagement_id=engagement.id,
            created_by=owner,
        )
        first = rotate_retrieval_grant(
            session,
            engagement_id=engagement.id,
            service_operator=service_operator,
            created_by=owner,
            requester_identity="mission-control:production",
            requester_system="mission-control",
            expires_at=timestamp + timedelta(days=1),
            now=timestamp,
        )
        engagement_id = engagement.id
        service_operator_id = service_operator.id
        first_token = first.token
        first_grant_id = first.grant.id

    with operator_session(test_operator.id) as session:
        owner = session.get_one(Operator, test_operator.id)
        service_operator = session.get_one(Operator, service_operator_id)
        with pytest.raises(ValueError, match="cannot exceed 24 hours"):
            rotate_retrieval_grant(
                session,
                engagement_id=engagement_id,
                service_operator=service_operator,
                created_by=owner,
                requester_identity="mission-control:production",
                requester_system="mission-control",
                expires_at=(
                    timestamp
                    + timedelta(seconds=1)
                    + MAX_RETRIEVAL_GRANT_TTL
                    + timedelta(microseconds=1)
                ),
                now=timestamp + timedelta(seconds=1),
            )
        assert session.get_one(PackageRetrievalGrant, first_grant_id).revoked_at is None
        replacement = rotate_retrieval_grant(
            session,
            engagement_id=engagement_id,
            service_operator=service_operator,
            created_by=owner,
            requester_identity="mission-control:production",
            requester_system="mission-control",
            expires_at=timestamp + timedelta(days=1),
            now=timestamp + timedelta(seconds=1),
        )
        replacement_token = replacement.token
        replacement_grant_id = replacement.grant.id

    with operator_session(service_operator_id) as session:
        old_decision = authenticate_retrieval_token(
            session,
            token=first_token,
            now=timestamp + timedelta(seconds=2),
        )
        replacement_decision = authenticate_retrieval_token(
            session,
            token=replacement_token,
            now=timestamp + timedelta(seconds=2),
        )

    assert first_grant_id != replacement_grant_id
    assert old_decision.authenticated is False
    assert old_decision.result == "REVOKED_TOKEN"
    assert replacement_decision.authenticated is True
    assert replacement_decision.result == "AUTHENTICATED"


@pytest.mark.integration
def test_issue_retrieval_grant_accepts_the_boundary_and_rejects_invalid_expiry(
    postgres_available: None,
    test_operator: OperatorFixture,
) -> None:
    timestamp = datetime.now(UTC)
    with operator_session(test_operator.id) as session:
        owner = session.get_one(Operator, test_operator.id)
        engagement = create_engagement(
            session,
            operator=owner,
            name=f"Retrieval expiry {test_operator.id}",
            workflow_name="Mission Control package retrieval",
            primary_outcome="Enforce a short-lived service credential.",
        )
        service_operator = provision_retrieval_service_identity(
            session,
            engagement_id=engagement.id,
            created_by=owner,
        )

        boundary = issue_retrieval_grant(
            session,
            engagement_id=engagement.id,
            service_operator=service_operator,
            created_by=owner,
            requester_identity="mission-control:production",
            requester_system="mission-control",
            expires_at=timestamp + MAX_RETRIEVAL_GRANT_TTL,
            now=timestamp,
        )
        assert boundary.grant.expires_at == timestamp + MAX_RETRIEVAL_GRANT_TTL

        with pytest.raises(ValueError, match="must include a timezone"):
            issue_retrieval_grant(
                session,
                engagement_id=engagement.id,
                service_operator=service_operator,
                created_by=owner,
                requester_identity="mission-control:production",
                requester_system="mission-control",
                expires_at=(timestamp + timedelta(hours=1)).replace(tzinfo=None),
                now=timestamp,
            )

        with pytest.raises(ValueError, match="cannot exceed 24 hours"):
            issue_retrieval_grant(
                session,
                engagement_id=engagement.id,
                service_operator=service_operator,
                created_by=owner,
                requester_identity="mission-control:production",
                requester_system="mission-control",
                expires_at=(
                    timestamp
                    + MAX_RETRIEVAL_GRANT_TTL
                    + timedelta(microseconds=1)
                ),
                now=timestamp,
            )
