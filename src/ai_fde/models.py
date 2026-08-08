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

    external_subject: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)


class Engagement(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "engagements"
    __table_args__ = (
        UniqueConstraint("created_by_id", "slug", name="engagement_slug_per_creator"),
        CheckConstraint(
            "lifecycle_stage IN ('qualify', 'discover', 'model', 'map')",
            name="valid_lifecycle_stage",
        ),
        CheckConstraint(
            "data_classification IN ('synthetic', 'sanitized')",
            name="valid_data_classification",
        ),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    primary_outcome: Mapped[str] = mapped_column(Text, nullable=False)
    lifecycle_stage: Mapped[str] = mapped_column(String(32), nullable=False, default="discover")
    data_classification: Mapped[str] = mapped_column(
        String(32), nullable=False, default="synthetic"
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id", ondelete="RESTRICT"), nullable=False
    )


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
        CheckConstraint(
            "status IN ('queued', 'processing', 'needs_review', 'failed', 'complete')",
            name="valid_status",
        ),
        CheckConstraint(
            "source_type IN ('upload', 'operator_note', 'fixture')", name="valid_source_type"
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
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="upload")
    source_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
