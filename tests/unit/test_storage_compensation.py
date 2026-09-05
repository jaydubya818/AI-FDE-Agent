from __future__ import annotations

from io import BytesIO
from typing import Any
from unittest.mock import MagicMock, call
from uuid import UUID

import boto3
import pytest
from botocore.exceptions import ClientError

from ai_fde.adapters.storage import (
    EvidenceObjectVersionNotFoundError,
    EvidencePrefixPurgeError,
    EvidenceStoreReadinessError,
    EvidenceStoreWriteError,
    InMemoryEvidenceStore,
    S3EvidenceStore,
)
from ai_fde.config import Settings

S3_KMS_KEY_ARN = (
    "arn:aws:kms:us-east-1:123456789012:key/11111111-2222-3333-4444-555555555555"
)


def _storage_settings(**overrides: object) -> Settings:
    """Build storage settings that do not inherit the CI job's integration bucket."""

    values: dict[str, object] = {
        "s3_bucket": "ai-fde-evidence",
        "s3_region": "us-east-1",
    }
    values.update(overrides)
    return Settings.model_validate(values)


def test_in_memory_compensation_deletes_only_the_written_version() -> None:
    store = InMemoryEvidenceStore()
    first = store.put("evidence/key", b"first", "text/plain")
    second = store.put("evidence/key", b"newer", "text/plain")

    store.delete_version(first)

    assert store.objects == {"evidence/key": b"newer"}
    assert store.stored_version_count == 1

    store.delete_version(second)

    assert store.objects == {}
    assert store.stored_version_count == 0


def test_in_memory_reads_the_exact_persisted_version() -> None:
    store = InMemoryEvidenceStore()
    first = store.put("evidence/key", b"first", "text/plain")
    store.put("evidence/key", b"newer", "text/plain")

    assert store.get("evidence/key", version_id=first.version_id) == b"first"
    assert store.get("evidence/key") == b"newer"


def test_development_bucket_is_versioned_before_evidence_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    monkeypatch.setattr(
        boto3,
        "client",
        lambda *_args, **_kwargs: client,
    )
    store = S3EvidenceStore(_storage_settings())

    store.ensure_bucket()

    client.put_bucket_versioning.assert_called_once_with(
        Bucket="ai-fde-evidence",
        VersioningConfiguration={"Status": "Enabled"},
    )


def test_non_development_startup_does_not_require_bucket_enumeration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    monkeypatch.setattr(boto3, "client", lambda *_args, **_kwargs: client)
    settings = _storage_settings().model_copy(update={"env": "production"})
    store = S3EvidenceStore(settings)

    store.ensure_bucket()

    assert client.mock_calls == []


@pytest.mark.parametrize(
    ("configured_region", "bucket_location"),
    [("us-east-1", None), ("eu-west-1", "EU"), ("us-west-2", "us-west-2")],
)
def test_storage_readiness_uses_non_enumerating_exact_region_metadata(
    monkeypatch: pytest.MonkeyPatch,
    configured_region: str,
    bucket_location: str | None,
) -> None:
    client = MagicMock()
    client.get_bucket_location.return_value = {
        "LocationConstraint": bucket_location,
    }
    monkeypatch.setattr(boto3, "client", lambda *_args, **_kwargs: client)
    settings = _storage_settings(s3_region=configured_region)
    store = S3EvidenceStore(settings)

    store.check_ready()

    client.get_bucket_location.assert_called_once_with(Bucket="ai-fde-evidence")
    client.head_bucket.assert_not_called()


def test_storage_readiness_rejects_a_different_bucket_region(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    client.get_bucket_location.return_value = {"LocationConstraint": "eu-west-1"}
    monkeypatch.setattr(boto3, "client", lambda *_args, **_kwargs: client)
    store = S3EvidenceStore(_storage_settings())

    with pytest.raises(EvidenceStoreReadinessError, match="region boundary"):
        store.check_ready()


def test_s3_compensation_uses_the_exact_put_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    client.put_object.return_value = {"VersionId": "version-written-by-this-request"}
    monkeypatch.setattr(
        boto3,
        "client",
        lambda *_args, **_kwargs: client,
    )
    store = S3EvidenceStore(_storage_settings(s3_kms_key_arn=S3_KMS_KEY_ARN))

    version = store.put("evidence/key", b"sensitive", "text/plain")
    store.delete_version(version)

    client.put_object.assert_called_once_with(
        Bucket="ai-fde-evidence",
        Key="evidence/key",
        Body=b"sensitive",
        ContentType="text/plain",
        ServerSideEncryption="aws:kms",
        SSEKMSKeyId=S3_KMS_KEY_ARN,
    )
    client.delete_object.assert_called_once_with(
        Bucket="ai-fde-evidence",
        Key="evidence/key",
        VersionId="version-written-by-this-request",
    )


def test_s3_read_uses_the_exact_persisted_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    client.get_object.return_value = {"Body": BytesIO(b"immutable evidence")}
    monkeypatch.setattr(
        boto3,
        "client",
        lambda *_args, **_kwargs: client,
    )
    store = S3EvidenceStore(_storage_settings())

    assert (
        store.get("evidence/key", version_id="persisted-version")
        == b"immutable evidence"
    )
    client.get_object.assert_called_once_with(
        Bucket="ai-fde-evidence",
        Key="evidence/key",
        VersionId="persisted-version",
    )


def test_in_memory_missing_persisted_version_fails_closed() -> None:
    store = InMemoryEvidenceStore()
    store.put("evidence/key", b"current", "text/plain")

    with pytest.raises(EvidenceObjectVersionNotFoundError, match="unavailable"):
        store.get("evidence/key", version_id="missing-version")


def test_in_memory_delete_marker_preserves_version_until_physical_prefix_purge() -> None:
    engagement_id = UUID("00000000-0000-4000-8000-000000000001")
    prefix = f"engagements/{engagement_id}/evidence/"
    store = InMemoryEvidenceStore()
    pinned = store.put(f"{prefix}known.md", b"known", "text/markdown")
    store.put(f"{prefix}untracked.md", b"untracked", "text/markdown")
    store.delete(pinned.key)

    assert pinned.key not in store.objects
    assert store.get(pinned.key, version_id=pinned.version_id) == b"known"
    assert store.stored_version_count == 2
    assert store.delete_marker_count == 1

    receipt = store.purge_engagement_evidence(engagement_id)

    assert receipt.object_versions_deleted == 2
    assert receipt.delete_markers_deleted == 1
    assert not any(key.startswith(prefix) for key in store.objects)
    assert store.stored_version_count == 0
    assert store.delete_marker_count == 0
    with pytest.raises(EvidenceObjectVersionNotFoundError, match="unavailable"):
        store.get(pinned.key, version_id=pinned.version_id)


def test_s3_physical_prefix_purge_paginates_versions_and_delete_markers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engagement_id = UUID("00000000-0000-4000-8000-000000000002")
    prefix = f"engagements/{engagement_id}/evidence/"
    client = MagicMock()
    client.list_object_versions.side_effect = [
        {
            "Versions": [
                {"Key": f"{prefix}known.md", "VersionId": "known-version"},
                {"Key": f"{prefix}untracked.md", "VersionId": "untracked-version"},
                {"Key": f"{prefix}pre-versioning.md", "VersionId": "null"},
            ],
            "DeleteMarkers": [
                {"Key": f"{prefix}known.md", "VersionId": "delete-marker"}
            ],
            "IsTruncated": True,
            "NextKeyMarker": f"{prefix}untracked.md",
            "NextVersionIdMarker": "untracked-version",
        },
        {
            "Versions": [
                {"Key": f"{prefix}older.md", "VersionId": "older-version"}
            ],
            "DeleteMarkers": [],
            "IsTruncated": False,
        },
        {"Versions": [], "DeleteMarkers": [], "IsTruncated": False},
    ]
    monkeypatch.setattr(boto3, "client", lambda *_args, **_kwargs: client)
    store = S3EvidenceStore(_storage_settings())

    receipt = store.purge_engagement_evidence(engagement_id)

    assert receipt.object_versions_deleted == 4
    assert receipt.delete_markers_deleted == 1
    assert client.list_object_versions.call_args_list == [
        call(Bucket="ai-fde-evidence", Prefix=prefix),
        call(
            Bucket="ai-fde-evidence",
            Prefix=prefix,
            KeyMarker=f"{prefix}untracked.md",
            VersionIdMarker="untracked-version",
        ),
        call(Bucket="ai-fde-evidence", Prefix=prefix),
    ]
    assert client.delete_object.call_args_list == [
        call(
            Bucket="ai-fde-evidence",
            Key=f"{prefix}known.md",
            VersionId="known-version",
        ),
        call(
            Bucket="ai-fde-evidence",
            Key=f"{prefix}untracked.md",
            VersionId="untracked-version",
        ),
        call(
            Bucket="ai-fde-evidence",
            Key=f"{prefix}pre-versioning.md",
            VersionId="null",
        ),
        call(
            Bucket="ai-fde-evidence",
            Key=f"{prefix}known.md",
            VersionId="delete-marker",
        ),
        call(
            Bucket="ai-fde-evidence",
            Key=f"{prefix}older.md",
            VersionId="older-version",
        ),
    ]
    client.get_object.side_effect = ClientError(
        {"Error": {"Code": "NoSuchVersion", "Message": "not found"}},
        "GetObject",
    )
    with pytest.raises(EvidenceObjectVersionNotFoundError, match="unavailable"):
        store.get(f"{prefix}known.md", version_id="known-version")


def test_s3_physical_prefix_purge_fails_on_partial_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engagement_id = UUID("00000000-0000-4000-8000-000000000003")
    prefix = f"engagements/{engagement_id}/evidence/"
    client = MagicMock()
    client.list_object_versions.return_value = {
        "Versions": [
            {"Key": f"{prefix}first.md", "VersionId": "first-version"},
            {"Key": f"{prefix}second.md", "VersionId": "second-version"},
        ],
        "DeleteMarkers": [],
        "IsTruncated": False,
    }
    denied = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "denied"}},
        "DeleteObject",
    )
    client.delete_object.side_effect = [None, denied]
    monkeypatch.setattr(boto3, "client", lambda *_args, **_kwargs: client)
    store = S3EvidenceStore(_storage_settings())

    with pytest.raises(ClientError) as caught:
        store.purge_engagement_evidence(engagement_id)

    assert caught.value.response["Error"]["Code"] == "AccessDenied"
    assert client.delete_object.call_count == 2
    assert client.list_object_versions.call_count == 1


def test_s3_physical_prefix_purge_fails_if_a_version_survives_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engagement_id = UUID("00000000-0000-4000-8000-000000000004")
    prefix = f"engagements/{engagement_id}/evidence/"
    client = MagicMock()
    client.list_object_versions.side_effect = [
        {"Versions": [], "DeleteMarkers": [], "IsTruncated": False},
        {
            "Versions": [
                {"Key": f"{prefix}late-untracked.md", "VersionId": "late-version"}
            ],
            "DeleteMarkers": [],
            "IsTruncated": False,
        },
    ]
    monkeypatch.setattr(boto3, "client", lambda *_args, **_kwargs: client)
    store = S3EvidenceStore(_storage_settings())

    with pytest.raises(EvidencePrefixPurgeError, match="prove the prefix is empty"):
        store.purge_engagement_evidence(engagement_id)

    client.delete_object.assert_not_called()


def test_s3_physical_prefix_purge_never_deletes_an_out_of_scope_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engagement_id = UUID("00000000-0000-4000-8000-000000000005")
    client = MagicMock()
    client.list_object_versions.return_value = {
        "Versions": [
            {
                "Key": (
                    "engagements/00000000-0000-4000-8000-000000000006/"
                    "evidence/other.md"
                ),
                "VersionId": "other-engagement-version",
            }
        ],
        "DeleteMarkers": [],
        "IsTruncated": False,
    }
    monkeypatch.setattr(boto3, "client", lambda *_args, **_kwargs: client)
    store = S3EvidenceStore(_storage_settings())

    with pytest.raises(EvidencePrefixPurgeError, match="invalid object identity"):
        store.purge_engagement_evidence(engagement_id)

    client.delete_object.assert_not_called()


def test_s3_missing_persisted_version_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    client.get_object.side_effect = ClientError(
        {"Error": {"Code": "NoSuchVersion", "Message": "not found"}},
        "GetObject",
    )
    monkeypatch.setattr(
        boto3,
        "client",
        lambda *_args, **_kwargs: client,
    )
    store = S3EvidenceStore(_storage_settings())

    with pytest.raises(EvidenceObjectVersionNotFoundError, match="unavailable"):
        store.get("evidence/key", version_id="missing-version")


@pytest.mark.parametrize("response", [{}, {"VersionId": ""}, {"VersionId": "null"}])
def test_s3_put_fails_closed_without_a_compensatable_version(
    monkeypatch: pytest.MonkeyPatch,
    response: dict[str, Any],
) -> None:
    client = MagicMock()
    client.put_object.return_value = response
    monkeypatch.setattr(
        boto3,
        "client",
        lambda *_args, **_kwargs: client,
    )
    store = S3EvidenceStore(_storage_settings())

    with pytest.raises(EvidenceStoreWriteError, match="version identifier"):
        store.put("evidence/key", b"sensitive", "text/plain")
