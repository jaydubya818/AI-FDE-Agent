from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from io import BytesIO
from zipfile import ZipFile

import pytest
import yaml
from sqlalchemy import select

from ai_fde.adapters.storage import (
    EvidenceObjectVersionNotFoundError,
    EvidencePrefixPurgeReceipt,
    InMemoryEvidenceStore,
)
from ai_fde.db import operator_session
from ai_fde.models import (
    AuditEvent,
    Engagement,
    EngagementAssessment,
    EngagementDeletionReceipt,
    EngagementExport,
    EvidenceAsset,
    Operator,
)
from ai_fde.modules.data_lifecycle.service import (
    DataLifecycleError,
    DeletionExecutionError,
    ExportGenerationError,
    create_engagement_export,
    delete_engagement_permanently,
    set_retention_deadline,
)
from ai_fde.modules.engagements.service import create_engagement
from ai_fde.modules.evidence.service import create_evidence_asset
from ai_fde.modules.identity.service import (
    EngagementPermissionDeniedError,
    authorize_engagement,
)
from tests.conftest import OperatorFixture


class RetryableDeleteStore(InMemoryEvidenceStore):
    def __init__(self) -> None:
        super().__init__()
        self.fail_deletes = True

    def purge_engagement_evidence(
        self, engagement_id: uuid.UUID
    ) -> EvidencePrefixPurgeReceipt:
        if self.fail_deletes:
            raise RuntimeError("object storage unavailable")
        return super().purge_engagement_evidence(engagement_id)


class TamperedVersionReadStore(InMemoryEvidenceStore):
    tamper_reads = False

    def get(self, key: str, *, version_id: str | None = None) -> bytes:
        if self.tamper_reads and version_id is not None:
            return b"bytes that do not match the accepted evidence digest"
        return super().get(key, version_id=version_id)


def _create_engagement_with_evidence(
    operator: OperatorFixture,
    store: InMemoryEvidenceStore,
    *,
    name: str,
) -> uuid.UUID:
    with operator_session(operator.id) as session:
        operator_record = session.get_one(Operator, operator.id)
        engagement = create_engagement(
            session,
            operator=operator_record,
            name=name,
            primary_outcome="Prove portable export and verified data deletion.",
        )
        create_evidence_asset(
            session,
            store,
            engagement_id=engagement.id,
            operator=operator_record,
            file_name="source.md",
            content_type="text/markdown",
            content=b"Invoices over $50,000 require CFO approval.",
        )
        return engagement.id


@pytest.mark.integration
@pytest.mark.isolation
def test_owner_exports_then_permanently_deletes_engagement(
    postgres_available: None,
    test_operator: OperatorFixture,
) -> None:
    store = InMemoryEvidenceStore()
    engagement_id = _create_engagement_with_evidence(
        test_operator,
        store,
        name="Lifecycle Manufacturing",
    )

    with operator_session(test_operator.id) as session:
        asset = session.scalar(
            select(EvidenceAsset).where(EvidenceAsset.engagement_id == engagement_id)
        )
        assert asset is not None
        assert asset.storage_version_id is not None
        asset_id = asset.id
        pinned_key = asset.storage_key
        pinned_version_id = asset.storage_version_id
        assessment = EngagementAssessment(
            engagement_id=engagement_id,
            evaluator_id=test_operator.id,
            delivery_method="conventional",
            perspective="operator",
            outcome="blocked",
            duration_minutes=30,
            usefulness_score=2,
            clarification_count=3,
            rework_count=1,
            workaround_count=0,
            trust_failure_count=1,
            notes="Exported with the governed engagement, not with telemetry.",
        )
        session.add(assessment)
        session.flush()
        assessment_id = assessment.id
        generated = create_engagement_export(
            session,
            store,
            engagement_id=engagement_id,
            operator=session.get_one(Operator, test_operator.id),
        )
        export_id = generated.record.id
        archive_hash = generated.record.archive_hash
        assert generated.record.record_count >= 4
        with ZipFile(BytesIO(generated.content)) as archive:
            names = set(archive.namelist())
            assert {"manifest.json", "records.json", "records.yaml", "README.md"} <= names
            evidence_path = next(name for name in names if name.startswith("evidence/"))
            assert evidence_path == f"evidence/{asset_id}/{asset_id}.md"
            assert all(not name.startswith("/") for name in names)
            assert all("\\" not in name for name in names)
            assert all(".." not in name.split("/") for name in names)
            assert archive.read(evidence_path) == b"Invoices over $50,000 require CFO approval."
            manifest = json.loads(archive.read("manifest.json"))
            yaml_records = yaml.safe_load(archive.read("records.yaml"))
            assert manifest["export_id"] == str(export_id)
            assert manifest["source_fingerprint"] == generated.record.source_fingerprint
            assert yaml_records["engagement"]["id"] == str(engagement_id)
            assert len(yaml_records["records"]["engagement_assessments"]) == 1
            assert yaml_records["records"]["engagement_assessments"][0]["outcome"] == "blocked"

    prefix = f"engagements/{engagement_id}/evidence/"
    untracked = store.put(
        f"{prefix}untracked-after-export.md",
        b"untracked version still belongs to this engagement",
        "text/markdown",
    )
    store.delete(untracked.key)

    receipt = delete_engagement_permanently(
        store,
        engagement_id=engagement_id,
        operator_id=test_operator.id,
        sanitized_data_allowed=False,
        export_id=export_id,
        confirmation_name="Lifecycle Manufacturing",
    )

    assert receipt.status == "completed"
    assert receipt.archive_hash == archive_hash
    assert receipt.database_row_count > 1
    assert receipt.evidence_object_count == 1
    assert store.objects == {}
    assert store.stored_version_count == 0
    assert store.delete_marker_count == 0
    with pytest.raises(EvidenceObjectVersionNotFoundError, match="unavailable"):
        store.get(pinned_key, version_id=pinned_version_id)
    with pytest.raises(EvidenceObjectVersionNotFoundError, match="unavailable"):
        store.get(untracked.key, version_id=untracked.version_id)
    with operator_session(test_operator.id) as session:
        assert session.get(Engagement, engagement_id) is None
        assert session.get(EngagementAssessment, assessment_id) is None
        persisted_receipt = session.get_one(EngagementDeletionReceipt, receipt.id)
        assert persisted_receipt.completed_at is not None


@pytest.mark.integration
@pytest.mark.isolation
def test_export_uses_the_pinned_version_after_current_overwrite_and_delete_marker(
    postgres_available: None,
    test_operator: OperatorFixture,
) -> None:
    store = InMemoryEvidenceStore()
    engagement_id = _create_engagement_with_evidence(
        test_operator,
        store,
        name="Pinned Export Manufacturing",
    )
    with operator_session(test_operator.id) as session:
        asset = session.scalar(
            select(EvidenceAsset).where(EvidenceAsset.engagement_id == engagement_id)
        )
        assert asset is not None
        assert asset.storage_version_id is not None
        store.put(
            asset.storage_key,
            b"a newer current version must not replace accepted evidence",
            "text/markdown",
        )
        store.delete(asset.storage_key)
        assert asset.storage_key not in store.objects

        generated = create_engagement_export(
            session,
            store,
            engagement_id=engagement_id,
            operator=session.get_one(Operator, test_operator.id),
        )

    with ZipFile(BytesIO(generated.content)) as archive:
        evidence_path = next(
            name for name in archive.namelist() if name.startswith("evidence/")
        )
        assert archive.read(evidence_path) == b"Invoices over $50,000 require CFO approval."


@pytest.mark.integration
@pytest.mark.isolation
def test_export_rejects_tampered_pinned_version_without_persisting_success(
    postgres_available: None,
    test_operator: OperatorFixture,
) -> None:
    store = TamperedVersionReadStore()
    engagement_id = _create_engagement_with_evidence(
        test_operator,
        store,
        name="Tampered Export Manufacturing",
    )
    store.tamper_reads = True

    with pytest.raises(ExportGenerationError, match="integrity verification"), operator_session(
        test_operator.id
    ) as session:
        create_engagement_export(
            session,
            store,
            engagement_id=engagement_id,
            operator=session.get_one(Operator, test_operator.id),
        )

    with operator_session(test_operator.id) as session:
        assert list(
            session.scalars(
                select(EngagementExport).where(
                    EngagementExport.engagement_id == engagement_id
                )
            )
        ) == []
        assert list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.engagement_id == engagement_id,
                    AuditEvent.action == "engagement.exported",
                )
            )
        ) == []


@pytest.mark.integration
@pytest.mark.isolation
def test_deletion_requires_current_export_and_expired_retention(
    postgres_available: None,
    test_operator: OperatorFixture,
) -> None:
    store = InMemoryEvidenceStore()
    engagement_id = _create_engagement_with_evidence(
        test_operator,
        store,
        name="Retained Manufacturing",
    )
    now = datetime.now(UTC)
    with operator_session(test_operator.id) as session:
        engagement = session.get_one(Engagement, engagement_id)
        set_retention_deadline(
            session,
            engagement=engagement,
            operator=session.get_one(Operator, test_operator.id),
            retain_until=now + timedelta(days=30),
            now=now,
        )
        generated = create_engagement_export(
            session,
            store,
            engagement_id=engagement_id,
            operator=session.get_one(Operator, test_operator.id),
            now=now,
        )
        export_id = generated.record.id

    with pytest.raises(DataLifecycleError, match="retention period"):
        delete_engagement_permanently(
            store,
            engagement_id=engagement_id,
            operator_id=test_operator.id,
            sanitized_data_allowed=False,
            export_id=export_id,
            confirmation_name="Retained Manufacturing",
            now=now,
        )

    with operator_session(test_operator.id) as session:
        session.add(
            EngagementAssessment(
                engagement_id=engagement_id,
                evaluator_id=test_operator.id,
                delivery_method="conventional",
                perspective="operator",
                outcome="blocked",
                duration_minutes=45,
                usefulness_score=2,
                clarification_count=2,
                rework_count=1,
                workaround_count=1,
                trust_failure_count=0,
            )
        )

    with pytest.raises(DataLifecycleError, match="export is stale"):
        delete_engagement_permanently(
            store,
            engagement_id=engagement_id,
            operator_id=test_operator.id,
            sanitized_data_allowed=False,
            export_id=export_id,
            confirmation_name="Retained Manufacturing",
            now=now + timedelta(days=31),
        )

    with operator_session(test_operator.id) as session:
        assert session.get(Engagement, engagement_id) is not None
        assert (
            list(
                session.scalars(
                    select(EngagementDeletionReceipt).where(
                        EngagementDeletionReceipt.engagement_id == engagement_id
                    )
                )
            )
            == []
        )


@pytest.mark.integration
@pytest.mark.isolation
def test_failed_object_deletion_is_receipted_and_retryable(
    postgres_available: None,
    test_operator: OperatorFixture,
) -> None:
    store = RetryableDeleteStore()
    engagement_id = _create_engagement_with_evidence(
        test_operator,
        store,
        name="Retryable Deletion Manufacturing",
    )
    with operator_session(test_operator.id) as session:
        generated = create_engagement_export(
            session,
            store,
            engagement_id=engagement_id,
            operator=session.get_one(Operator, test_operator.id),
        )
        export_id = generated.record.id

    with pytest.raises(DeletionExecutionError, match="write-blocked for retry"):
        delete_engagement_permanently(
            store,
            engagement_id=engagement_id,
            operator_id=test_operator.id,
            sanitized_data_allowed=False,
            export_id=export_id,
            confirmation_name="Retryable Deletion Manufacturing",
        )

    with operator_session(test_operator.id) as session:
        engagement = session.get_one(Engagement, engagement_id)
        assert engagement.data_lifecycle_status == "deletion_failed"
        with pytest.raises(EngagementPermissionDeniedError, match="business mutations are blocked"):
            authorize_engagement(
                session,
                engagement_id=engagement_id,
                operator_id=test_operator.id,
                permission="write",
                sanitized_data_allowed=False,
            )
        receipt = session.scalar(
            select(EngagementDeletionReceipt).where(
                EngagementDeletionReceipt.engagement_id == engagement_id
            )
        )
        assert receipt is not None
        assert receipt.status == "failed"
        assert receipt.failure_code == "evidence_object_delete_failed"

    store.fail_deletes = False
    receipt = delete_engagement_permanently(
        store,
        engagement_id=engagement_id,
        operator_id=test_operator.id,
        sanitized_data_allowed=False,
        export_id=export_id,
        confirmation_name="Retryable Deletion Manufacturing",
    )
    assert receipt.status == "completed"
