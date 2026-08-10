from __future__ import annotations

import uuid
from io import BytesIO
from zipfile import ZipFile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_fde.adapters.storage import InMemoryEvidenceStore
from ai_fde.api.dependencies import AuthenticatedPrincipal, get_principal
from ai_fde.api.routes import router
from ai_fde.db import SessionFactory, apply_operator_context, operator_session
from ai_fde.models import EngagementDeletionReceipt, EngagementMember, Operator
from ai_fde.modules.engagements.service import create_engagement
from ai_fde.modules.evidence.service import create_evidence_asset
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


def _app(principal: AuthenticatedPrincipal, store: InMemoryEvidenceStore) -> FastAPI:
    app = FastAPI()
    app.state.evidence_store = store
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_principal] = lambda: principal
    return app


def _principal(operator: OperatorFixture) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        operator_id=operator.id,
        auth_mode="development",
        sanitized_data_allowed=False,
    )


@pytest.mark.integration
@pytest.mark.isolation
def test_data_lifecycle_routes_are_owner_only_and_delete_without_cross_tenant_receipt_access(
    postgres_available: None,
) -> None:
    owner = _create_operator("lifecycle-owner")
    viewer = _create_operator("lifecycle-viewer")
    outsider = _create_operator("lifecycle-outsider")
    store = InMemoryEvidenceStore()

    with operator_session(owner.id) as session:
        owner_record = session.get_one(Operator, owner.id)
        engagement = create_engagement(
            session,
            operator=owner_record,
            name="Lifecycle Route Manufacturing",
            primary_outcome="Prove owner-only export and deletion routes.",
        )
        engagement_id = engagement.id
        session.add(
            EngagementMember(
                engagement_id=engagement_id,
                operator_id=viewer.id,
                role="viewer",
            )
        )
        create_evidence_asset(
            session,
            store,
            engagement_id=engagement_id,
            operator=owner_record,
            file_name="policy.md",
            content_type="text/markdown",
            content=b"Policy evidence retained for the portability export.",
        )

    with TestClient(_app(_principal(viewer), store)) as client:
        lifecycle = client.get(f"/api/engagements/{engagement_id}/data-lifecycle")
        assert lifecycle.status_code == 200
        assert lifecycle.json()["membership_role"] == "viewer"
        denied = client.post(f"/api/engagements/{engagement_id}/data-lifecycle/exports")
        assert denied.status_code == 403
        assert denied.json() == {"detail": "Only the engagement owner can manage its data."}

    with TestClient(_app(_principal(outsider), store)) as client:
        hidden = client.post(f"/api/engagements/{engagement_id}/data-lifecycle/exports")
        assert hidden.status_code == 404

    with TestClient(_app(_principal(owner), store)) as client:
        before = client.get(f"/api/engagements/{engagement_id}/data-lifecycle")
        assert before.status_code == 200
        assert before.json()["can_delete"] is False

        exported = client.post(f"/api/engagements/{engagement_id}/data-lifecycle/exports")
        assert exported.status_code == 200
        export_id = exported.headers["x-ai-fde-export-id"]
        assert exported.headers["content-type"] == "application/zip"
        with ZipFile(BytesIO(exported.content)) as archive:
            assert "records.json" in archive.namelist()

        ready = client.get(f"/api/engagements/{engagement_id}/data-lifecycle")
        assert ready.status_code == 200
        assert ready.json()["export_current"] is True
        assert ready.json()["can_delete"] is True

        deleted = client.post(
            f"/api/engagements/{engagement_id}/data-lifecycle/deletion",
            json={
                "export_id": export_id,
                "confirmation_name": "Lifecycle Route Manufacturing",
            },
        )
        assert deleted.status_code == 200
        receipt_id = uuid.UUID(deleted.json()["id"])
        assert deleted.json()["status"] == "completed"
        assert client.get(f"/api/engagements/{engagement_id}").status_code == 404

    with operator_session(outsider.id) as session:
        assert session.get(EngagementDeletionReceipt, receipt_id) is None
    with operator_session(owner.id) as session:
        assert session.get_one(EngagementDeletionReceipt, receipt_id).status == "completed"
