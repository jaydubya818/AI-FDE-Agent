from __future__ import annotations

import asyncio
import time
from urllib.parse import parse_qs

import httpx
import pytest
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet, generate_key
from pydantic import SecretStr

from ai_fde.config import Settings
from ai_fde.modules.identity.oidc import Auth0OIDCProvider, verify_id_token

ISSUER = "https://tenant.us.auth0.com/"
CLIENT_ID = "client-id"
NONCE = "verified-nonce"


def _settings() -> Settings:
    return Settings(
        auth_mode="oidc",
        oidc_issuer_url=ISSUER,
        oidc_client_id=CLIENT_ID,
        oidc_client_secret=SecretStr("client-secret"),
        oidc_allowed_emails=["fde@example.com"],
    )


def _signed_id_token() -> tuple[str, dict[str, object]]:
    key = generate_key("RSA", 2048, private=True, auto_kid=True)
    key_set = KeySet([key])
    now = int(time.time())
    value = jwt.encode(
        {"alg": "RS256", "kid": key.kid},
        {
            "iss": ISSUER,
            "sub": "auth0|operator-123",
            "aud": CLIENT_ID,
            "iat": now,
            "exp": now + 300,
            "nonce": NONCE,
            "email": "fde@example.com",
            "email_verified": True,
            "name": "Design Partner FDE",
        },
        key,
        algorithms=["RS256"],
    )
    return value, dict(key_set.as_dict(private=False))


def test_auth0_provider_exchanges_code_and_verifies_id_token() -> None:
    id_token, jwks = _signed_id_token()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": f"{ISSUER}authorize",
                    "token_endpoint": f"{ISSUER}oauth/token",
                    "jwks_uri": f"{ISSUER}.well-known/jwks.json",
                },
            )
        if request.url.path == "/oauth/token":
            body = parse_qs(request.content.decode("utf-8"))
            assert body["code"] == ["authorization-code"]
            assert body["code_verifier"] == ["pkce-verifier"]
            return httpx.Response(
                200,
                json={
                    "access_token": "discarded-provider-token",
                    "token_type": "Bearer",
                    "id_token": id_token,
                },
            )
        if request.url.path == "/.well-known/jwks.json":
            return httpx.Response(200, json=jwks)
        raise AssertionError(f"Unexpected provider request: {request.url}")

    provider = Auth0OIDCProvider(_settings(), transport=httpx.MockTransport(handler))
    identity = asyncio.run(
        provider.exchange_code(
            code="authorization-code",
            code_verifier="pkce-verifier",
            nonce=NONCE,
            redirect_uri="http://localhost:8000/api/auth/callback",
        )
    )

    assert identity.subject == "auth0|operator-123"
    assert identity.email == "fde@example.com"
    assert identity.display_name == "Design Partner FDE"


def test_id_token_rejects_wrong_nonce() -> None:
    id_token, jwks = _signed_id_token()

    with pytest.raises(JoseError):
        verify_id_token(
            id_token,
            jwks=jwks,
            issuer=ISSUER,
            client_id=CLIENT_ID,
            nonce="attacker-nonce",
        )
