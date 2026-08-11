# Auth0 Live-Tenant Validation Record

Use this record once for each environment and after any callback, cookie, proxy, or Auth0
application-setting change. Do not paste client secrets, authorization codes, state, cookies, ID
tokens, or screenshots containing those values into this record.

## Readiness

- [ ] Auth0 Regular Web Application exists for this environment.
- [ ] The exact callback URL is configured; there are no production wildcards or localhost URLs.
- [ ] The exact cockpit URL is an allowed logout URL and web origin.
- [ ] RS256 and OIDC-conformant behavior are enabled.
- [ ] One test operator email is verified and allowlisted in AI-FDE.
- [ ] Runtime secrets are configured outside source control.
- [ ] `make auth0-contract` passes.
- [ ] `make auth0-readiness` passes against the configured tenant.

## Browser validation

- [ ] An unauthenticated cockpit visit presents the authentication-required state.
- [ ] Sign in redirects to the expected Auth0 tenant and returns only to the exact callback.
- [ ] A successful callback returns to the original local cockpit path.
- [ ] The application cookie is `HttpOnly`, `Secure` in non-development environments,
      `SameSite=Lax`, scoped to `/`, and has the configured maximum age.
- [ ] `/api/auth/me` reports the expected operator and `auth_mode: oidc`.
- [ ] The same callback URL cannot be replayed.
- [ ] A non-allowlisted or unverified email is denied and not enrolled.
- [ ] Signing out revokes the server-side application session, clears the browser cookie, and makes
      `/api/auth/me` return 401.
- [ ] Signing out of AI-FDE does not claim to end every Auth0 or upstream identity-provider SSO
      session; that is a separate product decision.
- [ ] A session is rejected after the operator is marked inactive.

## Evidence

| Field | Value |
| --- | --- |
| Environment | |
| Auth0 tenant hostname | |
| AI-FDE release/commit | |
| Tester | |
| Test date/time | |
| Result | Pass / Fail |
| Failure ticket or notes (no secrets) | |
