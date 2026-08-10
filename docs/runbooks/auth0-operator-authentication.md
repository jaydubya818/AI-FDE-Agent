# Auth0 Operator Authentication

AI-FDE uses Auth0 only to authenticate the human operator. AI-FDE owns operator enrollment,
engagement membership, roles, row-level isolation, and the application session.

## Auth0 application

Create an Auth0 **Regular Web Application** for each environment. Configure these exact values for
local development:

- Allowed callback URL: `http://localhost:8000/api/auth/callback`
- Allowed web origin: `http://localhost:3000`
- Application login URI: `http://localhost:8000/api/auth/login`

Production callback, cockpit, and origin URLs must use HTTPS. Do not place Auth0 client secrets in
the web application or any `NEXT_PUBLIC_` environment variable.

## API configuration

Copy `.env.example` to `.env` and replace the example values:

```dotenv
AI_FDE_AUTH_MODE=oidc
AI_FDE_OIDC_ISSUER_URL=https://your-tenant.us.auth0.com/
AI_FDE_OIDC_CLIENT_ID=your-client-id
AI_FDE_OIDC_CLIENT_SECRET=your-client-secret
AI_FDE_OIDC_REDIRECT_URI=http://localhost:8000/api/auth/callback
AI_FDE_OIDC_ALLOWED_EMAILS=["fde@example.com"]
AI_FDE_COCKPIT_URL=http://localhost:3000
AI_FDE_ALLOWED_ORIGINS=["http://localhost:3000"]
```

The email allowlist controls first enrollment. After enrollment, the durable identity key is the
exact issuer plus the OIDC `sub`; email changes do not silently create a new authority mapping.
Disabling an operator in AI-FDE remains authoritative.

## Verification

Start the migrated stack, then open:

```text
http://localhost:8000/api/auth/login
```

After Auth0 authentication, the callback should return to the cockpit with an HTTP-only,
SameSite=Lax application cookie. `GET /api/auth/me` should report `auth_mode: "oidc"`. The database
stores only a SHA-256 digest of the opaque application token. Provider access, ID, and refresh
tokens are not persisted.

Validate these failure paths before using a deployment:

- a non-allowlisted email receives 403 and is not enrolled;
- a missing, expired, or replayed login state is rejected;
- a wrong nonce, issuer, audience, signature, or expired ID token is rejected;
- logout revokes the server-side session and clears the cookie;
- unauthenticated API calls receive 401;
- cross-engagement access remains non-disclosing and denied by both the application and PostgreSQL.

Sanitized customer data remains disabled in the current build. OIDC authentication is necessary
but not sufficient; retention, export, and deletion must be implemented and verified first.

## References

- [Auth0 FastAPI web-app quickstart](https://auth0.com/docs/quickstart/webapp/fastapi)
- [Auth0 authorization code flow with PKCE](https://auth0.com/docs/get-started/authentication-and-authorization-flow/authorization-code-flow-with-pkce)
- [OpenID Connect Core 1.0](https://openid.net/specs/openid-connect-core-1_0.html)
