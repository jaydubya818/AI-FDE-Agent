"""controlled design-partner qualification

Revision ID: c91f4e2a7b30
Revises: 9b0d4e7c2f11
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c91f4e2a7b30"
down_revision: str | None = "9b0d4e7c2f11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "design_partner_qualifications",
        sa.Column("engagement_id", sa.UUID(), nullable=False),
        sa.Column("partner_key", sa.String(length=120), nullable=False),
        sa.Column("organization", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("qualification_state", sa.String(length=24), nullable=False),
        sa.Column("authorized_data_source_keys", postgresql.JSONB(), nullable=False),
        sa.Column("authorized_repository_refs", postgresql.JSONB(), nullable=False),
        sa.Column("allowed_workflow_classes", postgresql.JSONB(), nullable=False),
        sa.Column("data_classification", sa.String(length=24), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.Column("authorization_basis_ref", sa.String(length=512), nullable=False),
        sa.Column("configured_by_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'SUSPENDED', 'REVOKED')",
            name=op.f("ck_design_partner_qualifications_valid_status"),
        ),
        sa.CheckConstraint(
            "qualification_state IN ('CONFIGURED', 'IN_PROGRESS', 'BLOCKED', 'QUALIFIED')",
            name=op.f("ck_design_partner_qualifications_valid_qualification_state"),
        ),
        sa.CheckConstraint(
            "data_classification IN ('PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED')",
            name=op.f("ck_design_partner_qualifications_valid_data_classification"),
        ),
        sa.CheckConstraint(
            "retention_days BETWEEN 1 AND 3650",
            name=op.f("ck_design_partner_qualifications_valid_retention_days"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(authorized_data_source_keys) = 'array' "
            "AND jsonb_array_length(authorized_data_source_keys) BETWEEN 1 AND 100",
            name=op.f("ck_design_partner_qualifications_valid_authorized_data_source_keys"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(authorized_repository_refs) = 'array' "
            "AND jsonb_array_length(authorized_repository_refs) BETWEEN 1 AND 100",
            name=op.f("ck_design_partner_qualifications_valid_authorized_repository_refs"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(allowed_workflow_classes) = 'array' "
            "AND jsonb_array_length(allowed_workflow_classes) BETWEEN 1 AND 100",
            name=op.f("ck_design_partner_qualifications_valid_allowed_workflow_classes"),
        ),
        sa.ForeignKeyConstraint(
            ["engagement_id"],
            ["engagements.id"],
            name=op.f(
                "fk_design_partner_qualifications_engagement_id_engagements"
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["configured_by_id"],
            ["operators.id"],
            name=op.f(
                "fk_design_partner_qualifications_configured_by_id_operators"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_design_partner_qualifications")),
        sa.UniqueConstraint(
            "engagement_id", name="design_partner_qualification_engagement"
        ),
        sa.UniqueConstraint("partner_key", name="design_partner_qualification_partner_key"),
        sa.UniqueConstraint(
            "engagement_id",
            "id",
            name="design_partner_qualification_tenant_id",
        ),
        sa.UniqueConstraint(
            "engagement_id",
            "id",
            "partner_key",
            name="design_partner_qualification_tenant_identity",
        ),
    )
    op.create_index(
        "ix_design_partner_qualification_status",
        "design_partner_qualifications",
        ["status", "qualification_state"],
    )

    op.add_column(
        "evidence_assets",
        sa.Column("design_partner_qualification_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "evidence_assets",
        sa.Column("authorized_source_key", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "evidence_assets",
        sa.Column("authorized_workflow_class", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "evidence_assets",
        sa.Column("data_classification", sa.String(length=24), nullable=True),
    )
    op.create_unique_constraint(
        "evidence_asset_tenant_identity",
        "evidence_assets",
        ["engagement_id", "id"],
    )
    op.create_foreign_key(
        "evidence_asset_design_partner_qualification_tenant",
        "evidence_assets",
        "design_partner_qualifications",
        ["engagement_id", "design_partner_qualification_id"],
        ["engagement_id", "id"],
    )
    op.create_check_constraint(
        op.f("ck_evidence_assets_valid_design_partner_context"),
        "evidence_assets",
        "(design_partner_qualification_id IS NULL "
        "AND authorized_source_key IS NULL "
        "AND authorized_workflow_class IS NULL "
        "AND data_classification IS NULL) "
        "OR (design_partner_qualification_id IS NOT NULL "
        "AND authorized_source_key IS NOT NULL "
        "AND authorized_workflow_class IS NOT NULL "
        "AND data_classification IN "
        "('PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED'))",
    )

    op.create_table(
        "customer_data_access_events",
        sa.Column("engagement_id", sa.UUID(), nullable=False),
        sa.Column("qualification_id", sa.UUID(), nullable=False),
        sa.Column("partner_key", sa.String(length=120), nullable=False),
        sa.Column("operator_id", sa.UUID(), nullable=False),
        sa.Column("evidence_asset_id", sa.UUID(), nullable=True),
        sa.Column("source_key", sa.String(length=120), nullable=False),
        sa.Column("workflow_class", sa.String(length=160), nullable=False),
        sa.Column("data_classification", sa.String(length=24), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=24), nullable=False),
        sa.Column("decision_code", sa.String(length=80), nullable=False),
        sa.Column("authorization_basis_ref", sa.String(length=512), nullable=False),
        sa.Column("correlation_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "data_classification IN ('PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED')",
            name=op.f("ck_customer_data_access_events_valid_data_classification"),
        ),
        sa.CheckConstraint(
            "operation IN ('MANUAL_DOCUMENT_UPLOAD')",
            name=op.f("ck_customer_data_access_events_valid_operation"),
        ),
        sa.CheckConstraint(
            "outcome IN ('AUTHORIZED', 'DENIED')",
            name=op.f("ck_customer_data_access_events_valid_outcome"),
        ),
        sa.CheckConstraint(
            "(outcome = 'AUTHORIZED' AND evidence_asset_id IS NOT NULL) "
            "OR (outcome = 'DENIED' AND evidence_asset_id IS NULL)",
            name=op.f("ck_customer_data_access_events_valid_evidence_binding"),
        ),
        sa.ForeignKeyConstraint(
            ["engagement_id"],
            ["engagements.id"],
            name=op.f("fk_customer_data_access_events_engagement_id_engagements"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["operator_id"],
            ["operators.id"],
            name=op.f("fk_customer_data_access_events_operator_id_operators"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["engagement_id", "evidence_asset_id"],
            ["evidence_assets.engagement_id", "evidence_assets.id"],
            name="customer_data_access_evidence_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["engagement_id", "qualification_id", "partner_key"],
            [
                "design_partner_qualifications.engagement_id",
                "design_partner_qualifications.id",
                "design_partner_qualifications.partner_key",
            ],
            name="customer_data_access_qualification_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customer_data_access_events")),
    )
    op.create_index(
        "ix_customer_data_access_engagement_created",
        "customer_data_access_events",
        ["engagement_id", "created_at"],
    )
    op.create_index(
        "ix_customer_data_access_correlation",
        "customer_data_access_events",
        ["correlation_id"],
    )

    op.execute("ALTER TABLE design_partner_qualifications ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY design_partner_qualifications_operator_read
        ON design_partner_qualifications
        FOR SELECT TO ai_fde_app
        USING (ai_fde_can_access_engagement(engagement_id))
        """
    )
    op.execute("GRANT SELECT ON design_partner_qualifications TO ai_fde_app")
    op.execute(
        "REVOKE INSERT, UPDATE, DELETE ON design_partner_qualifications FROM ai_fde_app"
    )

    op.execute("ALTER TABLE customer_data_access_events ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY customer_data_access_events_operator_read
        ON customer_data_access_events
        FOR SELECT TO ai_fde_app
        USING (ai_fde_can_access_engagement(engagement_id))
        """
    )
    op.execute(
        """
        CREATE POLICY customer_data_access_events_operator_insert
        ON customer_data_access_events
        FOR INSERT TO ai_fde_app
        WITH CHECK (
            ai_fde_can_access_engagement(engagement_id)
            AND operator_id = ai_fde_current_operator_id()
        )
        """
    )
    op.execute("GRANT SELECT, INSERT ON customer_data_access_events TO ai_fde_app")
    op.execute("REVOKE UPDATE, DELETE ON customer_data_access_events FROM ai_fde_app")
    op.execute(
        """
        CREATE FUNCTION ai_fde_protect_customer_data_access_event()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        SET row_security = off
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND NOT EXISTS (
                SELECT 1 FROM engagements WHERE id = OLD.engagement_id
            ) THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'customer data access events are append-only';
        END;
        $$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION ai_fde_protect_customer_data_access_event() FROM PUBLIC"
    )
    op.execute(
        """
        CREATE TRIGGER protect_customer_data_access_event
        BEFORE UPDATE OR DELETE ON customer_data_access_events
        FOR EACH ROW EXECUTE FUNCTION ai_fde_protect_customer_data_access_event()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS protect_customer_data_access_event "
        "ON customer_data_access_events"
    )
    op.execute("DROP FUNCTION IF EXISTS ai_fde_protect_customer_data_access_event()")
    op.drop_index(
        "ix_customer_data_access_correlation",
        table_name="customer_data_access_events",
    )
    op.drop_index(
        "ix_customer_data_access_engagement_created",
        table_name="customer_data_access_events",
    )
    op.drop_table("customer_data_access_events")
    op.drop_constraint(
        op.f("ck_evidence_assets_valid_design_partner_context"),
        "evidence_assets",
        type_="check",
    )
    op.drop_constraint(
        "evidence_asset_design_partner_qualification_tenant",
        "evidence_assets",
        type_="foreignkey",
    )
    op.drop_constraint(
        "evidence_asset_tenant_identity",
        "evidence_assets",
        type_="unique",
    )
    op.drop_column("evidence_assets", "data_classification")
    op.drop_column("evidence_assets", "authorized_workflow_class")
    op.drop_column("evidence_assets", "authorized_source_key")
    op.drop_column("evidence_assets", "design_partner_qualification_id")
    op.drop_index(
        "ix_design_partner_qualification_status",
        table_name="design_partner_qualifications",
    )
    op.drop_table("design_partner_qualifications")
