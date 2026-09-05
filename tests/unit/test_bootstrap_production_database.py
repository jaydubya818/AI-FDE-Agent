from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy.orm import Session

from ai_fde.config import Settings
from ai_fde.modules.identity.database import worker_database_user_for_release
from scripts import bootstrap_production_database


class _RoleCursor:
    def __init__(self) -> None:
        self.statements: list[tuple[object, object | None]] = []
        self.fetches = iter([(1,), (1,), None])

    def execute(self, statement: object, parameters: object | None = None) -> None:
        self.statements.append((statement, parameters))

    def fetchone(self) -> object:
        return next(self.fetches)


def _render(statement: object) -> str:
    as_string = getattr(statement, "as_string", None)
    return str(as_string()) if as_string is not None else str(statement)


def test_production_worker_group_is_nologin_and_exact_user_requires_rds_iam() -> None:
    cursor = _RoleCursor()
    worker_database_user = worker_database_user_for_release("bootstrap-test", "a" * 40)

    bootstrap_production_database._configure_database_roles(
        cursor,
        app_password="api-password",
        database_name="ai_fde",
        worker_database_user=worker_database_user,
    )

    statements = [_render(statement) for statement, _parameters in cursor.statements]
    assert (
        'ALTER ROLE "ai_fde_worker" NOLOGIN PASSWORD NULL NOSUPERUSER NOCREATEDB '
        "NOCREATEROLE NOINHERIT NOBYPASSRLS"
    ) in statements
    assert (
        f'ALTER ROLE "{worker_database_user}" LOGIN PASSWORD NULL NOSUPERUSER '
        "NOCREATEDB NOCREATEROLE INHERIT NOBYPASSRLS"
    ) in statements
    assert 'REVOKE rds_iam FROM "ai_fde_worker"' in statements
    assert f'GRANT rds_iam TO "{worker_database_user}"' in statements
    assert f'GRANT "ai_fde_worker" TO "{worker_database_user}"' in statements
    assert not any(
        worker_database_user in statement and "PASSWORD '" in statement
        for statement in statements
    )


def test_role_bootstrap_refuses_a_non_deployment_worker_login() -> None:
    cursor = _RoleCursor()

    with pytest.raises(ValueError, match="release-scoped"):
        bootstrap_production_database._configure_database_roles(
            cursor,
            app_password="api-password",
            database_name="ai_fde",
            worker_database_user="ai_fde_worker",
        )

    assert cursor.statements == []


def test_configured_bootstrap_grants_membership_before_exact_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker_id = uuid.uuid4()
    engagement_id = uuid.uuid4()
    settings = SimpleNamespace(
        worker_operator_id=worker_id,
        worker_engagement_id=engagement_id,
        env="production",
        release_revision="a" * 40,
        deployment_id="bootstrap-test",
        deployment_validation_id="sha256:" + ("b" * 64),
    )
    session = object()
    worker = object()
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(
        bootstrap_production_database,
        "provision_worker_identity",
        lambda *_args, **_kwargs: worker,
    )
    monkeypatch.setattr(
        bootstrap_production_database,
        "grant_worker_engagement",
        lambda *_args, **kwargs: calls.append(("grant", kwargs["engagement_id"])),
    )
    monkeypatch.setattr(
        bootstrap_production_database,
        "bind_worker_database_role",
        lambda *_args, **kwargs: calls.append(("bind", kwargs["engagement_id"])),
    )

    bound_database_user = bootstrap_production_database._bootstrap_worker_binding(
        cast(Session, session), cast(Settings, settings)
    )

    assert calls == [("grant", engagement_id), ("bind", engagement_id)]
    assert bound_database_user == worker_database_user_for_release(
        "bootstrap-test", "a" * 40
    )


def test_pre_onboarding_bootstrap_keeps_fail_closed_null_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(
        worker_operator_id=uuid.uuid4(),
        worker_engagement_id=None,
        env="production",
        release_revision="a" * 40,
        deployment_id="bootstrap-test",
        deployment_validation_id=None,
    )
    session = object()
    worker = object()
    grants: list[object] = []
    bindings: list[object] = []

    monkeypatch.setattr(
        bootstrap_production_database,
        "provision_worker_identity",
        lambda *_args, **_kwargs: worker,
    )
    monkeypatch.setattr(
        bootstrap_production_database,
        "grant_worker_engagement",
        lambda *_args, **kwargs: grants.append(kwargs["engagement_id"]),
    )
    monkeypatch.setattr(
        bootstrap_production_database,
        "bind_worker_database_role",
        lambda *_args, **kwargs: bindings.append(kwargs["engagement_id"]),
    )

    bound_database_user = bootstrap_production_database._bootstrap_worker_binding(
        cast(Session, session), cast(Settings, settings)
    )

    assert grants == []
    assert bindings == [None]
    assert bound_database_user == worker_database_user_for_release(
        "bootstrap-test", "a" * 40
    )


class _RetirementCursor:
    def __init__(self, prior_roles: list[str]) -> None:
        self.prior_roles = prior_roles
        self.statements: list[tuple[str, object | None]] = []

    def execute(self, statement: object, parameters: object | None = None) -> None:
        self.statements.append((_render(statement), parameters))

    def fetchall(self) -> list[tuple[str]]:
        return [(role,) for role in self.prior_roles]


def test_prior_worker_users_are_disabled_revoked_terminated_then_dropped() -> None:
    current = worker_database_user_for_release("current-deployment", "b" * 40)
    prior = worker_database_user_for_release("prior-deployment", "a" * 40)
    cursor = _RetirementCursor([prior])

    retired = bootstrap_production_database._retire_prior_worker_database_users(
        cursor,
        current_worker_database_user=current,
    )

    assert retired == [prior]
    statements = cursor.statements
    role_actions = [statement for statement, _parameters in statements[1:]]
    assert role_actions == [
        f'ALTER ROLE "{prior}" NOLOGIN PASSWORD NULL',
        f'REVOKE "ai_fde_worker" FROM "{prior}"',
        f'REVOKE rds_iam FROM "{prior}"',
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE usename = %s AND pid <> pg_backend_pid()",
        f'DROP ROLE "{prior}"',
    ]
    assert statements[0][1] == (current,)
    assert statements[4][1] == (prior,)


def test_worker_retirement_refuses_a_non_worker_role() -> None:
    cursor = _RetirementCursor([])

    with pytest.raises(ValueError, match="non-worker"):
        bootstrap_production_database._retire_worker_database_user(
            cursor,
            role_name="ai_fde_app",
            revoke_rds_iam=True,
        )

    assert cursor.statements == []
