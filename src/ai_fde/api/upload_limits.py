from __future__ import annotations

from starlette.datastructures import UploadFile
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ai_fde.modules.evidence.service import MAX_EVIDENCE_BYTES, EvidenceTooLargeError

UPLOAD_READ_CHUNK_BYTES = 64 * 1024
MAX_MULTIPART_ENVELOPE_BYTES = 64 * 1024
MAX_EVIDENCE_REQUEST_BYTES = MAX_EVIDENCE_BYTES + MAX_MULTIPART_ENVELOPE_BYTES


class _RequestBodyTooLarge(RuntimeError):
    pass


class EvidenceUploadLimitMiddleware:
    """Reject oversized evidence request bodies before multipart parsing buffers them."""

    def __init__(self, app: ASGIApp, max_request_bytes: int = MAX_EVIDENCE_REQUEST_BYTES) -> None:
        self.app = app
        self.max_request_bytes = max_request_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not _is_evidence_upload(scope):
            await self.app(scope, receive, send)
            return

        content_length = _content_length(scope)
        if content_length is not None and content_length > self.max_request_bytes:
            await _payload_too_large_response(scope, receive, send)
            return

        received_bytes = 0

        async def limited_receive() -> Message:
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self.max_request_bytes:
                    raise _RequestBodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _RequestBodyTooLarge:
            await _payload_too_large_response(scope, receive, send)


async def read_evidence_upload(upload: UploadFile) -> bytes:
    """Read at most one byte beyond the evidence limit, never the complete oversized file."""

    content = bytearray()
    while len(content) <= MAX_EVIDENCE_BYTES:
        remaining = MAX_EVIDENCE_BYTES + 1 - len(content)
        chunk = await upload.read(min(UPLOAD_READ_CHUNK_BYTES, remaining))
        if not chunk:
            return bytes(content)
        content.extend(chunk)
    raise EvidenceTooLargeError("Evidence exceeds the 5 MB vertical-slice limit.")


def _is_evidence_upload(scope: Scope) -> bool:
    return (
        scope["type"] == "http"
        and scope.get("method") == "POST"
        and scope.get("path", "").startswith("/api/engagements/")
        and scope.get("path", "").endswith("/evidence")
    )


def _content_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", []):
        if name.lower() != b"content-length":
            continue
        try:
            parsed = int(value)
        except ValueError:
            return None
        return parsed if parsed >= 0 else None
    return None


async def _payload_too_large_response(scope: Scope, receive: Receive, send: Send) -> None:
    response = JSONResponse(
        {"detail": "Evidence exceeds the 5 MB vertical-slice limit."},
        status_code=413,
    )
    await response(scope, receive, send)
