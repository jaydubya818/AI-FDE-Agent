from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from ai_fde.adapters.storage import EvidenceStore
from ai_fde.config import Settings
from ai_fde.db import SessionFactory
from ai_fde.modules.identity.database import (
    AWS_RDS_TLS_CA_PATH,
    AWS_RDS_TLS_CA_SHA256,
    worker_database_user_for_release,
)
from ai_fde.modules.runtime.models import RuntimeHeartbeat
from ai_fde.modules.runtime.qualification import DeploymentQualificationError

EXPECTED_DATABASE_REVISION = "b7e2c5d4a901"


@dataclass(frozen=True)
class ReadinessReport:
    ready: bool
    dependencies: dict[str, dict[str, Any]]


def evaluate_readiness(
    settings: Settings,
    store: EvidenceStore,
    *,
    session_factory: sessionmaker[Session] = SessionFactory,
    now: datetime | None = None,
) -> ReadinessReport:
    """Check exact release dependencies without reading or exposing customer data."""

    timestamp = now or datetime.now(UTC)
    dependencies: dict[str, dict[str, Any]] = {}
    if not settings.sanitized_data_enabled:
        dependencies["qualification"] = {"status": "ready", "mode": "disabled"}
    else:
        try:
            qualification = settings.verified_deployment_qualification(now=timestamp)
            dependencies["qualification"] = {
                "status": "ready",
                "version_id": qualification.version_id,
                "content_digest": qualification.content_digest,
            }
        except (DeploymentQualificationError, ValueError):
            dependencies["qualification"] = {"status": "unavailable"}
    heartbeat: RuntimeHeartbeat | None = None
    heartbeat_timestamp = timestamp
    try:
        with session_factory() as session:
            session.execute(text("SELECT 1"))
            dependencies["database"] = _database_check(settings)
            database_timestamp = session.scalar(text("SELECT clock_timestamp()"))
            if now is None:
                if not isinstance(database_timestamp, datetime):
                    raise RuntimeError("PostgreSQL did not return its current time.")
                heartbeat_timestamp = database_timestamp.astimezone(UTC)
            observed_revision = session.scalar(text("SELECT version_num FROM alembic_version"))
            migration_ready = observed_revision == EXPECTED_DATABASE_REVISION
            dependencies["migrations"] = {
                "status": "ready" if migration_ready else "mismatch",
                "expected_revision": EXPECTED_DATABASE_REVISION,
                "observed_revision": observed_revision or "missing",
            }
            heartbeat = _load_authorized_worker_heartbeat(session, settings=settings)
    except Exception:  # noqa: BLE001 - readiness returns a bounded dependency code
        dependencies["database"] = {"status": "unavailable"}
        dependencies["migrations"] = {
            "status": "unavailable",
            "expected_revision": EXPECTED_DATABASE_REVISION,
        }

    try:
        store.check_ready()
        dependencies["object_storage"] = {"status": "ready"}
    except Exception:  # noqa: BLE001 - readiness must never expose provider details
        dependencies["object_storage"] = {"status": "unavailable"}

    worker, queue = _worker_checks(heartbeat, settings=settings, now=heartbeat_timestamp)
    dependencies["worker"] = worker
    dependencies["queue"] = queue
    return ReadinessReport(
        ready=all(item["status"] == "ready" for item in dependencies.values()),
        dependencies=dependencies,
    )


def _database_check(settings: Settings) -> dict[str, Any]:
    if settings.env != "production":
        return {"status": "ready", "tls_ca": "development"}
    result: dict[str, Any] = {
        "status": "mismatch",
        "tls_ca_path": AWS_RDS_TLS_CA_PATH,
        "tls_ca_sha256": AWS_RDS_TLS_CA_SHA256,
    }
    try:
        ca_bundle = Path(AWS_RDS_TLS_CA_PATH).read_bytes()
    except OSError:
        return result
    if not ca_bundle or len(ca_bundle) > 1024 * 1024:
        return result
    observed_digest = f"sha256:{hashlib.sha256(ca_bundle).hexdigest()}"
    result["observed_tls_ca_sha256"] = observed_digest
    if observed_digest == AWS_RDS_TLS_CA_SHA256:
        result["status"] = "ready"
    return result


def _load_authorized_worker_heartbeat(
    session: Session,
    *,
    settings: Settings,
) -> RuntimeHeartbeat | None:
    """Return only a heartbeat backed by the exact currently active DB binding."""

    return session.scalar(
        select(RuntimeHeartbeat)
        .where(
            RuntimeHeartbeat.service == "ai-fde-worker",
            RuntimeHeartbeat.operator_id == settings.worker_operator_id,
            RuntimeHeartbeat.engagement_id == settings.worker_engagement_id,
            RuntimeHeartbeat.release_revision == settings.release_revision,
            RuntimeHeartbeat.deployment_id == settings.deployment_id,
            RuntimeHeartbeat.deployment_validation_id == settings.deployment_validation_id,
            RuntimeHeartbeat.qualification_mode == settings.deployment_qualification_mode,
            func.ai_fde_active_worker_binding(
                worker_database_user_for_release(
                    settings.deployment_id, settings.release_revision
                ),
                RuntimeHeartbeat.operator_id,
                RuntimeHeartbeat.engagement_id,
                RuntimeHeartbeat.release_revision,
                RuntimeHeartbeat.deployment_id,
                RuntimeHeartbeat.deployment_validation_id,
            ).is_(True),
        )
        .order_by(RuntimeHeartbeat.last_seen_at.desc())
        .limit(1)
    )


def _worker_checks(
    heartbeat: RuntimeHeartbeat | None,
    *,
    settings: Settings,
    now: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if heartbeat is None:
        return {"status": "missing"}, {"status": "unknown"}

    heartbeat_delta_seconds = (now - heartbeat.last_seen_at).total_seconds()
    heartbeat_age = int(heartbeat_delta_seconds)
    heartbeat_is_future = heartbeat_delta_seconds < 0
    worker_ready = (
        heartbeat.status == "RUNNING"
        and not heartbeat_is_future
        and heartbeat_age <= settings.worker_heartbeat_max_age_seconds
    )
    worker: dict[str, Any] = {
        "status": "ready" if worker_ready else "future" if heartbeat_is_future else "stale",
        "age_seconds": heartbeat_age,
    }
    if heartbeat.last_failure_code:
        worker["last_failure_code"] = heartbeat.last_failure_code

    oldest_age: int | None = None
    oldest_is_future = False
    if heartbeat.oldest_queued_at is not None:
        oldest_delta_seconds = (now - heartbeat.oldest_queued_at).total_seconds()
        oldest_age = int(oldest_delta_seconds)
        oldest_is_future = oldest_delta_seconds < 0
    queue_ready = (
        not oldest_is_future
        and (oldest_age is None or oldest_age <= settings.readiness_queue_max_age_seconds)
    )
    queue: dict[str, Any] = {
        "status": "ready" if queue_ready else "future" if oldest_is_future else "overdue",
        "depth": heartbeat.queue_depth,
        "oldest_age_seconds": oldest_age,
    }
    return worker, queue
