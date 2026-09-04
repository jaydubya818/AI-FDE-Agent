from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ai_fde.models import Base, TimestampMixin, UUIDPrimaryKeyMixin, utc_now


class CustomerFactoryModelVersion(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "customer_factory_model_versions"
    __table_args__ = (
        UniqueConstraint("engagement_id", "version_number", name="customer_factory_model_version"),
        UniqueConstraint("engagement_id", "id", name="customer_factory_model_tenant_identity"),
        UniqueConstraint(
            "engagement_id",
            "id",
            "version_number",
            name="customer_factory_model_exact_version",
        ),
        CheckConstraint("version_number > 0", name="positive_version_number"),
        CheckConstraint("status IN ('DRAFT', 'APPROVED', 'STALE')", name="valid_status"),
        Index("ix_customer_factory_models_engagement_status", "engagement_id", "status"),
        Index(
            "uq_customer_factory_model_approved",
            "engagement_id",
            unique=True,
            postgresql_where=text("status = 'APPROVED'"),
        ),
    )

    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="DRAFT")
    organization: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    systems: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    repositories: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    environments: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    workflows: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    policies: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    authority_boundaries: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    constraints: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    risks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    baselines: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    evidence_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    verified_claim_refs: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    assumption_refs: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    factory_opportunity_refs: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    content_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id", ondelete="RESTRICT"), nullable=False
    )
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id", ondelete="RESTRICT")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stale_reason: Mapped[str | None] = mapped_column(Text)
    staled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FDLCReadinessAssessment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "fdlc_readiness_assessments"
    __table_args__ = (
        UniqueConstraint("engagement_id", "version_number", name="fdlc_readiness_version"),
        UniqueConstraint("engagement_id", "id", name="fdlc_readiness_tenant_identity"),
        UniqueConstraint(
            "engagement_id", "id", "version_number", name="fdlc_readiness_exact_version"
        ),
        ForeignKeyConstraint(
            ["engagement_id", "customer_factory_model_id", "customer_factory_model_version"],
            [
                "customer_factory_model_versions.engagement_id",
                "customer_factory_model_versions.id",
                "customer_factory_model_versions.version_number",
            ],
            name="fdlc_readiness_customer_model_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["engagement_id", "selected_opportunity_id", "selected_opportunity_version"],
            [
                "factory_opportunities.engagement_id",
                "factory_opportunities.id",
                "factory_opportunities.version_number",
            ],
            name="fdlc_readiness_selected_opportunity_tenant",
            ondelete="CASCADE",
        ),
        CheckConstraint("version_number > 0", name="positive_version_number"),
        CheckConstraint("status IN ('DRAFT', 'APPROVED', 'STALE')", name="valid_status"),
        CheckConstraint(
            "overall_status IN ('NOT_STARTED', 'IN_PROGRESS', 'BLOCKED', 'READY', "
            "'CONDITIONALLY_READY', 'NOT_READY', 'STALE')",
            name="valid_overall_status",
        ),
        Index("ix_fdlc_readiness_engagement_status", "engagement_id", "status"),
        Index(
            "uq_fdlc_readiness_approved",
            "engagement_id",
            unique=True,
            postgresql_where=text("status = 'APPROVED'"),
        ),
    )

    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="DRAFT")
    overall_status: Mapped[str] = mapped_column(String(32), nullable=False)
    customer_factory_model_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    customer_factory_model_version: Mapped[int] = mapped_column(Integer, nullable=False)
    selected_opportunity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    selected_opportunity_version: Mapped[int] = mapped_column(Integer, nullable=False)
    current_workflow_ref: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    target_workflow_ref: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    stages: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    content_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id", ondelete="RESTRICT"), nullable=False
    )
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id", ondelete="RESTRICT")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stale_reason: Mapped[str | None] = mapped_column(Text)
    staled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FactoryOpportunity(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "factory_opportunities"
    __table_args__ = (
        UniqueConstraint(
            "engagement_id", "opportunity_key", "version_number", name="factory_opportunity_version"
        ),
        UniqueConstraint("engagement_id", "id", name="factory_opportunity_tenant_identity"),
        UniqueConstraint(
            "engagement_id", "id", "version_number", name="factory_opportunity_exact_version"
        ),
        ForeignKeyConstraint(
            ["engagement_id", "customer_factory_model_id", "customer_factory_model_version"],
            [
                "customer_factory_model_versions.engagement_id",
                "customer_factory_model_versions.id",
                "customer_factory_model_versions.version_number",
            ],
            name="factory_opportunity_customer_model_tenant",
            ondelete="CASCADE",
        ),
        CheckConstraint("version_number > 0", name="positive_version_number"),
        CheckConstraint(
            "status IN ('CANDIDATE', 'ASSESSED', 'RECOMMENDED', 'SELECTED', 'REJECTED', 'STALE')",
            name="valid_status",
        ),
        CheckConstraint(
            "value_score BETWEEN 0 AND 100 AND verifiability_score BETWEEN 0 AND 100 "
            "AND readiness_score BETWEEN 0 AND 100 AND risk_score BETWEEN 0 AND 100 "
            "AND autonomy_potential BETWEEN 0 AND 100 AND priority_score BETWEEN 0 AND 100",
            name="valid_scores",
        ),
        Index("ix_factory_opportunities_engagement_status", "engagement_id", "status"),
        Index(
            "uq_factory_opportunity_selected",
            "engagement_id",
            unique=True,
            postgresql_where=text("status = 'SELECTED'"),
        ),
    )

    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False
    )
    opportunity_key: Mapped[str] = mapped_column(String(160), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="CANDIDATE")
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    source_workflow_ref: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    customer_factory_model_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    customer_factory_model_version: Mapped[int] = mapped_column(Integer, nullable=False)
    value_score: Mapped[int] = mapped_column(Integer, nullable=False)
    verifiability_score: Mapped[int] = mapped_column(Integer, nullable=False)
    readiness_score: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False)
    autonomy_potential: Mapped[int] = mapped_column(Integer, nullable=False)
    priority_score: Mapped[int] = mapped_column(Integer, nullable=False)
    factors: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    rubric: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    rubric_version: Mapped[str] = mapped_column(String(64), nullable=False)
    economics_ref: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    evidence_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    rationale: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    blockers: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    content_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id", ondelete="RESTRICT"), nullable=False
    )
    selected_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id", ondelete="RESTRICT")
    )
    selected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    selection_reason: Mapped[str | None] = mapped_column(Text)
    rejected_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id", ondelete="RESTRICT")
    )
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    stale_reason: Mapped[str | None] = mapped_column(Text)
    staled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FactoryDeploymentPackageVersion(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "factory_deployment_package_versions"
    __table_args__ = (
        UniqueConstraint(
            "engagement_id", "package_id", "package_version", name="deployment_package_version"
        ),
        UniqueConstraint("package_id", "package_version", name="deployment_package_global_version"),
        UniqueConstraint("engagement_id", "id", name="deployment_package_version_tenant_identity"),
        UniqueConstraint(
            "engagement_id",
            "id",
            "package_version",
            name="deployment_package_exact_version",
        ),
        UniqueConstraint(
            "engagement_id",
            "id",
            "package_id",
            "package_version",
            name="deployment_package_exact_external_version",
        ),
        ForeignKeyConstraint(
            ["engagement_id", "customer_factory_model_id", "customer_factory_model_version"],
            [
                "customer_factory_model_versions.engagement_id",
                "customer_factory_model_versions.id",
                "customer_factory_model_versions.version_number",
            ],
            name="deployment_package_customer_model_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["engagement_id", "readiness_assessment_id", "readiness_assessment_version"],
            [
                "fdlc_readiness_assessments.engagement_id",
                "fdlc_readiness_assessments.id",
                "fdlc_readiness_assessments.version_number",
            ],
            name="deployment_package_readiness_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["engagement_id", "factory_opportunity_id", "factory_opportunity_version"],
            [
                "factory_opportunities.engagement_id",
                "factory_opportunities.id",
                "factory_opportunities.version_number",
            ],
            name="deployment_package_opportunity_tenant",
            ondelete="CASCADE",
        ),
        CheckConstraint("package_version > 0", name="positive_package_version"),
        CheckConstraint("issuer_type = 'FDLC_FACTORY_ENGINEER'", name="valid_issuer_type"),
        CheckConstraint(
            "issuer_authority_scope = 'DEPLOYMENT_PACKAGE_PUBLISH'",
            name="valid_issuer_authority_scope",
        ),
        CheckConstraint(
            "status IN ('DRAFT', 'READY_FOR_REVIEW', 'APPROVED', 'PUBLISHED', "
            "'SUPERSEDED', 'REJECTED', 'REVOKED', 'STALE')",
            name="valid_status",
        ),
        Index("ix_deployment_packages_engagement_status", "engagement_id", "status", "package_id"),
        Index(
            "uq_deployment_package_published",
            "engagement_id",
            unique=True,
            postgresql_where=text("status = 'PUBLISHED'"),
        ),
    )

    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False
    )
    package_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    package_version: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(
        String(80), nullable=False, default="fdlc.factory-deployment-package/v1"
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT")
    issuer_id: Mapped[str] = mapped_column(String(255), nullable=False)
    issuer_type: Mapped[str] = mapped_column(String(80), nullable=False)
    issuer_environment: Mapped[str] = mapped_column(String(120), nullable=False)
    issuer_authority_scope: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_factory_model_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    customer_factory_model_version: Mapped[int] = mapped_column(Integer, nullable=False)
    current_workflow_ref: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    target_workflow_ref: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    readiness_assessment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    readiness_assessment_version: Mapped[int] = mapped_column(Integer, nullable=False)
    factory_opportunity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    factory_opportunity_version: Mapped[int] = mapped_column(Integer, nullable=False)
    target: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    contract: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    digest: Mapped[str | None] = mapped_column(String(71))
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id", ondelete="RESTRICT"), nullable=False
    )
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id", ondelete="RESTRICT")
    )
    approval_binding: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    staled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state_reason: Mapped[str | None] = mapped_column(Text)


class PackageRetrievalGrant(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "package_retrieval_grants"
    __table_args__ = (
        UniqueConstraint("token_digest", name="package_retrieval_token_digest"),
        ForeignKeyConstraint(
            ["engagement_id", "service_operator_id"],
            ["engagement_members.engagement_id", "engagement_members.operator_id"],
            name="package_retrieval_grant_membership_tenant",
            ondelete="CASCADE",
        ),
        CheckConstraint("scope = 'deployment-packages:retrieve'", name="valid_scope"),
        CheckConstraint("expires_at > created_at", name="valid_expiry"),
        Index("ix_package_retrieval_grants_operator", "service_operator_id", "revoked_at"),
    )

    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False
    )
    service_operator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    requester_identity: Mapped[str] = mapped_column(String(255), nullable=False)
    requester_system: Mapped[str] = mapped_column(String(255), nullable=False)
    token_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(
        String(80), nullable=False, default="deployment-packages:retrieve"
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id", ondelete="RESTRICT"), nullable=False
    )


class PackageRetrievalEvent(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "package_retrieval_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["engagement_id", "package_version_id", "package_id", "package_version"],
            [
                "factory_deployment_package_versions.engagement_id",
                "factory_deployment_package_versions.id",
                "factory_deployment_package_versions.package_id",
                "factory_deployment_package_versions.package_version",
            ],
            name="package_retrieval_event_package_tenant",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "result IN ('RETRIEVED', 'DENIED_NOT_PUBLISHED', 'DENIED_STALE', "
            "'DENIED_REVOKED', 'DENIED_INTEGRITY', 'NOT_FOUND')",
            name="valid_result",
        ),
        CheckConstraint(
            "(result = 'NOT_FOUND' AND package_version_id IS NULL AND digest IS NULL) OR "
            "(result <> 'NOT_FOUND' AND package_version_id IS NOT NULL)",
            name="valid_package_binding",
        ),
        Index("ix_package_retrieval_events_package_created", "package_id", "created_at"),
        Index("ix_package_retrieval_events_engagement_created", "engagement_id", "created_at"),
    )

    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False
    )
    package_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    package_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    package_version: Mapped[int] = mapped_column(Integer, nullable=False)
    requester_identity: Mapped[str] = mapped_column(String(255), nullable=False)
    requester_system: Mapped[str] = mapped_column(String(255), nullable=False)
    result: Mapped[str] = mapped_column(String(48), nullable=False)
    digest: Mapped[str | None] = mapped_column(String(71))
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
