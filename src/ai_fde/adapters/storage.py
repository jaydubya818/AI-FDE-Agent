from __future__ import annotations

from typing import Protocol

import boto3
from botocore.exceptions import ClientError

from ai_fde.config import Settings


class EvidenceStore(Protocol):
    def put(self, key: str, content: bytes, content_type: str) -> None: ...

    def get(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...


class S3EvidenceStore:
    def __init__(self, settings: Settings) -> None:
        self._bucket = settings.s3_bucket
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
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError as exc:
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            code = exc.response.get("Error", {}).get("Code")
            if status != 404 and code not in {"404", "NoSuchBucket", "NotFound"}:
                raise
            self._client.create_bucket(Bucket=self._bucket)

    def put(self, key: str, content: bytes, content_type: str) -> None:
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=content,
            ContentType=content_type,
        )

    def get(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        body: bytes = response["Body"].read()
        return body

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)


class InMemoryEvidenceStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, content: bytes, content_type: str) -> None:
        self.objects[key] = content

    def get(self, key: str) -> bytes:
        return self.objects[key]

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)
