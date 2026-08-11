from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_fde.modules.evidence.parser import UnsupportedEvidenceTypeError
from ai_fde.modules.knowledge.jobs import JobProcessingError
from ai_fde.telemetry import SafeAccessLogMiddleware
from ai_fde.worker import public_job_failure


def test_access_log_excludes_raw_path_query_headers_and_body(caplog) -> None:  # type: ignore[no-untyped-def]
    app = FastAPI()
    app.add_middleware(SafeAccessLogMiddleware)

    @app.post("/evidence/{evidence_id}")
    def receive_evidence(evidence_id: str) -> dict[str, str]:
        return {"id": evidence_id}

    caplog.set_level(logging.INFO, logger="ai_fde.access")
    response = TestClient(app).post(
        "/evidence/private-record?code=secret-authorization-code",
        headers={"authorization": "Bearer secret-token"},
        json={"evidence": "raw customer evidence"},
    )

    assert response.status_code == 200
    assert response.headers["x-request-id"]
    assert "route=/evidence/{evidence_id}" in caplog.text
    for sensitive_value in (
        "private-record",
        "secret-authorization-code",
        "secret-token",
        "raw customer evidence",
    ):
        assert sensitive_value not in caplog.text


def test_unhandled_errors_return_and_log_only_bounded_metadata(caplog) -> None:  # type: ignore[no-untyped-def]
    app = FastAPI()
    app.add_middleware(SafeAccessLogMiddleware)

    @app.get("/failure")
    def fail() -> None:
        raise RuntimeError("raw evidence and provider secret")

    caplog.set_level(logging.INFO, logger="ai_fde.access")
    response = TestClient(app).get("/failure")

    assert response.status_code == 500
    assert response.json() == {
        "detail": "The operator service could not complete the request."
    }
    assert "failure_code=unhandled_application_error" in caplog.text
    assert "exception_type=RuntimeError" in caplog.text
    assert "raw evidence" not in caplog.text
    assert "provider secret" not in caplog.text


def test_worker_failures_have_bounded_public_messages() -> None:
    cases = (
        (
            UnsupportedEvidenceTypeError("private evidence payload"),
            "unsupported_evidence_type",
        ),
        (JobProcessingError("secret job payload"), "invalid_evidence_job"),
        (RuntimeError("provider response contained a secret"), "evidence_processing_failed"),
    )

    for error, expected_code in cases:
        failure = public_job_failure(error)
        assert failure.code == expected_code
        assert "private" not in failure.message
        assert "secret" not in failure.message
        assert "provider response" not in failure.message
