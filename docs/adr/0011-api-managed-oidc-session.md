# ADR 0011: Terminate OIDC in the API with an Opaque Application Session

**Status:** Proposed
**Date:** 2026-08-08

## Context

ADR 0007 requires OIDC authentication before sanitized customer use. The Next.js cockpit and
FastAPI API are separate runtimes, so the location of the OIDC exchange and application session is
a security boundary. Provider access and ID tokens must not become browser application state.

## Decision

Use one configured OpenID Connect issuer per deployment. FastAPI acts as the confidential client,
uses the authorization-code flow with PKCE S256 and OIDC state/nonce validation, maps the verified
issuer subject to an operator, and issues an opaque, revocable, HTTP-only application session.

The Next.js cockpit calls FastAPI with that application-session cookie. Engagement membership and
role authorization remain application concerns; PostgreSQL row policies remain the independent
engagement-isolation boundary. Local development identity is explicit, development-only, and
cannot authorize sanitized data.

## Consequences

- Provider tokens remain server-side and are not stored in browser JavaScript.
- CORS must allow credentials only from explicit cockpit origins.
- Session identifiers must be random, stored only as hashes, expire, support revocation, and rotate
  at authentication.
- OIDC discovery, issuer, audience, signature, expiry, nonce, state, and redirect behavior require
  integration tests against the selected provider.
- A specific OIDC provider and deployment callback remain an operational selection, not a domain
  dependency.

## Alternatives

- Auth.js plus a Next.js backend-for-frontend adds another authorization hop and token boundary.
- Direct browser bearer tokens reduce server work but increase token exposure and refresh/logout
  complexity.
