"""design partner readiness

Revision ID: d4f6a8b9c012
Revises: 7436202e211e
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d4f6a8b9c012"
down_revision: str | None = "7436202e211e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "operators",
        sa.Column("identity_kind", sa.String(length=24), nullable=False, server_default="human"),
    )
    op.create_check_constraint(
        "valid_identity_kind",
        "operators",
        "identity_kind IN ('human', 'service')",
    )

    op.add_column(
        "engagements",
        sa.Column(
            "workflow_name",
            sa.String(length=255),
            nullable=False,
            server_default="Primary Workflow",
        ),
    )
    op.execute("UPDATE engagements SET workflow_name = 'Accounts Payable'")

    op.add_column(
        "extraction_runs",
        sa.Column(
            "provider_name",
            sa.String(length=120),
            nullable=False,
            server_default="deterministic-acme-patterns",
        ),
    )
    op.add_column("extraction_runs", sa.Column("model_id", sa.String(length=512)))
    op.add_column(
        "extraction_runs",
        sa.Column(
            "prompt_version",
            sa.String(length=64),
            nullable=False,
            server_default="fixture-rules-v1",
        ),
    )
    op.add_column(
        "extraction_runs",
        sa.Column("input_hash", sa.String(length=64), nullable=False, server_default=""),
    )
    op.execute(
        """
        UPDATE extraction_runs AS runs
        SET input_hash = assets.content_hash
        FROM evidence_assets AS assets
        WHERE assets.id = runs.evidence_asset_id
        """
    )
    op.add_column(
        "extraction_runs",
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "extraction_runs",
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "extraction_runs",
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "extraction_runs",
        sa.Column("result_code", sa.String(length=120), nullable=False, server_default="complete"),
    )
    op.create_check_constraint(
        "nonnegative_provider_metrics",
        "extraction_runs",
        "input_tokens >= 0 AND output_tokens >= 0 AND latency_ms >= 0",
    )

    op.add_column(
        "economic_cases",
        sa.Column(
            "scenarios",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.drop_constraint(
        op.f("ck_implementation_artifacts_valid_artifact_type"),
        "implementation_artifacts",
        type_="check",
    )
    op.create_check_constraint(
        "valid_artifact_type",
        "implementation_artifacts",
        "artifact_type IN ('prd', 'architecture', 'business_rules', "
        "'integration_requirements', 'approval_controls', 'evaluation_plan', "
        "'implementation_spec')",
    )
    op.add_column(
        "implementation_artifacts",
        sa.Column("packet_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_check_constraint(
        "positive_packet_version",
        "implementation_artifacts",
        "packet_version > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_implementation_artifacts_positive_packet_version"),
        "implementation_artifacts",
        type_="check",
    )
    op.drop_column("implementation_artifacts", "packet_version")
    op.drop_constraint(
        op.f("ck_implementation_artifacts_valid_artifact_type"),
        "implementation_artifacts",
        type_="check",
    )
    # These packet members are generated, reproducible outputs that the previous schema cannot
    # represent. Preserve the legacy implementation specification and all canonical upstream data.
    op.execute("DELETE FROM implementation_artifacts WHERE artifact_type <> 'implementation_spec'")
    op.create_check_constraint(
        "valid_artifact_type",
        "implementation_artifacts",
        "artifact_type IN ('implementation_spec')",
    )
    op.drop_column("economic_cases", "scenarios")
    op.drop_constraint(
        op.f("ck_extraction_runs_nonnegative_provider_metrics"),
        "extraction_runs",
        type_="check",
    )
    for column in (
        "result_code",
        "latency_ms",
        "output_tokens",
        "input_tokens",
        "input_hash",
        "prompt_version",
        "model_id",
        "provider_name",
    ):
        op.drop_column("extraction_runs", column)
    op.drop_column("engagements", "workflow_name")
    op.drop_constraint(op.f("ck_operators_valid_identity_kind"), "operators", type_="check")
    op.drop_column("operators", "identity_kind")
