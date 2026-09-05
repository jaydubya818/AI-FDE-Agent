from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ai_fde.models import Base, TimestampMixin, UUIDPrimaryKeyMixin, utc_now


class DesignPartnerQualification(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "design_partner_qualifications"
    __table_args__ = (
        UniqueConstraint("engagement_id", name="design_partner_qualification_engagement"),
        UniqueConstraint("partner_key", name="design_partner_qualification_partner_key"),
        UniqueConstraint(
            "engagement_id",
            "id",
            name="design_partner_qualification_tenant_id",
        ),
        UniqueConstraint(
            "engagement_id",
            "id",
            "partner_key",
            name="design_partner_qualification_tenant_identity",
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'SUSPENDED', 'REVOKED')",
            name="valid_status",
        ),
        CheckConstraint(
            "qualification_state IN ('CONFIGURED', 'IN_PROGRESS', 'BLOCKED', 'QUALIFIED')",
            name="valid_qualification_state",
        ),
        CheckConstraint(
            "data_classification IN ('PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED')",
            name="valid_data_classification",
        ),
        CheckConstraint("retention_days BETWEEN 1 AND 3650", name="valid_retention_days"),
        CheckConstraint(
            "retention_expires_at = created_at + make_interval(days => retention_days)",
            name="valid_retention_ceiling",
        ),
        CheckConstraint(
            "jsonb_typeof(authorized_data_source_keys) = 'array' "
            "AND jsonb_array_length(authorized_data_source_keys) BETWEEN 1 AND 100",
            name="valid_authorized_data_source_keys",
        ),
        CheckConstraint(
            "jsonb_typeof(authorized_repository_refs) = 'array' "
            "AND jsonb_array_length(authorized_repository_refs) BETWEEN 1 AND 100",
            name="valid_authorized_repository_refs",
        ),
        CheckConstraint(
            "jsonb_typeof(allowed_workflow_classes) = 'array' "
            "AND jsonb_array_length(allowed_workflow_classes) BETWEEN 1 AND 100",
            name="valid_allowed_workflow_classes",
        ),
        Index(
            "ix_design_partner_qualification_status",
            "status",
            "qualification_state",
        ),
    )

    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False
    )
    partner_key: Mapped[str] = mapped_column(String(120), nullable=False)
    organization: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE")
    qualification_state: Mapped[str] = mapped_column(
        String(24), nullable=False, default="CONFIGURED"
    )
    authorized_data_source_keys: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    authorized_repository_refs: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    allowed_workflow_classes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    data_classification: Mapped[str] = mapped_column(String(24), nullable=False)
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False)
    retention_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    authorization_basis_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    configured_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id", ondelete="RESTRICT"), nullable=False
    )


class CustomerDataAccessEvent(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "customer_data_access_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["engagement_id", "qualification_id", "partner_key"],
            [
                "design_partner_qualifications.engagement_id",
                "design_partner_qualifications.id",
                "design_partner_qualifications.partner_key",
            ],
            name="customer_data_access_qualification_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["engagement_id", "evidence_asset_id"],
            ["evidence_assets.engagement_id", "evidence_assets.id"],
            name="customer_data_access_evidence_tenant",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "data_classification IN ('PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED')",
            name="valid_data_classification",
        ),
        CheckConstraint(
            "operation IN ('MANUAL_DOCUMENT_UPLOAD')",
            name="valid_operation",
        ),
        CheckConstraint("outcome IN ('AUTHORIZED', 'DENIED')", name="valid_outcome"),
        CheckConstraint(
            "(outcome = 'AUTHORIZED' AND evidence_asset_id IS NOT NULL) "
            "OR (outcome = 'DENIED' AND evidence_asset_id IS NULL)",
            name="valid_evidence_binding",
        ),
        Index(
            "ix_customer_data_access_engagement_created",
            "engagement_id",
            "created_at",
        ),
        Index(
            "ix_customer_data_access_correlation",
            "correlation_id",
        ),
    )

    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False
    )
    qualification_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    partner_key: Mapped[str] = mapped_column(String(120), nullable=False)
    operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id", ondelete="RESTRICT"), nullable=False
    )
    evidence_asset_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    source_key: Mapped[str] = mapped_column(String(120), nullable=False)
    workflow_class: Mapped[str] = mapped_column(String(160), nullable=False)
    data_classification: Mapped[str] = mapped_column(String(24), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    decision_code: Mapped[str] = mapped_column(String(80), nullable=False)
    authorization_basis_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=text("now()")
    )
