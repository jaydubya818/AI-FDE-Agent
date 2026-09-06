"""runtime readiness and least-privilege worker role

Revision ID: e8c4d2a791f0
Revises: c91f4e2a7b30
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "e8c4d2a791f0"
down_revision: str | None = "c91f4e2a7b30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "runtime_heartbeats",
        sa.Column("service", sa.String(length=40), nullable=False),
        sa.Column("instance_id", sa.String(length=80), nullable=False),
        sa.Column("release_revision", sa.String(length=40), nullable=False),
        sa.Column("deployment_id", sa.String(length=120), nullable=False),
        sa.Column("deployment_validation_id", sa.String(length=71)),
        sa.Column("qualification_mode", sa.String(length=40), nullable=False),
        sa.Column("operator_id", sa.UUID()),
        sa.Column("engagement_id", sa.UUID()),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("queue_depth", sa.Integer(), nullable=False),
        sa.Column("oldest_queued_at", sa.DateTime(timezone=True)),
        sa.Column("last_job_completed_at", sa.DateTime(timezone=True)),
        sa.Column("last_failure_code", sa.String(length=120)),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "queue_depth >= 0",
            name=op.f("ck_runtime_heartbeats_nonnegative_queue_depth"),
        ),
        sa.CheckConstraint(
            "status IN ('RUNNING', 'STOPPED')",
            name=op.f("ck_runtime_heartbeats_valid_status"),
        ),
        sa.CheckConstraint(
            "(operator_id IS NULL AND engagement_id IS NULL) OR "
            "(operator_id IS NOT NULL AND engagement_id IS NOT NULL)",
            name=op.f("ck_runtime_heartbeats_paired_worker_identity"),
        ),
        sa.CheckConstraint(
            "deployment_validation_id IS NULL OR "
            "deployment_validation_id ~ '^sha256:[0-9a-f]{64}$'",
            name=op.f("ck_runtime_heartbeats_valid_deployment_validation_digest"),
        ),
        sa.ForeignKeyConstraint(
            ["operator_id"],
            ["operators.id"],
            name=op.f("fk_runtime_heartbeats_operator_id_operators"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["engagement_id"],
            ["engagements.id"],
            name=op.f("fk_runtime_heartbeats_engagement_id_engagements"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runtime_heartbeats")),
        sa.UniqueConstraint("service", "instance_id", name="runtime_heartbeat_identity"),
    )
    op.create_index(
        "ix_runtime_heartbeats_deployment_seen",
        "runtime_heartbeats",
        [
            "service",
            "operator_id",
            "engagement_id",
            "release_revision",
            "deployment_id",
            "deployment_validation_id",
            "last_seen_at",
        ],
    )
    op.create_table(
        "worker_operator_bindings",
        sa.Column("database_role", sa.String(length=63), nullable=False),
        sa.Column("operator_id", sa.UUID(), nullable=False),
        sa.Column("engagement_id", sa.UUID(), nullable=True),
        sa.Column("release_revision", sa.String(length=40), nullable=False),
        sa.Column("deployment_id", sa.String(length=120), nullable=False),
        sa.Column("deployment_validation_id", sa.String(length=71)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "database_role ~ '^ai_fde_worker_[0-9a-f]{12}$'",
            name=op.f("ck_worker_operator_bindings_valid_worker_database_role"),
        ),
        sa.CheckConstraint(
            "release_revision ~ '^[0-9a-f]{40}$' AND "
            "release_revision <> '0000000000000000000000000000000000000000'",
            name=op.f("ck_worker_operator_bindings_valid_release_revision"),
        ),
        sa.CheckConstraint(
            "deployment_id ~ '^[a-z0-9][a-z0-9._-]{7,119}$'",
            name=op.f("ck_worker_operator_bindings_valid_deployment_id"),
        ),
        sa.CheckConstraint(
            "deployment_validation_id IS NULL OR "
            "deployment_validation_id ~ '^sha256:[0-9a-f]{64}$'",
            name=op.f("ck_worker_operator_bindings_valid_deployment_validation_digest"),
        ),
        sa.ForeignKeyConstraint(
            ["operator_id"],
            ["operators.id"],
            name=op.f("fk_worker_operator_bindings_operator_id_operators"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["engagement_id"],
            ["engagements.id"],
            name=op.f("fk_worker_operator_bindings_engagement_id_engagements"),
            ondelete="SET NULL",
            use_alter=True,
        ),
        sa.PrimaryKeyConstraint(
            "database_role",
            name=op.f("pk_worker_operator_bindings"),
        ),
        sa.UniqueConstraint(
            "operator_id",
            name=op.f("uq_worker_operator_bindings_operator_id"),
        ),
        sa.UniqueConstraint(
            "engagement_id",
            name=op.f("uq_worker_operator_bindings_engagement_id"),
        ),
    )
    op.create_foreign_key(
        op.f("fk_worker_operator_bindings_engagement_id_engagements"),
        "worker_operator_bindings",
        "engagements",
        ["engagement_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute("ALTER TABLE worker_operator_bindings ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON worker_operator_bindings FROM PUBLIC, ai_fde_app")
    _install_worker_identity_functions()

    op.execute("ALTER TABLE runtime_heartbeats ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON runtime_heartbeats FROM PUBLIC")
    _install_heartbeat_clock_trigger()

    op.execute("ALTER TABLE operators ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY operators_app_access ON operators
        FOR ALL TO ai_fde_app
        USING (true)
        WITH CHECK (true)
        """
    )

    op.execute("GRANT SELECT ON alembic_version TO ai_fde_app")
    op.execute("GRANT SELECT ON runtime_heartbeats TO ai_fde_app")
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "ai_fde_active_worker_binding(text, uuid, uuid, text, text, text) TO ai_fde_app"
    )
    op.execute("REVOKE INSERT, UPDATE, DELETE ON runtime_heartbeats FROM ai_fde_app")
    op.execute(
        "CREATE POLICY runtime_heartbeats_app_select ON runtime_heartbeats "
        "FOR SELECT TO ai_fde_app USING (true)"
    )

    # Production bootstrap and the development image create the cluster role before Alembic.
    # Older developer/CI databases may not have it yet; skipping grants is fail-closed and keeps
    # the schema migration usable while `ai-fde-admin bootstrap-production-database` remains the
    # mandatory production entry point. Offline generation cannot query pg_roles, so emit the
    # same static DDL behind a server-side existence check instead of touching a MockConnection.
    _install_worker_role_access()


def downgrade() -> None:
    for command in ("select", "insert", "update"):
        op.execute(
            f"DROP POLICY IF EXISTS runtime_heartbeats_worker_{command} ON runtime_heartbeats"
        )
    op.execute("DROP POLICY IF EXISTS runtime_heartbeats_app_select ON runtime_heartbeats")
    op.execute("DROP POLICY IF EXISTS operators_worker_select ON operators")
    for table_name in (
        "engagements",
        "engagement_members",
        "design_partner_qualifications",
        "evidence_assets",
        "jobs",
        "evidence_segments",
        "candidate_claims",
        "claim_evidence",
        "contradictions",
        "extraction_runs",
        "audit_events",
        "outbox_events",
    ):
        for command in ("select", "insert", "update"):
            op.execute(f"DROP POLICY IF EXISTS {table_name}_worker_{command} ON {table_name}")
    op.execute("DROP POLICY IF EXISTS operators_app_access ON operators")
    op.execute("ALTER TABLE operators DISABLE ROW LEVEL SECURITY")
    op.execute("DROP FUNCTION IF EXISTS ai_fde_worker_can_access_engagement(uuid)")
    op.execute(
        "DROP FUNCTION IF EXISTS ai_fde_worker_runtime_authorized(uuid, uuid, text, text, text)"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS ai_fde_active_worker_binding(text, uuid, uuid, text, text, text)"
    )
    op.execute("DROP FUNCTION IF EXISTS ai_fde_bound_worker_operator_id()")
    op.execute("DROP TRIGGER IF EXISTS runtime_heartbeats_set_seen_at ON runtime_heartbeats")
    op.execute("DROP FUNCTION IF EXISTS ai_fde_set_runtime_heartbeat_seen_at()")
    op.execute("DROP TABLE IF EXISTS worker_operator_bindings")
    op.drop_index("ix_runtime_heartbeats_deployment_seen", table_name="runtime_heartbeats")
    op.drop_table("runtime_heartbeats")


def _worker_role_access_statements() -> list[str]:
    heartbeat_predicate = (
        "service = 'ai-fde-worker' "
        "AND operator_id IS NOT NULL "
        "AND engagement_id IS NOT NULL "
        "AND operator_id = ai_fde_bound_worker_operator_id() "
        "AND ai_fde_worker_runtime_authorized("
        "operator_id, engagement_id, release_revision, deployment_id, "
        "deployment_validation_id)"
    )
    statements = [
        "REVOKE ALL ON worker_operator_bindings FROM ai_fde_worker",
        "GRANT USAGE ON SCHEMA public TO ai_fde_worker",
        "GRANT EXECUTE ON FUNCTION ai_fde_current_operator_id() TO ai_fde_worker",
        "GRANT EXECUTE ON FUNCTION ai_fde_bound_worker_operator_id() TO ai_fde_worker",
        "GRANT EXECUTE ON FUNCTION ai_fde_worker_can_access_engagement(uuid) "
        "TO ai_fde_worker",
        "GRANT EXECUTE ON FUNCTION "
        "ai_fde_worker_runtime_authorized(uuid, uuid, text, text, text) "
        "TO ai_fde_worker",
        "GRANT SELECT ON alembic_version TO ai_fde_worker",
        "GRANT SELECT ON operators TO ai_fde_worker",
        "GRANT SELECT ON engagements, engagement_members TO ai_fde_worker",
        "GRANT SELECT ON design_partner_qualifications TO ai_fde_worker",
        "GRANT SELECT ON evidence_assets, jobs TO ai_fde_worker",
        "GRANT UPDATE (status, error_message, updated_at) ON evidence_assets TO ai_fde_worker",
        "GRANT UPDATE (status, progress, attempts, available_at, lease_token, "
        "leased_until, error_message, completed_at, updated_at) ON jobs TO ai_fde_worker",
        "GRANT SELECT, INSERT ON evidence_segments, candidate_claims, "
        "claim_evidence, contradictions TO ai_fde_worker",
        "GRANT SELECT, INSERT ON extraction_runs TO ai_fde_worker",
        "GRANT UPDATE (input_tokens, output_tokens, latency_ms, result_code, status, "
        "error_message, completed_at, updated_at) ON extraction_runs TO ai_fde_worker",
        "GRANT INSERT ON audit_events, outbox_events TO ai_fde_worker",
        "GRANT SELECT, INSERT, UPDATE ON runtime_heartbeats TO ai_fde_worker",
        "CREATE POLICY runtime_heartbeats_worker_select ON runtime_heartbeats "
        f"FOR SELECT TO ai_fde_worker USING ({heartbeat_predicate})",
        "CREATE POLICY runtime_heartbeats_worker_insert ON runtime_heartbeats "
        f"FOR INSERT TO ai_fde_worker WITH CHECK ({heartbeat_predicate})",
        "CREATE POLICY runtime_heartbeats_worker_update ON runtime_heartbeats "
        f"FOR UPDATE TO ai_fde_worker USING ({heartbeat_predicate}) "
        f"WITH CHECK ({heartbeat_predicate})",
        "CREATE POLICY operators_worker_select ON operators "
        "FOR SELECT TO ai_fde_worker "
        "USING (id = ai_fde_bound_worker_operator_id() "
        "AND id = ai_fde_current_operator_id())",
    ]
    statements.extend(
        _worker_policy_sql(table_name, "SELECT")
        for table_name in (
            "engagements",
            "engagement_members",
            "design_partner_qualifications",
        )
    )
    for table_name in ("evidence_assets", "jobs"):
        statements.extend(
            (_worker_policy_sql(table_name, "SELECT"), _worker_policy_sql(table_name, "UPDATE"))
        )
    for table_name in (
        "evidence_segments",
        "candidate_claims",
        "claim_evidence",
        "contradictions",
    ):
        statements.extend(
            (_worker_policy_sql(table_name, "SELECT"), _worker_policy_sql(table_name, "INSERT"))
        )
    statements.extend(
        _worker_policy_sql("extraction_runs", command)
        for command in ("SELECT", "INSERT", "UPDATE")
    )
    statements.append(
        _worker_policy_sql(
            "audit_events",
            "INSERT",
            additional_check="actor_id = ai_fde_bound_worker_operator_id()",
        )
    )
    statements.append(_worker_policy_sql("outbox_events", "INSERT"))
    return statements


def _install_worker_role_access() -> None:
    worker_role_statements = _worker_role_access_statements()
    if context.is_offline_mode():
        op.execute(_conditional_worker_role_access_sql(worker_role_statements))
    elif _role_exists("ai_fde_worker"):
        for statement in worker_role_statements:
            op.execute(statement)


def _conditional_worker_role_access_sql(statements: Sequence[str]) -> str:
    dynamic_statements = "\n".join(
        "        EXECUTE $ai_fde_worker_statement$"
        f"{statement}"
        "$ai_fde_worker_statement$;"
        for statement in statements
    )
    return f"""
    DO $ai_fde_worker_role$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ai_fde_worker') THEN
{dynamic_statements}
        END IF;
    END
    $ai_fde_worker_role$
    """


def _worker_policy_sql(
    table_name: str,
    command: str,
    *,
    additional_check: str | None = None,
) -> str:
    command_lower = command.lower()
    engagement_column = "id" if table_name == "engagements" else "engagement_id"
    predicate = f"ai_fde_worker_can_access_engagement({engagement_column})"
    check_predicate = f"{predicate} AND {additional_check}" if additional_check else predicate
    clauses = f"USING ({predicate})" if command in {"SELECT", "UPDATE"} else ""
    if command in {"INSERT", "UPDATE"}:
        clauses = f"{clauses} WITH CHECK ({check_predicate})".strip()
    return (
        f"CREATE POLICY {table_name}_worker_{command_lower} ON {table_name} "
        f"FOR {command} TO ai_fde_worker {clauses}"
    )


def _install_worker_identity_functions() -> None:
    op.execute(
        """
        CREATE FUNCTION ai_fde_active_worker_binding(
            expected_database_role text,
            expected_operator_id uuid,
            expected_engagement_id uuid,
            expected_release_revision text,
            expected_deployment_id text,
            expected_deployment_validation_id text
        )
        RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public, pg_temp
        SET row_security = off
        AS $$
            SELECT COALESCE(
                expected_database_role ~ '^ai_fde_worker_[0-9a-f]{12}$'
                AND EXISTS (
                    SELECT 1
                    FROM worker_operator_bindings AS binding
                    JOIN operators AS worker_operator
                      ON worker_operator.id = binding.operator_id
                    JOIN engagement_members AS membership
                      ON membership.engagement_id = binding.engagement_id
                     AND membership.operator_id = binding.operator_id
                    WHERE binding.database_role = expected_database_role
                      AND binding.operator_id = expected_operator_id
                      AND binding.engagement_id = expected_engagement_id
                      AND binding.release_revision = expected_release_revision
                      AND binding.deployment_id = expected_deployment_id
                      AND binding.deployment_validation_id IS NOT DISTINCT FROM
                          expected_deployment_validation_id
                      AND worker_operator.identity_kind = 'service'
                      AND worker_operator.is_active = true
                      AND membership.role = 'operator'
                ),
                false
            )
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION ai_fde_bound_worker_operator_id()
        RETURNS uuid
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public, pg_temp
        SET row_security = off
        AS $$
            SELECT binding.operator_id
            FROM worker_operator_bindings AS binding
            JOIN operators AS operator ON operator.id = binding.operator_id
            WHERE binding.database_role = session_user
              AND binding.database_role ~ '^ai_fde_worker_[0-9a-f]{12}$'
              AND operator.identity_kind = 'service'
              AND operator.is_active = true
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION ai_fde_worker_can_access_engagement(target_engagement_id uuid)
        RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public, pg_temp
        SET row_security = off
        AS $$
            SELECT COALESCE(
                ai_fde_current_operator_id() = ai_fde_bound_worker_operator_id()
                AND EXISTS (
                    SELECT 1
                    FROM worker_operator_bindings AS binding
                    JOIN engagement_members AS membership
                      ON membership.engagement_id = binding.engagement_id
                     AND membership.operator_id = binding.operator_id
                    WHERE binding.database_role = session_user
                      AND binding.engagement_id = target_engagement_id
                      AND membership.role = 'operator'
                ),
                false
            )
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION ai_fde_worker_runtime_authorized(
            expected_operator_id uuid,
            expected_engagement_id uuid,
            expected_release_revision text,
            expected_deployment_id text,
            expected_deployment_validation_id text
        )
        RETURNS boolean
        LANGUAGE plpgsql
        VOLATILE
        SECURITY DEFINER
        SET search_path = public, pg_temp
        SET row_security = off
        AS $$
        BEGIN
            IF session_user !~ '^ai_fde_worker_[0-9a-f]{12}$' THEN
                RETURN false;
            END IF;

            PERFORM 1
            FROM worker_operator_bindings AS binding
            JOIN operators AS worker_operator
              ON worker_operator.id = binding.operator_id
            JOIN engagement_members AS membership
              ON membership.engagement_id = binding.engagement_id
             AND membership.operator_id = binding.operator_id
            WHERE binding.database_role = session_user
              AND binding.operator_id = expected_operator_id
              AND binding.engagement_id = expected_engagement_id
              AND binding.release_revision = expected_release_revision
              AND binding.deployment_id = expected_deployment_id
              AND binding.deployment_validation_id IS NOT DISTINCT FROM
                  expected_deployment_validation_id
              AND worker_operator.identity_kind = 'service'
              AND worker_operator.is_active = true
              AND membership.role = 'operator'
              AND ai_fde_current_operator_id() = expected_operator_id
            FOR KEY SHARE OF binding, worker_operator, membership;

            RETURN FOUND;
        END;
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION ai_fde_bound_worker_operator_id() FROM PUBLIC")
    op.execute("REVOKE ALL ON FUNCTION ai_fde_worker_can_access_engagement(uuid) FROM PUBLIC")
    op.execute(
        "REVOKE ALL ON FUNCTION "
        "ai_fde_active_worker_binding(text, uuid, uuid, text, text, text) FROM PUBLIC"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION "
        "ai_fde_worker_runtime_authorized(uuid, uuid, text, text, text) FROM PUBLIC"
    )


def _install_heartbeat_clock_trigger() -> None:
    op.execute(
        """
        CREATE FUNCTION ai_fde_set_runtime_heartbeat_seen_at()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            NEW.last_seen_at := clock_timestamp();
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER runtime_heartbeats_set_seen_at
        BEFORE INSERT OR UPDATE ON runtime_heartbeats
        FOR EACH ROW
        EXECUTE FUNCTION ai_fde_set_runtime_heartbeat_seen_at()
        """
    )


def _role_exists(role_name: str) -> bool:
    return bool(
        op.get_bind().scalar(
            sa.text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :role_name)"),
            {"role_name": role_name},
        )
    )
