from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from ai_fde.db import SessionFactory, apply_operator_context
from ai_fde.models import Operator


@dataclass(frozen=True)
class OperatorFixture:
    id: UUID
    subject: str
    display_name: str


@pytest.fixture(scope="session")
def postgres_available() -> None:
    session = SessionFactory()
    try:
        session.execute(text("SELECT 1"))
    except OperationalError as exc:
        if os.environ.get("AI_FDE_REQUIRE_POSTGRES_TESTS") == "1":
            pytest.fail(
                f"PostgreSQL-backed trust tests are required in this run: {exc}",
                pytrace=False,
            )
        pytest.skip(f"PostgreSQL test infrastructure is not running: {exc}")
    finally:
        session.close()


@pytest.fixture
def test_operator(postgres_available: None) -> OperatorFixture:
    token = uuid.uuid4()
    operator = OperatorFixture(
        id=token,
        subject=f"acceptance-{token}",
        display_name="Acceptance FDE",
    )
    session = SessionFactory()
    try:
        with session.begin():
            apply_operator_context(session, operator.id)
            session.add(
                Operator(
                    id=operator.id,
                    external_subject=operator.subject,
                    display_name=operator.display_name,
                )
            )
    finally:
        session.close()
    return operator
