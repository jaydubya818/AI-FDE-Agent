from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from ai_fde.db import operator_session
from ai_fde.models import EngagementMember, Operator
from ai_fde.modules.engagements.service import create_engagement, list_engagements
from ai_fde.modules.identity.admin import (
    WorkerProvisioningError,
    deactivate_worker_identity,
    grant_worker_engagement,
    provision_worker_identity,
    validate_worker_identity,
)
from tests.conftest import OperatorFixture


@pytest.mark.isolation
def test_service_worker_sees_only_explicit_engagement_memberships(
    test_operator: OperatorFixture,
) -> None:
    worker_id = uuid.uuid4()
    with operator_session(test_operator.id) as session:
        owner = session.get_one(Operator, test_operator.id)
        assigned = create_engagement(
            session,
            operator=owner,
            name="Assigned Worker Engagement",
            workflow_name="Vendor onboarding",
            primary_outcome="Prove an explicitly assigned service identity boundary.",
        )
        create_engagement(
            session,
            operator=owner,
            name="Unassigned Worker Engagement",
            workflow_name="Contract review",
            primary_outcome="Remain invisible to the unrelated service identity.",
        )
        worker = provision_worker_identity(
            session,
            operator_id=worker_id,
            environment=f"test-{worker_id}",
            display_name="Acceptance Worker",
        )
        membership = grant_worker_engagement(session, worker=worker, engagement_id=assigned.id)
        assert membership.role == "operator"

    with operator_session(worker_id) as session:
        worker = validate_worker_identity(session, operator_id=worker_id)
        assert worker.identity_kind == "service"
        assert [item.id for item in list_engagements(session, worker_id)] == [assigned.id]


@pytest.mark.isolation
def test_worker_provisioning_rejects_human_owner_and_inactive_service(
    test_operator: OperatorFixture,
) -> None:
    worker_id = uuid.uuid4()
    with operator_session(test_operator.id) as session:
        owner = session.get_one(Operator, test_operator.id)
        engagement = create_engagement(
            session,
            operator=owner,
            name="Worker Boundary Engagement",
            workflow_name="Order review",
            primary_outcome="Keep service identities out of human approval authority.",
        )
        with pytest.raises(WorkerProvisioningError, match="human identity"):
            provision_worker_identity(
                session,
                operator_id=owner.id,
                environment=f"test-{worker_id}",
                display_name="Invalid Worker",
            )

        worker = provision_worker_identity(
            session,
            operator_id=worker_id,
            environment=f"test-{worker_id}",
            display_name="Boundary Worker",
        )
        membership = grant_worker_engagement(session, worker=worker, engagement_id=engagement.id)
        membership.role = "owner"
        session.flush()
        with pytest.raises(WorkerProvisioningError, match="cannot own"):
            grant_worker_engagement(session, worker=worker, engagement_id=engagement.id)

        queried_membership = session.scalar(
            select(EngagementMember).where(EngagementMember.operator_id == worker_id)
        )
        assert queried_membership is not None
        queried_membership.role = "operator"
        deactivate_worker_identity(session, operator_id=worker_id)
        with pytest.raises(WorkerProvisioningError, match="inactive"):
            validate_worker_identity(session, operator_id=worker_id)


@pytest.mark.isolation
def test_sanitized_engagement_requires_the_explicit_worker_readiness_flag(
    test_operator: OperatorFixture,
) -> None:
    worker_id = uuid.uuid4()
    with operator_session(test_operator.id) as session:
        owner = session.get_one(Operator, test_operator.id)
        engagement = create_engagement(
            session,
            operator=owner,
            name="Sanitized Worker Engagement",
            workflow_name="Customer onboarding",
            primary_outcome="Remain hidden from workers until deployment readiness passes.",
            data_classification="sanitized",
        )
        worker = provision_worker_identity(
            session,
            operator_id=worker_id,
            environment=f"test-{worker_id}",
            display_name="Sanitized Boundary Worker",
        )
        grant_worker_engagement(session, worker=worker, engagement_id=engagement.id)

    with operator_session(worker_id) as session:
        assert list_engagements(session, worker_id, include_sanitized=False) == []
        assert [
            item.id for item in list_engagements(session, worker_id, include_sanitized=True)
        ] == [engagement.id]
