from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import yaml
from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from ai_fde.adapters.storage import EvidenceStore
from ai_fde.db import operator_session
from ai_fde.models import (
    Assertion,
    AssertionEvidence,
    AuditEvent,
    CandidateClaim,
    ClaimEvidence,
    Contradiction,
    EconomicCase,
    Engagement,
    EngagementAssessment,
    EngagementDeletionReceipt,
    EngagementExport,
    EngagementMember,
    EvidenceAsset,
    EvidenceSegment,
    ExtractionRun,
    ImplementationArtifact,
    Job,
    OperatingEntity,
    Operator,
    OutboxEvent,
    ReviewDecision,
    WorkflowStep,
    WorkflowVersion,
)
from ai_fde.modules.identity.service import authorize_engagement
from ai_fde.modules.shared import publish_domain_event, record_audit

EXPORT_SCHEMA_VERSION = "1.0.0"
MAX_EXPORT_SOURCE_BYTES = 64 * 1024 * 1024
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)

FINGERPRINT_MODELS: tuple[type[Any], ...] = (
    EngagementMember,
    EngagementAssessment,
    EvidenceAsset,
    EvidenceSegment,
    ExtractionRun,
    CandidateClaim,
    ClaimEvidence,
    ReviewDecision,
    OperatingEntity,
    Assertion,
    AssertionEvidence,
    Contradiction,
    WorkflowVersion,
    WorkflowStep,
    EconomicCase,
    ImplementationArtifact,
)
ARCHIVE_MODELS: tuple[type[Any], ...] = (*FINGERPRINT_MODELS, AuditEvent)
DELETE_COUNT_MODELS: tuple[type[Any], ...] = (
    *ARCHIVE_MODELS,
    Job,
    OutboxEvent,
    EngagementExport,
)


class DataLifecycleError(ValueError):
    """The requested lifecycle transition violates a product invariant."""


class ExportGenerationError(RuntimeError):
    """The portability archive could not be generated safely."""


class DeletionExecutionError(RuntimeError):
    """The deletion operation failed after entering its write-blocked state."""


@dataclass(frozen=True)
class ExportSnapshot:
    engagement: Engagement
    records: dict[str, list[dict[str, Any]]]
    operators: list[dict[str, Any]]
    source_fingerprint: str
    record_count: int
    evidence_assets: list[EvidenceAsset]


@dataclass(frozen=True)
class GeneratedExport:
    record: EngagementExport
    content: bytes


@dataclass(frozen=True)
class DeletionPlan:
    receipt_id: UUID
    engagement_id: UUID
    evidence_keys: tuple[str, ...]


def set_retention_deadline(
    session: Session,
    *,
    engagement: Engagement,
    operator: Operator,
    retain_until: datetime,
    now: datetime | None = None,
) -> Engagement:
    timestamp = now or datetime.now(UTC)
    normalized = _aware_utc(retain_until)
    if engagement.data_lifecycle_status != "active":
        raise DataLifecycleError("Retention cannot change after deletion has started.")
    if normalized <= timestamp:
        raise DataLifecycleError("The retention deadline must be in the future.")
    if engagement.retention_expires_at is not None:
        current = _aware_utc(engagement.retention_expires_at)
        if normalized < current:
            raise DataLifecycleError("V1 retention deadlines can be extended but not shortened.")
    previous = engagement.retention_expires_at
    engagement.retention_expires_at = normalized
    record_audit(
        session,
        engagement_id=engagement.id,
        actor_id=operator.id,
        action="engagement.retention_updated",
        target_type="engagement",
        target_id=engagement.id,
        detail={
            "previous_retention_expires_at": _iso(previous),
            "retention_expires_at": normalized.isoformat(),
        },
    )
    publish_domain_event(
        session,
        engagement_id=engagement.id,
        event_type="engagement.retention_updated",
        aggregate_type="engagement",
        aggregate_id=engagement.id,
        payload={"retention_expires_at": normalized.isoformat()},
    )
    return engagement


def create_engagement_export(
    session: Session,
    store: EvidenceStore,
    *,
    engagement_id: UUID,
    operator: Operator,
    now: datetime | None = None,
) -> GeneratedExport:
    snapshot = build_export_snapshot(session, engagement_id)
    if snapshot.engagement.data_lifecycle_status != "active":
        raise DataLifecycleError("Exports cannot start after deletion has started.")
    exported_at = now or datetime.now(UTC)
    export_id = uuid.uuid4()
    content = _build_archive(
        snapshot,
        store,
        export_id=export_id,
        exported_at=exported_at,
    )
    record = EngagementExport(
        id=export_id,
        engagement_id=engagement_id,
        schema_version=EXPORT_SCHEMA_VERSION,
        source_fingerprint=snapshot.source_fingerprint,
        archive_hash=hashlib.sha256(content).hexdigest(),
        byte_count=len(content),
        record_count=snapshot.record_count,
        evidence_object_count=len(snapshot.evidence_assets),
        requested_by_id=operator.id,
        exported_at=exported_at,
    )
    session.add(record)
    session.flush()
    record_audit(
        session,
        engagement_id=engagement_id,
        actor_id=operator.id,
        action="engagement.exported",
        target_type="engagement_export",
        target_id=record.id,
        detail={
            "schema_version": record.schema_version,
            "archive_hash": record.archive_hash,
            "byte_count": record.byte_count,
            "record_count": record.record_count,
            "evidence_object_count": record.evidence_object_count,
        },
    )
    publish_domain_event(
        session,
        engagement_id=engagement_id,
        event_type="engagement.exported",
        aggregate_type="engagement_export",
        aggregate_id=record.id,
        payload={"archive_hash": record.archive_hash},
    )
    return GeneratedExport(record=record, content=content)


def get_latest_export(session: Session, engagement_id: UUID) -> EngagementExport | None:
    return session.scalar(
        select(EngagementExport)
        .where(EngagementExport.engagement_id == engagement_id)
        .order_by(EngagementExport.created_at.desc())
        .limit(1)
    )


def export_is_current(
    session: Session,
    *,
    engagement_id: UUID,
    export: EngagementExport | None,
) -> bool:
    if export is None:
        return False
    return (
        build_export_snapshot(session, engagement_id).source_fingerprint
        == export.source_fingerprint
    )


def delete_engagement_permanently(
    store: EvidenceStore,
    *,
    engagement_id: UUID,
    operator_id: UUID,
    sanitized_data_allowed: bool,
    export_id: UUID,
    confirmation_name: str,
    now: datetime | None = None,
) -> EngagementDeletionReceipt:
    timestamp = now or datetime.now(UTC)
    plan = _prepare_deletion(
        engagement_id=engagement_id,
        operator_id=operator_id,
        sanitized_data_allowed=sanitized_data_allowed,
        export_id=export_id,
        confirmation_name=confirmation_name,
        now=timestamp,
    )
    try:
        for key in plan.evidence_keys:
            store.delete(key)
    except Exception as exc:  # noqa: BLE001 - object-store boundary is normalized and audited
        _mark_deletion_failed(operator_id, plan, "evidence_object_delete_failed")
        raise DeletionExecutionError(
            "Evidence object deletion failed; the engagement remains write-blocked for retry."
        ) from exc

    try:
        with operator_session(operator_id) as session:
            receipt = session.get_one(EngagementDeletionReceipt, plan.receipt_id)
            engagement = session.get(Engagement, engagement_id)
            if engagement is None or engagement.data_lifecycle_status != "deletion_processing":
                raise DeletionExecutionError("The prepared engagement deletion is no longer valid.")
            session.delete(engagement)
            receipt.status = "completed"
            receipt.failure_code = None
            receipt.completed_at = timestamp
            session.flush()
        return receipt
    except Exception as exc:
        _mark_deletion_failed(operator_id, plan, "database_delete_failed")
        if isinstance(exc, DeletionExecutionError):
            raise
        raise DeletionExecutionError(
            "Database deletion failed; the engagement remains write-blocked for retry."
        ) from exc


def build_export_snapshot(session: Session, engagement_id: UUID) -> ExportSnapshot:
    engagement = session.get(Engagement, engagement_id)
    if engagement is None:
        raise DataLifecycleError("Engagement not found.")
    records = {
        model.__tablename__: _records_for_model(session, model, engagement_id)
        for model in ARCHIVE_MODELS
    }
    operator_rows = session.execute(
        select(Operator.id, Operator.display_name)
        .join(EngagementMember, EngagementMember.operator_id == Operator.id)
        .where(EngagementMember.engagement_id == engagement_id)
        .order_by(Operator.id)
    ).all()
    operators = [{"id": str(row.id), "display_name": row.display_name} for row in operator_rows]
    engagement_record = _model_record(engagement)
    fingerprint_engagement = {
        key: value
        for key, value in engagement_record.items()
        if key not in {"updated_at", "data_lifecycle_status"}
    }
    fingerprint_records = {
        model.__tablename__: records[model.__tablename__] for model in FINGERPRINT_MODELS
    }
    fingerprint_payload = {
        "engagement": fingerprint_engagement,
        "operators": operators,
        "records": fingerprint_records,
    }
    evidence_assets = list(
        session.scalars(
            select(EvidenceAsset)
            .where(EvidenceAsset.engagement_id == engagement_id)
            .order_by(EvidenceAsset.id)
        )
    )
    record_count = 1 + len(operators) + sum(len(items) for items in records.values())
    return ExportSnapshot(
        engagement=engagement,
        records=records,
        operators=operators,
        source_fingerprint=_sha256_json(fingerprint_payload),
        record_count=record_count,
        evidence_assets=evidence_assets,
    )


def _prepare_deletion(
    *,
    engagement_id: UUID,
    operator_id: UUID,
    sanitized_data_allowed: bool,
    export_id: UUID,
    confirmation_name: str,
    now: datetime,
) -> DeletionPlan:
    with operator_session(operator_id) as session:
        authorize_engagement(
            session,
            engagement_id=engagement_id,
            operator_id=operator_id,
            permission="owner",
            sanitized_data_allowed=sanitized_data_allowed,
        )
        engagement = session.get_one(Engagement, engagement_id)
        if confirmation_name != engagement.name:
            raise DataLifecycleError(
                "The deletion confirmation does not match the engagement name."
            )
        if (
            engagement.retention_expires_at is not None
            and _aware_utc(engagement.retention_expires_at) > now
        ):
            raise DataLifecycleError("The engagement is still within its retention period.")
        if engagement.data_lifecycle_status not in {"active", "deletion_failed"}:
            raise DataLifecycleError("Engagement deletion is already in progress.")
        export = session.get(EngagementExport, export_id)
        if export is None or export.engagement_id != engagement_id:
            raise DataLifecycleError("Deletion requires an export from this engagement.")
        snapshot = build_export_snapshot(session, engagement_id)
        if snapshot.source_fingerprint != export.source_fingerprint:
            raise DataLifecycleError(
                "The selected export is stale; download a current export first."
            )

        evidence_keys = tuple(asset.storage_key for asset in snapshot.evidence_assets)
        receipt = session.scalar(
            select(EngagementDeletionReceipt).where(
                EngagementDeletionReceipt.engagement_id == engagement_id
            )
        )
        if receipt is None:
            receipt = EngagementDeletionReceipt(
                engagement_id=engagement_id,
                requested_by_id=operator_id,
                status="processing",
                data_classification=engagement.data_classification,
                export_id=export.id,
                source_fingerprint=export.source_fingerprint,
                archive_hash=export.archive_hash,
                database_row_count=0,
                evidence_object_count=len(evidence_keys),
                requested_at=now,
            )
            session.add(receipt)
        else:
            if receipt.status != "failed":
                raise DataLifecycleError("Engagement deletion is already in progress.")
            receipt.status = "processing"
            receipt.export_id = export.id
            receipt.source_fingerprint = export.source_fingerprint
            receipt.archive_hash = export.archive_hash
            receipt.evidence_object_count = len(evidence_keys)
            receipt.failure_code = None
            receipt.requested_at = now
            receipt.completed_at = None
        engagement.data_lifecycle_status = "deletion_processing"
        session.flush()
        record_audit(
            session,
            engagement_id=engagement_id,
            actor_id=operator_id,
            action="engagement.deletion_started",
            target_type="engagement_deletion_receipt",
            target_id=receipt.id,
            detail={"export_id": str(export.id)},
        )
        publish_domain_event(
            session,
            engagement_id=engagement_id,
            event_type="engagement.deletion_started",
            aggregate_type="engagement_deletion_receipt",
            aggregate_id=receipt.id,
            payload={"export_id": str(export.id)},
        )
        session.flush()
        receipt.database_row_count = 1 + sum(
            _count_model_rows(session, model, engagement_id) for model in DELETE_COUNT_MODELS
        )
        return DeletionPlan(
            receipt_id=receipt.id,
            engagement_id=engagement_id,
            evidence_keys=evidence_keys,
        )


def _mark_deletion_failed(operator_id: UUID, plan: DeletionPlan, failure_code: str) -> None:
    with operator_session(operator_id) as session:
        receipt = session.get(EngagementDeletionReceipt, plan.receipt_id)
        if receipt is not None:
            receipt.status = "failed"
            receipt.failure_code = failure_code
            receipt.completed_at = None
        engagement = session.get(Engagement, plan.engagement_id)
        if engagement is not None:
            engagement.data_lifecycle_status = "deletion_failed"


def _build_archive(
    snapshot: ExportSnapshot,
    store: EvidenceStore,
    *,
    export_id: UUID,
    exported_at: datetime,
) -> bytes:
    evidence_bytes = sum(asset.byte_count for asset in snapshot.evidence_assets)
    if evidence_bytes > MAX_EXPORT_SOURCE_BYTES:
        raise ExportGenerationError("The V1 export exceeds the 64 MB source-data limit.")

    engagement_record = _model_record(snapshot.engagement)
    portable_records = {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "engagement": engagement_record,
        "operators": snapshot.operators,
        "records": snapshot.records,
    }
    manifest = {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "export_id": str(export_id),
        "engagement_id": str(snapshot.engagement.id),
        "exported_at": exported_at.isoformat(),
        "source_fingerprint": snapshot.source_fingerprint,
        "record_count": snapshot.record_count,
        "evidence_object_count": len(snapshot.evidence_assets),
        "formats": ["json", "yaml", "markdown", "original_evidence"],
    }

    buffer = BytesIO()
    with ZipFile(buffer, mode="w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        _write_zip(archive, "manifest.json", _json_bytes(manifest))
        _write_zip(archive, "records.json", _json_bytes(portable_records))
        yaml_content = yaml.safe_dump(
            portable_records,
            allow_unicode=True,
            sort_keys=True,
        ).encode("utf-8")
        _write_zip(archive, "records.yaml", yaml_content)
        _write_zip(
            archive,
            "README.md",
            (
                b"# AI-FDE Engagement Export\n\n"
                b"This archive is a point-in-time portability package. Documents remain evidence; "
                b"`records.json` and `records.yaml` contain the exported structured state.\n"
            ),
        )

        artifacts = snapshot.records[ImplementationArtifact.__tablename__]
        for artifact in artifacts:
            content = artifact.get("content")
            if isinstance(content, str):
                path = (
                    "implementation-specifications/"
                    f"{artifact['id']}-v{artifact['version_number']}.md"
                )
                _write_zip(archive, path, content.encode("utf-8"))

        for asset in snapshot.evidence_assets:
            content = store.get(asset.storage_key)
            if hashlib.sha256(content).hexdigest() != asset.content_hash:
                raise ExportGenerationError(
                    f"Evidence integrity verification failed for asset {asset.id}."
                )
            file_name = Path(asset.file_name).name
            _write_zip(archive, f"evidence/{asset.id}/{file_name}", content)
    return buffer.getvalue()


def _write_zip(archive: ZipFile, path: str, content: bytes) -> None:
    info = ZipInfo(path, date_time=ZIP_TIMESTAMP)
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    archive.writestr(info, content)


def _records_for_model(
    session: Session,
    model: type[Any],
    engagement_id: UUID,
) -> list[dict[str, Any]]:
    engagement_column = model.engagement_id
    id_column = model.id
    instances = session.scalars(
        select(model).where(engagement_column == engagement_id).order_by(id_column)
    )
    return [_model_record(instance) for instance in instances]


def _model_record(instance: Any) -> dict[str, Any]:
    mapper = inspect(instance).mapper
    return {
        attribute.key: _json_value(getattr(instance, attribute.key))
        for attribute in mapper.column_attrs
    }


def _count_model_rows(session: Session, model: type[Any], engagement_id: UUID) -> int:
    engagement_column = model.engagement_id
    return int(
        session.scalar(
            select(func.count()).select_from(model).where(engagement_column == engagement_id)
        )
        or 0
    )


def _json_value(value: Any) -> Any:
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise DataLifecycleError("The retention deadline must include a timezone.")
    return value.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    return _aware_utc(value).isoformat() if value is not None else None
