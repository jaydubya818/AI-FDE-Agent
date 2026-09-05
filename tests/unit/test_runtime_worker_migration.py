from __future__ import annotations

import pytest
from alembic import context, op

import migrations.versions.e8c4d2a791f0_runtime_readiness_and_worker_role as migration


def test_offline_worker_role_ddl_is_server_conditioned_without_database_introspection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executed: list[str] = []

    def unexpected_role_lookup(_role_name: str) -> bool:
        raise AssertionError("Offline migration generation must not query pg_roles through a bind.")

    monkeypatch.setattr(context, "is_offline_mode", lambda: True)
    monkeypatch.setattr(migration, "_role_exists", unexpected_role_lookup)
    monkeypatch.setattr(op, "execute", lambda statement: executed.append(str(statement)))

    migration._install_worker_role_access()

    assert len(executed) == 1
    generated_sql = executed[0]
    assert "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ai_fde_worker')" in generated_sql
    assert "CREATE ROLE" not in generated_sql
    for statement in migration._worker_role_access_statements():
        assert (
            f"$ai_fde_worker_statement${statement}$ai_fde_worker_statement$" in generated_sql
        )


@pytest.mark.parametrize("role_exists", [False, True])
def test_online_worker_role_ddl_remains_fail_closed_when_the_role_is_absent(
    monkeypatch: pytest.MonkeyPatch,
    role_exists: bool,
) -> None:
    executed: list[str] = []
    monkeypatch.setattr(context, "is_offline_mode", lambda: False)
    monkeypatch.setattr(migration, "_role_exists", lambda _role_name: role_exists)
    monkeypatch.setattr(op, "execute", lambda statement: executed.append(str(statement)))

    migration._install_worker_role_access()

    expected = migration._worker_role_access_statements() if role_exists else []
    assert executed == expected


def test_worker_identity_functions_require_deployment_specific_login_and_active_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executed: list[str] = []
    monkeypatch.setattr(op, "execute", lambda statement: executed.append(str(statement)))

    migration._install_worker_identity_functions()

    sql = "\n".join(executed)
    assert "^ai_fde_worker_[0-9a-f]{12}$" in sql
    assert "binding.database_role = session_user" in sql
    assert "worker_operator.is_active = true" in sql
    assert "membership.role = 'operator'" in sql
    assert "ai_fde_active_worker_binding" in sql


def test_heartbeat_trigger_overwrites_caller_time_with_postgres_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executed: list[str] = []
    monkeypatch.setattr(op, "execute", lambda statement: executed.append(str(statement)))

    migration._install_heartbeat_clock_trigger()

    sql = "\n".join(executed)
    assert "NEW.last_seen_at := clock_timestamp()" in sql
    assert "BEFORE INSERT OR UPDATE ON runtime_heartbeats" in sql
