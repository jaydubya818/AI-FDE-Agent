from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, Protocol, cast
from uuid import UUID

import boto3
import psycopg
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from ai_fde.config import Settings, get_settings
from ai_fde.models import Operator


class RDSAuthClient(Protocol):
    def generate_db_auth_token(
        self,
        *,
        DBHostname: str,
        Port: int,
        DBUsername: str,
    ) -> str: ...


def build_engine(
    settings: Settings | None = None,
    *,
    rds_client: RDSAuthClient | None = None,
) -> Engine:
    resolved = settings or get_settings()
    if resolved.database_auth_mode == "rds-iam":
        database_url = make_url(resolved.database_url)
        client = rds_client or boto3.client("rds", region_name=resolved.s3_region)
        return create_engine(
            database_url,
            creator=_rds_iam_connection_creator(
                database_url,
                client=client,
                connect_timeout=resolved.database_connect_timeout_seconds,
            ),
            pool_pre_ping=True,
            pool_recycle=600,
        )
    return create_engine(
        resolved.database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": resolved.database_connect_timeout_seconds},
    )


def _rds_iam_connection_creator(
    database_url: URL,
    *,
    client: RDSAuthClient,
    connect_timeout: int,
) -> Callable[[], Any]:
    hostname = database_url.host
    username = database_url.username
    if hostname is None or username is None:
        raise ValueError("RDS IAM authentication requires an exact database host and user.")
    port = database_url.port or 5432
    connection_args: dict[str, Any] = database_url.translate_connect_args(database="dbname")
    connection_args.pop("password", None)
    connection_args.update({key: str(value) for key, value in database_url.query.items()})
    connection_args["connect_timeout"] = connect_timeout

    def connect() -> Any:
        token = client.generate_db_auth_token(
            DBHostname=hostname,
            Port=port,
            DBUsername=username,
        )
        return psycopg.connect(**connection_args, password=token)

    return connect


engine = build_engine()
SessionFactory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
_ROLLBACK_COMPENSATIONS_KEY = "ai_fde.rollback_compensations"


def register_transaction_rollback_compensation(
    session: Session,
    compensation: Callable[[], None],
) -> None:
    """Run an external-write compensation if the surrounding DB transaction fails."""

    pending = session.info.setdefault(_ROLLBACK_COMPENSATIONS_KEY, [])
    cast(list[Callable[[], None]], pending).append(compensation)


def _take_transaction_rollback_compensations(
    session: Session,
) -> list[Callable[[], None]]:
    pending = session.info.pop(_ROLLBACK_COMPENSATIONS_KEY, [])
    return cast(list[Callable[[], None]], pending)


def _run_transaction_rollback_compensations(session: Session) -> None:
    errors: list[Exception] = []
    for compensation in reversed(_take_transaction_rollback_compensations(session)):
        try:
            compensation()
        except Exception as exc:  # pragma: no cover - exercised by storage integration alarms
            errors.append(exc)
    if errors:
        raise ExceptionGroup("External-write rollback compensation failed.", errors)


def apply_operator_context(session: Session, operator_id: UUID) -> None:
    session.execute(
        text("SELECT set_config('ai_fde.operator_id', :operator_id, true)"),
        {"operator_id": str(operator_id)},
    )


@contextmanager
def operator_session(operator_id: UUID) -> Iterator[Session]:
    session = SessionFactory()
    try:
        try:
            with session.begin():
                apply_operator_context(session, operator_id)
                yield session
        except BaseException as transaction_error:
            try:
                _run_transaction_rollback_compensations(session)
            except Exception as compensation_error:
                raise BaseExceptionGroup(
                    "Database transaction and external-write compensation failed.",
                    [transaction_error, compensation_error],
                ) from None
            raise
        else:
            _take_transaction_rollback_compensations(session)
    finally:
        session.close()


def ensure_local_operator(settings: Settings | None = None) -> None:
    resolved = settings or get_settings()
    if resolved.auth_mode != "development":
        raise RuntimeError("Local operator initialization is development-only.")
    with operator_session(resolved.operator_id) as session:
        existing = session.scalar(select(Operator).where(Operator.id == resolved.operator_id))
        if existing is None:
            session.add(
                Operator(
                    id=resolved.operator_id,
                    external_subject=resolved.operator_subject,
                    display_name=resolved.operator_name,
                )
            )
