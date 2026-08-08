from __future__ import annotations

import logging
import signal
import time
from uuid import UUID

from ai_fde.adapters.storage import S3EvidenceStore
from ai_fde.config import get_settings
from ai_fde.db import ensure_local_operator, operator_session
from ai_fde.models import Job
from ai_fde.modules.engagements.service import list_engagements
from ai_fde.modules.knowledge.jobs import fail_job, lease_next_job, process_job

logger = logging.getLogger("ai_fde.worker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


class Worker:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.store = S3EvidenceStore(self.settings)
        self.running = True

    def stop(self, *_args: object) -> None:
        self.running = False

    def run(self) -> None:
        ensure_local_operator(self.settings)
        self.store.ensure_bucket()
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)
        logger.info("AI-FDE worker started for operator %s", self.settings.operator_id)
        while self.running:
            processed = self._process_one()
            if not processed:
                time.sleep(self.settings.worker_poll_seconds)

    def _process_one(self) -> bool:
        with operator_session(self.settings.operator_id) as session:
            engagement_ids = [
                item.id for item in list_engagements(session, self.settings.operator_id)
            ]

        for engagement_id in engagement_ids:
            job_id = self._lease(engagement_id)
            if job_id is None:
                continue
            try:
                with operator_session(self.settings.operator_id) as session:
                    job = session.get(Job, job_id)
                    if job is None:
                        continue
                    process_job(session, self.store, job)
                logger.info("Completed job %s", job_id)
            except Exception as exc:  # noqa: BLE001 - boundary records all job failures
                logger.exception("Job %s failed", job_id)
                with operator_session(self.settings.operator_id) as session:
                    fail_job(session, job_id, str(exc))
            return True
        return False

    def _lease(self, engagement_id: UUID) -> UUID | None:
        with operator_session(self.settings.operator_id) as session:
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
