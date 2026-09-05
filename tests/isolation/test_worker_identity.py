from __future__ import annotations

import os
import uuid
from datetime import timedelta
from types import SimpleNamespace
from typing import cast

import psycopg
import pytest
from psycopg import sql
from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session

from ai_fde.config import Settings, get_settings
from ai_fde.db import apply_operator_context, operator_session
from ai_fde.models import Engagement, EngagementMember, Operator, WorkerOperatorBinding
from ai_fde.modules.engagements.service import create_engagement, list_engagements
from ai_fde.modules.identity.admin import (
    WorkerProvisioningError,
    bind_worker_database_role,
    deactivate_worker_identity,
    grant_worker_engagement,
    provision_worker_identity,
    validate_worker_identity,
    validate_worker_runtime_authority,
)
from ai_fde.modules.identity.database import (
    WORKER_DATABASE_GROUP,
    worker_database_user_for_release,
)
from ai_fde.modules.runtime.models import RuntimeHeartbeat
from ai_fde.modules.runtime.readiness import _load_authorized_worker_heartbeat
from ai_fde.modules.runtime.service import record_worker_heartbeat
from scripts import bootstrap_production_database
from tests.conftest import OperatorFixture

WORKER_RELEASE_REVISION = "a" * 40
WORKER_DEPLOYMENT_ID = "worker-identity-test"
WORKER_VALIDATION_ID = "sha256:" + ("b" * 64)
WORKER_DATABASE_USER = worker_database_user_for_release(
    WORKER_DEPLOYMENT_ID, WORKER_RELEASE_REVISION
)


def _test_postgres_admin_url() -> str:
    settings = get_settings()
    return (
        make_url(settings.database_url)
        .set(
            drivername="postgresql",
            username=os.environ.get("AI_FDE_TEST_POSTGRES_ADMIN_USER", "postgres"),
            password=os.environ.get("AI_FDE_TEST_POSTGRES_ADMIN_PASSWORD", "postgres"),
        )
        .render_as_string(hide_password=False)
    )


def _ensure_test_worker_database_login(database_user: str) -> None:
    if not database_user.startswith(f"{WORKER_DATABASE_GROUP}_"):
        raise AssertionError("Test worker login must use the deployment-derived namespace.")
    database_name = make_url(get_settings().database_url).database
    assert database_name is not None
    with (
        psycopg.connect(_test_postgres_admin_url(), autocommit=True) as connection,
        connection.cursor() as cursor,
    ):
            cursor.execute(
                "SELECT 1 FROM pg_roles WHERE rolname = %s",
                (WORKER_DATABASE_GROUP,),
            )
            if cursor.fetchone() is None:
                cursor.execute(
                    sql.SQL("CREATE ROLE {} NOLOGIN NOINHERIT NOBYPASSRLS").format(
                        sql.Identifier(WORKER_DATABASE_GROUP)
                    )
                )
            else:
                cursor.execute(
                    sql.SQL("ALTER ROLE {} NOLOGIN PASSWORD NULL").format(
                        sql.Identifier(WORKER_DATABASE_GROUP)
                    )
                )
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (database_user,))
            if cursor.fetchone() is None:
                cursor.execute(
                    sql.SQL("CREATE ROLE {} LOGIN PASSWORD 'ai_fde_worker'").format(
                        sql.Identifier(database_user)
                    )
                )
            else:
                cursor.execute(
                    sql.SQL("ALTER ROLE {} LOGIN PASSWORD 'ai_fde_worker'").format(
                        sql.Identifier(database_user)
                    )
                )
            cursor.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(database_name),
                    sql.Identifier(WORKER_DATABASE_GROUP),
                )
            )
            cursor.execute(
                sql.SQL("GRANT {} TO {}").format(
                    sql.Identifier(WORKER_DATABASE_GROUP),
                    sql.Identifier(database_user),
                )
            )


def _drop_test_worker_database_login(database_user: str) -> None:
    with (
        psycopg.connect(_test_postgres_admin_url(), autocommit=True) as connection,
        connection.cursor() as cursor,
    ):
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (database_user,))
            if cursor.fetchone() is not None:
                bootstrap_production_database._retire_worker_database_user(
                    cursor,
                    role_name=database_user,
                    revoke_rds_iam=False,
                )


def _write_running_heartbeat(
    session: Session,
    *,
    worker_id: uuid.UUID,
    engagement_id: uuid.UUID,
    release_revision: str = WORKER_RELEASE_REVISION,
    deployment_id: str = WORKER_DEPLOYMENT_ID,
    deployment_validation_id: str = WORKER_VALIDATION_ID,
) -> RuntimeHeartbeat:
    return record_worker_heartbeat(
        session,
        instance_id=uuid.uuid4().hex,
        release_revision=release_revision,
        deployment_id=deployment_id,
        deployment_validation_id=deployment_validation_id,
        qualification_mode="controlled-design-partner",
        operator_id=worker_id,
        engagement_id=engagement_id,
        status="RUNNING",
        last_job_completed_at=None,
        last_failure_code=None,
    )


def _readiness_heartbeat(
    engine: Engine,
    *,
    worker_id: uuid.UUID,
    engagement_id: uuid.UUID,
) -> RuntimeHeartbeat | None:
    settings = SimpleNamespace(
        worker_operator_id=worker_id,
        worker_engagement_id=engagement_id,
        release_revision=WORKER_RELEASE_REVISION,
        deployment_id=WORKER_DEPLOYMENT_ID,
        deployment_validation_id=WORKER_VALIDATION_ID,
        deployment_qualification_mode="controlled-design-partner",
    )
    with Session(engine) as session, session.begin():
        return _load_authorized_worker_heartbeat(
            session,
            settings=cast(Settings, settings),
        )


@pytest.mark.integration
@pytest.mark.isolation
def test_worker_database_login_cannot_impersonate_a_human_operator(
    test_operator: OperatorFixture,
) -> None:
    worker_id = uuid.uuid4()
    with operator_session(test_operator.id) as session:
        owner = session.get_one(Operator, test_operator.id)
        assigned = create_engagement(
            session,
            operator=owner,
            name="Database-bound Worker Engagement",
            workflow_name="Tenant isolation",
            primary_outcome="Bind one database login to one service identity.",
        )
        hidden = create_engagement(
            session,
            operator=owner,
            name="Database-hidden Worker Engagement",
            workflow_name="Tenant isolation",
            primary_outcome="Remain inaccessible to the worker login.",
        )
        worker = provision_worker_identity(
            session,
            operator_id=worker_id,
            environment=f"test-{worker_id}",
            display_name="Database-bound Worker",
        )
        grant_worker_engagement(session, worker=worker, engagement_id=assigned.id)

    settings = get_settings()
    _ensure_test_worker_database_login(WORKER_DATABASE_USER)
    app_engine = create_engine(settings.database_url)
    owner_engine = create_engine(settings.migration_database_url)
    worker_url = make_url(settings.database_url).set(
        username=WORKER_DATABASE_USER,
        password=os.environ.get("AI_FDE_TEST_WORKER_DATABASE_PASSWORD", "ai_fde_worker"),
    )
    worker_engine = create_engine(worker_url)
    try:
        with Session(owner_engine) as session, session.begin():
            worker_record = session.get_one(Operator, worker_id)
            bind_worker_database_role(
                session,
                worker=worker_record,
                engagement_id=assigned.id,
                release_revision=WORKER_RELEASE_REVISION,
                deployment_id=WORKER_DEPLOYMENT_ID,
                deployment_validation_id=WORKER_VALIDATION_ID,
            )
            grant_worker_engagement(
                session,
                worker=worker_record,
                engagement_id=hidden.id,
            )
            with pytest.raises(WorkerProvisioningError, match="another engagement"):
                bind_worker_database_role(
                    session,
                    worker=worker_record,
                    engagement_id=hidden.id,
                    release_revision=WORKER_RELEASE_REVISION,
                    deployment_id=WORKER_DEPLOYMENT_ID,
                    deployment_validation_id=WORKER_VALIDATION_ID,
                )

        with Session(app_engine) as session, session.begin():
            # The operator GUC is not database authentication. Even the correct worker UUID
            # cannot turn the API login into the worker runtime principal.
            apply_operator_context(session, worker_id)
            with pytest.raises(
                WorkerProvisioningError,
                match="release-scoped database login",
            ):
                validate_worker_runtime_authority(
                    session,
                    operator_id=worker_id,
                    engagement_id=assigned.id,
                    release_revision=WORKER_RELEASE_REVISION,
                    deployment_id=WORKER_DEPLOYMENT_ID,
                    deployment_validation_id=WORKER_VALIDATION_ID,
                )

        with Session(worker_engine) as session, session.begin():
            # This is the direct database-credential attack: setting a human GUC must not
            # grant that human's tenant access or reveal their operator record.
            apply_operator_context(session, test_operator.id)
            assert list(session.scalars(select(Engagement))) == []
            assert list(session.scalars(select(Operator))) == []

            apply_operator_context(session, worker_id)
            assert session.get_one(Operator, worker_id).identity_kind == "service"
            visible_ids = {item.id for item in list_engagements(session, worker_id)}
            assert visible_ids == {assigned.id}
            assert hidden.id not in visible_ids

            validate_worker_runtime_authority(
                session,
                operator_id=worker_id,
                engagement_id=assigned.id,
                release_revision=WORKER_RELEASE_REVISION,
                deployment_id=WORKER_DEPLOYMENT_ID,
                deployment_validation_id=WORKER_VALIDATION_ID,
            )
            heartbeat = _write_running_heartbeat(
                session,
                worker_id=worker_id,
                engagement_id=assigned.id,
            )
            assert heartbeat.operator_id == worker_id
            assert heartbeat.engagement_id == assigned.id
            assert heartbeat.deployment_validation_id == WORKER_VALIDATION_ID

            # Even a direct ORM attempt to submit a +365-day heartbeat is overwritten by
            # PostgreSQL's clock before the row can become observable.
            database_now = session.scalar(text("SELECT clock_timestamp()"))
            assert database_now is not None
            future_heartbeat = RuntimeHeartbeat(
                service="ai-fde-worker",
                instance_id=uuid.uuid4().hex,
                release_revision=WORKER_RELEASE_REVISION,
                deployment_id=WORKER_DEPLOYMENT_ID,
                deployment_validation_id=WORKER_VALIDATION_ID,
                qualification_mode="controlled-design-partner",
                operator_id=worker_id,
                engagement_id=assigned.id,
                status="RUNNING",
                queue_depth=0,
                last_seen_at=database_now + timedelta(days=365),
            )
            session.add(future_heartbeat)
            session.flush()
            session.refresh(future_heartbeat, attribute_names=["last_seen_at"])
            refreshed_database_now = session.scalar(text("SELECT clock_timestamp()"))
            assert refreshed_database_now is not None
            assert database_now <= future_heartbeat.last_seen_at <= refreshed_database_now
            apply_operator_context(session, test_operator.id)
            with pytest.raises(WorkerProvisioningError, match="not authorized"):
                validate_worker_runtime_authority(
                    session,
                    operator_id=worker_id,
                    engagement_id=assigned.id,
                    release_revision=WORKER_RELEASE_REVISION,
                    deployment_id=WORKER_DEPLOYMENT_ID,
                    deployment_validation_id=WORKER_VALIDATION_ID,
                )

        assert _readiness_heartbeat(
            app_engine,
            worker_id=worker_id,
            engagement_id=assigned.id,
        ) is not None

        forged_release_fields = (
            {"release_revision": "c" * 40},
            {"deployment_id": "forged-deployment"},
            {"deployment_validation_id": "sha256:" + ("d" * 64)},
        )
        for overrides in forged_release_fields:
            with Session(worker_engine) as session, session.begin():
                apply_operator_context(session, worker_id)
                with pytest.raises(DBAPIError, match="row-level security"):
                    _write_running_heartbeat(
                        session,
                        worker_id=worker_id,
                        engagement_id=assigned.id,
                        release_revision=overrides.get(
                            "release_revision", WORKER_RELEASE_REVISION
                        ),
                        deployment_id=overrides.get(
                            "deployment_id", WORKER_DEPLOYMENT_ID
                        ),
                        deployment_validation_id=overrides.get(
                            "deployment_validation_id", WORKER_VALIDATION_ID
                        ),
                    )

        with Session(owner_engine) as session, session.begin():
            binding = session.get_one(WorkerOperatorBinding, WORKER_DATABASE_USER)
            binding.engagement_id = None

        assert _readiness_heartbeat(
            app_engine,
            worker_id=worker_id,
            engagement_id=assigned.id,
        ) is None

        with Session(worker_engine) as session, session.begin():
            apply_operator_context(session, worker_id)
            with pytest.raises(WorkerProvisioningError, match="not authorized"):
                validate_worker_runtime_authority(
                    session,
                    operator_id=worker_id,
                    engagement_id=assigned.id,
                    release_revision=WORKER_RELEASE_REVISION,
                    deployment_id=WORKER_DEPLOYMENT_ID,
                    deployment_validation_id=WORKER_VALIDATION_ID,
                )

        with Session(worker_engine) as session, session.begin():
            apply_operator_context(session, worker_id)
            with pytest.raises(DBAPIError, match="row-level security"):
                _write_running_heartbeat(
                    session,
                    worker_id=worker_id,
                    engagement_id=assigned.id,
                )

        with Session(owner_engine) as session, session.begin():
            binding = session.get_one(WorkerOperatorBinding, WORKER_DATABASE_USER)
            binding.engagement_id = hidden.id

        assert _readiness_heartbeat(
            app_engine,
            worker_id=worker_id,
            engagement_id=assigned.id,
        ) is None

        with Session(worker_engine) as session, session.begin():
            apply_operator_context(session, worker_id)
            with pytest.raises(WorkerProvisioningError, match="not authorized"):
                validate_worker_runtime_authority(
                    session,
                    operator_id=worker_id,
                    engagement_id=assigned.id,
                    release_revision=WORKER_RELEASE_REVISION,
                    deployment_id=WORKER_DEPLOYMENT_ID,
                    deployment_validation_id=WORKER_VALIDATION_ID,
                )

        with Session(worker_engine) as session, session.begin():
            apply_operator_context(session, worker_id)
            with pytest.raises(DBAPIError, match="row-level security"):
                _write_running_heartbeat(
                    session,
                    worker_id=worker_id,
                    engagement_id=assigned.id,
                )

        with Session(owner_engine) as session, session.begin():
            binding = session.get_one(WorkerOperatorBinding, WORKER_DATABASE_USER)
            binding.engagement_id = assigned.id
            membership = session.scalar(
                select(EngagementMember).where(
                    EngagementMember.engagement_id == assigned.id,
                    EngagementMember.operator_id == worker_id,
                )
            )
            assert membership is not None
            membership.role = "viewer"

        assert _readiness_heartbeat(
            app_engine,
            worker_id=worker_id,
            engagement_id=assigned.id,
        ) is None

        with Session(worker_engine) as session, session.begin():
            apply_operator_context(session, worker_id)
            with pytest.raises(WorkerProvisioningError, match="not authorized"):
                validate_worker_runtime_authority(
                    session,
                    operator_id=worker_id,
                    engagement_id=assigned.id,
                    release_revision=WORKER_RELEASE_REVISION,
                    deployment_id=WORKER_DEPLOYMENT_ID,
                    deployment_validation_id=WORKER_VALIDATION_ID,
                )

        with Session(owner_engine) as session, session.begin():
            membership = session.scalar(
                select(EngagementMember).where(
                    EngagementMember.engagement_id == assigned.id,
                    EngagementMember.operator_id == worker_id,
                )
            )
            assert membership is not None
            membership.role = "operator"

        with Session(owner_engine) as session, session.begin():
            session.execute(
                delete(WorkerOperatorBinding).where(
                    WorkerOperatorBinding.database_role == WORKER_DATABASE_USER
                )
            )

        assert _readiness_heartbeat(
            app_engine,
            worker_id=worker_id,
            engagement_id=assigned.id,
        ) is None

        with Session(owner_engine) as session, session.begin():
            bind_worker_database_role(
                session,
                worker=session.get_one(Operator, worker_id),
                engagement_id=assigned.id,
                release_revision=WORKER_RELEASE_REVISION,
                deployment_id=WORKER_DEPLOYMENT_ID,
                deployment_validation_id=WORKER_VALIDATION_ID,
            )

        with operator_session(test_operator.id) as session:
            deactivate_worker_identity(session, operator_id=worker_id)

        assert _readiness_heartbeat(
            app_engine,
            worker_id=worker_id,
            engagement_id=assigned.id,
        ) is None

        with Session(worker_engine) as session, session.begin():
            apply_operator_context(session, worker_id)
            with pytest.raises(WorkerProvisioningError, match="not authorized"):
                validate_worker_runtime_authority(
                    session,
                    operator_id=worker_id,
                    engagement_id=assigned.id,
                    release_revision=WORKER_RELEASE_REVISION,
                    deployment_id=WORKER_DEPLOYMENT_ID,
                    deployment_validation_id=WORKER_VALIDATION_ID,
                )
            assert list(session.scalars(select(Engagement))) == []
            assert list(session.scalars(select(Operator))) == []

        with Session(worker_engine) as session, session.begin():
            apply_operator_context(session, worker_id)
            with pytest.raises(DBAPIError, match="row-level security"):
                _write_running_heartbeat(
                    session,
                    worker_id=worker_id,
                    engagement_id=assigned.id,
                )
    finally:
        with Session(owner_engine) as session, session.begin():
            session.execute(
                delete(RuntimeHeartbeat).where(RuntimeHeartbeat.operator_id == worker_id)
            )
            session.execute(
                delete(WorkerOperatorBinding).where(
                    WorkerOperatorBinding.database_role == WORKER_DATABASE_USER
                )
            )
        worker_engine.dispose()
        owner_engine.dispose()
        app_engine.dispose()


@pytest.mark.integration
@pytest.mark.isolation
def test_binding_rotation_revokes_an_open_old_session_and_drops_the_old_login(
    test_operator: OperatorFixture,
) -> None:
    token = uuid.uuid4().hex[:12]
    deployment_id = f"rotation-same-label-{token}"
    old_release_revision = "a" * 40
    current_release_revision = "b" * 40
    old_database_user = worker_database_user_for_release(
        deployment_id,
        old_release_revision,
    )
    current_database_user = worker_database_user_for_release(
        deployment_id,
        current_release_revision,
    )
    _ensure_test_worker_database_login(old_database_user)
    _ensure_test_worker_database_login(current_database_user)

    worker_id = uuid.uuid4()
    with operator_session(test_operator.id) as session:
        owner = session.get_one(Operator, test_operator.id)
        assigned = create_engagement(
            session,
            operator=owner,
            name=f"Worker rotation {token}",
            workflow_name="Deployment identity rotation",
            primary_outcome="Invalidate an old database session before retiring its login.",
        )
        hidden = create_engagement(
            session,
            operator=owner,
            name=f"Worker rotation hidden {token}",
            workflow_name="Deployment identity rotation",
            primary_outcome="Remain invisible to either deployment worker login.",
        )
        worker = provision_worker_identity(
            session,
            operator_id=worker_id,
            environment=f"rotation-{token}",
            display_name="Rotating worker",
        )
        grant_worker_engagement(session, worker=worker, engagement_id=assigned.id)

    settings = get_settings()
    owner_engine = create_engine(settings.migration_database_url)
    base_url = make_url(settings.database_url)
    old_engine = create_engine(
        base_url.set(
            username=old_database_user,
            password="ai_fde_worker",
        )
    )
    current_engine = create_engine(
        base_url.set(
            username=current_database_user,
            password="ai_fde_worker",
        )
    )
    old_connection = old_engine.connect()
    old_session = Session(bind=old_connection)
    try:
        with Session(owner_engine) as session, session.begin():
            bind_worker_database_role(
                session,
                worker=session.get_one(Operator, worker_id),
                engagement_id=assigned.id,
                release_revision=old_release_revision,
                deployment_id=deployment_id,
                deployment_validation_id=WORKER_VALIDATION_ID,
            )

        with old_session.begin():
            apply_operator_context(old_session, worker_id)
            validate_worker_runtime_authority(
                old_session,
                operator_id=worker_id,
                engagement_id=assigned.id,
                release_revision=old_release_revision,
                deployment_id=deployment_id,
                deployment_validation_id=WORKER_VALIDATION_ID,
            )
            assert {item.id for item in list_engagements(old_session, worker_id)} == {
                assigned.id
            }

        # Binding commit is the revocation linearization point. The old physical session
        # remains connected here, but every SECURITY DEFINER/RLS decision must now deny it.
        with Session(owner_engine) as session, session.begin():
            bind_worker_database_role(
                session,
                worker=session.get_one(Operator, worker_id),
                engagement_id=assigned.id,
                release_revision=current_release_revision,
                deployment_id=deployment_id,
                deployment_validation_id=WORKER_VALIDATION_ID,
            )

        with old_session.begin():
            apply_operator_context(old_session, worker_id)
            with pytest.raises(WorkerProvisioningError, match="not authorized"):
                validate_worker_runtime_authority(
                    old_session,
                    operator_id=worker_id,
                    engagement_id=assigned.id,
                    release_revision=old_release_revision,
                    deployment_id=deployment_id,
                    deployment_validation_id=WORKER_VALIDATION_ID,
                )
            assert list_engagements(old_session, worker_id) == []

        with Session(current_engine) as session, session.begin():
            apply_operator_context(session, worker_id)
            validate_worker_runtime_authority(
                session,
                operator_id=worker_id,
                engagement_id=assigned.id,
                release_revision=current_release_revision,
                deployment_id=deployment_id,
                deployment_validation_id=WORKER_VALIDATION_ID,
            )
            visible_ids = {item.id for item in list_engagements(session, worker_id)}
            assert visible_ids == {assigned.id}
            assert hidden.id not in visible_ids
            heartbeat = _write_running_heartbeat(
                session,
                worker_id=worker_id,
                engagement_id=assigned.id,
                release_revision=current_release_revision,
                deployment_id=deployment_id,
            )
            assert heartbeat.last_seen_at is not None

        # Production cleanup first disables the old login, then kills this still-open
        # backend and drops the role. A fresh connection with the stolen credential fails.
        _drop_test_worker_database_login(old_database_user)
        old_session.close()
        old_connection.close()
        old_engine.dispose()
        with pytest.raises(OperationalError), old_engine.connect():
            pass

        with Session(current_engine) as session, session.begin():
            apply_operator_context(session, worker_id)
            validate_worker_runtime_authority(
                session,
                operator_id=worker_id,
                engagement_id=assigned.id,
                release_revision=current_release_revision,
                deployment_id=deployment_id,
                deployment_validation_id=WORKER_VALIDATION_ID,
            )
    finally:
        old_session.close()
        old_connection.close()
        old_engine.dispose()
        current_engine.dispose()
        with Session(owner_engine) as session, session.begin():
            session.execute(
                delete(RuntimeHeartbeat).where(RuntimeHeartbeat.operator_id == worker_id)
            )
            session.execute(
                delete(WorkerOperatorBinding).where(
                    WorkerOperatorBinding.operator_id == worker_id
                )
            )
        owner_engine.dispose()
        _drop_test_worker_database_login(old_database_user)
        _drop_test_worker_database_login(current_database_user)


@pytest.mark.isolation
def test_service_worker_sees_only_explicit_engagement_memberships(
    test_operator: OperatorFixture,
) -> None:
    worker_id = uuid.uuid4()
    with operator_session(test_operator.id) as session:
        owner = session.get_one(Operator, test_operator.id)
        assigned = create_engagement(
            session,
            operator=owner,
            name="Assigned Worker Engagement",
            workflow_name="Vendor onboarding",
            primary_outcome="Prove an explicitly assigned service identity boundary.",
        )
        create_engagement(
            session,
            operator=owner,
            name="Unassigned Worker Engagement",
            workflow_name="Contract review",
            primary_outcome="Remain invisible to the unrelated service identity.",
        )
        worker = provision_worker_identity(
            session,
            operator_id=worker_id,
            environment=f"test-{worker_id}",
            display_name="Acceptance Worker",
        )
        membership = grant_worker_engagement(session, worker=worker, engagement_id=assigned.id)
        assert membership.role == "operator"

    with operator_session(worker_id) as session:
        worker = validate_worker_identity(session, operator_id=worker_id)
        assert worker.identity_kind == "service"
        assert [item.id for item in list_engagements(session, worker_id)] == [assigned.id]


@pytest.mark.isolation
def test_worker_provisioning_rejects_human_owner_and_inactive_service(
    test_operator: OperatorFixture,
) -> None:
    worker_id = uuid.uuid4()
    with operator_session(test_operator.id) as session:
        owner = session.get_one(Operator, test_operator.id)
        engagement = create_engagement(
            session,
            operator=owner,
            name="Worker Boundary Engagement",
            workflow_name="Order review",
            primary_outcome="Keep service identities out of human approval authority.",
        )
        with pytest.raises(WorkerProvisioningError, match="human identity"):
            provision_worker_identity(
                session,
                operator_id=owner.id,
                environment=f"test-{worker_id}",
                display_name="Invalid Worker",
            )

        worker = provision_worker_identity(
            session,
            operator_id=worker_id,
            environment=f"test-{worker_id}",
            display_name="Boundary Worker",
        )
        membership = grant_worker_engagement(session, worker=worker, engagement_id=engagement.id)
        membership.role = "owner"
        session.flush()
        with pytest.raises(WorkerProvisioningError, match="cannot own"):
            grant_worker_engagement(session, worker=worker, engagement_id=engagement.id)

        queried_membership = session.scalar(
            select(EngagementMember).where(EngagementMember.operator_id == worker_id)
        )
        assert queried_membership is not None
        queried_membership.role = "operator"
        deactivate_worker_identity(session, operator_id=worker_id)
        with pytest.raises(WorkerProvisioningError, match="inactive"):
            validate_worker_identity(session, operator_id=worker_id)


@pytest.mark.isolation
def test_sanitized_engagement_requires_the_explicit_worker_readiness_flag(
    test_operator: OperatorFixture,
) -> None:
    worker_id = uuid.uuid4()
    with operator_session(test_operator.id) as session:
        owner = session.get_one(Operator, test_operator.id)
        engagement = create_engagement(
            session,
            operator=owner,
            name="Sanitized Worker Engagement",
            workflow_name="Customer onboarding",
            primary_outcome="Remain hidden from workers until deployment readiness passes.",
            data_classification="sanitized",
        )
        worker = provision_worker_identity(
            session,
            operator_id=worker_id,
            environment=f"test-{worker_id}",
            display_name="Sanitized Boundary Worker",
        )
        grant_worker_engagement(session, worker=worker, engagement_id=engagement.id)

    with operator_session(worker_id) as session:
        assert list_engagements(session, worker_id, include_sanitized=False) == []
        assert [
            item.id for item in list_engagements(session, worker_id, include_sanitized=True)
        ] == [engagement.id]
