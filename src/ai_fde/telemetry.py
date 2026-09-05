from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import MutableSequence
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from starlette.types import ASGIApp, Message, Receive, Scope, Send

access_logger = logging.getLogger("ai_fde.access")
worker_logger = logging.getLogger("ai_fde.worker")
_current_correlation_id: ContextVar[UUID | None] = ContextVar(
    "ai_fde_correlation_id", default=None
)


def configure_access_logging() -> None:
    """Configure one-line JSON logs for the container logging driver."""

    access_logger.setLevel(logging.INFO)
    access_logger.propagate = False
    if access_logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    access_logger.addHandler(handler)


def configure_worker_logging() -> None:
    """Configure one-line JSON worker logs without customer content."""

    worker_logger.setLevel(logging.INFO)
    worker_logger.propagate = False
    if worker_logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    worker_logger.addHandler(handler)


def emit_worker_event(
    *,
    event: Literal[
        "worker.started",
        "worker.stopped",
        "workflow.job.completed",
        "workflow.job.failed",
        "workflow.dependency_failed",
    ],
    outcome: Literal["success", "failure", "stopped"],
    revision: str,
    deployment_id: str,
    level: int = logging.INFO,
    job_id: UUID | None = None,
    correlation_id: UUID | None = None,
    duration_ms: int | None = None,
    failure_code: str | None = None,
) -> None:
    """Emit the bounded worker event contract consumed by operational alarms."""

    _write_event(
        worker_logger,
        level,
        service="ai-fde-worker",
        event=event,
        outcome=outcome,
        revision=revision,
        deployment_id=deployment_id,
        job_id=str(job_id) if job_id is not None else None,
        correlation_id=str(correlation_id) if correlation_id is not None else None,
        duration_ms=duration_ms,
        failure_code=failure_code,
    )


class SafeAccessLogMiddleware:
    """Emit bounded request telemetry without paths, queries, headers, or bodies."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid.uuid4())
        correlation_id = _correlation_id(scope)
        trace_id = correlation_id.replace("-", "")
        correlation_token = _current_correlation_id.set(UUID(correlation_id))
        state = scope.setdefault("state", {})
        state["request_id"] = request_id
        state["correlation_id"] = correlation_id
        state["trace_id"] = trace_id

        started_at = time.perf_counter()
        status_code = 500
        response_started = False
        response_complete = False

        async def send_with_trace_context(message: Message) -> None:
            nonlocal response_complete, response_started, status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                response_started = True
                headers = message.setdefault("headers", [])
                _set_header(headers, b"x-request-id", request_id.encode("ascii"))
                _set_header(headers, b"x-correlation-id", correlation_id.encode("ascii"))
            elif message["type"] == "http.response.body" and not message.get(
                "more_body", False
            ):
                response_complete = True
            await send(message)

        try:
            await self.app(scope, receive, send_with_trace_context)
        except Exception as error:  # noqa: BLE001 - this is the API's privacy boundary
            _emit(
                logging.ERROR,
                event="http.request.failed",
                request_id=request_id,
                correlation_id=correlation_id,
                trace_id=trace_id,
                outcome="failure",
                failure_code="unhandled_application_error",
                exception_type=type(error).__name__,
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
                                (b"x-correlation-id", correlation_id.encode("ascii")),
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
            outcome = _request_outcome(status_code)
            failure_code = _status_failure_code(status_code)
            if status_code in {401, 403}:
                _emit(
                    logging.WARNING,
                    event="auth.denied",
                    request_id=request_id,
                    correlation_id=correlation_id,
                    trace_id=trace_id,
                    route=route_template,
                    method=scope["method"],
                    outcome="denied",
                    status_code=status_code,
                    failure_code=failure_code,
                )
            _emit(
                logging.INFO,
                event="http.request.completed",
                request_id=request_id,
                correlation_id=correlation_id,
                trace_id=trace_id,
                route=route_template,
                method=scope["method"],
                outcome=outcome,
                status_code=status_code,
                duration_ms=duration_ms,
                failure_code=failure_code,
            )
            _current_correlation_id.reset(correlation_token)


def current_correlation_id() -> UUID | None:
    """Return the validated request correlation ID for same-context domain records."""

    return _current_correlation_id.get()


def _emit(level: int, *, event: str, **fields: str | int | None) -> None:
    _write_event(
        access_logger,
        level,
        service="ai-fde-api",
        event=event,
        **fields,
    )


def _write_event(
    logger: logging.Logger,
    level: int,
    *,
    service: str,
    event: str,
    **fields: str | int | None,
) -> None:
    payload: dict[str, str | int] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "service": service,
        "event": event,
    }
    payload.update({key: value for key, value in fields.items() if value is not None})
    logger.log(level, json.dumps(payload, separators=(",", ":"), sort_keys=True))


def _correlation_id(scope: Scope) -> str:
    for raw_name, raw_value in scope.get("headers", []):
        if raw_name.lower() != b"x-correlation-id":
            continue
        try:
            return str(uuid.UUID(raw_value.decode("ascii")))
        except (UnicodeDecodeError, ValueError):
            break
    return str(uuid.uuid4())


def _request_outcome(status_code: int) -> str:
    if status_code >= 500:
        return "server_error"
    if status_code >= 400:
        return "client_error"
    return "success"


def _status_failure_code(status_code: int) -> str | None:
    if status_code == 401:
        return "authentication_required"
    if status_code == 403:
        return "authorization_denied"
    if status_code >= 500:
        return "service_error"
    if status_code >= 400:
        return "request_rejected"
    return None


def _set_header(
    headers: MutableSequence[tuple[bytes, bytes]], name: bytes, value: bytes
) -> None:
    headers[:] = [(key, item) for key, item in headers if key.lower() != name]
    headers.append((name, value))
