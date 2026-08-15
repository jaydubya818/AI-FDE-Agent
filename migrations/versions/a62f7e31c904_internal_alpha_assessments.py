"""internal alpha assessments

Revision ID: a62f7e31c904
Revises: d4f6a8b9c012
Create Date: 2026-08-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a62f7e31c904"
down_revision: str | None = "d4f6a8b9c012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "engagement_assessments",
        sa.Column("engagement_id", sa.UUID(), nullable=False),
        sa.Column("evaluator_id", sa.UUID(), nullable=False),
        sa.Column("delivery_method", sa.String(length=24), nullable=False),
        sa.Column("perspective", sa.String(length=24), nullable=False),
        sa.Column("outcome", sa.String(length=24), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("usefulness_score", sa.Integer(), nullable=False),
        sa.Column("clarification_count", sa.Integer(), nullable=False),
        sa.Column("rework_count", sa.Integer(), nullable=False),
        sa.Column("workaround_count", sa.Integer(), nullable=False),
        sa.Column("trust_failure_count", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "delivery_method IN ('ai_fde', 'conventional')",
            name=op.f("ck_engagement_assessments_valid_delivery_method"),
        ),
        sa.CheckConstraint(
            "perspective IN ('operator', 'engineering')",
            name=op.f("ck_engagement_assessments_valid_perspective"),
        ),
        sa.CheckConstraint(
            "outcome IN ('completed', 'blocked', 'abandoned')",
            name=op.f("ck_engagement_assessments_valid_outcome"),
        ),
        sa.CheckConstraint(
            "duration_minutes BETWEEN 1 AND 10080",
            name=op.f("ck_engagement_assessments_valid_duration_minutes"),
        ),
        sa.CheckConstraint(
            "usefulness_score BETWEEN 1 AND 5",
            name=op.f("ck_engagement_assessments_valid_usefulness_score"),
        ),
        sa.CheckConstraint(
            "clarification_count BETWEEN 0 AND 10000 AND "
            "rework_count BETWEEN 0 AND 10000 AND "
            "workaround_count BETWEEN 0 AND 10000 AND "
            "trust_failure_count BETWEEN 0 AND 10000",
            name=op.f("ck_engagement_assessments_valid_assessment_counts"),
        ),
        sa.ForeignKeyConstraint(
            ["engagement_id"],
            ["engagements.id"],
            name=op.f("fk_engagement_assessments_engagement_id_engagements"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["evaluator_id"],
            ["operators.id"],
            name=op.f("fk_engagement_assessments_evaluator_id_operators"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_engagement_assessments")),
        sa.UniqueConstraint(
            "engagement_id",
            "evaluator_id",
            "delivery_method",
            "perspective",
            name="assessment_identity",
        ),
    )
    op.create_index(
        "ix_engagement_assessments_engagement_updated",
        "engagement_assessments",
        ["engagement_id", "updated_at"],
        unique=False,
    )
    op.execute("ALTER TABLE engagement_assessments ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY engagement_assessments_operator_access ON engagement_assessments
        FOR ALL TO ai_fde_app
        USING (ai_fde_can_access_engagement(engagement_id))
        WITH CHECK (ai_fde_can_access_engagement(engagement_id))
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON engagement_assessments TO ai_fde_app")


def downgrade() -> None:
    op.drop_index(
        "ix_engagement_assessments_engagement_updated",
        table_name="engagement_assessments",
    )
    op.drop_table("engagement_assessments")
