from __future__ import annotations

import pytest
from pydantic import ValidationError

from ai_fde.config import Settings


def test_development_identity_is_rejected_in_production() -> None:
    with pytest.raises(ValidationError, match="Development identity is forbidden"):
        Settings(env="production", auth_mode="development")


def test_oidc_mode_is_allowed_in_production_configuration() -> None:
    settings = Settings(env="production", auth_mode="oidc")

    assert settings.auth_mode == "oidc"
