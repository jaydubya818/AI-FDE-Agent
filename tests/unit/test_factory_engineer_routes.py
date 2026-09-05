from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import ai_fde.api.factory_engineer_routes as routes
from ai_fde.api.factory_engineer_schemas import RetrievalGrantCreateRequest
from ai_fde.config import Settings, get_settings
from ai_fde.models import EngagementMember, Operator
from ai_fde.modules.design_partner.service import DesignPartnerQualificationError
from ai_fde.modules.factory_engineer.retrieval import (
    AuthenticatedRetrievalPrincipal,
    RetrievalAuthenticationDecision,
    RetrievalTokenSubject,
)
from ai_fde.modules.factory_engineer.schemas import (
    ImmutableVersionReference,
    ProvenanceKind,
    PublishedPackageEnvelope,
    RetrievalDecision,
    SourceReference,
)

FIXTURE = (
    Path(__file__).resolve().parents[2] / "fixtures/contracts/factory-deployment-package-v1.json"
)
CORRELATION_ID = UUID("90000000-0000-4000-8000-000000000001")
OPERATOR_ID = UUID("90000000-0000-4000-8000-000000000002")
GRANT_ID = UUID("90000000-0000-4000-8000-000000000003")
ENGAGEMENT_ID = UUID("90000000-0000-4000-8000-000000000004")


def _app(settings: object | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    if settings is not None:
        app.dependency_overrides[get_settings] = lambda: settings
    return app


def _envelope() -> PublishedPackageEnvelope:
    package = json.loads(FIXTURE.read_text())
    return PublishedPackageEnvelope.model_validate(
        {
            "package": package,
            "attestation": {
                "package_id": package["package_id"],
                "package_version": package["package_version"],
                "digest": package["integrity"]["digest"],
                "current_status": "PUBLISHED",
                "issuer": package["issuer"],
                "approval": package["approval"],
                "published_at": "2026-09-04T16:00:01Z",
                "retrieved_at": "2026-09-04T16:00:02Z",
                "correlation_id": str(CORRELATION_ID),
            },
        }
    )


def _install_authenticated_retrieval(monkeypatch: object) -> None:
    principal = AuthenticatedRetrievalPrincipal(
        operator_id=OPERATOR_ID,
        grant_id=GRANT_ID,
        engagement_id=ENGAGEMENT_ID,
        requester_identity="mission-control-test",
        requester_system="MISSION_CONTROL",
    )
    monkeypatch.setattr(  # type: ignore[attr-defined]
        routes,
        "parse_retrieval_token_subject",
        lambda _token: RetrievalTokenSubject(OPERATOR_ID, GRANT_ID),
    )
    monkeypatch.setattr(  # type: ignore[attr-defined]
        routes,
        "operator_session",
        lambda _operator_id: nullcontext(object()),
    )
    monkeypatch.setattr(  # type: ignore[attr-defined]
        routes,
        "authenticate_retrieval_token",
        lambda _session, *, token: RetrievalAuthenticationDecision(
            authenticated=True,
            result="AUTHENTICATED",
            principal=principal,
        ),
    )


def test_retrieval_route_requires_bearer_authentication() -> None:
    with TestClient(_app()) as client:
        response = client.get(
            "/api/deployment-packages/10000000-0000-4000-8000-000000000001/versions/1",
            headers={"X-Correlation-ID": str(CORRELATION_ID)},
        )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["x-correlation-id"] == str(CORRELATION_ID)
    assert response.json() == {
        "error": {
            "code": "AUTHENTICATION_REQUIRED",
            "message": "A valid package-retrieval bearer credential is required.",
            "correlation_id": str(CORRELATION_ID),
        }
    }


def test_retrieval_route_returns_exact_versioned_media_type(
    monkeypatch: object,
) -> None:
    _install_authenticated_retrieval(monkeypatch)
    envelope = _envelope()
    monkeypatch.setattr(  # type: ignore[attr-defined]
        routes,
        "retrieve_published_package",
        lambda _session, **_kwargs: RetrievalDecision(
            allowed=True,
            result="RETRIEVED",
            correlation_id=CORRELATION_ID,
            package=envelope,
        ),
    )

    with TestClient(_app()) as client:
        response = client.get(
            "/api/deployment-packages/10000000-0000-4000-8000-000000000001/versions/1",
            headers={
                "Authorization": "Bearer fdp1.test",
                "X-Correlation-ID": str(CORRELATION_ID),
            },
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == routes.PACKAGE_MEDIA_TYPE
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == envelope.model_dump(mode="json")


def test_retrieval_route_preserves_bounded_revoked_failure(
    monkeypatch: object,
) -> None:
    _install_authenticated_retrieval(monkeypatch)
    monkeypatch.setattr(  # type: ignore[attr-defined]
        routes,
        "retrieve_published_package",
        lambda _session, **_kwargs: RetrievalDecision(
            allowed=False,
            result="DENIED_REVOKED",
            correlation_id=CORRELATION_ID,
        ),
    )

    with TestClient(_app()) as client:
        response = client.get(
            "/api/deployment-packages/10000000-0000-4000-8000-000000000001/versions/1",
            headers={
                "Authorization": "Bearer fdp1.test",
                "X-Correlation-ID": str(CORRELATION_ID),
            },
        )

    assert response.status_code == 410
    assert response.json() == {
        "error": {
            "code": "PACKAGE_REVOKED",
            "message": "The package version is revoked.",
            "correlation_id": str(CORRELATION_ID),
        }
    }


def test_retrieval_route_withdraws_package_without_content_when_qualification_is_invalid(
    monkeypatch: object,
) -> None:
    _install_authenticated_retrieval(monkeypatch)
    monkeypatch.setattr(  # type: ignore[attr-defined]
        routes,
        "retrieve_published_package",
        lambda _session, **_kwargs: RetrievalDecision(
            allowed=False,
            result="DENIED_QUALIFICATION",
            correlation_id=CORRELATION_ID,
        ),
    )

    with TestClient(_app()) as client:
        response = client.get(
            "/api/deployment-packages/10000000-0000-4000-8000-000000000001/versions/1",
            headers={
                "Authorization": "Bearer fdp1.test",
                "X-Correlation-ID": str(CORRELATION_ID),
            },
        )

    assert response.status_code == 410
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "error": {
            "code": "PACKAGE_QUALIFICATION_WITHDRAWN",
            "message": ("The package version is outside the current design-partner qualification."),
            "correlation_id": str(CORRELATION_ID),
        }
    }
    assert "package" not in response.json()


def test_retrieval_route_wires_exact_time_runtime_qualification_and_returns_no_content(
    monkeypatch: object,
) -> None:
    _install_authenticated_retrieval(monkeypatch)
    expires_at = datetime(2026, 9, 4, 20, 0, tzinfo=UTC)
    runtime_checks: list[datetime] = []

    class _ExpiredRuntimeSettings:
        sanitized_data_enabled = True

        def verified_deployment_qualification(self, *, now: datetime) -> None:
            runtime_checks.append(now)
            raise ValueError("expired")

    def retrieve_with_runtime_check(
        _session: object,
        *,
        runtime_authority_check: Callable[[datetime], None],
        **_kwargs: object,
    ) -> RetrievalDecision:
        with pytest.raises(DesignPartnerQualificationError):
            runtime_authority_check(expires_at)
        return RetrievalDecision(
            allowed=False,
            result="DENIED_QUALIFICATION",
            correlation_id=CORRELATION_ID,
        )

    monkeypatch.setattr(  # type: ignore[attr-defined]
        routes,
        "retrieve_published_package",
        retrieve_with_runtime_check,
    )

    with TestClient(_app(_ExpiredRuntimeSettings())) as client:
        response = client.get(
            "/api/deployment-packages/10000000-0000-4000-8000-000000000001/versions/1",
            headers={
                "Authorization": "Bearer fdp1.test",
                "X-Correlation-ID": str(CORRELATION_ID),
            },
        )

    assert runtime_checks == [expires_at]
    assert response.status_code == 410
    assert response.json()["error"]["code"] == "PACKAGE_QUALIFICATION_WITHDRAWN"
    assert "package" not in response.json()


def test_sanitized_retrieval_runtime_authority_fails_closed_when_disabled() -> None:
    decision_time = datetime(2026, 9, 4, 20, 0, tzinfo=UTC)

    class _DisabledRuntimeSettings:
        sanitized_data_enabled = False

        def verified_deployment_qualification(self, *, now: datetime) -> None:
            raise AssertionError(f"Disabled sanitized access must not validate a record at {now}.")

    with pytest.raises(
        DesignPartnerQualificationError,
        match="not enabled",
    ):
        routes._require_sanitized_retrieval_runtime_authority(
            _DisabledRuntimeSettings(),  # type: ignore[arg-type]
            now=decision_time,
        )


def test_retrieval_route_returns_the_existing_authentication_denial_if_grant_expires_late(
    monkeypatch: object,
) -> None:
    _install_authenticated_retrieval(monkeypatch)
    monkeypatch.setattr(  # type: ignore[attr-defined]
        routes,
        "retrieve_published_package",
        lambda _session, **_kwargs: RetrievalDecision(
            allowed=False,
            result="EXPIRED_TOKEN",
            correlation_id=CORRELATION_ID,
        ),
    )

    with TestClient(_app()) as client:
        response = client.get(
            "/api/deployment-packages/10000000-0000-4000-8000-000000000001/versions/1",
            headers={
                "Authorization": "Bearer fdp1.test",
                "X-Correlation-ID": str(CORRELATION_ID),
            },
        )

    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "error": {
            "code": "EXPIRED_TOKEN",
            "message": "The package-retrieval credential is not authorized.",
            "correlation_id": str(CORRELATION_ID),
        }
    }
    assert "package" not in response.json()


def test_factory_engineer_operator_routes_are_explicitly_registered() -> None:
    paths = set(_app().openapi()["paths"])
    assert {
        "/api/engagements/{engagement_id}/factory-handoff/prerequisites",
        "/api/engagements/{engagement_id}/customer-factory-models",
        "/api/engagements/{engagement_id}/factory-opportunities",
        "/api/engagements/{engagement_id}/fdlc-readiness",
        "/api/engagements/{engagement_id}/deployment-packages",
        "/api/engagements/{engagement_id}/deployment-package-retrieval-grants",
        "/api/deployment-packages/{package_id}/versions/{package_version}",
    }.issubset(paths)


def test_factory_handoff_prerequisites_endpoint_projects_server_references(
    monkeypatch: object,
) -> None:
    evidence_ref = SourceReference(
        kind=ProvenanceKind.EVIDENCE,
        ref="evidence_asset:90000000-0000-4000-8000-000000000005",
        sha256=f"sha256:{'a' * 64}",
    )
    current_ref = ImmutableVersionReference(
        id=UUID("90000000-0000-4000-8000-000000000006"),
        version=2,
        digest=f"sha256:{'b' * 64}",
    )
    monkeypatch.setattr(  # type: ignore[attr-defined]
        routes,
        "get_factory_handoff_prerequisites",
        lambda _session, _engagement_id: SimpleNamespace(
            engagement=SimpleNamespace(
                id=ENGAGEMENT_ID,
                slug="acme-manufacturing",
                name="Acme Manufacturing",
                workflow_name="Invoice approval",
                primary_outcome="Reduce bounded invoice-review cycle time.",
            ),
            evidence_refs=[evidence_ref],
            verified_claim_refs=[],
            current_workflow_ref=current_ref,
            target_workflow_ref=None,
            economic_case_ref=None,
            implementation_artifact_refs=[],
        ),
    )

    response = routes.get_factory_handoff_prerequisites_endpoint(
        engagement_id=ENGAGEMENT_ID,
        session=cast(Session, object()),
        _access=cast(EngagementMember, object()),
    )

    assert response.engagement_id == ENGAGEMENT_ID
    assert response.organization_key == "acme-manufacturing"
    assert response.evidence_refs == [evidence_ref]
    assert response.current_workflow_ref == current_ref
    assert response.target_workflow_ref is None


def test_deployed_api_never_returns_package_retrieval_credentials() -> None:
    payload = RetrievalGrantCreateRequest(
        requester_identity="mission-control:production",
        requester_system="mission-control",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    with pytest.raises(HTTPException) as exc_info:
        routes.issue_retrieval_grant_endpoint(
            engagement_id=ENGAGEMENT_ID,
            payload=payload,
            session=cast(Session, object()),
            operator=cast(Operator, object()),
            _access=cast(EngagementMember, object()),
            settings=cast(Settings, SimpleNamespace(env="production")),
        )

    assert exc_info.value.status_code == 403
    assert "never returned by a deployed API" in exc_info.value.detail
