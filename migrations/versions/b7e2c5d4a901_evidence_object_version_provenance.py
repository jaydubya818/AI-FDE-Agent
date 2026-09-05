"""pin evidence object version provenance

Revision ID: b7e2c5d4a901
Revises: f4d9c2a7b310
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7e2c5d4a901"
down_revision: str | None = "f4d9c2a7b310"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable only for pre-versioning synthetic evidence. Qualified customer-data
    # processing rejects a missing version before object access.
    op.add_column(
        "evidence_assets",
        sa.Column("storage_version_id", sa.String(length=1024), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_evidence_assets_valid_storage_version_id"),
        "evidence_assets",
        "storage_version_id IS NULL "
        "OR (storage_version_id <> '' AND storage_version_id <> 'null')",
        postgresql_not_valid=True,
    )
    op.execute(
        "ALTER TABLE evidence_assets "
        "VALIDATE CONSTRAINT ck_evidence_assets_valid_storage_version_id"
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_evidence_assets_valid_storage_version_id"),
        "evidence_assets",
        type_="check",
    )
    op.drop_column("evidence_assets", "storage_version_id")
