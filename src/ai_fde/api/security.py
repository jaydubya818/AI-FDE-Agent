from __future__ import annotations

from collections.abc import MutableSequence, Sequence
from http.cookies import CookieError, SimpleCookie

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_MUTATION_INTENT = b"browser-mutation"


class BrowserMutationGuardMiddleware:
    """Reject cross-site cookie-authenticated mutations before route handling."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        enabled: bool,
        allowed_origins: Sequence[str],
        session_cookie_name: str,
    ) -> None:
        self.app = app
        self.enabled = enabled
        self.allowed_origins = frozenset(
            origin.rstrip("/").encode("utf-8") for origin in allowed_origins
        )
        self.session_cookie_name = session_cookie_name

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or not self.enabled
            or scope["method"] not in _UNSAFE_METHODS
            or not _has_session_cookie(scope, self.session_cookie_name)
        ):
            await self.app(scope, receive, send)
            return

        origin = _header(scope, b"origin")
        intent = _header(scope, b"x-ai-fde-intent")
        if origin in self.allowed_origins and intent == _MUTATION_INTENT:
            await self.app(scope, receive, send)
            return

        body = b'{"detail":"The browser mutation could not be authorized."}'
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


class SecurityResponseHeadersMiddleware:
    """Apply browser hardening headers to every API response."""

    def __init__(self, app: ASGIApp, *, production: bool) -> None:
        self.app = app
        self.production = production

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                _set_header(headers, b"x-content-type-options", b"nosniff")
                _set_header(headers, b"x-frame-options", b"DENY")
                _set_header(headers, b"referrer-policy", b"no-referrer")
                _set_header(
                    headers,
                    b"permissions-policy",
                    b"camera=(), microphone=(), geolocation=(), payment=()",
                )
                if self.production:
                    _set_header(
                        headers,
                        b"content-security-policy",
                        b"default-src 'none'; frame-ancestors 'none'; "
                        b"base-uri 'none'; form-action 'none'",
                    )
                    _set_header(
                        headers,
                        b"strict-transport-security",
                        b"max-age=31536000; includeSubDomains",
                    )
            await send(message)

        await self.app(scope, receive, send_with_security_headers)


def _has_session_cookie(scope: Scope, session_cookie_name: str) -> bool:
    raw_cookie = _header(scope, b"cookie")
    if raw_cookie is None:
        return False
    parsed = SimpleCookie()
    try:
        parsed.load(raw_cookie.decode("latin-1"))
    except CookieError:
        return False
    return session_cookie_name in parsed


def _header(scope: Scope, name: bytes) -> bytes | None:
    for raw_name, raw_value in scope.get("headers", []):
        if raw_name.lower() == name:
            return bytes(raw_value)
    return None


def _set_header(
    headers: MutableSequence[tuple[bytes, bytes]], name: bytes, value: bytes
) -> None:
    headers[:] = [(key, item) for key, item in headers if key.lower() != name]
    headers.append((name, value))
