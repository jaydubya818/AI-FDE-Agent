from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from ai_fde.admin import _deliver_retrieval_token, _parser

SECRET_ARN = (
    "arn:aws:secretsmanager:us-east-1:123456789012:"
    "secret:ai-fde/package-retrieval-AbCdEf"
)
GRANT_ID = UUID("70000000-0000-4000-8000-000000000007")


class RecordingSecretsManagerClient:
    def __init__(self) -> None:
        self.request: dict[str, Any] | None = None

    def put_secret_value(self, **kwargs: Any) -> object:
        self.request = kwargs
        return {"VersionId": kwargs["ClientRequestToken"]}


def test_retrieval_token_is_delivered_to_secret_manager_without_output_or_logs(
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    token = "fdp1.operator.grant.do-not-log-this-secret"
    client = RecordingSecretsManagerClient()

    _deliver_retrieval_token(
        secret_arn=SECRET_ARN,
        token=token,
        grant_id=GRANT_ID,
        client=client,
    )

    captured = capsys.readouterr()
    assert client.request == {
        "SecretId": SECRET_ARN,
        "ClientRequestToken": GRANT_ID.hex,
        "SecretString": token,
        "VersionStages": ["AWSCURRENT"],
    }
    assert token not in captured.out
    assert token not in captured.err
    assert token not in caplog.text
    assert str(GRANT_ID) in captured.out


def test_retrieval_rotation_command_requires_an_explicit_secret_arn() -> None:
    common = [
        "rotate-package-retrieval-grant",
        "--engagement-id",
        "70000000-0000-4000-8000-000000000001",
        "--owner-operator-id",
        "70000000-0000-4000-8000-000000000002",
        "--requester-identity",
        "mission-control:production",
        "--requester-system",
        "mission-control",
        "--expires-at",
        "2026-09-05T00:00:00Z",
    ]

    with pytest.raises(SystemExit):
        _parser().parse_args(common)
    with pytest.raises(SystemExit):
        _parser().parse_args([*common, "--target-secret-arn", "plain-secret-name"])

    parsed = _parser().parse_args([*common, "--target-secret-arn", SECRET_ARN])
    assert parsed.target_secret_arn == SECRET_ARN
