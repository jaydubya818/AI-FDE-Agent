from __future__ import annotations

import signal
import threading
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from ai_fde.adapters.extraction import BedrockExtractionProvider
from ai_fde.adapters.storage import S3EvidenceStore
from ai_fde.config import get_settings
from ai_fde.db import ensure_local_operator, operator_session
from ai_fde.models import Job, Operator
from ai_fde.modules.design_partner.service import CustomerDataProcessingDeniedError
from ai_fde.modules.engagements.service import list_engagements
from ai_fde.modules.evidence.parser import EvidenceParseError, UnsupportedEvidenceTypeError
from ai_fde.modules.identity.admin import (
    WorkerProvisioningError,
    validate_worker_runtime_authority,
)
from ai_fde.modules.knowledge.extractor import (
    DeterministicFixtureExtractor,
    ExtractionProvider,
    ExtractionProviderError,
)
from ai_fde.modules.knowledge.jobs import (
    EvidenceIntegrityError,
    ExtractionBudgetExceededError,
    ExtractionJobBudget,
    JobLeaseLostError,
    JobProcessingError,
    fail_job,
    lease_next_job,
    process_job,
)
from ai_fde.modules.runtime.service import record_worker_heartbeat
from ai_fde.telemetry import configure_worker_logging, emit_worker_event


@dataclass(frozen=True)
class PublicJobFailure:
    code: str
    message: str
    retryable: bool


def public_job_failure(error: Exception) -> PublicJobFailure:
    if isinstance(error, UnsupportedEvidenceTypeError):
        return PublicJobFailure(
            code="unsupported_evidence_type",
            message="Evidence must use a supported file type and matching content type.",
            retryable=False,
        )
    if isinstance(error, EvidenceParseError):
        return PublicJobFailure(
            code="evidence_parse_rejected",
            message="Evidence could not be parsed safely.",
            retryable=False,
        )
    if isinstance(error, ExtractionProviderError):
        return PublicJobFailure(
            code=error.result_code,
            message="The configured extraction provider could not complete this evidence.",
            retryable=error.retryable,
        )
    if isinstance(error, ExtractionBudgetExceededError):
        return PublicJobFailure(
            code="extraction_budget_exceeded",
            message="Evidence exceeded a configured extraction workload budget.",
            retryable=False,
        )
    if isinstance(error, EvidenceIntegrityError):
        return PublicJobFailure(
            code="evidence_integrity_failed",
            message="The immutable evidence object failed integrity verification.",
            retryable=False,
        )
    if isinstance(error, JobLeaseLostError):
        return PublicJobFailure(
            code="job_lease_lost",
            message="The evidence job lease is no longer owned by this worker.",
            retryable=False,
        )
    if isinstance(error, JobProcessingError):
        return PublicJobFailure(
            code="invalid_evidence_job",
            message="Evidence processing could not be completed because the job is invalid.",
            retryable=False,
        )
    if isinstance(error, CustomerDataProcessingDeniedError):
        return PublicJobFailure(
            code="customer_data_authorization_denied",
            message="Customer-data processing authorization is no longer valid.",
            retryable=False,
        )
    return PublicJobFailure(
        code="evidence_processing_failed",
        message="Evidence processing could not be completed.",
        retryable=True,
    )


class Worker:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.store = S3EvidenceStore(self.settings)
        self.operator_id = self.settings.operator_id
        self.extractor: ExtractionProvider = DeterministicFixtureExtractor()
        if self.settings.extraction_provider == "bedrock":
            self.extractor = BedrockExtractionProvider(self.settings)
        if self.settings.env != "development":
            assert self.settings.worker_operator_id is not None
            self.operator_id = self.settings.worker_operator_id
        self.instance_id = uuid.uuid4().hex
        self.last_job_completed_at: datetime | None = None
        self.last_failure_code: str | None = None
        self.last_heartbeat_monotonic = 0.0
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None
        self.running = True

    def stop(self, *_args: object) -> None:
        self.running = False

    def run(self) -> None:
        configure_worker_logging()
        if self.settings.env == "development":
            ensure_local_operator(self.settings)
        else:
            self._require_current_qualification()
            if self.settings.worker_engagement_id is None:
                raise WorkerProvisioningError(
                    "The worker runtime requires an exact configured engagement binding."
                )
            with operator_session(self.operator_id) as session:
                validate_worker_runtime_authority(
                    session,
                    operator_id=self.operator_id,
                    engagement_id=self.settings.worker_engagement_id,
                    release_revision=self.settings.release_revision,
                    deployment_id=self.settings.deployment_id,
                    deployment_validation_id=self.settings.deployment_validation_id,
                )
        if self.settings.env == "development":
            self.store.ensure_bucket()
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)
        emit_worker_event(
            event="worker.started",
            outcome="success",
            revision=self.settings.release_revision,
            deployment_id=self.settings.deployment_id,
        )
        self._record_heartbeat(status="RUNNING", force=True)
        self._start_heartbeat_loop()
        try:
            while self.running:
                processed = self._process_one()
                if not processed:
                    time.sleep(self.settings.worker_poll_seconds)
        finally:
            self._stop_heartbeat_loop()
            self._record_heartbeat(status="STOPPED", force=True)
            emit_worker_event(
                event="worker.stopped",
                outcome="stopped",
                revision=self.settings.release_revision,
                deployment_id=self.settings.deployment_id,
            )

    def _process_one(self) -> bool:
        self._require_current_qualification()
        if self.settings.env != "development" and self.settings.worker_engagement_id is None:
            return False
        with operator_session(self.operator_id) as session:
            engagement_ids = [
                item.id
                for item in list_engagements(
                    session,
                    self.operator_id,
                    include_sanitized=self.settings.sanitized_data_enabled,
                )
            ]
        if self.settings.worker_engagement_id is not None:
            engagement_ids = [
                engagement_id
                for engagement_id in engagement_ids
                if engagement_id == self.settings.worker_engagement_id
            ]

        for engagement_id in engagement_ids:
            leased = self._lease(engagement_id)
            if leased is None:
                continue
            job_id, lease_token = leased
            correlation_id = None
            started_at = time.perf_counter()
            try:
                with operator_session(self.operator_id) as session:
                    job = session.get(Job, job_id)
                    if job is None:
                        continue
                    correlation_id = _job_correlation_id(job)
                    actor = session.get_one(Operator, self.operator_id)
                    process_job(
                        session,
                        self.store,
                        job,
                        lease_token=lease_token,
                        extractor=self.extractor,
                        actor=actor,
                        budget=ExtractionJobBudget(
                            max_segments=self.settings.extraction_max_segments_per_job,
                            max_provider_calls=(
                                self.settings.extraction_max_provider_calls_per_job
                            ),
                            max_provider_tokens=(
                                self.settings.extraction_max_provider_tokens_per_job
                            ),
                        ),
                        provider_allowed_data_classifications=set(
                            self.settings.bedrock_allowed_data_classifications
                        ),
                        runtime_authority_check=(
                            self._require_current_job_runtime_authority
                        ),
                    )
                emit_worker_event(
                    event="workflow.job.completed",
                    outcome="success",
                    revision=self.settings.release_revision,
                    deployment_id=self.settings.deployment_id,
                    job_id=job_id,
                    correlation_id=correlation_id,
                    duration_ms=round((time.perf_counter() - started_at) * 1000),
                )
                self.last_job_completed_at = datetime.now(UTC)
                self.last_failure_code = None
            except Exception as exc:  # noqa: BLE001 - boundary records all job failures
                failure = public_job_failure(exc)
                event: Literal["workflow.job.failed", "workflow.dependency_failed"] = (
                    "workflow.dependency_failed"
                    if isinstance(exc, ExtractionProviderError)
                    else "workflow.job.failed"
                )
                emit_worker_event(
                    event=event,
                    outcome="failure",
                    revision=self.settings.release_revision,
                    deployment_id=self.settings.deployment_id,
                    level=40,
                    job_id=job_id,
                    correlation_id=correlation_id,
                    duration_ms=round((time.perf_counter() - started_at) * 1000),
                    failure_code=failure.code,
                )
                self.last_failure_code = failure.code
                with operator_session(self.operator_id) as session:
                    fail_job(
                        session,
                        job_id,
                        failure.message,
                        lease_token=lease_token,
                        retryable=failure.retryable,
                        result_code=failure.code,
                        extractor=self.extractor,
                    )
            return True
        return False

    def _lease(self, engagement_id: UUID) -> tuple[UUID, UUID] | None:
        with operator_session(self.operator_id) as session:
            job = lease_next_job(
                session,
                engagement_id=engagement_id,
                lease_seconds=self.settings.worker_lease_seconds,
            )
            if job is None or job.lease_token is None:
                return None
            return job.id, job.lease_token

    def _record_heartbeat(self, *, status: str, force: bool = False) -> None:
        if not getattr(self.settings, "worker_heartbeat_enabled", True):
            return
        current_monotonic = time.monotonic()
        if (
            not force
            and current_monotonic - self.last_heartbeat_monotonic
            < self.settings.worker_heartbeat_interval_seconds
        ):
            return
        with operator_session(self.operator_id) as session:
            if self.settings.env != "development" and status == "RUNNING":
                self._require_current_qualification()
                if self.settings.worker_engagement_id is None:
                    raise WorkerProvisioningError(
                        "The worker runtime requires an exact configured engagement binding."
                    )
                validate_worker_runtime_authority(
                    session,
                    operator_id=self.operator_id,
                    engagement_id=self.settings.worker_engagement_id,
                    release_revision=self.settings.release_revision,
                    deployment_id=self.settings.deployment_id,
                    deployment_validation_id=self.settings.deployment_validation_id,
                )
            record_worker_heartbeat(
                session,
                instance_id=self.instance_id,
                release_revision=self.settings.release_revision,
                deployment_id=self.settings.deployment_id,
                deployment_validation_id=self.settings.deployment_validation_id,
                qualification_mode=self.settings.deployment_qualification_mode,
                operator_id=(
                    self.operator_id if self.settings.env != "development" else None
                ),
                engagement_id=(
                    self.settings.worker_engagement_id
                    if self.settings.env != "development"
                    else None
                ),
                status=status,
                last_job_completed_at=self.last_job_completed_at,
                last_failure_code=self.last_failure_code,
            )
        self.last_heartbeat_monotonic = current_monotonic

    def _require_current_qualification(self) -> None:
        if not getattr(self.settings, "sanitized_data_enabled", False):
            return
        try:
            self.settings.verified_deployment_qualification()
        except ValueError as error:
            raise WorkerProvisioningError(
                "The immutable deployment qualification is no longer current."
            ) from error

    def _require_current_job_runtime_authority(self, now: datetime) -> None:
        if not getattr(self.settings, "sanitized_data_enabled", False):
            raise CustomerDataProcessingDeniedError(
                "Customer-data processing is not enabled for this runtime."
            )
        try:
            self.settings.verified_deployment_qualification(now=now)
        except ValueError as error:
            raise CustomerDataProcessingDeniedError(
                "The deployment qualification is no longer current."
            ) from error

    def _start_heartbeat_loop(self) -> None:
        self._heartbeat_stop.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="ai-fde-worker-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def _stop_heartbeat_loop(self) -> None:
        self._heartbeat_stop.set()
        thread = self._heartbeat_thread
        if thread is not None:
            thread.join(timeout=self.settings.database_connect_timeout_seconds + 2)
        self._heartbeat_thread = None

    def _heartbeat_loop(self) -> None:
        while not self._heartbeat_stop.wait(self.settings.worker_heartbeat_interval_seconds):
            try:
                self._record_heartbeat(status="RUNNING", force=True)
            except Exception as exc:  # noqa: BLE001 - emit bounded dependency telemetry
                if isinstance(exc, WorkerProvisioningError):
                    self.running = False
                    self._heartbeat_stop.set()
                    with suppress(Exception):
                        self._record_heartbeat(status="STOPPED", force=True)
                emit_worker_event(
                    event="workflow.dependency_failed",
                    outcome="failure",
                    revision=self.settings.release_revision,
                    deployment_id=self.settings.deployment_id,
                    level=40,
                    failure_code=(
                        "worker_authority_denied"
                        if isinstance(exc, WorkerProvisioningError)
                        else "worker_heartbeat_failed"
                    ),
                )


def _job_correlation_id(job: Job) -> UUID | None:
    value = job.payload.get("correlation_id")
    if value is None:
        return None
    try:
        return UUID(str(value))
    except ValueError:
        return None


def main() -> None:
    Worker().run()


if __name__ == "__main__":
    main()
