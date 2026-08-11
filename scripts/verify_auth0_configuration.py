from __future__ import annotations

import asyncio
import secrets

from ai_fde.config import get_settings
from ai_fde.modules.identity.oidc import Auth0OIDCProvider


async def verify() -> None:
    settings = get_settings()
    if settings.auth_mode != "oidc":
        raise SystemExit("AI_FDE_AUTH_MODE must be oidc for live Auth0 readiness.")
    provider = Auth0OIDCProvider(settings)
    await provider.build_authorization_url(
        state=secrets.token_urlsafe(32),
        nonce=secrets.token_urlsafe(32),
        code_verifier=secrets.token_urlsafe(64),
        redirect_uri=settings.oidc_redirect_uri,
    )
    print("Auth0 discovery, endpoint validation, and authorization request construction passed.")


if __name__ == "__main__":
    asyncio.run(verify())
