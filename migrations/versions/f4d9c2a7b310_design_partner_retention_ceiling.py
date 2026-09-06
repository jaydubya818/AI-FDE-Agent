"""immutable design-partner retention ceiling

Revision ID: f4d9c2a7b310
Revises: e8c4d2a791f0
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4d9c2a7b310"
down_revision: str | None = "e8c4d2a791f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "design_partner_qualifications",
        sa.Column("retention_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        UPDATE design_partner_qualifications
        SET retention_expires_at = created_at + make_interval(days => retention_days)
        """
    )
    op.alter_column(
        "design_partner_qualifications",
        "retention_expires_at",
        nullable=False,
    )
    op.create_check_constraint(
        op.f("ck_design_partner_qualifications_valid_retention_ceiling"),
        "design_partner_qualifications",
        "retention_expires_at = created_at + make_interval(days => retention_days)",
    )

    # Existing Phase 3 rows were already checked by the domain service. If a database was
    # manually extended past that authority before this invariant existed, restore the
    # persisted engagement deadline to the newly materialized authorization ceiling.
    op.execute(
        """
        UPDATE engagements AS engagement
        SET retention_expires_at = qualification.retention_expires_at,
            updated_at = now()
        FROM design_partner_qualifications AS qualification
        WHERE qualification.engagement_id = engagement.id
          AND (
              engagement.retention_expires_at IS NULL
              OR engagement.retention_expires_at > qualification.retention_expires_at
          )
        """
    )

    op.execute(
        """
        CREATE FUNCTION ai_fde_enforce_design_partner_retention_policy()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        SET row_security = off
        AS $$
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                IF NEW.engagement_id IS DISTINCT FROM OLD.engagement_id
                   OR NEW.retention_days IS DISTINCT FROM OLD.retention_days
                   OR NEW.retention_expires_at IS DISTINCT FROM OLD.retention_expires_at
                   OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                    RAISE EXCEPTION
                        'design-partner retention authority is immutable'
                        USING ERRCODE = '23514';
                END IF;
            ELSE
                IF NOT EXISTS (
                    SELECT 1
                    FROM engagements AS engagement
                    WHERE engagement.id = NEW.engagement_id
                      AND engagement.retention_expires_at IS NOT NULL
                      AND engagement.retention_expires_at <= NEW.retention_expires_at
                ) THEN
                    RAISE EXCEPTION
                        'engagement retention exceeds design-partner authority'
                        USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION ai_fde_enforce_design_partner_retention_policy() FROM PUBLIC"
    )
    op.execute(
        """
        CREATE TRIGGER enforce_design_partner_retention_policy
        BEFORE INSERT OR UPDATE ON design_partner_qualifications
        FOR EACH ROW EXECUTE FUNCTION ai_fde_enforce_design_partner_retention_policy()
        """
    )

    op.execute(
        """
        CREATE FUNCTION ai_fde_enforce_engagement_retention_ceiling()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        SET row_security = off
        AS $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM design_partner_qualifications AS qualification
                WHERE qualification.engagement_id = NEW.id
                  AND (
                      NEW.retention_expires_at IS NULL
                      OR NEW.retention_expires_at > qualification.retention_expires_at
                  )
            ) THEN
                RAISE EXCEPTION
                    'engagement retention exceeds design-partner authority'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION ai_fde_enforce_engagement_retention_ceiling() FROM PUBLIC")
    op.execute(
        """
        CREATE TRIGGER enforce_engagement_retention_ceiling
        BEFORE UPDATE OF retention_expires_at ON engagements
        FOR EACH ROW EXECUTE FUNCTION ai_fde_enforce_engagement_retention_ceiling()
        """
    )

    op.drop_constraint(
        op.f("ck_package_retrieval_events_valid_result"),
        "package_retrieval_events",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_package_retrieval_events_valid_result"),
        "package_retrieval_events",
        "result IN ('RETRIEVED', 'DENIED_NOT_PUBLISHED', 'DENIED_STALE', "
        "'DENIED_REVOKED', 'DENIED_QUALIFICATION', 'DENIED_INTEGRITY', 'NOT_FOUND')",
    )

    # Runtime roles intentionally cannot UPDATE qualification rows, which also means
    # they cannot issue SELECT ... FOR UPDATE directly. This narrowly-scoped function
    # serializes sensitive customer-data decisions with owner qualification changes
    # without widening either runtime role's table privileges.
    op.execute("DROP FUNCTION IF EXISTS ai_fde_lock_design_partner_authority(uuid)")
    op.execute(
        """
        CREATE FUNCTION ai_fde_lock_design_partner_authority(
            target_engagement_id uuid,
            required_access text
        )
        RETURNS boolean
        LANGUAGE plpgsql
        VOLATILE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        SET row_security = off
        AS $$
        DECLARE
            caller_operator_id uuid;
        BEGIN
            IF required_access IS NULL OR required_access NOT IN ('read', 'write') THEN
                RETURN false;
            END IF;

            IF session_user = 'ai_fde_app' THEN
                caller_operator_id := public.ai_fde_current_operator_id();
                IF caller_operator_id IS NULL OR NOT EXISTS (
                    SELECT 1
                    FROM public.operators AS caller_operator
                    JOIN public.engagement_members AS membership
                      ON membership.operator_id = caller_operator.id
                    WHERE caller_operator.id = caller_operator_id
                      AND caller_operator.is_active = true
                      AND membership.engagement_id = target_engagement_id
                      AND membership.role IN ('owner', 'operator', 'viewer')
                      AND (
                          required_access = 'read'
                          OR membership.role IN ('owner', 'operator')
                      )
                ) THEN
                    RETURN false;
                END IF;
            ELSIF session_user ~ '^ai_fde_worker_[0-9a-f]{12}$' THEN
                IF NOT public.ai_fde_worker_can_access_engagement(target_engagement_id) THEN
                    RETURN false;
                END IF;
            ELSE
                RETURN false;
            END IF;

            PERFORM 1
            FROM public.engagements AS engagement
            WHERE engagement.id = target_engagement_id
            FOR UPDATE;
            IF NOT FOUND THEN
                RETURN false;
            END IF;

            -- Revalidate and retain the caller's access rows after the aggregate lock.
            -- This makes identity or membership removal wait until the caller commits.
            IF session_user = 'ai_fde_app' THEN
                PERFORM 1
                FROM public.operators AS caller_operator
                JOIN public.engagement_members AS membership
                  ON membership.operator_id = caller_operator.id
                WHERE caller_operator.id = caller_operator_id
                  AND caller_operator.is_active = true
                  AND membership.engagement_id = target_engagement_id
                  AND membership.role IN ('owner', 'operator', 'viewer')
                  AND (
                      required_access = 'read'
                      OR membership.role IN ('owner', 'operator')
                  )
                FOR SHARE OF caller_operator, membership;
                IF NOT FOUND THEN
                    RETURN false;
                END IF;
            ELSE
                PERFORM 1
                FROM public.worker_operator_bindings AS binding
                JOIN public.operators AS worker_operator
                  ON worker_operator.id = binding.operator_id
                JOIN public.engagement_members AS membership
                  ON membership.engagement_id = binding.engagement_id
                 AND membership.operator_id = binding.operator_id
                WHERE binding.database_role = session_user
                  AND binding.engagement_id = target_engagement_id
                  AND binding.operator_id = public.ai_fde_current_operator_id()
                  AND worker_operator.identity_kind = 'service'
                  AND worker_operator.is_active = true
                  AND membership.role = 'operator'
                FOR SHARE OF binding, worker_operator, membership;
                IF NOT FOUND THEN
                    RETURN false;
                END IF;
            END IF;

            PERFORM 1
            FROM public.design_partner_qualifications AS qualification
            WHERE qualification.engagement_id = target_engagement_id
            FOR UPDATE;
            RETURN FOUND;
        END;
        $$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION ai_fde_lock_design_partner_authority(uuid, text) FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "ai_fde_lock_design_partner_authority(uuid, text) TO ai_fde_app"
    )
    op.execute(
        """
        DO $ai_fde_worker_role$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ai_fde_worker') THEN
                GRANT EXECUTE ON FUNCTION
                    ai_fde_lock_design_partner_authority(uuid, text) TO ai_fde_worker;
            END IF;
        END
        $ai_fde_worker_role$
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS ai_fde_lock_design_partner_authority(uuid, text)")
    op.execute("DROP FUNCTION IF EXISTS ai_fde_lock_design_partner_authority(uuid)")
    op.drop_constraint(
        op.f("ck_package_retrieval_events_valid_result"),
        "package_retrieval_events",
        type_="check",
    )
    op.execute(
        """
        UPDATE package_retrieval_events
        SET result = 'DENIED_REVOKED'
        WHERE result = 'DENIED_QUALIFICATION'
        """
    )
    op.create_check_constraint(
        op.f("ck_package_retrieval_events_valid_result"),
        "package_retrieval_events",
        "result IN ('RETRIEVED', 'DENIED_NOT_PUBLISHED', 'DENIED_STALE', "
        "'DENIED_REVOKED', 'DENIED_INTEGRITY', 'NOT_FOUND')",
    )
    op.execute("DROP TRIGGER IF EXISTS enforce_engagement_retention_ceiling ON engagements")
    op.execute("DROP FUNCTION IF EXISTS ai_fde_enforce_engagement_retention_ceiling()")
    op.execute(
        "DROP TRIGGER IF EXISTS enforce_design_partner_retention_policy "
        "ON design_partner_qualifications"
    )
    op.execute("DROP FUNCTION IF EXISTS ai_fde_enforce_design_partner_retention_policy()")
    op.drop_constraint(
        op.f("ck_design_partner_qualifications_valid_retention_ceiling"),
        "design_partner_qualifications",
        type_="check",
    )
    op.drop_column("design_partner_qualifications", "retention_expires_at")
