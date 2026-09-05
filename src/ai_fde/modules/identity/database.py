from __future__ import annotations

import hashlib
import re

WORKER_DATABASE_GROUP = "ai_fde_worker"
WORKER_DATABASE_USER_PATTERN = re.compile(r"ai_fde_worker_[0-9a-f]{12}")
AWS_RDS_TLS_CA_PATH = "/opt/ai-fde/certs/aws-rds-global-bundle.pem"
AWS_RDS_TLS_CA_SHA256 = (
    "sha256:e5bb2084ccf45087bda1c9bffdea0eb15ee67f0b91646106e466714f9de3c7e3"
)


def worker_database_user_for_release(deployment_id: str, release_revision: str) -> str:
    """Return the bounded PostgreSQL login assigned to one immutable release."""

    release_identity = f"{deployment_id}:{release_revision}"
    suffix = hashlib.sha256(release_identity.encode("utf-8")).hexdigest()[:12]
    return f"{WORKER_DATABASE_GROUP}_{suffix}"


def is_worker_database_user(value: str) -> bool:
    return WORKER_DATABASE_USER_PATTERN.fullmatch(value) is not None
