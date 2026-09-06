from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.engine import make_url

from ai_fde.db import _rds_iam_connection_creator
from ai_fde.modules.identity.database import (
    AWS_RDS_TLS_CA_PATH,
    worker_database_user_for_release,
)

WORKER_DATABASE_USER = worker_database_user_for_release("qualification-test", "a" * 40)


class _RDSClient:
    def __init__(self) -> None:
        self.calls = 0

    def generate_db_auth_token(
        self,
        *,
        DBHostname: str,
        Port: int,
        DBUsername: str,
    ) -> str:
        assert DBHostname == "db.example.us-east-1.rds.amazonaws.com"
        assert Port == 5432
        assert DBUsername == WORKER_DATABASE_USER
        self.calls += 1
        return f"short-lived-token-{self.calls}"


def test_rds_iam_creator_generates_a_fresh_token_for_each_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _RDSClient()
    connections: list[dict[str, Any]] = []

    def connect(**kwargs: Any) -> object:
        connections.append(kwargs)
        return object()

    monkeypatch.setattr("ai_fde.db.psycopg.connect", connect)
    creator = _rds_iam_connection_creator(
        make_url(
            f"postgresql+psycopg://{WORKER_DATABASE_USER}@"
            "db.example.us-east-1.rds.amazonaws.com:5432/ai_fde?"
            f"sslmode=verify-full&sslrootcert={AWS_RDS_TLS_CA_PATH}"
        ),
        client=client,
        connect_timeout=5,
    )

    creator()
    creator()

    assert [connection["password"] for connection in connections] == [
        "short-lived-token-1",
        "short-lived-token-2",
    ]
    assert all(connection["sslmode"] == "verify-full" for connection in connections)
    assert all(
        connection["sslrootcert"] == AWS_RDS_TLS_CA_PATH for connection in connections
    )
    assert client.calls == 2
