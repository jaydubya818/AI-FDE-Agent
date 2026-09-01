from __future__ import annotations

import asyncio
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet, generate_key
from pydantic import SecretStr

from ai_fde.config import Settings
from ai_fde.modules.identity.oidc import (
    Auth0OIDCProvider,
    OIDCProviderError,
    verify_id_token,
)

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


def _signed_id_token(**claim_overrides: object) -> tuple[str, dict[str, object]]:
    key = generate_key("RSA", 2048, private=True, auto_kid=True)
    key_set = KeySet([key])
    now = int(time.time())
    claims: dict[str, object] = {
        "iss": ISSUER,
        "sub": "auth0|operator-123",
        "aud": CLIENT_ID,
        "iat": now,
        "exp": now + 300,
        "nonce": NONCE,
        "email": "fde@example.com",
        "email_verified": True,
        "name": "Design Partner FDE",
    }
    claims.update(claim_overrides)
    claims = {name: value for name, value in claims.items() if value is not None}
    value = jwt.encode(
        {"alg": "RS256", "kid": key.kid},
        claims,
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


def test_auth0_provider_builds_pkce_authorization_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/.well-known/openid-configuration"
        return httpx.Response(
            200,
            json={
                "issuer": ISSUER,
                "authorization_endpoint": f"{ISSUER}authorize",
                "token_endpoint": f"{ISSUER}oauth/token",
                "jwks_uri": f"{ISSUER}.well-known/jwks.json",
            },
        )

    provider = Auth0OIDCProvider(_settings(), transport=httpx.MockTransport(handler))
    authorization_url = asyncio.run(
        provider.build_authorization_url(
            state="verified-state",
            nonce=NONCE,
            code_verifier="verified-code-verifier",
            redirect_uri="http://localhost:8000/api/auth/callback",
        )
    )
    query = parse_qs(urlparse(authorization_url).query)

    assert query["response_type"] == ["code"]
    assert query["state"] == ["verified-state"]
    assert query["nonce"] == [NONCE]
    assert query["code_challenge_method"] == ["S256"]
    assert query["scope"] == ["openid profile email"]


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


def _discovery(**overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "issuer": ISSUER,
        "authorization_endpoint": f"{ISSUER}authorize",
        "token_endpoint": f"{ISSUER}oauth/token",
        "jwks_uri": f"{ISSUER}.well-known/jwks.json",
    }
    document.update(overrides)
    return document


def _provider_returning(document: object) -> Auth0OIDCProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/.well-known/openid-configuration"
        return httpx.Response(200, json=document)

    return Auth0OIDCProvider(_settings(), transport=httpx.MockTransport(handler))


def _start_login(provider: Auth0OIDCProvider) -> str:
    return asyncio.run(
        provider.build_authorization_url(
            state="verified-state",
            nonce=NONCE,
            code_verifier="verified-code-verifier",
            redirect_uri="http://localhost:8000/api/auth/callback",
        )
    )


def test_discovery_rejects_an_unexpected_issuer() -> None:
    provider = _provider_returning(_discovery(issuer="https://attacker.example.com/"))

    with pytest.raises(OIDCProviderError, match="unexpected issuer"):
        _start_login(provider)


@pytest.mark.parametrize(
    "endpoint",
    ["authorization_endpoint", "token_endpoint", "jwks_uri"],
)
def test_discovery_rejects_an_endpoint_on_another_host(endpoint: str) -> None:
    """Every endpoint must live on the issuer's host, not merely be HTTPS."""
    provider = _provider_returning(_discovery(**{endpoint: "https://attacker.example.com/steal"}))

    with pytest.raises(OIDCProviderError, match=f"invalid {endpoint}"):
        _start_login(provider)


@pytest.mark.parametrize(
    "endpoint",
    ["authorization_endpoint", "token_endpoint", "jwks_uri"],
)
def test_discovery_rejects_a_plaintext_endpoint(endpoint: str) -> None:
    provider = _provider_returning(_discovery(**{endpoint: f"http://tenant.us.auth0.com/{endpoint}"}))

    with pytest.raises(OIDCProviderError, match=f"invalid {endpoint}"):
        _start_login(provider)


def test_discovery_rejects_a_non_string_endpoint() -> None:
    provider = _provider_returning(_discovery(jwks_uri=None))

    with pytest.raises(OIDCProviderError, match="invalid jwks_uri"):
        _start_login(provider)


def test_discovery_rejects_a_non_object_document() -> None:
    provider = _provider_returning(["not", "an", "object"])

    with pytest.raises(OIDCProviderError, match="invalid JSON document"):
        _start_login(provider)


def test_provider_requires_complete_credentials() -> None:
    with pytest.raises(ValueError, match="settings are incomplete"):
        Auth0OIDCProvider(
            Settings(auth_mode="development", oidc_issuer_url=None, oidc_client_id=None)
        )


def test_id_token_rejects_an_untrusted_authorized_party() -> None:
    """A multi-audience token must name this client in `azp`."""
    id_token, jwks = _signed_id_token(aud=[CLIENT_ID, "another-api"], azp="another-api")

    with pytest.raises(OIDCProviderError, match="invalid authorized party"):
        verify_id_token(id_token, jwks=jwks, issuer=ISSUER, client_id=CLIENT_ID, nonce=NONCE)


def test_id_token_accepts_a_multi_audience_token_authorized_for_this_client() -> None:
    id_token, jwks = _signed_id_token(aud=[CLIENT_ID, "another-api"], azp=CLIENT_ID)

    identity = verify_id_token(
        id_token, jwks=jwks, issuer=ISSUER, client_id=CLIENT_ID, nonce=NONCE
    )

    assert identity.subject == "auth0|operator-123"


def test_id_token_rejects_a_non_boolean_email_verification_claim() -> None:
    """`email_verified` gates enrollment, so a truthy string must not pass."""
    id_token, jwks = _signed_id_token(email_verified="true")

    with pytest.raises(OIDCProviderError, match="email verification claim is invalid"):
        verify_id_token(id_token, jwks=jwks, issuer=ISSUER, client_id=CLIENT_ID, nonce=NONCE)


def test_id_token_rejects_a_non_string_email_claim() -> None:
    """joserfc type-checks `sub` but not `email`, so this guard is load-bearing."""
    id_token, jwks = _signed_id_token(email=12345)

    with pytest.raises(OIDCProviderError, match="identity claims are invalid"):
        verify_id_token(id_token, jwks=jwks, issuer=ISSUER, client_id=CLIENT_ID, nonce=NONCE)


def test_id_token_without_a_name_claim_falls_back_to_the_email() -> None:
    id_token, jwks = _signed_id_token(name=None)

    identity = verify_id_token(
        id_token, jwks=jwks, issuer=ISSUER, client_id=CLIENT_ID, nonce=NONCE
    )

    assert identity.display_name == "fde@example.com"


def test_unverified_email_is_carried_through_for_the_enrollment_guard() -> None:
    """`verify_id_token` reports verification state; `enroll_operator` enforces it."""
    id_token, jwks = _signed_id_token(email_verified=False)

    identity = verify_id_token(
        id_token, jwks=jwks, issuer=ISSUER, client_id=CLIENT_ID, nonce=NONCE
    )

    assert identity.email_verified is False
