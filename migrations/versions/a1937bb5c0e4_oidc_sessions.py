"""OIDC login attempts and opaque operator sessions

Revision ID: a1937bb5c0e4
Revises: 5c01e3b1557b
Create Date: 2026-08-08 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1937bb5c0e4"
down_revision: str | None = "5c01e3b1557b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "operators",
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.create_table(
        "oidc_login_attempts",
        sa.Column("state_digest", sa.String(length=64), nullable=False),
        sa.Column("nonce", sa.String(length=128), nullable=False),
        sa.Column("code_verifier", sa.String(length=128), nullable=False),
        sa.Column("redirect_uri", sa.String(length=1024), nullable=False),
        sa.Column("return_to", sa.String(length=1024), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "expires_at > created_at",
            name=op.f("ck_oidc_login_attempts_valid_oidc_attempt_expiry"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oidc_login_attempts")),
        sa.UniqueConstraint("state_digest", name=op.f("uq_oidc_login_attempts_state_digest")),
    )
    op.create_index(
        "ix_oidc_login_attempts_expires_at",
        "oidc_login_attempts",
        ["expires_at"],
        unique=False,
    )
    op.create_table(
        "operator_sessions",
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("operator_id", sa.UUID(), nullable=False),
        sa.Column("authenticated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "expires_at > authenticated_at",
            name=op.f("ck_operator_sessions_valid_operator_session_expiry"),
        ),
        sa.ForeignKeyConstraint(
            ["operator_id"],
            ["operators.id"],
            name=op.f("fk_operator_sessions_operator_id_operators"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_operator_sessions")),
        sa.UniqueConstraint("token_digest", name=op.f("uq_operator_sessions_token_digest")),
    )
    op.create_index(
        "ix_operator_sessions_operator_expires",
        "operator_sessions",
        ["operator_id", "expires_at"],
        unique=False,
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON "
        "oidc_login_attempts, operator_sessions TO ai_fde_app"
    )


def downgrade() -> None:
    op.drop_index("ix_operator_sessions_operator_expires", table_name="operator_sessions")
    op.drop_table("operator_sessions")
    op.drop_index("ix_oidc_login_attempts_expires_at", table_name="oidc_login_attempts")
    op.drop_table("oidc_login_attempts")
    op.drop_column("operators", "is_active")
