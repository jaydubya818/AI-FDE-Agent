from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_fde.adapters.storage import EvidenceStore
from ai_fde.models import EvidenceAsset, Job, Operator
from ai_fde.modules.evidence.parser import (
    UnsupportedEvidenceTypeError,
    validate_evidence_upload_metadata,
)
from ai_fde.modules.shared import publish_domain_event, record_audit

MAX_EVIDENCE_BYTES = 5 * 1024 * 1024


class EvidenceValidationError(ValueError):
    pass


def create_evidence_asset(
    session: Session,
    store: EvidenceStore,
    *,
    engagement_id: UUID,
    operator: Operator,
    file_name: str,
    content_type: str,
    content: bytes,
    source_type: str = "upload",
    source_timestamp: datetime | None = None,
) -> EvidenceAsset:
    safe_name = Path(file_name).name.strip()
    if not safe_name or safe_name in {".", ".."}:
        raise EvidenceValidationError("Evidence needs a valid file name.")
    if not content:
        raise EvidenceValidationError("Evidence cannot be empty.")
    if len(content) > MAX_EVIDENCE_BYTES:
        raise EvidenceValidationError("Evidence exceeds the 5 MB vertical-slice limit.")
    try:
        validate_evidence_upload_metadata(content_type, safe_name)
    except UnsupportedEvidenceTypeError as exc:
        raise EvidenceValidationError(str(exc)) from exc

    digest = hashlib.sha256(content).hexdigest()
    existing = session.scalar(
        select(EvidenceAsset).where(
            EvidenceAsset.engagement_id == engagement_id,
            EvidenceAsset.content_hash == digest,
        )
    )
    if existing is not None:
        return existing

    storage_key = f"engagements/{engagement_id}/evidence/{digest}/{safe_name}"
    store.put(storage_key, content, content_type)

    asset = EvidenceAsset(
        engagement_id=engagement_id,
        file_name=safe_name,
        content_type=content_type,
        content_hash=digest,
        byte_count=len(content),
        storage_key=storage_key,
        source_type=source_type,
        source_timestamp=source_timestamp,
        status="queued",
        created_by_id=operator.id,
    )
    session.add(asset)
    session.flush()

    session.add(
        Job(
            engagement_id=engagement_id,
            kind="ingest_evidence",
            payload={"evidence_asset_id": str(asset.id)},
            idempotency_key=f"evidence:{asset.id}:ingest:v1",
        )
    )
    record_audit(
        session,
        engagement_id=engagement_id,
        actor_id=operator.id,
        action="evidence.queued",
        target_type="evidence_asset",
        target_id=asset.id,
        detail={
            "file_name": safe_name,
            "source_type": source_type,
            "content_hash": digest,
            "byte_count": len(content),
        },
    )
    publish_domain_event(
        session,
        engagement_id=engagement_id,
        event_type="evidence.queued",
        aggregate_type="evidence_asset",
        aggregate_id=asset.id,
        payload={"source_type": source_type},
    )
    return asset


def list_evidence(session: Session, engagement_id: UUID) -> list[EvidenceAsset]:
    statement = (
        select(EvidenceAsset)
        .where(EvidenceAsset.engagement_id == engagement_id)
        .order_by(EvidenceAsset.created_at.desc())
    )
    return list(session.scalars(statement))
