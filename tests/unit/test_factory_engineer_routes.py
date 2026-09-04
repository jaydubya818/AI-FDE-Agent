from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

import ai_fde.api.factory_engineer_routes as routes
from ai_fde.modules.factory_engineer.retrieval import (
    AuthenticatedRetrievalPrincipal,
    RetrievalAuthenticationDecision,
    RetrievalTokenSubject,
)
from ai_fde.modules.factory_engineer.schemas import (
    PublishedPackageEnvelope,
    RetrievalDecision,
)

FIXTURE = (
    Path(__file__).resolve().parents[2] / "fixtures/contracts/factory-deployment-package-v1.json"
)
CORRELATION_ID = UUID("90000000-0000-4000-8000-000000000001")
OPERATOR_ID = UUID("90000000-0000-4000-8000-000000000002")
GRANT_ID = UUID("90000000-0000-4000-8000-000000000003")
ENGAGEMENT_ID = UUID("90000000-0000-4000-8000-000000000004")


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
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


def test_factory_engineer_operator_routes_are_explicitly_registered() -> None:
    paths = set(_app().openapi()["paths"])
    assert {
        "/api/engagements/{engagement_id}/customer-factory-models",
        "/api/engagements/{engagement_id}/factory-opportunities",
        "/api/engagements/{engagement_id}/fdlc-readiness",
        "/api/engagements/{engagement_id}/deployment-packages",
        "/api/engagements/{engagement_id}/deployment-package-retrieval-grants",
        "/api/deployment-packages/{package_id}/versions/{package_version}",
    }.issubset(paths)
