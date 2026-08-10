from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from ai_fde.config import Settings


def test_development_identity_is_rejected_in_production() -> None:
    with pytest.raises(ValidationError, match="Development identity is forbidden"):
        Settings(env="production", auth_mode="development")


def test_oidc_mode_is_allowed_in_production_configuration() -> None:
    settings = Settings(
        env="production",
        auth_mode="oidc",
        cockpit_url="https://cockpit.example.com",
        allowed_origins=["https://cockpit.example.com"],
        oidc_issuer_url="https://tenant.us.auth0.com/",
        oidc_client_id="client-id",
        oidc_client_secret=SecretStr("client-secret"),
        oidc_redirect_uri="https://api.example.com/api/auth/callback",
        oidc_allowed_emails=["fde@example.com"],
    )

    assert settings.auth_mode == "oidc"


def test_oidc_mode_rejects_missing_provider_configuration() -> None:
    with pytest.raises(ValidationError, match="OIDC authentication requires"):
        Settings(auth_mode="oidc")


def test_production_oidc_rejects_insecure_application_urls() -> None:
    with pytest.raises(ValidationError, match="must use HTTPS"):
        Settings(
            env="production",
            auth_mode="oidc",
            oidc_issuer_url="https://tenant.us.auth0.com/",
            oidc_client_id="client-id",
            oidc_client_secret=SecretStr("client-secret"),
            oidc_allowed_emails=["fde@example.com"],
        )
