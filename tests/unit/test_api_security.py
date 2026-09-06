from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_fde.api.security import (
    BrowserMutationGuardMiddleware,
    SecurityResponseHeadersMiddleware,
)


def _guarded_app(*, production: bool = False) -> FastAPI:
    app = FastAPI()

    @app.post("/mutation")
    def mutate() -> dict[str, bool]:
        return {"updated": True}

    app.add_middleware(
        BrowserMutationGuardMiddleware,
        enabled=True,
        allowed_origins=["https://factory.example"],
        session_cookie_name="ai_fde_session",
    )
    app.add_middleware(SecurityResponseHeadersMiddleware, production=production)
    return app


def test_cookie_authenticated_mutation_requires_exact_origin_and_intent() -> None:
    client = TestClient(_guarded_app())
    client.cookies.set("ai_fde_session", "opaque-session-secret")

    no_origin = client.post("/mutation")
    wrong_origin = client.post(
        "/mutation",
        headers={
            "origin": "https://attacker.example",
            "x-ai-fde-intent": "browser-mutation",
        },
    )
    no_intent = client.post(
        "/mutation",
        headers={"origin": "https://factory.example"},
    )
    allowed = client.post(
        "/mutation",
        headers={
            "origin": "https://factory.example",
            "x-ai-fde-intent": "browser-mutation",
        },
    )

    assert no_origin.status_code == 403
    assert wrong_origin.status_code == 403
    assert no_intent.status_code == 403
    assert allowed.status_code == 200


def test_bearer_and_unauthenticated_requests_are_not_misclassified_as_csrf() -> None:
    client = TestClient(_guarded_app())

    assert client.post("/mutation").status_code == 200
    assert (
        client.post(
            "/mutation",
            headers={"authorization": "Bearer server-held-retrieval-secret"},
        ).status_code
        == 200
    )


def test_security_headers_cover_success_and_guard_rejection() -> None:
    client = TestClient(_guarded_app(production=True))
    client.cookies.set("ai_fde_session", "opaque-session-secret")

    rejected = client.post("/mutation")

    assert rejected.headers["x-content-type-options"] == "nosniff"
    assert rejected.headers["x-frame-options"] == "DENY"
    assert rejected.headers["referrer-policy"] == "no-referrer"
    assert rejected.headers["content-security-policy"].startswith("default-src 'none'")
    assert rejected.headers["strict-transport-security"].startswith("max-age=31536000")
