from __future__ import annotations

import os

import psycopg
from alembic import command
from alembic.config import Config
from psycopg import sql

from ai_fde.config import get_settings


def main() -> None:
    settings = get_settings()
    if settings.env != "production":
        raise SystemExit("Production database bootstrap is forbidden outside production.")
    app_password = os.environ.get("AI_FDE_APP_DATABASE_PASSWORD")
    if not app_password:
        raise SystemExit("AI_FDE_APP_DATABASE_PASSWORD is required.")

    owner_url = settings.migration_database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    with (
        psycopg.connect(owner_url, autocommit=True) as connection,
        connection.cursor() as cursor,
    ):
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
        cursor.execute("GRANT CONNECT ON DATABASE ai_fde TO ai_fde_app")
        cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")

    command.upgrade(Config("alembic.ini"), "head")
    print("Production application role is scoped and migrations are current.")


if __name__ == "__main__":
    main()
