from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from ai_fde.adapters.storage import InMemoryEvidenceStore
from ai_fde.api.dependencies import AuthenticatedPrincipal, get_principal
from ai_fde.api.routes import router
from ai_fde.db import SessionFactory, apply_operator_context, operator_session
from ai_fde.models import EngagementMember, EvidenceAsset, Operator
from ai_fde.modules.engagements.service import create_engagement
from ai_fde.modules.identity.service import (
    EngagementAccessNotFoundError,
    EngagementPermissionDeniedError,
    authorize_engagement,
)
from tests.conftest import OperatorFixture


def _create_operator(label: str) -> OperatorFixture:
    operator_id = uuid.uuid4()
    fixture = OperatorFixture(
        operator_id,
        f"{label}-{operator_id}",
        f"{label.title()} FDE",
    )
    session = SessionFactory()
    try:
        with session.begin():
            apply_operator_context(session, operator_id)
            session.add(
                Operator(
                    id=fixture.id,
                    external_subject=fixture.subject,
                    display_name=fixture.display_name,
                )
            )
    finally:
        session.close()
    return fixture


def _test_app(principal: AuthenticatedPrincipal) -> FastAPI:
    app = FastAPI()
    app.state.evidence_store = InMemoryEvidenceStore()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_principal] = lambda: principal
    return app


@pytest.mark.integration
@pytest.mark.isolation
def test_viewer_can_read_but_cannot_mutate_engagement(
    postgres_available: None,
) -> None:
    owner = _create_operator("owner")
    operator_member = _create_operator("operator")
    viewer = _create_operator("viewer")

    with operator_session(owner.id) as session:
        owner_record = session.get_one(Operator, owner.id)
        engagement = create_engagement(
            session,
            operator=owner_record,
            name="Role Boundary Manufacturing",
            primary_outcome="Prove viewer access remains read-only.",
        )
        engagement_id = engagement.id
        session.add(
            EngagementMember(
                engagement_id=engagement_id,
                operator_id=viewer.id,
                role="viewer",
            )
        )
        session.add(
            EngagementMember(
                engagement_id=engagement_id,
                operator_id=operator_member.id,
                role="operator",
            )
        )

    with operator_session(operator_member.id) as session:
        membership = authorize_engagement(
            session,
            engagement_id=engagement_id,
            operator_id=operator_member.id,
            permission="write",
            sanitized_data_allowed=False,
        )
        assert membership.role == "operator"

    with operator_session(viewer.id) as session:
        membership = authorize_engagement(
            session,
            engagement_id=engagement_id,
            operator_id=viewer.id,
            permission="read",
            sanitized_data_allowed=False,
        )
        assert membership.role == "viewer"
        with pytest.raises(EngagementPermissionDeniedError):
            authorize_engagement(
                session,
                engagement_id=engagement_id,
                operator_id=viewer.id,
                permission="write",
                sanitized_data_allowed=False,
            )

    app = _test_app(
        AuthenticatedPrincipal(
            operator_id=viewer.id,
            auth_mode="development",
            sanitized_data_allowed=False,
        )
    )
    with TestClient(app) as client:
        assert client.get(f"/api/engagements/{engagement_id}").status_code == 200
        denied = client.post(
            f"/api/engagements/{engagement_id}/notes",
            json={"title": "Unauthorized", "content": "A viewer must not create evidence."},
        )
        assert denied.status_code == 403
        assert denied.json() == {"detail": "This engagement membership is read-only."}
        assessment_denied = client.post(
            f"/api/engagements/{engagement_id}/assessments",
            json={
                "delivery_method": "conventional",
                "perspective": "operator",
                "outcome": "blocked",
                "duration_minutes": 30,
                "usefulness_score": 2,
                "clarification_count": 1,
                "rework_count": 0,
                "workaround_count": 0,
                "trust_failure_count": 1,
            },
        )
        assert assessment_denied.status_code == 403
        assert assessment_denied.json() == {"detail": "This engagement membership is read-only."}

    with operator_session(owner.id) as session:
        evidence_count = session.scalar(
            select(func.count())
            .select_from(EvidenceAsset)
            .where(EvidenceAsset.engagement_id == engagement_id)
        )
        assert evidence_count == 0


@pytest.mark.integration
@pytest.mark.isolation
def test_non_member_gets_not_found_without_engagement_disclosure(
    postgres_available: None,
) -> None:
    owner = _create_operator("owner")
    outsider = _create_operator("outsider")

    with operator_session(owner.id) as session:
        engagement = create_engagement(
            session,
            operator=session.get_one(Operator, owner.id),
            name="Hidden Manufacturing",
            primary_outcome="Do not disclose this engagement to non-members.",
        )
        engagement_id = engagement.id

    with (
        operator_session(outsider.id) as session,
        pytest.raises(EngagementAccessNotFoundError),
    ):
        authorize_engagement(
            session,
            engagement_id=engagement_id,
            operator_id=outsider.id,
            permission="read",
            sanitized_data_allowed=False,
        )

    app = _test_app(
        AuthenticatedPrincipal(
            operator_id=outsider.id,
            auth_mode="development",
            sanitized_data_allowed=False,
        )
    )
    with TestClient(app) as client:
        response = client.get(f"/api/engagements/{engagement_id}")
        assert response.status_code == 404
        assert response.json() == {"detail": "Engagement not found."}


@pytest.mark.integration
@pytest.mark.isolation
def test_development_identity_cannot_access_sanitized_engagement(
    postgres_available: None,
) -> None:
    owner = _create_operator("owner")
    with operator_session(owner.id) as session:
        engagement = create_engagement(
            session,
            operator=session.get_one(Operator, owner.id),
            name="Sanitized Manufacturing",
            primary_outcome="Require production authentication for sanitized data.",
            data_classification="sanitized",
        )
        engagement_id = engagement.id

    app = _test_app(
        AuthenticatedPrincipal(
            operator_id=owner.id,
            auth_mode="development",
            sanitized_data_allowed=False,
        )
    )
    with TestClient(app) as client:
        listed = client.get("/api/engagements")
        assert listed.status_code == 200
        assert listed.json() == []
        denied = client.get(f"/api/engagements/{engagement_id}")
        assert denied.status_code == 403
        assert denied.json() == {
            "detail": "Sanitized engagements require production OIDC authentication."
        }
        creation_denied = client.post(
            "/api/engagements",
            json={
                "name": "Another Sanitized Company",
                "primary_outcome": "Do not create sanitized state with development identity.",
                "data_classification": "sanitized",
            },
        )
        assert creation_denied.status_code == 403

    with operator_session(owner.id) as session:
        membership = authorize_engagement(
            session,
            engagement_id=engagement_id,
            operator_id=owner.id,
            permission="write",
            sanitized_data_allowed=True,
        )
        assert membership.role == "owner"
