from __future__ import annotations

import json
import logging
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_fde.modules.evidence.parser import UnsupportedEvidenceTypeError
from ai_fde.modules.knowledge.jobs import EvidenceIntegrityError, JobProcessingError
from ai_fde.modules.shared import record_audit
from ai_fde.telemetry import SafeAccessLogMiddleware, emit_worker_event
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
    events = [json.loads(record.message) for record in caplog.records]
    completed = next(event for event in events if event["event"] == "http.request.completed")
    assert completed["route"] == "/evidence/{evidence_id}"
    assert completed["outcome"] == "success"
    assert completed["status_code"] == 200
    assert completed["request_id"] == response.headers["x-request-id"]
    assert completed["correlation_id"] == response.headers["x-correlation-id"]
    assert completed["trace_id"] == completed["correlation_id"].replace("-", "")
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
    events = [json.loads(record.message) for record in caplog.records]
    failed = next(event for event in events if event["event"] == "http.request.failed")
    completed = next(event for event in events if event["event"] == "http.request.completed")
    assert failed["failure_code"] == "unhandled_application_error"
    assert failed["exception_type"] == "RuntimeError"
    assert completed["outcome"] == "server_error"
    assert "raw evidence" not in caplog.text
    assert "provider secret" not in caplog.text


def test_valid_correlation_id_is_propagated_and_invalid_value_is_discarded(caplog) -> None:  # type: ignore[no-untyped-def]
    app = FastAPI()
    app.add_middleware(SafeAccessLogMiddleware)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    caplog.set_level(logging.INFO, logger="ai_fde.access")
    supplied = "f2b43bc6-b370-437d-a692-bc6b2e084d1b"
    accepted = TestClient(app).get("/health", headers={"x-correlation-id": supplied})
    rejected = TestClient(app).get(
        "/health",
        headers={"x-correlation-id": "private-customer-value"},
    )

    assert accepted.headers["x-correlation-id"] == supplied
    assert rejected.headers["x-correlation-id"] != "private-customer-value"
    UUID(rejected.headers["x-correlation-id"])
    assert "private-customer-value" not in caplog.text


def test_auth_denial_emits_stable_bounded_event(caplog) -> None:  # type: ignore[no-untyped-def]
    app = FastAPI()
    app.add_middleware(SafeAccessLogMiddleware)

    @app.get("/protected")
    def protected() -> dict[str, str]:
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="private policy detail")

    caplog.set_level(logging.INFO, logger="ai_fde.access")
    response = TestClient(app).get("/protected")

    events = [json.loads(record.message) for record in caplog.records]
    denied = next(event for event in events if event["event"] == "auth.denied")
    assert response.status_code == 403
    assert denied["failure_code"] == "authorization_denied"
    assert denied["route"] == "/protected"
    assert "private policy detail" not in caplog.text


def test_request_correlation_id_flows_into_domain_audit_records() -> None:
    class CaptureSession:
        event = None

        def add(self, event) -> None:  # type: ignore[no-untyped-def]
            self.event = event

    capture = CaptureSession()
    app = FastAPI()
    app.add_middleware(SafeAccessLogMiddleware)

    @app.post("/audit")
    def audit() -> dict[str, str]:
        event = record_audit(
            capture,  # type: ignore[arg-type]
            engagement_id=UUID("00000000-0000-4000-8000-000000000010"),
            actor_id=UUID("00000000-0000-4000-8000-000000000011"),
            action="qualification.checked",
            target_type="qualification",
            target_id=UUID("00000000-0000-4000-8000-000000000012"),
        )
        return {"correlation_id": str(event.correlation_id)}

    supplied = "f2b43bc6-b370-437d-a692-bc6b2e084d1b"
    response = TestClient(app).post("/audit", headers={"x-correlation-id": supplied})

    assert response.status_code == 200
    assert response.json()["correlation_id"] == supplied
    assert response.headers["x-correlation-id"] == supplied


def test_worker_failures_have_bounded_public_messages() -> None:
    cases = (
        (
            UnsupportedEvidenceTypeError("private evidence payload"),
            "unsupported_evidence_type",
        ),
        (EvidenceIntegrityError("secret object metadata"), "evidence_integrity_failed"),
        (JobProcessingError("secret job payload"), "invalid_evidence_job"),
        (RuntimeError("provider response contained a secret"), "evidence_processing_failed"),
    )

    for error, expected_code in cases:
        failure = public_job_failure(error)
        assert failure.code == expected_code
        assert "private" not in failure.message
        assert "secret" not in failure.message
        assert "provider response" not in failure.message


def test_worker_dependency_event_is_structured_and_bounded(caplog) -> None:  # type: ignore[no-untyped-def]
    caplog.set_level(logging.INFO, logger="ai_fde.worker")
    correlation_id = UUID("f2b43bc6-b370-437d-a692-bc6b2e084d1b")

    emit_worker_event(
        event="workflow.dependency_failed",
        outcome="failure",
        revision="a" * 40,
        deployment_id="qualification-test",
        level=logging.ERROR,
        job_id=UUID("00000000-0000-4000-8000-000000000020"),
        correlation_id=correlation_id,
        duration_ms=125,
        failure_code="provider_timeout",
    )

    [event] = [json.loads(record.message) for record in caplog.records]
    assert event["service"] == "ai-fde-worker"
    assert event["event"] == "workflow.dependency_failed"
    assert event["correlation_id"] == str(correlation_id)
    assert event["failure_code"] == "provider_timeout"
    assert "customer" not in caplog.text
