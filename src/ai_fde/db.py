from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from ai_fde.config import Settings, get_settings
from ai_fde.models import Operator


def build_engine(settings: Settings | None = None) -> Engine:
    resolved = settings or get_settings()
    return create_engine(resolved.database_url, pool_pre_ping=True)


engine = build_engine()
SessionFactory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def apply_operator_context(session: Session, operator_id: UUID) -> None:
    session.execute(
        text("SELECT set_config('ai_fde.operator_id', :operator_id, true)"),
        {"operator_id": str(operator_id)},
    )


@contextmanager
def operator_session(operator_id: UUID) -> Iterator[Session]:
    session = SessionFactory()
    try:
        with session.begin():
            apply_operator_context(session, operator_id)
            yield session
    finally:
        session.close()


def ensure_local_operator(settings: Settings | None = None) -> None:
    resolved = settings or get_settings()
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
