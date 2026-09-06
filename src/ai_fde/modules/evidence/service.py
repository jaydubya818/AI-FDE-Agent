from __future__ import annotations

import hashlib
import unicodedata
from datetime import datetime
from functools import partial
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_fde.adapters.storage import EvidenceStore
from ai_fde.db import register_transaction_rollback_compensation
from ai_fde.models import EvidenceAsset, Job, Operator
from ai_fde.modules.evidence.parser import (
    UnsupportedEvidenceTypeError,
    validate_evidence_upload_metadata,
)
from ai_fde.modules.shared import publish_domain_event, record_audit
from ai_fde.telemetry import current_correlation_id

MAX_EVIDENCE_BYTES = 5 * 1024 * 1024
MAX_EVIDENCE_FILE_NAME_CHARACTERS = 512
UNSAFE_FILE_NAME_CHARACTERS = frozenset('/\\<>:"|?*%')
WINDOWS_RESERVED_FILE_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)


class EvidenceValidationError(ValueError):
    pass


class EvidenceTooLargeError(EvidenceValidationError):
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
    design_partner_qualification_id: UUID | None = None,
    authorized_source_key: str | None = None,
    authorized_workflow_class: str | None = None,
    data_classification: str | None = None,
) -> EvidenceAsset:
    qualification_context = (
        design_partner_qualification_id,
        authorized_source_key,
        authorized_workflow_class,
        data_classification,
    )
    if any(value is not None for value in qualification_context) and not all(
        value is not None for value in qualification_context
    ):
        raise EvidenceValidationError(
            "Qualified evidence requires qualification, source, workflow, and classification."
        )
    safe_name = normalize_evidence_file_name(file_name)
    if not content:
        raise EvidenceValidationError("Evidence cannot be empty.")
    if len(content) > MAX_EVIDENCE_BYTES:
        raise EvidenceTooLargeError("Evidence exceeds the 5 MB vertical-slice limit.")
    if design_partner_qualification_id is not None:
        media_type = content_type.partition(";")[0].strip().casefold()
        suffix = Path(safe_name).suffix.casefold()
        if media_type not in {"text/plain", "text/markdown"} or suffix not in {
            ".txt",
            ".md",
        }:
            raise EvidenceValidationError(
                "Qualified customer data must be one plain-text or Markdown document."
            )
        try:
            qualified_text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise EvidenceValidationError(
                "Qualified customer data must contain valid UTF-8 text."
            ) from exc
        if not qualified_text.strip() or "\x00" in qualified_text:
            raise EvidenceValidationError(
                "Qualified customer data must contain readable UTF-8 text."
            )
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
        existing_context = (
            existing.design_partner_qualification_id,
            existing.authorized_source_key,
            existing.authorized_workflow_class,
            existing.data_classification,
        )
        if existing_context != qualification_context:
            raise EvidenceValidationError(
                "Matching evidence already exists under a different authorization context."
            )
        if (
            design_partner_qualification_id is not None
            and existing.storage_version_id is None
        ):
            raise EvidenceValidationError(
                "Qualified evidence without immutable object provenance cannot be reused."
            )
        return existing

    storage_key = f"engagements/{engagement_id}/evidence/{digest}/{safe_name}"
    stored_version = store.put(storage_key, content, content_type)
    try:
        register_transaction_rollback_compensation(
            session,
            partial(store.delete_version, stored_version),
        )
    except Exception:
        store.delete_version(stored_version)
        raise

    asset = EvidenceAsset(
        engagement_id=engagement_id,
        file_name=safe_name,
        content_type=content_type,
        content_hash=digest,
        byte_count=len(content),
        storage_key=storage_key,
        storage_version_id=stored_version.version_id,
        source_type=source_type,
        source_timestamp=source_timestamp,
        design_partner_qualification_id=design_partner_qualification_id,
        authorized_source_key=authorized_source_key,
        authorized_workflow_class=authorized_workflow_class,
        data_classification=data_classification,
        status="queued",
        created_by_id=operator.id,
    )
    session.add(asset)
    session.flush()

    job_payload = {"evidence_asset_id": str(asset.id)}
    correlation_id = current_correlation_id()
    if correlation_id is not None:
        job_payload["correlation_id"] = str(correlation_id)
    session.add(
        Job(
            engagement_id=engagement_id,
            kind="ingest_evidence",
            payload=job_payload,
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


def normalize_evidence_file_name(file_name: str) -> str:
    """Return one display-safe basename, never a caller-controlled path."""

    canonical = unicodedata.normalize("NFC", file_name)
    if any(unicodedata.category(character).startswith("C") for character in canonical):
        raise EvidenceValidationError("Evidence needs one safe file basename.")
    normalized = canonical.strip()
    stem = normalized.partition(".")[0].upper()
    if (
        not normalized
        or len(normalized) > MAX_EVIDENCE_FILE_NAME_CHARACTERS
        or normalized in {".", ".."}
        or normalized.startswith(".")
        or normalized.endswith(".")
        or any(character in UNSAFE_FILE_NAME_CHARACTERS for character in normalized)
        or stem in WINDOWS_RESERVED_FILE_NAMES
    ):
        raise EvidenceValidationError("Evidence needs one safe file basename.")
    return normalized
