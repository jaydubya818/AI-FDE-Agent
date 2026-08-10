---
date: 2026-08-08
topic: auth0-production-session
---

# Auth0 Production Session

## What We're Building

Use Auth0 as AI-FDE's first production OIDC issuer while retaining AI-FDE-owned authorization and
an opaque PostgreSQL-backed application session. Auth0 authenticates the person; AI-FDE decides
which engagements that operator can read or change.

## Why This Approach

Auth0 is a standards-based issuer with a Regular Web Application flow that fits the existing
FastAPI confidential-client boundary. Direct Microsoft Entra ID would make the first deployment
dependent on one corporate tenant. WorkOS is better reserved for the later point when customer
organizations need managed federation across many identity providers.

## Key Decisions

- Identity key: exact OIDC issuer plus `sub`; email is used only for initial allowlisted enrollment.
- Login: authorization code with PKCE S256, state, nonce, exact redirect URI, and verified ID token.
- Session: random opaque cookie; only a SHA-256 digest is stored; sessions expire and can be revoked.
- Browser: HTTP-only, SameSite=Lax cookie; Secure is mandatory outside development.
- Tokens: provider access, ID, and refresh tokens are not persisted after identity verification.
- Authority: Auth0 organizations and claims never grant engagement access directly.
- Logout: revoke the AI-FDE session and clear its cookie; provider-wide logout is deferred.

## Open Questions

- Production Auth0 tenant credentials and callback hostname must be supplied through deployment
  secrets before live-provider validation.

## Next Steps

Persistent login attempts, application sessions, login/callback/logout, and provider-test-double
coverage are implemented. Exercise the flow against the configured Auth0 tenant, then implement
retention, export, and deletion before enabling sanitized customer data.
