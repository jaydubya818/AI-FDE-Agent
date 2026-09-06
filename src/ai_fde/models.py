from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class Operator(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "operators"
    __table_args__ = (
        CheckConstraint("identity_kind IN ('human', 'service')", name="valid_identity_kind"),
    )

    external_subject: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    identity_kind: Mapped[str] = mapped_column(String(24), nullable=False, default="human")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class WorkerOperatorBinding(Base, TimestampMixin):
    """Owner-managed binding between a database login and one deployed service identity."""

    __tablename__ = "worker_operator_bindings"
    __table_args__ = (
        CheckConstraint(
            "database_role ~ '^ai_fde_worker_[0-9a-f]{12}$'",
            name="valid_worker_database_role",
        ),
        CheckConstraint(
            "release_revision ~ '^[0-9a-f]{40}$' AND "
            "release_revision <> '0000000000000000000000000000000000000000'",
            name="valid_release_revision",
        ),
        CheckConstraint(
            "deployment_id ~ '^[a-z0-9][a-z0-9._-]{7,119}$'",
            name="valid_deployment_id",
        ),
        CheckConstraint(
            "deployment_validation_id IS NULL OR "
            "deployment_validation_id ~ '^sha256:[0-9a-f]{64}$'",
            name="valid_worker_deployment_validation_digest",
        ),
    )

    database_role: Mapped[str] = mapped_column(String(63), primary_key=True)
    operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("operators.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    engagement_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("engagements.id", ondelete="SET NULL", use_alter=True),
        unique=True,
    )
    release_revision: Mapped[str] = mapped_column(String(40), nullable=False)
    deployment_id: Mapped[str] = mapped_column(String(120), nullable=False)
    deployment_validation_id: Mapped[str | None] = mapped_column(String(71))


class OIDCLoginAttempt(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "oidc_login_attempts"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="valid_oidc_attempt_expiry"),
        Index("ix_oidc_login_attempts_expires_at", "expires_at"),
    )

    state_digest: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    nonce: Mapped[str] = mapped_column(String(128), nullable=False)
    code_verifier: Mapped[str] = mapped_column(String(128), nullable=False)
    redirect_uri: Mapped[str] = mapped_column(String(1024), nullable=False)
    return_to: Mapped[str] = mapped_column(String(1024), nullable=False, default="/")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OperatorSession(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "operator_sessions"
    __table_args__ = (
        CheckConstraint("expires_at > authenticated_at", name="valid_operator_session_expiry"),
        Index("ix_operator_sessions_operator_expires", "operator_id", "expires_at"),
    )

    token_digest: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id", ondelete="CASCADE"), nullable=False
    )
    authenticated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Engagement(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "engagements"
    __table_args__ = (
        UniqueConstraint("created_by_id", "slug", name="engagement_slug_per_creator"),
        CheckConstraint(
            "lifecycle_stage IN ('qualify', 'discover', 'model', 'map', 'decide', "
            "'design', 'economic_case', 'specify')",
            name="valid_lifecycle_stage",
        ),
        CheckConstraint(
            "data_classification IN ('synthetic', 'sanitized')",
            name="valid_data_classification",
        ),
        CheckConstraint(
            "data_lifecycle_status IN ('active', 'deletion_processing', 'deletion_failed')",
            name="valid_data_lifecycle_status",
        ),
        CheckConstraint(
            "retention_expires_at IS NULL OR retention_expires_at > created_at",
            name="valid_retention_expiry",
        ),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    workflow_name: Mapped[str] = mapped_column(String(255), nullable=False)
    primary_outcome: Mapped[str] = mapped_column(Text, nullable=False)
    lifecycle_stage: Mapped[str] = mapped_column(String(32), nullable=False, default="discover")
    data_classification: Mapped[str] = mapped_column(
        String(32), nullable=False, default="synthetic"
    )
    data_lifecycle_status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    retention_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id", ondelete="RESTRICT"), nullable=False
    )


class EngagementAssessment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "engagement_assessments"
    __table_args__ = (
        UniqueConstraint(
            "engagement_id",
            "evaluator_id",
            "delivery_method",
            "perspective",
            name="assessment_identity",
        ),
        CheckConstraint(
            "delivery_method IN ('ai_fde', 'conventional')",
            name="valid_delivery_method",
        ),
        CheckConstraint(
            "perspective IN ('operator', 'engineering')",
            name="valid_perspective",
        ),
        CheckConstraint(
            "outcome IN ('completed', 'blocked', 'abandoned')",
            name="valid_outcome",
        ),
        CheckConstraint(
            "duration_minutes BETWEEN 1 AND 10080",
            name="valid_duration_minutes",
        ),
        CheckConstraint("usefulness_score BETWEEN 1 AND 5", name="valid_usefulness_score"),
        CheckConstraint(
            "clarification_count BETWEEN 0 AND 10000 AND "
            "rework_count BETWEEN 0 AND 10000 AND "
            "workaround_count BETWEEN 0 AND 10000 AND "
            "trust_failure_count BETWEEN 0 AND 10000",
            name="valid_assessment_counts",
        ),
        Index(
            "ix_engagement_assessments_engagement_updated",
            "engagement_id",
            "updated_at",
        ),
    )

    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False
    )
    evaluator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id", ondelete="RESTRICT"), nullable=False
    )
    delivery_method: Mapped[str] = mapped_column(String(24), nullable=False)
    perspective: Mapped[str] = mapped_column(String(24), nullable=False)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    usefulness_score: Mapped[int] = mapped_column(Integer, nullable=False)
    clarification_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rework_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    workaround_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trust_failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(Text)


class EngagementExport(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "engagement_exports"
    __table_args__ = (
        CheckConstraint("byte_count >= 0", name="nonnegative_byte_count"),
        CheckConstraint("record_count >= 0", name="nonnegative_record_count"),
        CheckConstraint("evidence_object_count >= 0", name="nonnegative_evidence_object_count"),
        Index("ix_engagement_exports_engagement_created", "engagement_id", "created_at"),
    )

    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False
    )
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    archive_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    record_count: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_object_count: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id", ondelete="RESTRICT"), nullable=False
    )
    exported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class EngagementDeletionReceipt(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "engagement_deletion_receipts"
    __table_args__ = (
        UniqueConstraint("engagement_id", name="one_deletion_receipt_per_engagement"),
        CheckConstraint("status IN ('processing', 'completed', 'failed')", name="valid_status"),
        CheckConstraint(
            "data_classification IN ('synthetic', 'sanitized')",
            name="valid_data_classification",
        ),
        CheckConstraint("database_row_count >= 0", name="nonnegative_database_row_count"),
        CheckConstraint("evidence_object_count >= 0", name="nonnegative_evidence_object_count"),
        Index("ix_deletion_receipts_operator_created", "requested_by_id", "created_at"),
    )

    engagement_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    requested_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="processing")
    data_classification: Mapped[str] = mapped_column(String(32), nullable=False)
    export_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    archive_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    database_row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_object_count: Mapped[int] = mapped_column(Integer, nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(120))
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EngagementMember(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "engagement_members"
    __table_args__ = (
        UniqueConstraint("engagement_id", "operator_id", name="membership_identity"),
        CheckConstraint("role IN ('owner', 'operator', 'viewer')", name="valid_role"),
    )

    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False
    )
    operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(24), nullable=False, default="owner")


class EvidenceAsset(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "evidence_assets"
    __table_args__ = (
        UniqueConstraint("engagement_id", "content_hash", name="evidence_content_per_engagement"),
        UniqueConstraint("engagement_id", "id", name="evidence_asset_tenant_identity"),
        ForeignKeyConstraint(
            ["engagement_id", "design_partner_qualification_id"],
            [
                "design_partner_qualifications.engagement_id",
                "design_partner_qualifications.id",
            ],
            name="evidence_asset_design_partner_qualification_tenant",
        ),
        CheckConstraint(
            "status IN ('queued', 'processing', 'needs_review', 'failed', 'complete')",
            name="valid_status",
        ),
        CheckConstraint(
            "source_type IN ('upload', 'operator_note', 'fixture')", name="valid_source_type"
        ),
        CheckConstraint(
            "(design_partner_qualification_id IS NULL "
            "AND authorized_source_key IS NULL "
            "AND authorized_workflow_class IS NULL "
            "AND data_classification IS NULL) "
            "OR (design_partner_qualification_id IS NOT NULL "
            "AND authorized_source_key IS NOT NULL "
            "AND authorized_workflow_class IS NOT NULL "
            "AND data_classification IN "
            "('PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED'))",
            name="valid_design_partner_context",
        ),
        CheckConstraint(
            "storage_version_id IS NULL "
            "OR (storage_version_id <> '' AND storage_version_id <> 'null')",
            name="valid_storage_version_id",
        ),
        Index("ix_evidence_assets_engagement_status", "engagement_id", "status"),
    )

    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False
    )
    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    storage_version_id: Mapped[str | None] = mapped_column(String(1024))
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="upload")
    source_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    design_partner_qualification_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True)
    )
    authorized_source_key: Mapped[str | None] = mapped_column(String(120))
    authorized_workflow_class: Mapped[str | None] = mapped_column(String(160))
    data_classification: Mapped[str | None] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    error_message: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id", ondelete="RESTRICT"), nullable=False
    )


class EvidenceSegment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "evidence_segments"
    __table_args__ = (
        UniqueConstraint("evidence_asset_id", "ordinal", name="evidence_segment_ordinal"),
        Index("ix_evidence_segments_engagement_asset", "engagement_id", "evidence_asset_id"),
    )

    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False
    )
    evidence_asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evidence_assets.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    locator: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    parser_name: Mapped[str] = mapped_column(String(120), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(32), nullable=False)


class ExtractionRun(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "extraction_runs"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'complete', 'failed')", name="valid_status"),
        Index("ix_extraction_runs_engagement_asset", "engagement_id", "evidence_asset_id"),
    )

    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False
    )
    evidence_asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evidence_assets.id", ondelete="CASCADE"), nullable=False
    )
    extractor_name: Mapped[str] = mapped_column(String(120), nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(120), nullable=False)
    model_id: Mapped[str | None] = mapped_column(String(512))
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result_code: Mapped[str] = mapped_column(String(120), nullable=False, default="running")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="running")
    error_message: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CandidateClaim(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "candidate_claims"
    __table_args__ = (
        CheckConstraint(
            "claim_kind IN ('entity', 'relationship', 'rule', 'exception')",
            name="valid_claim_kind",
        ),
        CheckConstraint(
            "status IN ('candidate', 'accepted', 'rejected', 'deferred')",
            name="valid_status",
        ),
        CheckConstraint("materiality IN ('low', 'material')", name="valid_materiality"),
        Index("ix_candidate_claims_engagement_status", "engagement_id", "status"),
    )

    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False
    )
    extraction_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("extraction_runs.id", ondelete="CASCADE"), nullable=False
    )
    claim_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_text: Mapped[str] = mapped_column(String(512), nullable=False)
    predicate: Mapped[str] = mapped_column(String(120), nullable=False)
    object_text: Mapped[str | None] = mapped_column(String(1024))
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    materiality: Mapped[str] = mapped_column(String(16), nullable=False, default="material")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="candidate")


class ClaimEvidence(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "claim_evidence"
    __table_args__ = (
        UniqueConstraint("candidate_claim_id", "evidence_segment_id", name="claim_segment"),
    )

    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False
    )
    candidate_claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidate_claims.id", ondelete="CASCADE"), nullable=False
    )
    evidence_segment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evidence_segments.id", ondelete="CASCADE"), nullable=False
    )
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)


class ReviewDecision(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "review_decisions"
    __table_args__ = (
        UniqueConstraint("candidate_claim_id", name="one_decision_per_candidate_claim"),
        CheckConstraint("decision IN ('accepted', 'rejected', 'deferred')", name="valid_decision"),
    )

    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False
    )
    candidate_claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidate_claims.id", ondelete="CASCADE"), nullable=False
    )
    reviewer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id", ondelete="RESTRICT"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class OperatingEntity(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "operating_entities"
    __table_args__ = (
        UniqueConstraint("engagement_id", "entity_type", "canonical_key", name="entity_identity"),
        CheckConstraint(
            "entity_type IN ('company', 'department', 'team', 'person', 'role', 'system', "
            "'process', 'policy', 'rule', 'exception')",
            name="valid_entity_type",
        ),
        Index("ix_operating_entities_engagement_type", "engagement_id", "entity_type"),
    )

    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(48), nullable=False)
    canonical_key: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="verified")
    verified_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id", ondelete="RESTRICT"), nullable=False
    )


class Assertion(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "assertions"
    __table_args__ = (
        UniqueConstraint("candidate_claim_id", name="assertion_source_claim"),
        CheckConstraint(
            "status IN ('verified', 'superseded', 'disputed', 'retired')",
            name="valid_status",
        ),
        Index("ix_assertions_engagement_status", "engagement_id", "status"),
    )

    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False
    )
    subject_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operating_entities.id", ondelete="RESTRICT"), nullable=False
    )
    predicate: Mapped[str] = mapped_column(String(120), nullable=False)
    object_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operating_entities.id", ondelete="RESTRICT")
    )
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="verified")
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    candidate_claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidate_claims.id", ondelete="RESTRICT"), nullable=False
    )
    verified_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id", ondelete="RESTRICT"), nullable=False
    )


class AssertionEvidence(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "assertion_evidence"
    __table_args__ = (
        UniqueConstraint("assertion_id", "evidence_segment_id", name="assertion_segment"),
    )

    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False
    )
    assertion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assertions.id", ondelete="CASCADE"), nullable=False
    )
    evidence_segment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evidence_segments.id", ondelete="RESTRICT"), nullable=False
    )
    claim_evidence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("claim_evidence.id", ondelete="RESTRICT"), nullable=False
    )


class Contradiction(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "contradictions"
    __table_args__ = (
        UniqueConstraint("left_claim_id", "right_claim_id", name="contradiction_claim_pair"),
        CheckConstraint(
            "status IN ('open', 'investigating', 'resolved', "
            "'accepted_exception', 'not_a_conflict')",
            name="valid_status",
        ),
    )

    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False
    )
    left_claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidate_claims.id", ondelete="CASCADE"), nullable=False
    )
    right_claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidate_claims.id", ondelete="CASCADE"), nullable=False
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    blocking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    resolution_type: Mapped[str | None] = mapped_column(String(32))
    resolution_reason: Mapped[str | None] = mapped_column(Text)
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id", ondelete="RESTRICT")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkflowVersion(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "workflow_versions"
    __table_args__ = (
        UniqueConstraint(
            "engagement_id", "workflow_kind", "version_number", name="workflow_version_identity"
        ),
        CheckConstraint("workflow_kind IN ('current', 'target')", name="valid_workflow_kind"),
        CheckConstraint("status IN ('draft', 'approved', 'stale')", name="valid_status"),
        CheckConstraint("generated_by IN ('system', 'operator')", name="valid_generated_by"),
        Index("ix_workflow_versions_engagement_kind", "engagement_id", "workflow_kind", "status"),
    )

    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False
    )
    workflow_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    source_workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_versions.id", ondelete="RESTRICT")
    )
    source_assertion_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    generated_by: Mapped[str] = mapped_column(String(24), nullable=False, default="system")
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id", ondelete="RESTRICT"), nullable=False
    )
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id", ondelete="RESTRICT")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_reason: Mapped[str | None] = mapped_column(Text)


class WorkflowStep(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "workflow_steps"
    __table_args__ = (
        UniqueConstraint("workflow_version_id", "step_key", name="workflow_step_identity"),
        CheckConstraint(
            "step_type IN ('human_task', 'software_task', 'decision', 'approval', 'handoff')",
            name="valid_step_type",
        ),
        CheckConstraint(
            "allocation IN ('human', 'software', 'ai', 'ai_human')",
            name="valid_allocation",
        ),
        Index("ix_workflow_steps_engagement_workflow", "engagement_id", "workflow_version_id"),
    )

    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False
    )
    workflow_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_versions.id", ondelete="CASCADE"), nullable=False
    )
    step_key: Mapped[str] = mapped_column(String(120), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    step_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_label: Mapped[str | None] = mapped_column(String(255))
    system_label: Mapped[str | None] = mapped_column(String(255))
    allocation: Mapped[str] = mapped_column(String(24), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    controls: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    source_assertion_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assertions.id", ondelete="RESTRICT")
    )


class EconomicCase(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "economic_cases"
    __table_args__ = (
        UniqueConstraint("engagement_id", "version_number", name="economic_case_version"),
        CheckConstraint("status IN ('draft', 'approved', 'stale')", name="valid_status"),
        Index("ix_economic_cases_engagement_status", "engagement_id", "status"),
    )

    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    source_target_workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_versions.id", ondelete="RESTRICT"), nullable=False
    )
    formula_version: Mapped[str] = mapped_column(String(64), nullable=False)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    outputs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    scenarios: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    assumptions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id", ondelete="RESTRICT"), nullable=False
    )
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id", ondelete="RESTRICT")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ImplementationArtifact(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "implementation_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "engagement_id", "artifact_type", "version_number", name="artifact_version_identity"
        ),
        CheckConstraint(
            "artifact_type IN ('prd', 'architecture', 'business_rules', "
            "'integration_requirements', 'approval_controls', 'evaluation_plan', "
            "'implementation_spec')",
            name="valid_artifact_type",
        ),
        CheckConstraint("status IN ('current', 'stale')", name="valid_status"),
        CheckConstraint("packet_version > 0", name="positive_packet_version"),
        Index("ix_implementation_artifacts_engagement_status", "engagement_id", "status"),
    )

    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False
    )
    artifact_type: Mapped[str] = mapped_column(String(48), nullable=False)
    packet_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="current")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_current_workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_versions.id", ondelete="RESTRICT"), nullable=False
    )
    source_target_workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_versions.id", ondelete="RESTRICT"), nullable=False
    )
    economic_case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("economic_cases.id", ondelete="RESTRICT"), nullable=False
    )
    source_assertion_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    generated_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id", ondelete="RESTRICT"), nullable=False
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class Job(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("engagement_id", "idempotency_key", name="job_idempotency"),
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="valid_status",
        ),
        Index("ix_jobs_engagement_available", "engagement_id", "status", "available_at"),
    )

    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    leased_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OutboxEvent(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_events_unpublished", "published_at", "created_at"),)

    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(160), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(120), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEvent(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_engagement_created", "engagement_id", "created_at"),)

    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False
    )
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(160), nullable=False)
    target_type: Mapped[str] = mapped_column(String(120), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    correlation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, default=uuid.uuid4
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
