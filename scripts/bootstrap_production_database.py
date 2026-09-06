from __future__ import annotations

import os
from typing import Any

import psycopg
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from ai_fde.config import Settings, get_settings
from ai_fde.modules.identity.admin import (
    bind_worker_database_role,
    grant_worker_engagement,
    provision_worker_identity,
)
from ai_fde.modules.identity.database import (
    WORKER_DATABASE_GROUP,
    is_worker_database_user,
    worker_database_user_for_release,
)


def _bootstrap_worker_binding(session: Session, settings: Settings) -> str:
    """Provision the worker and bind its configured scope, if onboarding supplied one."""

    assert settings.worker_operator_id is not None
    worker = provision_worker_identity(
        session,
        operator_id=settings.worker_operator_id,
        environment=settings.env,
        display_name="AI-FDE Production Worker",
    )
    if settings.worker_engagement_id is not None:
        grant_worker_engagement(
            session,
            worker=worker,
            engagement_id=settings.worker_engagement_id,
        )
    worker_database_user = worker_database_user_for_release(
        settings.deployment_id, settings.release_revision
    )
    bind_worker_database_role(
        session,
        worker=worker,
        database_role=worker_database_user,
        engagement_id=settings.worker_engagement_id,
        release_revision=settings.release_revision,
        deployment_id=settings.deployment_id,
        deployment_validation_id=settings.deployment_validation_id,
    )
    return worker_database_user


def _configure_database_roles(
    cursor: Any,
    *,
    app_password: str,
    database_name: str,
    worker_database_user: str,
) -> None:
    if not is_worker_database_user(worker_database_user):
        raise ValueError("The worker database login must be release-scoped.")
    cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = 'ai_fde_app'")
    if cursor.fetchone() is None:
        cursor.execute(
            sql.SQL("CREATE ROLE ai_fde_app LOGIN PASSWORD {}").format(
                sql.Literal(app_password)
            )
        )
    else:
        cursor.execute(
            sql.SQL("ALTER ROLE ai_fde_app PASSWORD {}").format(sql.Literal(app_password))
        )
    cursor.execute(
        "ALTER ROLE ai_fde_app NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS"
    )
    cursor.execute(
        sql.SQL("GRANT CONNECT ON DATABASE {} TO ai_fde_app").format(
            sql.Identifier(database_name)
        )
    )
    cursor.execute(
        "SELECT 1 FROM pg_roles WHERE rolname = %s",
        (WORKER_DATABASE_GROUP,),
    )
    if cursor.fetchone() is None:
        cursor.execute(
            sql.SQL("CREATE ROLE {} NOLOGIN").format(
                sql.Identifier(WORKER_DATABASE_GROUP)
            )
        )
    cursor.execute(
        sql.SQL(
            "ALTER ROLE {} NOLOGIN PASSWORD NULL NOSUPERUSER NOCREATEDB "
            "NOCREATEROLE NOINHERIT NOBYPASSRLS"
        ).format(sql.Identifier(WORKER_DATABASE_GROUP))
    )
    cursor.execute(
        sql.SQL("REVOKE rds_iam FROM {}").format(
            sql.Identifier(WORKER_DATABASE_GROUP)
        )
    )
    cursor.execute(
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
            sql.Identifier(database_name),
            sql.Identifier(WORKER_DATABASE_GROUP),
        )
    )
    cursor.execute(
        "SELECT 1 FROM pg_roles WHERE rolname = %s",
        (worker_database_user,),
    )
    if cursor.fetchone() is None:
        cursor.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD NULL").format(
                sql.Identifier(worker_database_user)
            )
        )
    cursor.execute(
        sql.SQL(
            "ALTER ROLE {} LOGIN PASSWORD NULL NOSUPERUSER NOCREATEDB "
            "NOCREATEROLE INHERIT NOBYPASSRLS"
        ).format(sql.Identifier(worker_database_user))
    )
    cursor.execute(
        sql.SQL("GRANT rds_iam TO {}").format(sql.Identifier(worker_database_user))
    )
    cursor.execute(
        sql.SQL("GRANT {} TO {}").format(
            sql.Identifier(WORKER_DATABASE_GROUP),
            sql.Identifier(worker_database_user),
        )
    )
    cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")


def _retire_prior_worker_database_users(
    cursor: Any,
    *,
    current_worker_database_user: str,
) -> list[str]:
    """Make every prior deployment login inert before removing it."""

    if not is_worker_database_user(current_worker_database_user):
        raise ValueError("The current worker database login must be release-scoped.")
    cursor.execute(
        "SELECT rolname FROM pg_roles "
        "WHERE rolname ~ '^ai_fde_worker_[0-9a-f]{12}$' AND rolname <> %s "
        "ORDER BY rolname",
        (current_worker_database_user,),
    )
    retired: list[str] = []
    for (role_name,) in cursor.fetchall():
        _retire_worker_database_user(cursor, role_name=role_name, revoke_rds_iam=True)
        retired.append(role_name)
    return retired


def _retire_worker_database_user(
    cursor: Any,
    *,
    role_name: str,
    revoke_rds_iam: bool,
) -> None:
    if not is_worker_database_user(role_name):
        raise ValueError("Refusing to retire a non-worker database role.")
    cursor.execute(
        sql.SQL("ALTER ROLE {} NOLOGIN PASSWORD NULL").format(sql.Identifier(role_name))
    )
    cursor.execute(
        sql.SQL("REVOKE {} FROM {}").format(
            sql.Identifier(WORKER_DATABASE_GROUP),
            sql.Identifier(role_name),
        )
    )
    if revoke_rds_iam:
        cursor.execute(sql.SQL("REVOKE rds_iam FROM {}").format(sql.Identifier(role_name)))
    cursor.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE usename = %s AND pid <> pg_backend_pid()",
        (role_name,),
    )
    cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name)))


def main() -> None:
    settings = get_settings()
    if settings.env != "production":
        raise SystemExit("Production database bootstrap is forbidden outside production.")
    app_password = os.environ.get("AI_FDE_APP_DATABASE_PASSWORD")
    if not app_password:
        raise SystemExit("AI_FDE_APP_DATABASE_PASSWORD is required.")
    owner_url = settings.migration_database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    database_name = make_url(settings.migration_database_url).database
    if database_name is None:
        raise SystemExit("The migration database URL must name a database.")
    worker_database_user = worker_database_user_for_release(
        settings.deployment_id, settings.release_revision
    )
    with (
        psycopg.connect(owner_url, autocommit=True) as connection,
        connection.cursor() as cursor,
    ):
        _configure_database_roles(
            cursor,
            app_password=app_password,
            database_name=database_name,
            worker_database_user=worker_database_user,
        )

    command.upgrade(Config("alembic.ini"), "head")
    owner_engine = create_engine(
        settings.migration_database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": settings.database_connect_timeout_seconds},
    )
    try:
        with Session(owner_engine) as session, session.begin():
            bound_database_user = _bootstrap_worker_binding(session, settings)
            if bound_database_user != worker_database_user:
                raise RuntimeError("The worker binding does not match the configured deployment.")
    finally:
        owner_engine.dispose()
    with (
        psycopg.connect(owner_url, autocommit=True) as connection,
        connection.cursor() as cursor,
    ):
        retired_users = _retire_prior_worker_database_users(
            cursor,
            current_worker_database_user=worker_database_user,
        )
    print(
        "Production API and worker roles are scoped, the release-scoped worker login "
        "is bound to its "
        "configured engagement or a fail-closed pre-onboarding null binding, the production "
        "worker login requires RDS IAM, prior deployment logins are retired "
        f"({len(retired_users)}), and migrations are current."
    )


if __name__ == "__main__":
    main()
