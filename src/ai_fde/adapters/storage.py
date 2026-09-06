from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

import boto3
from botocore.exceptions import ClientError

from ai_fde.config import Settings

MAX_EVIDENCE_PURGE_PAGES = 10_000


class EvidenceStoreWriteError(RuntimeError):
    """Object storage did not return the identity needed for safe compensation."""


class EvidenceObjectVersionNotFoundError(RuntimeError):
    """The immutable object version named by persisted evidence is unavailable."""


class EvidencePrefixPurgeError(RuntimeError):
    """An engagement evidence prefix could not be proven physically empty."""


class EvidenceStoreReadinessError(RuntimeError):
    """Object storage metadata does not match the configured deployment boundary."""


@dataclass(frozen=True)
class StoredObjectVersion:
    key: str
    version_id: str


@dataclass(frozen=True)
class EvidencePrefixPurgeReceipt:
    prefix: str
    object_versions_deleted: int
    delete_markers_deleted: int


class EvidenceStore(Protocol):
    def check_ready(self) -> None: ...

    def put(self, key: str, content: bytes, content_type: str) -> StoredObjectVersion: ...

    def get(self, key: str, *, version_id: str | None = None) -> bytes: ...

    def delete(self, key: str) -> None: ...

    def delete_version(self, version: StoredObjectVersion) -> None: ...

    def purge_engagement_evidence(
        self, engagement_id: uuid.UUID
    ) -> EvidencePrefixPurgeReceipt: ...


class S3EvidenceStore:
    def __init__(self, settings: Settings) -> None:
        self._bucket = settings.s3_bucket
        self._region = settings.s3_region
        self._kms_key_arn = settings.s3_kms_key_arn
        self._enable_development_versioning = settings.env == "development"
        client_options: dict[str, object] = {
            "endpoint_url": settings.s3_endpoint_url,
            "region_name": settings.s3_region,
        }
        if not settings.s3_use_workload_identity:
            client_options.update(
                aws_access_key_id=settings.s3_access_key,
                aws_secret_access_key=(
                    settings.s3_secret_key.get_secret_value()
                    if settings.s3_secret_key is not None
                    else None
                ),
            )
        self._client = boto3.client("s3", **client_options)

    def ensure_bucket(self) -> None:
        if not self._enable_development_versioning:
            return
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError as exc:
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            code = exc.response.get("Error", {}).get("Code")
            if status != 404 and code not in {"404", "NoSuchBucket", "NotFound"}:
                raise
            self._client.create_bucket(Bucket=self._bucket)
        self._client.put_bucket_versioning(
            Bucket=self._bucket,
            VersioningConfiguration={"Status": "Enabled"},
        )

    def check_ready(self) -> None:
        """Prove the configured bucket exists without reading customer objects."""

        response = self._client.get_bucket_location(Bucket=self._bucket)
        location = response.get("LocationConstraint")
        if location is None:
            actual_region = "us-east-1"
        elif location == "EU":
            actual_region = "eu-west-1"
        elif isinstance(location, str) and location:
            actual_region = location
        else:
            raise EvidenceStoreReadinessError(
                "The evidence bucket returned an invalid region boundary."
            )
        if actual_region != self._region:
            raise EvidenceStoreReadinessError(
                "The evidence bucket does not match the configured region boundary."
            )

    def put(self, key: str, content: bytes, content_type: str) -> StoredObjectVersion:
        put_options: dict[str, object] = {
            "Bucket": self._bucket,
            "Key": key,
            "Body": content,
            "ContentType": content_type,
        }
        if self._kms_key_arn is not None:
            put_options.update(
                ServerSideEncryption="aws:kms",
                SSEKMSKeyId=self._kms_key_arn,
            )
        response = self._client.put_object(**put_options)
        version_id = response.get("VersionId")
        if not isinstance(version_id, str) or not version_id or version_id == "null":
            raise EvidenceStoreWriteError(
                "The versioned evidence bucket did not return an object version identifier."
            )
        return StoredObjectVersion(key=key, version_id=version_id)

    def get(self, key: str, *, version_id: str | None = None) -> bytes:
        get_options: dict[str, object] = {"Bucket": self._bucket, "Key": key}
        if version_id is not None:
            if not version_id or version_id == "null":
                raise EvidenceObjectVersionNotFoundError(
                    "The persisted evidence object version is unavailable."
                )
            get_options["VersionId"] = version_id
        try:
            response = self._client.get_object(**get_options)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if version_id is not None and code in {
                "404",
                "NoSuchKey",
                "NoSuchVersion",
                "NotFound",
            }:
                raise EvidenceObjectVersionNotFoundError(
                    "The persisted evidence object version is unavailable."
                ) from None
            raise
        body: bytes = response["Body"].read()
        return body

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)

    def delete_version(self, version: StoredObjectVersion) -> None:
        self._client.delete_object(
            Bucket=self._bucket,
            Key=version.key,
            VersionId=version.version_id,
        )

    def purge_engagement_evidence(
        self, engagement_id: uuid.UUID
    ) -> EvidencePrefixPurgeReceipt:
        prefix = _engagement_evidence_prefix(engagement_id)
        key_marker: str | None = None
        version_id_marker: str | None = None
        seen_markers: set[tuple[str, str | None]] = set()
        seen_versions: set[tuple[str, str]] = set()
        object_versions_deleted = 0
        delete_markers_deleted = 0

        for _page_number in range(MAX_EVIDENCE_PURGE_PAGES):
            list_options: dict[str, object] = {
                "Bucket": self._bucket,
                "Prefix": prefix,
            }
            if key_marker is not None:
                list_options["KeyMarker"] = key_marker
            if version_id_marker is not None:
                list_options["VersionIdMarker"] = version_id_marker
            response = self._client.list_object_versions(**list_options)
            versions = _listed_object_versions(response, "Versions", prefix)
            delete_markers = _listed_object_versions(
                response,
                "DeleteMarkers",
                prefix,
            )
            for version in (*versions, *delete_markers):
                identity = (version.key, version.version_id)
                if identity in seen_versions:
                    raise EvidencePrefixPurgeError(
                        "Evidence prefix deletion returned a duplicate object identity."
                    )
                seen_versions.add(identity)
                self.delete_version(version)
            object_versions_deleted += len(versions)
            delete_markers_deleted += len(delete_markers)

            if not _listing_is_truncated(response):
                break
            next_key_marker = response.get("NextKeyMarker")
            next_version_id_marker = response.get("NextVersionIdMarker")
            if not isinstance(next_key_marker, str) or not next_key_marker.startswith(prefix):
                raise EvidencePrefixPurgeError(
                    "Evidence prefix deletion returned an invalid pagination boundary."
                )
            if next_version_id_marker is not None and not isinstance(
                next_version_id_marker, str
            ):
                raise EvidencePrefixPurgeError(
                    "Evidence prefix deletion returned an invalid pagination boundary."
                )
            next_marker = (next_key_marker, next_version_id_marker)
            if next_marker in seen_markers:
                raise EvidencePrefixPurgeError(
                    "Evidence prefix deletion repeated a pagination boundary."
                )
            seen_markers.add(next_marker)
            key_marker, version_id_marker = next_marker
        else:
            raise EvidencePrefixPurgeError(
                "Evidence prefix deletion exceeded its bounded page limit."
            )

        verification = self._client.list_object_versions(
            Bucket=self._bucket,
            Prefix=prefix,
        )
        if (
            _listed_object_versions(verification, "Versions", prefix)
            or _listed_object_versions(verification, "DeleteMarkers", prefix)
            or _listing_is_truncated(verification)
        ):
            raise EvidencePrefixPurgeError(
                "Evidence prefix deletion could not prove the prefix is empty."
            )
        return EvidencePrefixPurgeReceipt(
            prefix=prefix,
            object_versions_deleted=object_versions_deleted,
            delete_markers_deleted=delete_markers_deleted,
        )


class InMemoryEvidenceStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self._versions: dict[str, list[tuple[str, bytes | None]]] = {}

    def check_ready(self) -> None:
        return None

    def put(self, key: str, content: bytes, content_type: str) -> StoredObjectVersion:
        del content_type
        version_id = uuid.uuid4().hex
        self._versions.setdefault(key, []).append((version_id, content))
        self.objects[key] = content
        return StoredObjectVersion(key=key, version_id=version_id)

    def get(self, key: str, *, version_id: str | None = None) -> bytes:
        if version_id is None:
            return self.objects[key]
        for stored_version_id, content in self._versions.get(key, []):
            if stored_version_id == version_id:
                if content is not None:
                    return content
                break
        raise EvidenceObjectVersionNotFoundError(
            "The persisted evidence object version is unavailable."
        )

    def delete(self, key: str) -> None:
        marker_id = uuid.uuid4().hex
        self._versions.setdefault(key, []).append((marker_id, None))
        self.objects.pop(key, None)

    def delete_version(self, version: StoredObjectVersion) -> None:
        versions = self._versions.get(version.key)
        if versions is None:
            return
        remaining = [item for item in versions if item[0] != version.version_id]
        if len(remaining) == len(versions):
            return
        if remaining:
            self._versions[version.key] = remaining
            current = remaining[-1][1]
            if current is None:
                self.objects.pop(version.key, None)
            else:
                self.objects[version.key] = current
            return
        self._versions.pop(version.key, None)
        self.objects.pop(version.key, None)

    def purge_engagement_evidence(
        self, engagement_id: uuid.UUID
    ) -> EvidencePrefixPurgeReceipt:
        prefix = _engagement_evidence_prefix(engagement_id)
        keys = {
            key
            for key in set(self._versions) | set(self.objects)
            if key.startswith(prefix)
        }
        object_versions_deleted = sum(
            content is not None
            for key in keys
            for _version_id, content in self._versions.get(key, [])
        )
        delete_markers_deleted = sum(
            content is None
            for key in keys
            for _version_id, content in self._versions.get(key, [])
        )
        for key in keys:
            self._versions.pop(key, None)
            self.objects.pop(key, None)
        if any(
            key.startswith(prefix)
            for key in set(self._versions) | set(self.objects)
        ):
            raise EvidencePrefixPurgeError(
                "Evidence prefix deletion could not prove the prefix is empty."
            )
        return EvidencePrefixPurgeReceipt(
            prefix=prefix,
            object_versions_deleted=object_versions_deleted,
            delete_markers_deleted=delete_markers_deleted,
        )

    @property
    def stored_version_count(self) -> int:
        return sum(
            content is not None
            for versions in self._versions.values()
            for _version_id, content in versions
        )

    @property
    def delete_marker_count(self) -> int:
        return sum(
            content is None
            for versions in self._versions.values()
            for _version_id, content in versions
        )


def _engagement_evidence_prefix(engagement_id: uuid.UUID) -> str:
    if not isinstance(engagement_id, uuid.UUID):
        raise EvidencePrefixPurgeError(
            "Evidence prefix deletion requires one canonical engagement identifier."
        )
    return f"engagements/{engagement_id}/evidence/"


def _listed_object_versions(
    response: object,
    field: str,
    prefix: str,
) -> tuple[StoredObjectVersion, ...]:
    if not isinstance(response, dict):
        raise EvidencePrefixPurgeError(
            "Evidence prefix deletion returned an invalid object listing."
        )
    entries = response.get(field, [])
    if not isinstance(entries, list):
        raise EvidencePrefixPurgeError(
            "Evidence prefix deletion returned an invalid object listing."
        )
    versions: list[StoredObjectVersion] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise EvidencePrefixPurgeError(
                "Evidence prefix deletion returned an invalid object identity."
            )
        key = entry.get("Key")
        version_id = entry.get("VersionId")
        if (
            not isinstance(key, str)
            or not key.startswith(prefix)
            or not isinstance(version_id, str)
            or not version_id
        ):
            raise EvidencePrefixPurgeError(
                "Evidence prefix deletion returned an invalid object identity."
            )
        versions.append(StoredObjectVersion(key=key, version_id=version_id))
    return tuple(versions)


def _listing_is_truncated(response: object) -> bool:
    if not isinstance(response, dict):
        raise EvidencePrefixPurgeError(
            "Evidence prefix deletion returned an invalid object listing."
        )
    is_truncated = response.get("IsTruncated", False)
    if type(is_truncated) is not bool:
        raise EvidencePrefixPurgeError(
            "Evidence prefix deletion returned an invalid pagination state."
        )
    return is_truncated
