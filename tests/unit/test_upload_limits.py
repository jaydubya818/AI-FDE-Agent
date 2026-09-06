from __future__ import annotations

import asyncio
from io import BytesIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile

from ai_fde.api.upload_limits import (
    MAX_EVIDENCE_REQUEST_BYTES,
    EvidenceUploadLimitMiddleware,
    read_evidence_upload,
)
from ai_fde.modules.evidence.service import MAX_EVIDENCE_BYTES, EvidenceTooLargeError


class TrackingBytesIO(BytesIO):
    bytes_read = 0

    def read(self, size: int | None = -1) -> bytes:
        chunk = super().read(-1 if size is None else size)
        self.bytes_read += len(chunk)
        return chunk


def test_bounded_upload_reader_stops_after_the_first_oversized_byte() -> None:
    source = TrackingBytesIO(b"x" * (MAX_EVIDENCE_BYTES + 100_000))
    upload = UploadFile(file=source, filename="large.md")

    with pytest.raises(EvidenceTooLargeError, match="5 MB"):
        asyncio.run(read_evidence_upload(upload))

    assert source.bytes_read == MAX_EVIDENCE_BYTES + 1
    assert source.tell() < len(source.getvalue())


def test_request_limit_rejects_before_the_upload_handler_runs() -> None:
    app = FastAPI()
    app.add_middleware(EvidenceUploadLimitMiddleware)
    handler_called = False

    @app.post("/api/engagements/example/evidence")
    def upload_handler() -> dict[str, bool]:
        nonlocal handler_called
        handler_called = True
        return {"accepted": True}

    with TestClient(app) as client:
        response = client.post(
            "/api/engagements/example/evidence",
            files={"file": ("large.md", b"x" * (MAX_EVIDENCE_REQUEST_BYTES + 1))},
        )

    assert response.status_code == 413
    assert response.json() == {"detail": "Evidence exceeds the 5 MB vertical-slice limit."}
    assert handler_called is False
