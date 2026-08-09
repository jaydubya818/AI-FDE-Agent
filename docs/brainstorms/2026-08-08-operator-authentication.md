---
date: 2026-08-08
topic: operator-authentication
---

# Operator Authentication and Engagement Authorization

## What We Are Building

Replace the hidden configured operator with an explicit authenticated principal, enforce the
owner/operator/viewer role matrix in the application layer, and preserve PostgreSQL row isolation
as a second boundary. Development identity remains available only in development and is never
allowed to authorize sanitized data.

The production login adapter will use one configured OpenID Connect issuer. The API will own the
authorization-code exchange and an opaque HTTP-only application session; the Next.js cockpit will
not receive provider tokens.

## Approaches Considered

1. **API-managed OIDC session — recommended.** FastAPI performs discovery, authorization-code +
   PKCE exchange, identity validation, and session issuance. This keeps identity and authorization
   in one module and keeps tokens out of browser JavaScript.
2. **Auth.js browser-facing session plus an API proxy.** Mature Next.js integration, but it adds a
   second authorization boundary and requires every API call to traverse a web BFF.
3. **Browser-held bearer token sent directly to FastAPI.** Fewer server components, but exposes
   access tokens to the browser runtime and makes refresh, logout, and leakage controls harder.

## Key Decisions

- Authentication establishes an operator; engagement membership establishes authority.
- `owner` and `operator` may mutate V1 engagement state; `viewer` is read-only.
- Non-members receive `404` to avoid revealing engagement existence; read-only members receive
  `403` for mutations.
- Development identity fails closed outside the development environment.
- Sanitized engagements require production OIDC authentication.
- Provider tokens will remain server-side; application sessions will be opaque and revocable.
- The OIDC client will use issuer discovery, authorization code, PKCE S256, state/nonce validation,
  exact registered redirects, and secure HTTP-only cookies.

## Open Question

- Select the first design-partner OIDC provider and register the production callback before the
  OIDC adapter can be exercised against a real issuer.

## Next Steps

Implement the principal and engagement-authorization boundary first, then implement the OIDC
adapter after ADR 0011 and the first provider configuration are approved.
