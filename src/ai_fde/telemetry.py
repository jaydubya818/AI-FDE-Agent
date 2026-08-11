from __future__ import annotations

import logging
import time
import uuid
from collections.abc import MutableSequence

from starlette.types import ASGIApp, Message, Receive, Scope, Send

access_logger = logging.getLogger("ai_fde.access")


def configure_access_logging() -> None:
    access_logger.setLevel(logging.INFO)
    access_logger.propagate = False
    if access_logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    access_logger.addHandler(handler)


class SafeAccessLogMiddleware:
    """Log request metadata without raw paths, queries, headers, or bodies."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid.uuid4())
        started_at = time.perf_counter()
        status_code = 500
        response_started = False
        response_complete = False

        async def send_with_request_id(message: Message) -> None:
            nonlocal response_complete, response_started, status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                response_started = True
                headers = message.setdefault("headers", [])
                _append_header(headers, b"x-request-id", request_id.encode("ascii"))
            elif message["type"] == "http.response.body" and not message.get(
                "more_body", False
            ):
                response_complete = True
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception as error:  # noqa: BLE001 - this is the API's privacy boundary
            access_logger.error(
                "HTTP request failed request_id=%s failure_code=unhandled_application_error "
                "exception_type=%s",
                request_id,
                type(error).__name__,
            )
            if not response_complete:
                if not response_started:
                    body = b'{"detail":"The operator service could not complete the request."}'
                    await send(
                        {
                            "type": "http.response.start",
                            "status": 500,
                            "headers": [
                                (b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode("ascii")),
                                (b"x-request-id", request_id.encode("ascii")),
                            ],
                        }
                    )
                    await send({"type": "http.response.body", "body": body})
                else:
                    await send(
                        {
                            "type": "http.response.body",
                            "body": b"",
                            "more_body": False,
                        }
                    )
        finally:
            route = scope.get("route")
            route_template = getattr(route, "path", "unmatched")
            duration_ms = round((time.perf_counter() - started_at) * 1000)
            access_logger.info(
                "HTTP request completed request_id=%s method=%s route=%s "
                "status_code=%s duration_ms=%s",
                request_id,
                scope["method"],
                route_template,
                status_code,
                duration_ms,
            )


def _append_header(
    headers: MutableSequence[tuple[bytes, bytes]], name: bytes, value: bytes
) -> None:
    headers.append((name, value))
