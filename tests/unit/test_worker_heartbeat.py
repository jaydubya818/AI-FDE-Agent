from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NoReturn, cast

import pytest

from ai_fde.modules.identity.admin import WorkerProvisioningError
from ai_fde.worker import Worker


class _Store:
    def ensure_bucket(self) -> None:
        return None


def test_synthetic_demo_skips_heartbeat_and_keeps_the_app_database_role() -> None:
    worker = cast(Any, Worker.__new__(Worker))
    worker.settings = SimpleNamespace(worker_heartbeat_enabled=False)
    worker.last_heartbeat_monotonic = 41.0

    worker._record_heartbeat(status="RUNNING", force=True)

    assert worker.last_heartbeat_monotonic == 41.0
    script = (
        Path(__file__).resolve().parents[2] / "scripts" / "rehearse-sample-demo.sh"
    ).read_text()
    assert "AI_FDE_WORKER_HEARTBEAT_ENABLED=false" in script
    assert "postgresql+psycopg://ai_fde_worker_" not in script


def test_default_local_stack_entrypoints_disable_only_development_heartbeats() -> None:
    root = Path(__file__).resolve().parents[2]
    package = json.loads((root / "package.json").read_text())
    worker_command = package["scripts"]["dev:worker"]
    assert worker_command == (
        "AI_FDE_WORKER_HEARTBEAT_ENABLED=false "
        "PYTHONPATH=src uv run python -m ai_fde.worker"
    )
    assert package["scripts"]["dev"].count("pnpm dev:worker") == 1

    makefile = (root / "Makefile").read_text()
    assert "dev:\n\tAI_FDE_WORKER_HEARTBEAT_ENABLED=false pnpm dev\n" in makefile
    runbook = (root / "docs" / "runbooks" / "sample-demo.md").read_text()
    assert "Both `pnpm dev` and `make dev` explicitly disable deployment heartbeats" in runbook
    assert "validation rejects disabled heartbeats outside development" in runbook


def test_disabled_development_heartbeat_never_opens_a_database_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = cast(Any, Worker.__new__(Worker))
    worker.settings = SimpleNamespace(worker_heartbeat_enabled=False)
    worker.last_heartbeat_monotonic = 0.0

    def unexpected_session(_operator_id: object) -> NoReturn:
        raise AssertionError("disabled development heartbeat opened a database session")

    monkeypatch.setattr("ai_fde.worker.operator_session", unexpected_session)
    worker._record_heartbeat(status="RUNNING", force=True)

    assert worker.last_heartbeat_monotonic == 0.0


def test_worker_heartbeat_continues_while_job_processing_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = cast(Any, Worker.__new__(Worker))
    worker.settings = SimpleNamespace(
        env="development",
        release_revision="a" * 40,
        deployment_id="qualification-test",
        worker_poll_seconds=0.01,
        worker_heartbeat_interval_seconds=0.01,
        database_connect_timeout_seconds=1,
    )
    worker.store = _Store()
    worker.operator_id = None
    worker.running = True
    worker._heartbeat_stop = threading.Event()
    worker._heartbeat_thread = None
    heartbeat_statuses: list[str] = []
    two_background_heartbeats = threading.Event()

    def record_heartbeat(*, status: str, force: bool = False) -> None:
        del force
        heartbeat_statuses.append(status)
        if heartbeat_statuses.count("RUNNING") >= 3:
            two_background_heartbeats.set()

    def process_one() -> bool:
        assert two_background_heartbeats.wait(timeout=1)
        worker.running = False
        return True

    worker._record_heartbeat = record_heartbeat
    worker._process_one = process_one
    monkeypatch.setattr("ai_fde.worker.ensure_local_operator", lambda _settings: None)
    monkeypatch.setattr("ai_fde.worker.configure_worker_logging", lambda: None)
    monkeypatch.setattr("ai_fde.worker.emit_worker_event", lambda **_fields: None)
    monkeypatch.setattr("ai_fde.worker.signal.signal", lambda *_args: None)

    worker.run()

    assert heartbeat_statuses[:3] == ["RUNNING", "RUNNING", "RUNNING"]
    assert heartbeat_statuses[-1] == "STOPPED"


def test_production_running_heartbeat_revalidates_exact_worker_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = cast(Any, Worker.__new__(Worker))
    worker_id = uuid.uuid4()
    engagement_id = uuid.uuid4()
    worker.settings = SimpleNamespace(
        env="production",
        worker_engagement_id=engagement_id,
        worker_heartbeat_interval_seconds=15,
        release_revision="a" * 40,
        deployment_id="qualification-test",
        deployment_validation_id="sha256:" + ("b" * 64),
        deployment_qualification_mode="controlled-design-partner",
    )
    worker.operator_id = worker_id
    worker.instance_id = "worker-1"
    worker.last_job_completed_at = None
    worker.last_failure_code = None
    worker.last_heartbeat_monotonic = 0.0
    session = object()
    validations: list[tuple[Any, uuid.UUID, uuid.UUID]] = []
    writes: list[str] = []

    @contextmanager
    def scoped_session(_operator_id: object) -> Iterator[object]:
        yield session

    def validate_authority(
        received_session: object,
        *,
        operator_id: uuid.UUID,
        engagement_id: uuid.UUID,
        release_revision: str,
        deployment_id: str,
        deployment_validation_id: str | None,
    ) -> None:
        assert release_revision == "a" * 40
        assert deployment_id == "qualification-test"
        assert deployment_validation_id == "sha256:" + ("b" * 64)
        validations.append((received_session, operator_id, engagement_id))

    def record_heartbeat(_session: object, **fields: object) -> None:
        writes.append(cast(str, fields["status"]))

    monkeypatch.setattr("ai_fde.worker.operator_session", scoped_session)
    monkeypatch.setattr("ai_fde.worker.validate_worker_runtime_authority", validate_authority)
    monkeypatch.setattr("ai_fde.worker.record_worker_heartbeat", record_heartbeat)

    worker._record_heartbeat(status="RUNNING", force=True)

    assert validations == [(session, worker_id, engagement_id)]
    assert writes == ["RUNNING"]

    def deny_authority(*_args: object, **_kwargs: object) -> NoReturn:
        raise WorkerProvisioningError("revoked")

    monkeypatch.setattr("ai_fde.worker.validate_worker_runtime_authority", deny_authority)

    with pytest.raises(WorkerProvisioningError, match="revoked"):
        worker._record_heartbeat(status="RUNNING", force=True)

    assert writes == ["RUNNING"]


def test_production_worker_refuses_running_without_an_engagement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = cast(Any, Worker.__new__(Worker))
    worker.settings = SimpleNamespace(env="production", worker_engagement_id=None)
    worker.operator_id = uuid.uuid4()
    emitted: list[dict[str, object]] = []
    monkeypatch.setattr("ai_fde.worker.configure_worker_logging", lambda: None)
    monkeypatch.setattr(
        "ai_fde.worker.emit_worker_event",
        lambda **fields: emitted.append(fields),
    )

    with pytest.raises(WorkerProvisioningError, match="exact configured engagement"):
        worker.run()

    assert emitted == []


def test_runtime_authority_loss_marks_heartbeat_stopped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = cast(Any, Worker.__new__(Worker))
    worker.settings = SimpleNamespace(
        worker_heartbeat_interval_seconds=0.01,
        release_revision="a" * 40,
        deployment_id="qualification-test",
    )
    worker.running = True
    worker._heartbeat_stop = threading.Event()
    statuses: list[str] = []
    emitted: list[dict[str, object]] = []

    def record_heartbeat(*, status: str, force: bool = False) -> None:
        del force
        statuses.append(status)
        if status == "RUNNING":
            raise WorkerProvisioningError("revoked")

    monkeypatch.setattr(worker, "_record_heartbeat", record_heartbeat)
    monkeypatch.setattr(
        "ai_fde.worker.emit_worker_event",
        lambda **fields: emitted.append(fields),
    )

    worker._heartbeat_loop()

    assert worker.running is False
    assert statuses == ["RUNNING", "STOPPED"]
    assert emitted[0]["failure_code"] == "worker_authority_denied"
