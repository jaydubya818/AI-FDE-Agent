"""Factory Engineer trusted deployment handoff

Revision ID: 9b0d4e7c2f11
Revises: a62f7e31c904
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9b0d4e7c2f11"
down_revision: str | None = "a62f7e31c904"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "customer_factory_model_versions",
        sa.Column("engagement_id", sa.UUID(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("organization", postgresql.JSONB(), nullable=False),
        sa.Column("systems", postgresql.JSONB(), nullable=False),
        sa.Column("repositories", postgresql.JSONB(), nullable=False),
        sa.Column("environments", postgresql.JSONB(), nullable=False),
        sa.Column("workflows", postgresql.JSONB(), nullable=False),
        sa.Column("policies", postgresql.JSONB(), nullable=False),
        sa.Column("authority_boundaries", postgresql.JSONB(), nullable=False),
        sa.Column("constraints", postgresql.JSONB(), nullable=False),
        sa.Column("risks", postgresql.JSONB(), nullable=False),
        sa.Column("baselines", postgresql.JSONB(), nullable=False),
        sa.Column("evidence_refs", postgresql.JSONB(), nullable=False),
        sa.Column("verified_claim_refs", postgresql.JSONB(), nullable=False),
        sa.Column("assumption_refs", postgresql.JSONB(), nullable=False),
        sa.Column("factory_opportunity_refs", postgresql.JSONB(), nullable=False),
        sa.Column("content_digest", sa.String(length=71), nullable=False),
        sa.Column("created_by_id", sa.UUID(), nullable=False),
        sa.Column("approved_by_id", sa.UUID()),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("stale_reason", sa.Text()),
        sa.Column("staled_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "version_number > 0",
            name=op.f("ck_customer_factory_model_versions_positive_version_number"),
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'APPROVED', 'STALE')",
            name=op.f("ck_customer_factory_model_versions_valid_status"),
        ),
        sa.ForeignKeyConstraint(
            ["engagement_id"],
            ["engagements.id"],
            name=op.f("fk_customer_factory_model_versions_engagement_id_engagements"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["operators.id"],
            name=op.f("fk_customer_factory_model_versions_created_by_id_operators"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_id"],
            ["operators.id"],
            name=op.f("fk_customer_factory_model_versions_approved_by_id_operators"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customer_factory_model_versions")),
        sa.UniqueConstraint(
            "engagement_id", "version_number", name="customer_factory_model_version"
        ),
        sa.UniqueConstraint("engagement_id", "id", name="customer_factory_model_tenant_identity"),
        sa.UniqueConstraint(
            "engagement_id",
            "id",
            "version_number",
            name="customer_factory_model_exact_version",
        ),
    )
    op.create_index(
        "ix_customer_factory_models_engagement_status",
        "customer_factory_model_versions",
        ["engagement_id", "status"],
    )
    op.create_index(
        "uq_customer_factory_model_approved",
        "customer_factory_model_versions",
        ["engagement_id"],
        unique=True,
        postgresql_where=sa.text("status = 'APPROVED'"),
    )

    op.create_table(
        "fdlc_readiness_assessments",
        sa.Column("engagement_id", sa.UUID(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("overall_status", sa.String(length=32), nullable=False),
        sa.Column("customer_factory_model_id", sa.UUID(), nullable=False),
        sa.Column("customer_factory_model_version", sa.Integer(), nullable=False),
        sa.Column("selected_opportunity_id", sa.UUID(), nullable=False),
        sa.Column("selected_opportunity_version", sa.Integer(), nullable=False),
        sa.Column("current_workflow_ref", postgresql.JSONB(), nullable=False),
        sa.Column("target_workflow_ref", postgresql.JSONB(), nullable=False),
        sa.Column("stages", postgresql.JSONB(), nullable=False),
        sa.Column("content_digest", sa.String(length=71), nullable=False),
        sa.Column("created_by_id", sa.UUID(), nullable=False),
        sa.Column("approved_by_id", sa.UUID()),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("stale_reason", sa.Text()),
        sa.Column("staled_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "version_number > 0",
            name=op.f("ck_fdlc_readiness_assessments_positive_version_number"),
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'APPROVED', 'STALE')",
            name=op.f("ck_fdlc_readiness_assessments_valid_status"),
        ),
        sa.CheckConstraint(
            "overall_status IN ('NOT_STARTED', 'IN_PROGRESS', 'BLOCKED', 'READY', "
            "'CONDITIONALLY_READY', 'NOT_READY', 'STALE')",
            name=op.f("ck_fdlc_readiness_assessments_valid_overall_status"),
        ),
        sa.ForeignKeyConstraint(
            ["engagement_id"],
            ["engagements.id"],
            name=op.f("fk_fdlc_readiness_assessments_engagement_id_engagements"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["engagement_id", "customer_factory_model_id", "customer_factory_model_version"],
            [
                "customer_factory_model_versions.engagement_id",
                "customer_factory_model_versions.id",
                "customer_factory_model_versions.version_number",
            ],
            name="fdlc_readiness_customer_model_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["operators.id"],
            name=op.f("fk_fdlc_readiness_assessments_created_by_id_operators"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_id"],
            ["operators.id"],
            name=op.f("fk_fdlc_readiness_assessments_approved_by_id_operators"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fdlc_readiness_assessments")),
        sa.UniqueConstraint("engagement_id", "version_number", name="fdlc_readiness_version"),
        sa.UniqueConstraint("engagement_id", "id", name="fdlc_readiness_tenant_identity"),
        sa.UniqueConstraint(
            "engagement_id", "id", "version_number", name="fdlc_readiness_exact_version"
        ),
    )
    op.create_index(
        "ix_fdlc_readiness_engagement_status",
        "fdlc_readiness_assessments",
        ["engagement_id", "status"],
    )
    op.create_index(
        "uq_fdlc_readiness_approved",
        "fdlc_readiness_assessments",
        ["engagement_id"],
        unique=True,
        postgresql_where=sa.text("status = 'APPROVED'"),
    )

    op.create_table(
        "factory_opportunities",
        sa.Column("engagement_id", sa.UUID(), nullable=False),
        sa.Column("opportunity_key", sa.String(length=160), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("source_workflow_ref", postgresql.JSONB(), nullable=False),
        sa.Column("customer_factory_model_id", sa.UUID(), nullable=False),
        sa.Column("customer_factory_model_version", sa.Integer(), nullable=False),
        sa.Column("value_score", sa.Integer(), nullable=False),
        sa.Column("verifiability_score", sa.Integer(), nullable=False),
        sa.Column("readiness_score", sa.Integer(), nullable=False),
        sa.Column("risk_score", sa.Integer(), nullable=False),
        sa.Column("autonomy_potential", sa.Integer(), nullable=False),
        sa.Column("priority_score", sa.Integer(), nullable=False),
        sa.Column("factors", postgresql.JSONB(), nullable=False),
        sa.Column("rubric", postgresql.JSONB(), nullable=False),
        sa.Column("rubric_version", sa.String(length=64), nullable=False),
        sa.Column("economics_ref", postgresql.JSONB(), nullable=False),
        sa.Column("evidence_refs", postgresql.JSONB(), nullable=False),
        sa.Column("rationale", postgresql.JSONB(), nullable=False),
        sa.Column("blockers", postgresql.JSONB(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False),
        sa.Column("content_digest", sa.String(length=71), nullable=False),
        sa.Column("created_by_id", sa.UUID(), nullable=False),
        sa.Column("selected_by_id", sa.UUID()),
        sa.Column("selected_at", sa.DateTime(timezone=True)),
        sa.Column("selection_reason", sa.Text()),
        sa.Column("rejected_by_id", sa.UUID()),
        sa.Column("rejected_at", sa.DateTime(timezone=True)),
        sa.Column("rejection_reason", sa.Text()),
        sa.Column("stale_reason", sa.Text()),
        sa.Column("staled_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "version_number > 0", name=op.f("ck_factory_opportunities_positive_version_number")
        ),
        sa.CheckConstraint(
            "status IN ('CANDIDATE', 'ASSESSED', 'RECOMMENDED', 'SELECTED', 'REJECTED', 'STALE')",
            name=op.f("ck_factory_opportunities_valid_status"),
        ),
        sa.CheckConstraint(
            "value_score BETWEEN 0 AND 100 AND verifiability_score BETWEEN 0 AND 100 "
            "AND readiness_score BETWEEN 0 AND 100 AND risk_score BETWEEN 0 AND 100 "
            "AND autonomy_potential BETWEEN 0 AND 100 AND priority_score BETWEEN 0 AND 100",
            name=op.f("ck_factory_opportunities_valid_scores"),
        ),
        sa.ForeignKeyConstraint(
            ["engagement_id"],
            ["engagements.id"],
            name=op.f("fk_factory_opportunities_engagement_id_engagements"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["engagement_id", "customer_factory_model_id", "customer_factory_model_version"],
            [
                "customer_factory_model_versions.engagement_id",
                "customer_factory_model_versions.id",
                "customer_factory_model_versions.version_number",
            ],
            name="factory_opportunity_customer_model_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["operators.id"],
            name=op.f("fk_factory_opportunities_created_by_id_operators"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["selected_by_id"],
            ["operators.id"],
            name=op.f("fk_factory_opportunities_selected_by_id_operators"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["rejected_by_id"],
            ["operators.id"],
            name=op.f("fk_factory_opportunities_rejected_by_id_operators"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_factory_opportunities")),
        sa.UniqueConstraint(
            "engagement_id",
            "opportunity_key",
            "version_number",
            name="factory_opportunity_version",
        ),
        sa.UniqueConstraint("engagement_id", "id", name="factory_opportunity_tenant_identity"),
        sa.UniqueConstraint(
            "engagement_id", "id", "version_number", name="factory_opportunity_exact_version"
        ),
    )
    op.create_index(
        "ix_factory_opportunities_engagement_status",
        "factory_opportunities",
        ["engagement_id", "status"],
    )
    op.create_index(
        "uq_factory_opportunity_selected",
        "factory_opportunities",
        ["engagement_id"],
        unique=True,
        postgresql_where=sa.text("status = 'SELECTED'"),
    )
    op.create_foreign_key(
        "fdlc_readiness_selected_opportunity_tenant",
        "fdlc_readiness_assessments",
        "factory_opportunities",
        ["engagement_id", "selected_opportunity_id", "selected_opportunity_version"],
        ["engagement_id", "id", "version_number"],
        ondelete="CASCADE",
    )

    op.create_table(
        "factory_deployment_package_versions",
        sa.Column("engagement_id", sa.UUID(), nullable=False),
        sa.Column("package_id", sa.UUID(), nullable=False),
        sa.Column("package_version", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("issuer_id", sa.String(length=255), nullable=False),
        sa.Column("issuer_type", sa.String(length=80), nullable=False),
        sa.Column("issuer_environment", sa.String(length=120), nullable=False),
        sa.Column("issuer_authority_scope", sa.String(length=255), nullable=False),
        sa.Column("customer_factory_model_id", sa.UUID(), nullable=False),
        sa.Column("customer_factory_model_version", sa.Integer(), nullable=False),
        sa.Column("current_workflow_ref", postgresql.JSONB(), nullable=False),
        sa.Column("target_workflow_ref", postgresql.JSONB(), nullable=False),
        sa.Column("readiness_assessment_id", sa.UUID(), nullable=False),
        sa.Column("readiness_assessment_version", sa.Integer(), nullable=False),
        sa.Column("factory_opportunity_id", sa.UUID(), nullable=False),
        sa.Column("factory_opportunity_version", sa.Integer(), nullable=False),
        sa.Column("target", postgresql.JSONB(), nullable=False),
        sa.Column("contract", postgresql.JSONB(), nullable=False),
        sa.Column("digest", sa.String(length=71)),
        sa.Column("created_by_id", sa.UUID(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True)),
        sa.Column("approved_by_id", sa.UUID()),
        sa.Column("approval_binding", postgresql.JSONB()),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("rejected_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("staled_at", sa.DateTime(timezone=True)),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        sa.Column("state_reason", sa.Text()),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "package_version > 0",
            name=op.f("ck_factory_deployment_package_versions_positive_package_version"),
        ),
        sa.CheckConstraint(
            "issuer_type = 'FDLC_FACTORY_ENGINEER'",
            name=op.f("ck_factory_deployment_package_versions_valid_issuer_type"),
        ),
        sa.CheckConstraint(
            "issuer_authority_scope = 'DEPLOYMENT_PACKAGE_PUBLISH'",
            name=op.f("ck_factory_deployment_package_versions_valid_issuer_authority_scope"),
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'READY_FOR_REVIEW', 'APPROVED', 'PUBLISHED', "
            "'SUPERSEDED', 'REJECTED', 'REVOKED', 'STALE')",
            name=op.f("ck_factory_deployment_package_versions_valid_status"),
        ),
        sa.ForeignKeyConstraint(
            ["engagement_id"],
            ["engagements.id"],
            name=op.f("fk_factory_deployment_package_versions_engagement_id_engagements"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["engagement_id", "customer_factory_model_id", "customer_factory_model_version"],
            [
                "customer_factory_model_versions.engagement_id",
                "customer_factory_model_versions.id",
                "customer_factory_model_versions.version_number",
            ],
            name="deployment_package_customer_model_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["engagement_id", "readiness_assessment_id", "readiness_assessment_version"],
            [
                "fdlc_readiness_assessments.engagement_id",
                "fdlc_readiness_assessments.id",
                "fdlc_readiness_assessments.version_number",
            ],
            name="deployment_package_readiness_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["engagement_id", "factory_opportunity_id", "factory_opportunity_version"],
            [
                "factory_opportunities.engagement_id",
                "factory_opportunities.id",
                "factory_opportunities.version_number",
            ],
            name="deployment_package_opportunity_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["operators.id"],
            name=op.f("fk_factory_deployment_package_versions_created_by_id_operators"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_id"],
            ["operators.id"],
            name=op.f("fk_factory_deployment_package_versions_approved_by_id_operators"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_factory_deployment_package_versions")),
        sa.UniqueConstraint(
            "engagement_id",
            "package_id",
            "package_version",
            name="deployment_package_version",
        ),
        sa.UniqueConstraint(
            "package_id", "package_version", name="deployment_package_global_version"
        ),
        sa.UniqueConstraint(
            "engagement_id", "id", name="deployment_package_version_tenant_identity"
        ),
        sa.UniqueConstraint(
            "engagement_id",
            "id",
            "package_version",
            name="deployment_package_exact_version",
        ),
        sa.UniqueConstraint(
            "engagement_id",
            "id",
            "package_id",
            "package_version",
            name="deployment_package_exact_external_version",
        ),
    )
    op.create_index(
        "ix_deployment_packages_engagement_status",
        "factory_deployment_package_versions",
        ["engagement_id", "status", "package_id"],
    )
    op.create_index(
        "uq_deployment_package_published",
        "factory_deployment_package_versions",
        ["engagement_id"],
        unique=True,
        postgresql_where=sa.text("status = 'PUBLISHED'"),
    )

    op.create_table(
        "package_retrieval_grants",
        sa.Column("engagement_id", sa.UUID(), nullable=False),
        sa.Column("service_operator_id", sa.UUID(), nullable=False),
        sa.Column("requester_identity", sa.String(length=255), nullable=False),
        sa.Column("requester_system", sa.String(length=255), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=80), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "scope = 'deployment-packages:retrieve'",
            name=op.f("ck_package_retrieval_grants_valid_scope"),
        ),
        sa.CheckConstraint(
            "expires_at > created_at", name=op.f("ck_package_retrieval_grants_valid_expiry")
        ),
        sa.ForeignKeyConstraint(
            ["engagement_id"],
            ["engagements.id"],
            name=op.f("fk_package_retrieval_grants_engagement_id_engagements"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["engagement_id", "service_operator_id"],
            ["engagement_members.engagement_id", "engagement_members.operator_id"],
            name="package_retrieval_grant_membership_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["operators.id"],
            name=op.f("fk_package_retrieval_grants_created_by_id_operators"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_package_retrieval_grants")),
        sa.UniqueConstraint("token_digest", name="package_retrieval_token_digest"),
    )
    op.create_index(
        "ix_package_retrieval_grants_operator",
        "package_retrieval_grants",
        ["service_operator_id", "revoked_at"],
    )

    op.create_table(
        "package_retrieval_events",
        sa.Column("engagement_id", sa.UUID(), nullable=False),
        sa.Column("package_version_id", sa.UUID()),
        sa.Column("package_id", sa.UUID(), nullable=False),
        sa.Column("package_version", sa.Integer(), nullable=False),
        sa.Column("requester_identity", sa.String(length=255), nullable=False),
        sa.Column("requester_system", sa.String(length=255), nullable=False),
        sa.Column("result", sa.String(length=48), nullable=False),
        sa.Column("digest", sa.String(length=71)),
        sa.Column("correlation_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "result IN ('RETRIEVED', 'DENIED_NOT_PUBLISHED', 'DENIED_STALE', "
            "'DENIED_REVOKED', 'DENIED_INTEGRITY', 'NOT_FOUND')",
            name=op.f("ck_package_retrieval_events_valid_result"),
        ),
        sa.CheckConstraint(
            "(result = 'NOT_FOUND' AND package_version_id IS NULL AND digest IS NULL) OR "
            "(result <> 'NOT_FOUND' AND package_version_id IS NOT NULL)",
            name=op.f("ck_package_retrieval_events_valid_package_binding"),
        ),
        sa.ForeignKeyConstraint(
            ["engagement_id"],
            ["engagements.id"],
            name=op.f("fk_package_retrieval_events_engagement_id_engagements"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_package_retrieval_events")),
    )
    op.create_index(
        "ix_package_retrieval_events_package_created",
        "package_retrieval_events",
        ["package_id", "created_at"],
    )
    op.create_index(
        "ix_package_retrieval_events_engagement_created",
        "package_retrieval_events",
        ["engagement_id", "created_at"],
    )

    _install_version_immutability_triggers()
    _install_grant_immutability_trigger()
    _enable_row_security()


def _install_version_immutability_triggers() -> None:
    _install_customer_model_trigger()
    _install_readiness_trigger()
    _install_opportunity_trigger()
    _install_package_trigger()


def _install_customer_model_trigger() -> None:
    op.execute(
        """
        CREATE FUNCTION ai_fde_protect_customer_factory_model_version()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.status <> 'DRAFT'
                   OR NEW.approved_by_id IS NOT NULL OR NEW.approved_at IS NOT NULL
                   OR NEW.stale_reason IS NOT NULL OR NEW.staled_at IS NOT NULL THEN
                    RAISE EXCEPTION 'customer factory model versions must begin as DRAFT';
                END IF;
                RETURN NEW;
            END IF;

            IF (to_jsonb(NEW) - ARRAY[
                    'status', 'approved_by_id', 'approved_at', 'stale_reason', 'staled_at',
                    'updated_at'
                ]) IS DISTINCT FROM (to_jsonb(OLD) - ARRAY[
                    'status', 'approved_by_id', 'approved_at', 'stale_reason', 'staled_at',
                    'updated_at'
                ]) THEN
                RAISE EXCEPTION 'customer factory model content is immutable';
            END IF;
            IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
                (OLD.status = 'DRAFT' AND NEW.status IN ('APPROVED', 'STALE')) OR
                (OLD.status = 'APPROVED' AND NEW.status = 'STALE')
            ) THEN
                RAISE EXCEPTION 'invalid customer factory model status transition: % to %',
                    OLD.status, NEW.status;
            END IF;
            IF ROW(NEW.approved_by_id, NEW.approved_at)
               IS DISTINCT FROM ROW(OLD.approved_by_id, OLD.approved_at) THEN
                IF NOT (OLD.status = 'DRAFT' AND NEW.status = 'APPROVED'
                        AND NEW.approved_by_id IS NOT NULL AND NEW.approved_at IS NOT NULL) THEN
                    RAISE EXCEPTION 'customer factory model approval metadata is immutable';
                END IF;
            END IF;
            IF ROW(NEW.stale_reason, NEW.staled_at)
               IS DISTINCT FROM ROW(OLD.stale_reason, OLD.staled_at) THEN
                IF NOT (OLD.status <> 'STALE' AND NEW.status = 'STALE'
                        AND NEW.stale_reason IS NOT NULL AND NEW.staled_at IS NOT NULL) THEN
                    RAISE EXCEPTION 'customer factory model staleness metadata is immutable';
                END IF;
            END IF;
            IF NEW.status = 'APPROVED'
               AND (NEW.approved_by_id IS NULL OR NEW.approved_at IS NULL) THEN
                RAISE EXCEPTION 'approved customer factory model requires approval metadata';
            END IF;
            IF NEW.status = 'STALE'
               AND (NEW.stale_reason IS NULL OR NEW.staled_at IS NULL) THEN
                RAISE EXCEPTION 'stale customer factory model requires a reason and timestamp';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER protect_customer_factory_model_version
        BEFORE INSERT OR UPDATE ON customer_factory_model_versions
        FOR EACH ROW EXECUTE FUNCTION ai_fde_protect_customer_factory_model_version()
        """
    )


def _install_readiness_trigger() -> None:
    op.execute(
        """
        CREATE FUNCTION ai_fde_protect_fdlc_readiness_assessment()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.status <> 'DRAFT'
                   OR NEW.approved_by_id IS NOT NULL OR NEW.approved_at IS NOT NULL
                   OR NEW.stale_reason IS NOT NULL OR NEW.staled_at IS NOT NULL THEN
                    RAISE EXCEPTION 'readiness assessments must begin as DRAFT';
                END IF;
                RETURN NEW;
            END IF;

            IF (to_jsonb(NEW) - ARRAY[
                    'status', 'overall_status', 'approved_by_id', 'approved_at',
                    'stale_reason', 'staled_at', 'updated_at'
                ]) IS DISTINCT FROM (to_jsonb(OLD) - ARRAY[
                    'status', 'overall_status', 'approved_by_id', 'approved_at',
                    'stale_reason', 'staled_at', 'updated_at'
                ]) THEN
                RAISE EXCEPTION 'readiness assessment content is immutable';
            END IF;
            IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
                (OLD.status = 'DRAFT' AND NEW.status IN ('APPROVED', 'STALE')) OR
                (OLD.status = 'APPROVED' AND NEW.status = 'STALE')
            ) THEN
                RAISE EXCEPTION 'invalid readiness assessment status transition: % to %',
                    OLD.status, NEW.status;
            END IF;
            IF NEW.overall_status IS DISTINCT FROM OLD.overall_status
               AND NOT (OLD.status <> 'STALE' AND NEW.status = 'STALE'
                        AND NEW.overall_status = 'STALE') THEN
                RAISE EXCEPTION 'readiness result is immutable except when becoming stale';
            END IF;
            IF ROW(NEW.approved_by_id, NEW.approved_at)
               IS DISTINCT FROM ROW(OLD.approved_by_id, OLD.approved_at) THEN
                IF NOT (OLD.status = 'DRAFT' AND NEW.status = 'APPROVED'
                        AND NEW.overall_status = 'READY'
                        AND NEW.approved_by_id IS NOT NULL AND NEW.approved_at IS NOT NULL) THEN
                    RAISE EXCEPTION 'readiness approval metadata is immutable';
                END IF;
            END IF;
            IF ROW(NEW.stale_reason, NEW.staled_at)
               IS DISTINCT FROM ROW(OLD.stale_reason, OLD.staled_at) THEN
                IF NOT (OLD.status <> 'STALE' AND NEW.status = 'STALE'
                        AND NEW.overall_status = 'STALE'
                        AND NEW.stale_reason IS NOT NULL AND NEW.staled_at IS NOT NULL) THEN
                    RAISE EXCEPTION 'readiness staleness metadata is immutable';
                END IF;
            END IF;
            IF NEW.status = 'APPROVED'
               AND (NEW.overall_status <> 'READY'
                    OR NEW.approved_by_id IS NULL OR NEW.approved_at IS NULL) THEN
                RAISE EXCEPTION 'approved readiness requires READY and approval metadata';
            END IF;
            IF NEW.status = 'STALE'
               AND (NEW.overall_status <> 'STALE'
                    OR NEW.stale_reason IS NULL OR NEW.staled_at IS NULL) THEN
                RAISE EXCEPTION 'stale readiness requires a reason and timestamp';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER protect_fdlc_readiness_assessment
        BEFORE INSERT OR UPDATE ON fdlc_readiness_assessments
        FOR EACH ROW EXECUTE FUNCTION ai_fde_protect_fdlc_readiness_assessment()
        """
    )


def _install_opportunity_trigger() -> None:
    op.execute(
        """
        CREATE FUNCTION ai_fde_protect_factory_opportunity()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.status NOT IN ('CANDIDATE', 'ASSESSED', 'RECOMMENDED')
                   OR NEW.selected_by_id IS NOT NULL OR NEW.selected_at IS NOT NULL
                   OR NEW.selection_reason IS NOT NULL
                   OR NEW.rejected_by_id IS NOT NULL OR NEW.rejected_at IS NOT NULL
                   OR NEW.rejection_reason IS NOT NULL
                   OR NEW.stale_reason IS NOT NULL OR NEW.staled_at IS NOT NULL THEN
                    RAISE EXCEPTION 'factory opportunities must begin unselected and current';
                END IF;
                RETURN NEW;
            END IF;

            IF (to_jsonb(NEW) - ARRAY[
                    'status', 'selected_by_id', 'selected_at', 'selection_reason',
                    'rejected_by_id', 'rejected_at', 'rejection_reason',
                    'stale_reason', 'staled_at', 'updated_at'
                ]) IS DISTINCT FROM (to_jsonb(OLD) - ARRAY[
                    'status', 'selected_by_id', 'selected_at', 'selection_reason',
                    'rejected_by_id', 'rejected_at', 'rejection_reason',
                    'stale_reason', 'staled_at', 'updated_at'
                ]) THEN
                RAISE EXCEPTION 'factory opportunity content and score are immutable';
            END IF;
            IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
                (OLD.status = 'CANDIDATE'
                    AND NEW.status IN ('ASSESSED', 'RECOMMENDED', 'REJECTED', 'STALE')) OR
                (OLD.status IN ('ASSESSED', 'RECOMMENDED')
                    AND NEW.status IN ('SELECTED', 'REJECTED', 'STALE')) OR
                (OLD.status = 'SELECTED' AND NEW.status = 'STALE')
            ) THEN
                RAISE EXCEPTION 'invalid factory opportunity status transition: % to %',
                    OLD.status, NEW.status;
            END IF;
            IF ROW(NEW.selected_by_id, NEW.selected_at, NEW.selection_reason)
               IS DISTINCT FROM ROW(OLD.selected_by_id, OLD.selected_at, OLD.selection_reason) THEN
                IF NOT (OLD.status IN ('ASSESSED', 'RECOMMENDED') AND NEW.status = 'SELECTED'
                        AND NEW.selected_by_id IS NOT NULL AND NEW.selected_at IS NOT NULL
                        AND NEW.selection_reason IS NOT NULL) THEN
                    RAISE EXCEPTION 'opportunity selection metadata is immutable';
                END IF;
            END IF;
            IF ROW(NEW.stale_reason, NEW.staled_at)
               IS DISTINCT FROM ROW(OLD.stale_reason, OLD.staled_at) THEN
                IF NOT (OLD.status <> 'STALE' AND NEW.status = 'STALE'
                        AND NEW.stale_reason IS NOT NULL AND NEW.staled_at IS NOT NULL) THEN
                    RAISE EXCEPTION 'opportunity staleness metadata is immutable';
                END IF;
            END IF;
            IF ROW(NEW.rejected_by_id, NEW.rejected_at, NEW.rejection_reason)
               IS DISTINCT FROM ROW(OLD.rejected_by_id, OLD.rejected_at, OLD.rejection_reason) THEN
                IF NOT (OLD.status IN ('CANDIDATE', 'ASSESSED', 'RECOMMENDED')
                        AND NEW.status = 'REJECTED'
                        AND NEW.rejected_by_id IS NOT NULL AND NEW.rejected_at IS NOT NULL
                        AND NEW.rejection_reason IS NOT NULL) THEN
                    RAISE EXCEPTION 'opportunity rejection metadata is immutable';
                END IF;
            END IF;
            IF NEW.status = 'SELECTED'
               AND (NEW.selected_by_id IS NULL OR NEW.selected_at IS NULL
                    OR NEW.selection_reason IS NULL) THEN
                RAISE EXCEPTION 'selected opportunity requires human decision metadata';
            END IF;
            IF NEW.status = 'STALE'
               AND (NEW.stale_reason IS NULL OR NEW.staled_at IS NULL) THEN
                RAISE EXCEPTION 'stale opportunity requires a reason and timestamp';
            END IF;
            IF NEW.status = 'REJECTED'
               AND (NEW.rejected_by_id IS NULL OR NEW.rejected_at IS NULL
                    OR NEW.rejection_reason IS NULL) THEN
                RAISE EXCEPTION 'rejected opportunity requires human decision metadata';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER protect_factory_opportunity
        BEFORE INSERT OR UPDATE ON factory_opportunities
        FOR EACH ROW EXECUTE FUNCTION ai_fde_protect_factory_opportunity()
        """
    )


def _install_package_trigger() -> None:
    op.execute(
        """
        CREATE FUNCTION ai_fde_protect_deployment_package_version()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
            existing_engagement_id uuid;
            existing_issuer_id text;
            existing_issuer_type text;
            existing_issuer_environment text;
            existing_issuer_authority_scope text;
            next_version integer;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                PERFORM pg_advisory_xact_lock(hashtextextended(NEW.package_id::text, 0));
                SELECT engagement_id, issuer_id, issuer_type, issuer_environment,
                       issuer_authority_scope
                INTO existing_engagement_id, existing_issuer_id, existing_issuer_type,
                     existing_issuer_environment, existing_issuer_authority_scope
                FROM factory_deployment_package_versions
                WHERE package_id = NEW.package_id
                ORDER BY package_version
                LIMIT 1;

                IF FOUND THEN
                    IF ROW(
                        NEW.engagement_id, NEW.issuer_id, NEW.issuer_type,
                        NEW.issuer_environment, NEW.issuer_authority_scope
                    ) IS DISTINCT FROM ROW(
                        existing_engagement_id, existing_issuer_id, existing_issuer_type,
                        existing_issuer_environment, existing_issuer_authority_scope
                    ) THEN
                        RAISE EXCEPTION
                            'package identity is permanently bound to its engagement and issuer';
                    END IF;
                    SELECT max(package_version) + 1 INTO next_version
                    FROM factory_deployment_package_versions
                    WHERE package_id = NEW.package_id;
                    IF NEW.package_version <> next_version THEN
                        RAISE EXCEPTION 'package version must be the next immutable version';
                    END IF;
                ELSIF NEW.package_version <> 1 THEN
                    RAISE EXCEPTION 'a new package identity must begin at version 1';
                END IF;

                IF NEW.status <> 'DRAFT'
                   OR NEW.digest IS NOT NULL OR NEW.issued_at IS NOT NULL
                   OR NEW.approved_by_id IS NOT NULL OR NEW.approval_binding IS NOT NULL
                   OR NEW.approved_at IS NOT NULL OR NEW.published_at IS NOT NULL
                   OR NEW.rejected_at IS NOT NULL OR NEW.revoked_at IS NOT NULL
                   OR NEW.staled_at IS NOT NULL OR NEW.superseded_at IS NOT NULL
                   OR NEW.state_reason IS NOT NULL THEN
                    RAISE EXCEPTION 'deployment package versions must begin as DRAFT';
                END IF;
                RETURN NEW;
            END IF;

            IF (to_jsonb(NEW) - ARRAY[
                    'status', 'digest', 'issued_at', 'approved_by_id', 'approval_binding',
                    'approved_at', 'published_at', 'rejected_at', 'revoked_at', 'staled_at',
                    'superseded_at', 'state_reason', 'updated_at'
                ]) IS DISTINCT FROM (to_jsonb(OLD) - ARRAY[
                    'status', 'digest', 'issued_at', 'approved_by_id', 'approval_binding',
                    'approved_at', 'published_at', 'rejected_at', 'revoked_at', 'staled_at',
                    'superseded_at', 'state_reason', 'updated_at'
                ]) THEN
                RAISE EXCEPTION 'deployment package versions are immutable; create a new version';
            END IF;

            IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
                (OLD.status = 'DRAFT'
                    AND NEW.status IN ('READY_FOR_REVIEW', 'REJECTED', 'STALE')) OR
                (OLD.status = 'READY_FOR_REVIEW'
                    AND NEW.status IN ('APPROVED', 'REJECTED', 'STALE')) OR
                (OLD.status = 'APPROVED' AND NEW.status IN ('PUBLISHED', 'REJECTED', 'STALE')) OR
                (OLD.status = 'PUBLISHED' AND NEW.status IN ('SUPERSEDED', 'REVOKED', 'STALE'))
            ) THEN
                RAISE EXCEPTION 'invalid deployment package status transition: % to %',
                    OLD.status, NEW.status;
            END IF;

            IF ROW(NEW.digest, NEW.issued_at, NEW.approved_by_id,
                   NEW.approval_binding, NEW.approved_at)
               IS DISTINCT FROM ROW(OLD.digest, OLD.issued_at, OLD.approved_by_id,
                                    OLD.approval_binding, OLD.approved_at) THEN
                IF NOT (OLD.status = 'READY_FOR_REVIEW' AND NEW.status = 'APPROVED'
                        AND NEW.digest ~ '^sha256:[0-9a-f]{64}$'
                        AND NEW.issued_at IS NOT NULL AND NEW.approved_by_id IS NOT NULL
                        AND NEW.approval_binding IS NOT NULL AND NEW.approved_at IS NOT NULL) THEN
                    RAISE EXCEPTION 'deployment package approval and digest are immutable';
                END IF;
            END IF;
            IF NEW.published_at IS DISTINCT FROM OLD.published_at
               AND NOT (OLD.status = 'APPROVED' AND NEW.status = 'PUBLISHED'
                        AND NEW.published_at IS NOT NULL) THEN
                RAISE EXCEPTION 'package publication timestamp is transition-bound';
            END IF;
            IF NEW.rejected_at IS DISTINCT FROM OLD.rejected_at
               AND NOT (OLD.status <> 'REJECTED' AND NEW.status = 'REJECTED'
                        AND NEW.rejected_at IS NOT NULL) THEN
                RAISE EXCEPTION 'package rejection timestamp is transition-bound';
            END IF;
            IF NEW.revoked_at IS DISTINCT FROM OLD.revoked_at
               AND NOT (OLD.status = 'PUBLISHED' AND NEW.status = 'REVOKED'
                        AND NEW.revoked_at IS NOT NULL) THEN
                RAISE EXCEPTION 'package revocation timestamp is transition-bound';
            END IF;
            IF NEW.staled_at IS DISTINCT FROM OLD.staled_at
               AND NOT (OLD.status <> 'STALE' AND NEW.status = 'STALE'
                        AND NEW.staled_at IS NOT NULL) THEN
                RAISE EXCEPTION 'package staleness timestamp is transition-bound';
            END IF;
            IF NEW.superseded_at IS DISTINCT FROM OLD.superseded_at
               AND NOT (OLD.status = 'PUBLISHED' AND NEW.status = 'SUPERSEDED'
                        AND NEW.superseded_at IS NOT NULL) THEN
                RAISE EXCEPTION 'package supersession timestamp is transition-bound';
            END IF;
            IF NEW.state_reason IS DISTINCT FROM OLD.state_reason
               AND NOT (OLD.status <> NEW.status
                        AND NEW.status IN ('REJECTED', 'REVOKED', 'STALE', 'SUPERSEDED')
                        AND NEW.state_reason IS NOT NULL) THEN
                RAISE EXCEPTION 'package state reason is transition-bound';
            END IF;

            IF (NEW.status IN ('APPROVED', 'PUBLISHED', 'REVOKED', 'SUPERSEDED')
                OR (NEW.status = 'STALE' AND NEW.digest IS NOT NULL))
               AND (NEW.digest !~ '^sha256:[0-9a-f]{64}$'
                    OR NEW.issued_at IS NULL OR NEW.approved_by_id IS NULL
                    OR NEW.approval_binding IS NULL OR NEW.approved_at IS NULL
                    OR NEW.approved_at > NEW.issued_at
                    OR NEW.approval_binding->>'approved_by'
                        IS DISTINCT FROM NEW.approved_by_id::text
                    OR (NEW.approval_binding->>'approved_at')::timestamptz
                        IS DISTINCT FROM NEW.approved_at
                    OR NEW.approval_binding->>'authorized_by_ref'
                        IS DISTINCT FROM NEW.approval_binding->'authority_basis_ref'->>'ref') THEN
                RAISE EXCEPTION 'approved package state requires immutable approval and digest';
            END IF;
            IF NEW.status = 'PUBLISHED' AND NEW.published_at IS NULL THEN
                RAISE EXCEPTION 'published package requires publication timestamp';
            END IF;
            IF NEW.status = 'REJECTED'
               AND (NEW.rejected_at IS NULL OR NEW.state_reason IS NULL) THEN
                RAISE EXCEPTION 'rejected package requires a reason and timestamp';
            END IF;
            IF NEW.status = 'REVOKED'
               AND (NEW.revoked_at IS NULL OR NEW.state_reason IS NULL) THEN
                RAISE EXCEPTION 'revoked package requires a reason and timestamp';
            END IF;
            IF NEW.status = 'STALE'
               AND (NEW.staled_at IS NULL OR NEW.state_reason IS NULL) THEN
                RAISE EXCEPTION 'stale package requires a reason and timestamp';
            END IF;
            IF NEW.status = 'SUPERSEDED'
               AND (NEW.superseded_at IS NULL OR NEW.state_reason IS NULL) THEN
                RAISE EXCEPTION 'superseded package requires a reason and timestamp';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER protect_deployment_package_version
        BEFORE INSERT OR UPDATE ON factory_deployment_package_versions
        FOR EACH ROW EXECUTE FUNCTION ai_fde_protect_deployment_package_version()
        """
    )


def _install_grant_immutability_trigger() -> None:
    op.execute(
        """
        CREATE FUNCTION ai_fde_protect_package_retrieval_grant()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.revoked_at IS NOT NULL THEN
                    RAISE EXCEPTION 'retrieval grants must begin active';
                END IF;
                RETURN NEW;
            END IF;
            IF (to_jsonb(NEW) - ARRAY['revoked_at', 'updated_at'])
               IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['revoked_at', 'updated_at']) THEN
                RAISE EXCEPTION 'retrieval grant identity and credential are immutable';
            END IF;
            IF NEW.revoked_at IS DISTINCT FROM OLD.revoked_at
               AND NOT (OLD.revoked_at IS NULL AND NEW.revoked_at IS NOT NULL) THEN
                RAISE EXCEPTION 'retrieval grant revocation is irreversible';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER protect_package_retrieval_grant
        BEFORE INSERT OR UPDATE ON package_retrieval_grants
        FOR EACH ROW EXECUTE FUNCTION ai_fde_protect_package_retrieval_grant()
        """
    )


def _enable_row_security() -> None:
    mutable_tables = (
        "customer_factory_model_versions",
        "fdlc_readiness_assessments",
        "factory_opportunities",
        "factory_deployment_package_versions",
        "package_retrieval_grants",
    )
    for table_name in mutable_tables:
        op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table_name}_operator_access ON {table_name}
            FOR ALL TO ai_fde_app
            USING (ai_fde_can_access_engagement(engagement_id))
            WITH CHECK (ai_fde_can_access_engagement(engagement_id))
            """
        )
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table_name} TO ai_fde_app")
        op.execute(f"REVOKE DELETE ON {table_name} FROM ai_fde_app")

    op.execute("ALTER TABLE package_retrieval_events ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY package_retrieval_events_operator_read ON package_retrieval_events
        FOR SELECT TO ai_fde_app
        USING (ai_fde_can_access_engagement(engagement_id))
        """
    )
    op.execute(
        """
        CREATE POLICY package_retrieval_events_operator_insert ON package_retrieval_events
        FOR INSERT TO ai_fde_app
        WITH CHECK (ai_fde_can_access_engagement(engagement_id))
        """
    )
    op.execute("GRANT SELECT, INSERT ON package_retrieval_events TO ai_fde_app")
    op.execute("REVOKE UPDATE, DELETE ON package_retrieval_events FROM ai_fde_app")
    op.execute("REVOKE UPDATE, DELETE ON audit_events FROM ai_fde_app")


def downgrade() -> None:
    op.execute("GRANT UPDATE, DELETE ON audit_events TO ai_fde_app")
    op.execute("DROP TRIGGER IF EXISTS protect_package_retrieval_grant ON package_retrieval_grants")
    op.execute("DROP FUNCTION IF EXISTS ai_fde_protect_package_retrieval_grant()")
    op.execute(
        "DROP TRIGGER IF EXISTS protect_deployment_package_version "
        "ON factory_deployment_package_versions"
    )
    op.execute("DROP FUNCTION IF EXISTS ai_fde_protect_deployment_package_version()")
    op.execute("DROP TRIGGER IF EXISTS protect_factory_opportunity ON factory_opportunities")
    op.execute("DROP FUNCTION IF EXISTS ai_fde_protect_factory_opportunity()")
    op.execute(
        "DROP TRIGGER IF EXISTS protect_fdlc_readiness_assessment ON fdlc_readiness_assessments"
    )
    op.execute("DROP FUNCTION IF EXISTS ai_fde_protect_fdlc_readiness_assessment()")
    op.execute(
        "DROP TRIGGER IF EXISTS protect_customer_factory_model_version "
        "ON customer_factory_model_versions"
    )
    op.execute("DROP FUNCTION IF EXISTS ai_fde_protect_customer_factory_model_version()")
    op.drop_index(
        "ix_package_retrieval_events_engagement_created",
        table_name="package_retrieval_events",
    )
    op.drop_index(
        "ix_package_retrieval_events_package_created", table_name="package_retrieval_events"
    )
    op.drop_table("package_retrieval_events")
    op.drop_index("ix_package_retrieval_grants_operator", table_name="package_retrieval_grants")
    op.drop_table("package_retrieval_grants")
    op.drop_index(
        "ix_deployment_packages_engagement_status",
        table_name="factory_deployment_package_versions",
    )
    op.drop_table("factory_deployment_package_versions")
    op.drop_constraint(
        "fdlc_readiness_selected_opportunity_tenant",
        "fdlc_readiness_assessments",
        type_="foreignkey",
    )
    op.drop_index("ix_fdlc_readiness_engagement_status", table_name="fdlc_readiness_assessments")
    op.drop_table("fdlc_readiness_assessments")
    op.drop_index("ix_factory_opportunities_engagement_status", table_name="factory_opportunities")
    op.drop_table("factory_opportunities")
    op.drop_index(
        "ix_customer_factory_models_engagement_status",
        table_name="customer_factory_model_versions",
    )
    op.drop_table("customer_factory_model_versions")
