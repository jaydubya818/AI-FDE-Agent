"""engagement data lifecycle

Revision ID: 7436202e211e
Revises: a1937bb5c0e4
Create Date: 2026-08-09 21:54:51.689634
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7436202e211e"
down_revision: str | None = "a1937bb5c0e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "engagement_deletion_receipts",
        sa.Column("engagement_id", sa.UUID(), nullable=False),
        sa.Column("requested_by_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("data_classification", sa.String(length=32), nullable=False),
        sa.Column("export_id", sa.UUID(), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("archive_hash", sa.String(length=64), nullable=False),
        sa.Column("database_row_count", sa.Integer(), nullable=False),
        sa.Column("evidence_object_count", sa.Integer(), nullable=False),
        sa.Column("failure_code", sa.String(length=120), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "data_classification IN ('synthetic', 'sanitized')",
            name=op.f("ck_engagement_deletion_receipts_valid_data_classification"),
        ),
        sa.CheckConstraint(
            "status IN ('processing', 'completed', 'failed')",
            name=op.f("ck_engagement_deletion_receipts_valid_status"),
        ),
        sa.CheckConstraint(
            "database_row_count >= 0",
            name=op.f("ck_engagement_deletion_receipts_nonnegative_database_row_count"),
        ),
        sa.CheckConstraint(
            "evidence_object_count >= 0",
            name=op.f("ck_engagement_deletion_receipts_nonnegative_evidence_object_count"),
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_id"],
            ["operators.id"],
            name=op.f("fk_engagement_deletion_receipts_requested_by_id_operators"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_engagement_deletion_receipts")),
        sa.UniqueConstraint("engagement_id", name="one_deletion_receipt_per_engagement"),
    )
    op.create_index(
        "ix_deletion_receipts_operator_created",
        "engagement_deletion_receipts",
        ["requested_by_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "engagement_exports",
        sa.Column("engagement_id", sa.UUID(), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("archive_hash", sa.String(length=64), nullable=False),
        sa.Column("byte_count", sa.BigInteger(), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("evidence_object_count", sa.Integer(), nullable=False),
        sa.Column("requested_by_id", sa.UUID(), nullable=False),
        sa.Column("exported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "byte_count >= 0", name=op.f("ck_engagement_exports_nonnegative_byte_count")
        ),
        sa.CheckConstraint(
            "evidence_object_count >= 0",
            name=op.f("ck_engagement_exports_nonnegative_evidence_object_count"),
        ),
        sa.CheckConstraint(
            "record_count >= 0", name=op.f("ck_engagement_exports_nonnegative_record_count")
        ),
        sa.ForeignKeyConstraint(
            ["engagement_id"],
            ["engagements.id"],
            name=op.f("fk_engagement_exports_engagement_id_engagements"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_id"],
            ["operators.id"],
            name=op.f("fk_engagement_exports_requested_by_id_operators"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_engagement_exports")),
    )
    op.create_index(
        "ix_engagement_exports_engagement_created",
        "engagement_exports",
        ["engagement_id", "created_at"],
        unique=False,
    )
    op.add_column(
        "engagements",
        sa.Column(
            "data_lifecycle_status",
            sa.String(length=32),
            server_default="active",
            nullable=False,
        ),
    )
    op.alter_column("engagements", "data_lifecycle_status", server_default=None)
    op.add_column(
        "engagements",
        sa.Column("retention_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "valid_data_lifecycle_status",
        "engagements",
        "data_lifecycle_status IN ('active', 'deletion_processing', 'deletion_failed')",
    )
    op.create_check_constraint(
        "valid_retention_expiry",
        "engagements",
        "retention_expires_at IS NULL OR retention_expires_at > created_at",
    )

    op.execute("ALTER TABLE engagement_exports ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY engagement_exports_operator_access ON engagement_exports
        FOR ALL TO ai_fde_app
        USING (ai_fde_can_access_engagement(engagement_id))
        WITH CHECK (ai_fde_can_access_engagement(engagement_id))
        """
    )
    op.execute("ALTER TABLE engagement_deletion_receipts ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY engagement_deletion_receipts_operator_access
        ON engagement_deletion_receipts
        FOR ALL TO ai_fde_app
        USING (requested_by_id = ai_fde_current_operator_id())
        WITH CHECK (requested_by_id = ai_fde_current_operator_id())
        """
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON "
        "engagement_exports, engagement_deletion_receipts TO ai_fde_app"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_engagements_valid_retention_expiry"), "engagements", type_="check")
    op.drop_constraint(
        op.f("ck_engagements_valid_data_lifecycle_status"), "engagements", type_="check"
    )
    op.drop_column("engagements", "retention_expires_at")
    op.drop_column("engagements", "data_lifecycle_status")
    op.drop_index("ix_engagement_exports_engagement_created", table_name="engagement_exports")
    op.drop_table("engagement_exports")
    op.drop_index(
        "ix_deletion_receipts_operator_created", table_name="engagement_deletion_receipts"
    )
    op.drop_table("engagement_deletion_receipts")
