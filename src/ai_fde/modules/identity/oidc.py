from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, cast
from urllib.parse import urlparse

import httpx
from authlib.integrations.base_client.errors import OAuthError
from authlib.integrations.httpx_client import AsyncOAuth2Client
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet, KeySetSerialization
from joserfc.jwt import JWTClaimsRegistry

from ai_fde.config import Settings


class OIDCProviderError(RuntimeError):
    """The configured provider could not complete or verify authentication."""


@dataclass(frozen=True)
class OIDCIdentity:
    issuer: str
    subject: str
    email: str
    email_verified: bool
    display_name: str


class OIDCProvider(Protocol):
    async def build_authorization_url(
        self,
        *,
        state: str,
        nonce: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> str: ...

    async def exchange_code(
        self,
        *,
        code: str,
        code_verifier: str,
        nonce: str,
        redirect_uri: str,
    ) -> OIDCIdentity: ...


class Auth0OIDCProvider:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not settings.oidc_issuer_url or not settings.oidc_client_id:
            raise ValueError("Auth0 OIDC settings are incomplete.")
        if settings.oidc_client_secret is None:
            raise ValueError("Auth0 client secret is missing.")
        self._issuer = settings.oidc_issuer_url.rstrip("/") + "/"
        self._client_id = settings.oidc_client_id
        self._client_secret = settings.oidc_client_secret.get_secret_value()
        self._timeout = settings.oidc_request_timeout_seconds
        self._transport = transport

    async def build_authorization_url(
        self,
        *,
        state: str,
        nonce: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> str:
        try:
            metadata = await self._load_metadata()
            async with self._oauth_client(redirect_uri) as client:
                authorization_url, returned_state = client.create_authorization_url(
                    metadata["authorization_endpoint"],
                    state=state,
                    code_verifier=code_verifier,
                    nonce=nonce,
                )
        except OIDCProviderError:
            raise
        except (httpx.HTTPError, OAuthError, KeyError, TypeError, ValueError) as exc:
            raise OIDCProviderError("Auth0 could not start the login flow.") from exc
        if returned_state != state:
            raise OIDCProviderError("The provider client changed the login state.")
        if not isinstance(authorization_url, str):
            raise OIDCProviderError("The provider client returned an invalid authorization URL.")
        return authorization_url

    async def exchange_code(
        self,
        *,
        code: str,
        code_verifier: str,
        nonce: str,
        redirect_uri: str,
    ) -> OIDCIdentity:
        try:
            metadata = await self._load_metadata()
            async with self._oauth_client(redirect_uri) as client:
                token = await client.fetch_token(
                    metadata["token_endpoint"],
                    grant_type="authorization_code",
                    code=code,
                    code_verifier=code_verifier,
                    redirect_uri=redirect_uri,
                )
            id_token = token.get("id_token")
            if not isinstance(id_token, str):
                raise OIDCProviderError("The provider did not return an ID token.")
            jwks = await self._load_json(metadata["jwks_uri"])
            return verify_id_token(
                id_token,
                jwks=jwks,
                issuer=self._issuer,
                client_id=self._client_id,
                nonce=nonce,
            )
        except OIDCProviderError:
            raise
        except (httpx.HTTPError, OAuthError, JoseError, KeyError, TypeError, ValueError) as exc:
            raise OIDCProviderError("Auth0 could not verify the login response.") from exc

    def _oauth_client(self, redirect_uri: str) -> AsyncOAuth2Client:
        return AsyncOAuth2Client(
            self._client_id,
            self._client_secret,
            redirect_uri=redirect_uri,
            scope="openid profile email",
            code_challenge_method="S256",
            token_endpoint_auth_method="client_secret_basic",
            timeout=self._timeout,
            transport=self._transport,
        )

    async def _load_metadata(self) -> dict[str, str]:
        metadata = await self._load_json(f"{self._issuer}.well-known/openid-configuration")
        if metadata.get("issuer") != self._issuer:
            raise OIDCProviderError("OIDC discovery returned an unexpected issuer.")
        required = ("authorization_endpoint", "token_endpoint", "jwks_uri")
        resolved: dict[str, str] = {"issuer": self._issuer}
        issuer_hostname = urlparse(self._issuer).hostname
        for key in required:
            value = metadata.get(key)
            if not isinstance(value, str):
                raise OIDCProviderError(f"OIDC discovery returned an invalid {key}.")
            parsed = urlparse(value)
            if parsed.scheme != "https" or parsed.hostname != issuer_hostname:
                raise OIDCProviderError(f"OIDC discovery returned an invalid {key}.")
            resolved[key] = value
        return resolved

    async def _load_json(self, url: str) -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=self._timeout,
            transport=self._transport,
            follow_redirects=False,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise OIDCProviderError("OIDC endpoint returned an invalid JSON document.")
        return cast(dict[str, Any], payload)


def verify_id_token(
    value: str,
    *,
    jwks: dict[str, Any],
    issuer: str,
    client_id: str,
    nonce: str,
) -> OIDCIdentity:
    key_set = KeySet.import_key_set(cast(KeySetSerialization, jwks))
    token = jwt.decode(value, key_set, algorithms=["RS256"])
    claims = token.claims
    registry = JWTClaimsRegistry(
        leeway=60,
        iss={"essential": True, "value": issuer},
        sub={"essential": True},
        aud={"essential": True, "value": client_id},
        exp={"essential": True},
        iat={"essential": True},
        nonce={"essential": True, "value": nonce},
        email={"essential": True},
        email_verified={"essential": True},
    )
    registry.validate(claims)

    audience = claims["aud"]
    if isinstance(audience, list) and len(audience) > 1 and claims.get("azp") != client_id:
        raise OIDCProviderError("The ID token has an invalid authorized party.")
    subject = claims["sub"]
    email = claims["email"]
    email_verified = claims["email_verified"]
    if not isinstance(subject, str) or not isinstance(email, str):
        raise OIDCProviderError("The ID token identity claims are invalid.")
    if not isinstance(email_verified, bool):
        raise OIDCProviderError("The ID token email verification claim is invalid.")
    display_name_claim = claims.get("name")
    display_name = display_name_claim if isinstance(display_name_claim, str) else email
    return OIDCIdentity(
        issuer=issuer,
        subject=subject,
        email=email,
        email_verified=email_verified,
        display_name=display_name,
    )
