from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_fde.adapters.storage import InMemoryEvidenceStore
from ai_fde.api import runtime_routes
from ai_fde.config import Settings, get_settings
from ai_fde.modules.identity.database import AWS_RDS_TLS_CA_SHA256
from ai_fde.modules.runtime.models import RuntimeHeartbeat
from ai_fde.modules.runtime.readiness import (
    ReadinessReport,
    _database_check,
    _worker_checks,
)


def _settings() -> Settings:
    return Settings(  # type: ignore[call-arg]  # pydantic-settings supports _env_file
        _env_file=None,
        worker_heartbeat_interval_seconds=15,
        worker_heartbeat_max_age_seconds=90,
        readiness_queue_max_age_seconds=600,
    )


def test_worker_readiness_rejects_stale_heartbeat_and_overdue_queue() -> None:
    now = datetime(2026, 9, 4, 20, 0, tzinfo=UTC)
    heartbeat = RuntimeHeartbeat(
        service="ai-fde-worker",
        instance_id="worker-1",
        release_revision="development",
        deployment_id="local-development",
        qualification_mode="development",
        status="RUNNING",
        queue_depth=3,
        oldest_queued_at=now - timedelta(seconds=601),
        last_seen_at=now - timedelta(seconds=91),
    )

    worker, queue = _worker_checks(heartbeat, settings=_settings(), now=now)

    assert worker == {"status": "stale", "age_seconds": 91}
    assert queue == {
        "status": "overdue",
        "depth": 3,
        "oldest_age_seconds": 601,
    }


def test_worker_readiness_rejects_a_future_heartbeat_without_clamping_age() -> None:
    now = datetime(2026, 9, 4, 20, 0, tzinfo=UTC)
    heartbeat = RuntimeHeartbeat(
        service="ai-fde-worker",
        instance_id="worker-future",
        release_revision="development",
        deployment_id="local-development",
        qualification_mode="development",
        status="RUNNING",
        queue_depth=0,
        last_seen_at=now + timedelta(days=365),
    )

    worker, queue = _worker_checks(heartbeat, settings=_settings(), now=now)

    assert worker == {"status": "future", "age_seconds": -(365 * 24 * 60 * 60)}
    assert queue == {
        "status": "ready",
        "depth": 0,
        "oldest_age_seconds": None,
    }


def test_runtime_routes_separate_liveness_version_and_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    app = FastAPI()
    app.state.evidence_store = InMemoryEvidenceStore()
    app.include_router(runtime_routes.router, prefix="/api")
    app.dependency_overrides[get_settings] = lambda: settings
    monkeypatch.setattr(runtime_routes, "get_settings", lambda: settings)
    monkeypatch.setattr(
        runtime_routes,
        "evaluate_readiness",
        lambda _settings, _store: ReadinessReport(
            ready=False,
            dependencies={
                "database": {"status": "ready"},
                "migrations": {"status": "ready"},
                "object_storage": {"status": "ready"},
                "worker": {"status": "missing"},
                "queue": {"status": "unknown"},
            },
        ),
    )
    client = TestClient(app)

    live = client.get("/api/live")
    version = client.get("/api/version")
    ready = client.get("/api/ready")

    assert live.status_code == 200
    assert live.json()["status"] == "live"
    assert version.json()["release_revision"] == "development"
    assert ready.status_code == 503
    assert ready.headers["cache-control"] == "no-store"
    assert ready.json()["dependencies"]["worker"] == {"status": "missing"}
    assert "database_url" not in str(ready.json())


def test_config_requires_heartbeat_freshness_margin() -> None:
    try:
        Settings(  # type: ignore[call-arg]  # pydantic-settings supports _env_file
            _env_file=None,
            worker_heartbeat_interval_seconds=45,
            worker_heartbeat_max_age_seconds=90,
        )
    except ValueError as error:
        assert "maximum age" in str(error)
    else:
        raise AssertionError("Expected an invalid heartbeat freshness configuration.")


def test_production_readiness_reports_and_verifies_the_pinned_database_ca(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Use bytes whose expected digest is injected at the module boundary so this test proves
    # the readiness comparison without embedding a certificate fixture.
    ca_bundle = b"test-rds-ca-bundle"
    observed_digest = f"sha256:{hashlib.sha256(ca_bundle).hexdigest()}"
    monkeypatch.setattr(
        "ai_fde.modules.runtime.readiness.AWS_RDS_TLS_CA_SHA256",
        observed_digest,
    )
    monkeypatch.setattr("pathlib.Path.read_bytes", lambda _path: ca_bundle)

    result = _database_check(cast(Settings, SimpleNamespace(env="production")))

    assert result["status"] == "ready"
    assert result["tls_ca_sha256"] == observed_digest
    assert result["observed_tls_ca_sha256"] == observed_digest


def test_production_readiness_rejects_a_different_database_ca(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("pathlib.Path.read_bytes", lambda _path: b"attacker-ca")

    result = _database_check(cast(Settings, SimpleNamespace(env="production")))

    assert result["status"] == "mismatch"
    assert result["tls_ca_sha256"] == AWS_RDS_TLS_CA_SHA256
    assert result["observed_tls_ca_sha256"] != AWS_RDS_TLS_CA_SHA256
