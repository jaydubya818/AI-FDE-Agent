from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from scripts.verify_isolated_restore import (
    RESTORE_DESIGNATION,
    RestoreDrillFailure,
    _read_database_url,
    compare_restore_snapshots,
    validate_restore_targets,
)

SOURCE_URL = (
    "postgresql+psycopg://ai_fde_app:source-password@"
    "ai-fde-design-partner.a1b2c3.us-east-1.rds.amazonaws.com:5432/ai_fde"
    "?sslmode=verify-full"
)
TARGET_URL = (
    "postgresql+psycopg://ai_fde_app:target-password@"
    "ai-fde-restore-20260904.d4e5f6.us-east-1.rds.amazonaws.com:5432/ai_fde"
    "?sslmode=verify-full"
)


def test_restore_guard_accepts_only_distinct_designated_tls_target() -> None:
    source, target = validate_restore_targets(
        source_database_url=SOURCE_URL,
        target_database_url=TARGET_URL,
        source_identifier="ai-fde-design-partner",
        target_identifier="ai-fde-restore-20260904",
        target_designation=RESTORE_DESIGNATION,
    )
    assert source.host == "ai-fde-design-partner.a1b2c3.us-east-1.rds.amazonaws.com"
    assert target.host == "ai-fde-restore-20260904.d4e5f6.us-east-1.rds.amazonaws.com"

    with pytest.raises(RestoreDrillFailure, match="different database hosts"):
        validate_restore_targets(
            source_database_url=SOURCE_URL,
            target_database_url=SOURCE_URL,
            source_identifier="ai-fde-design-partner",
            target_identifier="ai-fde-restore-20260904",
            target_designation=RESTORE_DESIGNATION,
        )
    with pytest.raises(RestoreDrillFailure, match="dedicated"):
        validate_restore_targets(
            source_database_url=SOURCE_URL,
            target_database_url=TARGET_URL,
            source_identifier="ai-fde-design-partner",
            target_identifier="ai-fde-production",
            target_designation=RESTORE_DESIGNATION,
        )
    with pytest.raises(RestoreDrillFailure, match="explicitly designated"):
        validate_restore_targets(
            source_database_url=SOURCE_URL,
            target_database_url=TARGET_URL,
            source_identifier="ai-fde-design-partner",
            target_identifier="ai-fde-restore-20260904",
            target_designation="PRODUCTION",
        )
    with pytest.raises(RestoreDrillFailure, match="direct AWS RDS"):
        validate_restore_targets(
            source_database_url=SOURCE_URL,
            target_database_url=TARGET_URL.replace(
                "d4e5f6.us-east-1.rds.amazonaws.com", "attacker.example"
            ),
            source_identifier="ai-fde-design-partner",
            target_identifier="ai-fde-restore-20260904",
            target_designation=RESTORE_DESIGNATION,
        )
    with pytest.raises(RestoreDrillFailure, match="sslmode"):
        validate_restore_targets(
            source_database_url=SOURCE_URL,
            target_database_url=TARGET_URL.replace("verify-full", "require"),
            source_identifier="ai-fde-design-partner",
            target_identifier="ai-fde-restore-20260904",
            target_designation=RESTORE_DESIGNATION,
        )


def test_restore_snapshot_comparison_requires_exact_record_and_digest() -> None:
    snapshot = {
        "database_role": "ai_fde_app",
        "audit_event_id": "00000000-0000-4000-8000-000000000001",
        "audit_fingerprint": "sha256:" + "a" * 64,
        "digest_subject": {
            "type": "deployment-package",
            "id": "00000000-0000-4000-8000-000000000002",
            "stored_digest": "sha256:" + "b" * 64,
            "row_fingerprint": "sha256:" + "c" * 64,
        },
    }
    result = compare_restore_snapshots(
        snapshot,
        deepcopy(snapshot),
        expected_subject_digest="sha256:" + "b" * 64,
    )
    assert result["stored_digest"] == "sha256:" + "b" * 64

    changed = deepcopy(snapshot)
    assert isinstance(changed["digest_subject"], dict)
    changed["digest_subject"]["stored_digest"] = "sha256:" + "d" * 64
    with pytest.raises(RestoreDrillFailure, match="stored_digest"):
        compare_restore_snapshots(
            snapshot,
            changed,
            expected_subject_digest="sha256:" + "b" * 64,
        )

    with pytest.raises(RestoreDrillFailure, match="independently recorded"):
        compare_restore_snapshots(
            snapshot,
            deepcopy(snapshot),
            expected_subject_digest="sha256:" + "d" * 64,
        )


def test_database_url_file_must_be_private_and_single_line(tmp_path: Path) -> None:
    path = tmp_path / "source-url"
    path.write_text(SOURCE_URL, encoding="utf-8")
    path.chmod(0o600)
    assert _read_database_url(path, label="source") == SOURCE_URL

    path.chmod(0o640)
    with pytest.raises(RestoreDrillFailure, match="group or other"):
        _read_database_url(path, label="source")

    path.chmod(0o600)
    path.write_text(f"{SOURCE_URL}\n{TARGET_URL}", encoding="utf-8")
    with pytest.raises(RestoreDrillFailure, match="one value"):
        _read_database_url(path, label="source")
