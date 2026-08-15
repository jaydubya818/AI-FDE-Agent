from __future__ import annotations

import logging
import signal
import time
from dataclasses import dataclass
from uuid import UUID

from ai_fde.adapters.extraction import BedrockExtractionProvider
from ai_fde.adapters.storage import S3EvidenceStore
from ai_fde.config import get_settings
from ai_fde.db import ensure_local_operator, operator_session
from ai_fde.models import Job, Operator
from ai_fde.modules.engagements.service import list_engagements
from ai_fde.modules.evidence.parser import EvidenceParseError, UnsupportedEvidenceTypeError
from ai_fde.modules.identity.admin import validate_worker_identity
from ai_fde.modules.knowledge.extractor import (
    DeterministicFixtureExtractor,
    ExtractionProvider,
    ExtractionProviderError,
)
from ai_fde.modules.knowledge.jobs import (
    JobProcessingError,
    fail_job,
    lease_next_job,
    process_job,
)

logger = logging.getLogger("ai_fde.worker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


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
    if isinstance(error, JobProcessingError):
        return PublicJobFailure(
            code="invalid_evidence_job",
            message="Evidence processing could not be completed because the job is invalid.",
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
        self.running = True

    def stop(self, *_args: object) -> None:
        self.running = False

    def run(self) -> None:
        if self.settings.env == "development":
            ensure_local_operator(self.settings)
        else:
            with operator_session(self.operator_id) as session:
                validate_worker_identity(session, operator_id=self.operator_id)
        self.store.ensure_bucket()
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)
        logger.info("AI-FDE worker started for operator %s", self.operator_id)
        while self.running:
            processed = self._process_one()
            if not processed:
                time.sleep(self.settings.worker_poll_seconds)

    def _process_one(self) -> bool:
        with operator_session(self.operator_id) as session:
            engagement_ids = [
                item.id
                for item in list_engagements(
                    session,
                    self.operator_id,
                    include_sanitized=self.settings.sanitized_data_enabled,
                )
            ]

        for engagement_id in engagement_ids:
            job_id = self._lease(engagement_id)
            if job_id is None:
                continue
            try:
                with operator_session(self.operator_id) as session:
                    job = session.get(Job, job_id)
                    if job is None:
                        continue
                    actor = session.get_one(Operator, self.operator_id)
                    process_job(
                        session,
                        self.store,
                        job,
                        extractor=self.extractor,
                        actor=actor,
                    )
                logger.info("Completed job %s", job_id)
            except Exception as exc:  # noqa: BLE001 - boundary records all job failures
                failure = public_job_failure(exc)
                logger.error("Job failed job_id=%s failure_code=%s", job_id, failure.code)
                with operator_session(self.operator_id) as session:
                    fail_job(
                        session,
                        job_id,
                        failure.message,
                        retryable=failure.retryable,
                        result_code=failure.code,
                        extractor=self.extractor,
                    )
            return True
        return False

    def _lease(self, engagement_id: UUID) -> UUID | None:
        with operator_session(self.operator_id) as session:
            job = lease_next_job(
                session,
                engagement_id=engagement_id,
                lease_seconds=self.settings.worker_lease_seconds,
            )
            return job.id if job else None


def main() -> None:
    Worker().run()


if __name__ == "__main__":
    main()
