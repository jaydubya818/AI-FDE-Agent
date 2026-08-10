from __future__ import annotations

import uuid
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select

from ai_fde.adapters.storage import InMemoryEvidenceStore
from ai_fde.api.routes import router
from ai_fde.config import Settings, get_settings
from ai_fde.db import SessionFactory
from ai_fde.models import OIDCLoginAttempt, Operator, OperatorSession
from ai_fde.modules.identity.oidc import OIDCIdentity
from ai_fde.modules.identity.sessions import digest_secret


class FakeOIDCProvider:
    def __init__(self, identity: OIDCIdentity) -> None:
        self.identity = identity
        self.authorization_request: dict[str, str] | None = None
        self.exchange_request: dict[str, str] | None = None

    async def build_authorization_url(
        self,
        *,
        state: str,
        nonce: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> str:
        self.authorization_request = {
            "state": state,
            "nonce": nonce,
            "code_verifier": code_verifier,
            "redirect_uri": redirect_uri,
        }
        return f"https://tenant.us.auth0.com/authorize?state={state}"

    async def exchange_code(
        self,
        *,
        code: str,
        code_verifier: str,
        nonce: str,
        redirect_uri: str,
    ) -> OIDCIdentity:
        self.exchange_request = {
            "code": code,
            "code_verifier": code_verifier,
            "nonce": nonce,
            "redirect_uri": redirect_uri,
        }
        return self.identity


def _settings(allowed_email: str) -> Settings:
    return Settings(
        auth_mode="oidc",
        oidc_issuer_url="https://tenant.us.auth0.com/",
        oidc_client_id="client-id",
        oidc_client_secret=SecretStr("client-secret"),
        oidc_allowed_emails=[allowed_email],
    )


def _app(settings: Settings, provider: FakeOIDCProvider) -> FastAPI:
    app = FastAPI()
    app.state.evidence_store = InMemoryEvidenceStore()
    app.state.oidc_provider = provider
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_settings] = lambda: settings
    return app


@pytest.mark.integration
@pytest.mark.isolation
def test_oidc_login_creates_opaque_session_and_logout_revokes_it(
    postgres_available: None,
) -> None:
    subject = f"auth0|{uuid.uuid4()}"
    identity = OIDCIdentity(
        issuer="https://tenant.us.auth0.com/",
        subject=subject,
        email="fde@example.com",
        email_verified=True,
        display_name="Authenticated FDE",
    )
    provider = FakeOIDCProvider(identity)
    settings = _settings(identity.email)

    with TestClient(_app(settings, provider)) as client:
        unauthenticated = client.get("/api/auth/me")
        assert unauthenticated.status_code == 401
        assert unauthenticated.headers["www-authenticate"] == "Cookie"

        invalid_return = client.get(
            "/api/auth/login",
            params={"return_to": "https://attacker.example"},
            follow_redirects=False,
        )
        assert invalid_return.status_code == 400
        ambiguous_return = client.get(
            "/api/auth/login",
            params={"return_to": "/\\attacker.example"},
            follow_redirects=False,
        )
        assert ambiguous_return.status_code == 400

        return_to = "/engagements/verified-workspace"
        login = client.get(
            "/api/auth/login",
            params={"return_to": return_to},
            follow_redirects=False,
        )
        assert login.status_code == 302
        state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
        assert provider.authorization_request is not None

        with SessionFactory() as session:
            attempt = session.scalar(
                select(OIDCLoginAttempt).where(
                    OIDCLoginAttempt.state_digest == digest_secret(state)
                )
            )
            assert attempt is not None
            assert attempt.state_digest != state

        callback = client.get(
            "/api/auth/callback",
            params={"code": "authorization-code", "state": state},
            follow_redirects=False,
        )
        assert callback.status_code == 303
        assert callback.headers["location"] == f"{settings.cockpit_url}{return_to}"
        assert "HttpOnly" in callback.headers["set-cookie"]
        assert "SameSite=lax" in callback.headers["set-cookie"]
        assert provider.exchange_request == {
            "code": "authorization-code",
            "code_verifier": provider.authorization_request["code_verifier"],
            "nonce": provider.authorization_request["nonce"],
            "redirect_uri": settings.oidc_redirect_uri,
        }
        with SessionFactory() as session:
            assert (
                session.scalar(
                    select(OIDCLoginAttempt).where(
                        OIDCLoginAttempt.state_digest == digest_secret(state)
                    )
                )
                is None
            )

        authenticated = client.get("/api/auth/me")
        assert authenticated.status_code == 200
        assert authenticated.json()["auth_mode"] == "oidc"
        assert authenticated.json()["sanitized_data_allowed"] is False

        reused = client.get(
            "/api/auth/callback",
            params={"code": "replayed-code", "state": state},
            follow_redirects=False,
        )
        assert reused.status_code == 400

        cookie_token = client.cookies.get(settings.session_cookie_name)
        assert cookie_token is not None
        with SessionFactory() as session:
            operator = session.scalar(
                select(Operator).where(
                    Operator.external_subject == f"{identity.issuer}|{identity.subject}"
                )
            )
            assert operator is not None
            stored_session = session.scalar(
                select(OperatorSession).where(
                    OperatorSession.token_digest == digest_secret(cookie_token)
                )
            )
            assert stored_session is not None
            assert stored_session.token_digest != cookie_token

        logout = client.post("/api/auth/logout")
        assert logout.status_code == 204
        assert client.get("/api/auth/me").status_code == 401

        with SessionFactory() as session:
            revoked = session.get_one(OperatorSession, stored_session.id)
            assert revoked.revoked_at is not None


@pytest.mark.integration
@pytest.mark.isolation
def test_oidc_callback_rejects_identity_outside_allowlist(
    postgres_available: None,
) -> None:
    identity = OIDCIdentity(
        issuer="https://tenant.us.auth0.com/",
        subject=f"auth0|{uuid.uuid4()}",
        email="outsider@example.com",
        email_verified=True,
        display_name="Unapproved Operator",
    )
    provider = FakeOIDCProvider(identity)
    settings = _settings("approved@example.com")

    with TestClient(_app(settings, provider)) as client:
        login = client.get("/api/auth/login", follow_redirects=False)
        state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
        callback = client.get(
            "/api/auth/callback",
            params={"code": "authorization-code", "state": state},
            follow_redirects=False,
        )

    assert callback.status_code == 403
    assert callback.json() == {"detail": "This identity is not an approved AI-FDE operator."}
    with SessionFactory() as session:
        assert (
            session.scalar(
                select(Operator).where(
                    Operator.external_subject == f"{identity.issuer}|{identity.subject}"
                )
            )
            is None
        )
