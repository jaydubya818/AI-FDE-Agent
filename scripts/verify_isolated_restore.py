from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import re
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import boto3
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

try:
    from scripts.qualification_evidence import EvidenceRecordError, build_signed_evidence_record
except ModuleNotFoundError:  # Direct `python scripts/...` invocation.
    from qualification_evidence import (  # type: ignore[no-redef]
        EvidenceRecordError,
        build_signed_evidence_record,
    )

RESTORE_DESIGNATION = "ISOLATED-RESTORE-DRILL"
_TARGET_IDENTIFIER_PATTERN = re.compile(r"ai-fde-restore-[a-z0-9][a-z0-9-]{0,50}")
_RDS_ENDPOINT_PATTERN = re.compile(
    r"[a-z0-9-]+\.[a-z0-9-]+\.[a-z0-9-]+\.rds\.amazonaws\.com(?:\.cn)?"
)
_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_ARTIFACT_HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
_RECORD_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{7,119}")
_REVISION_PATTERN = re.compile(r"[0-9a-f]{40}")


class RestoreDrillFailure(RuntimeError):
    """Raised when the drill cannot prove a safe, isolated, exact restore."""


def validate_restore_targets(
    *,
    source_database_url: str,
    target_database_url: str,
    source_identifier: str,
    target_identifier: str,
    target_designation: str,
) -> tuple[URL, URL]:
    """Fail closed before making either database connection."""

    if target_designation != RESTORE_DESIGNATION:
        raise RestoreDrillFailure("The target is not explicitly designated for an isolated drill.")
    if _TARGET_IDENTIFIER_PATTERN.fullmatch(target_identifier) is None:
        raise RestoreDrillFailure(
            "The target identifier must use the dedicated ai-fde-restore-* naming boundary."
        )
    if source_identifier == target_identifier:
        raise RestoreDrillFailure("The source and target identifiers must differ.")
    if _RECORD_ID_PATTERN.fullmatch(source_identifier) is None:
        raise RestoreDrillFailure("The source identifier is not a bounded stable identifier.")

    source = _validated_postgres_url(source_database_url, label="source")
    target = _validated_postgres_url(target_database_url, label="target")
    source_host = source.host
    target_host = target.host
    if source_host is None or target_host is None:
        raise RestoreDrillFailure("The source and target must have explicit database hosts.")
    source_identity = (source_host.casefold(), source.port or 5432, source.database)
    target_identity = (target_host.casefold(), target.port or 5432, target.database)
    if source_identity == target_identity or source_host.casefold() == target_host.casefold():
        raise RestoreDrillFailure("The source and target must use different database hosts.")
    normalized_source_host = source_host.casefold()
    normalized_target_host = target_host.casefold()
    if _RDS_ENDPOINT_PATTERN.fullmatch(
        normalized_source_host
    ) is None or not normalized_source_host.startswith(f"{source_identifier}."):
        raise RestoreDrillFailure(
            "The source identifier is not bound to a direct AWS RDS instance endpoint."
        )
    if _RDS_ENDPOINT_PATTERN.fullmatch(
        normalized_target_host
    ) is None or not normalized_target_host.startswith(f"{target_identifier}."):
        raise RestoreDrillFailure(
            "The restore target identifier is not bound to a direct AWS RDS instance endpoint."
        )
    return source, target


def capture_restore_snapshot(
    database_url: URL,
    *,
    label: str,
    operator_id: uuid.UUID,
    engagement_id: uuid.UUID,
    audit_event_id: uuid.UUID,
    package_version_id: uuid.UUID | None,
    artifact_id: uuid.UUID | None,
) -> dict[str, object]:
    """Read the durable proof rows in a transaction that PostgreSQL enforces as read-only."""

    engine = create_engine(
        database_url,
        poolclass=NullPool,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 10},
    )
    try:
        with engine.connect() as connection, connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            database_role = _verify_application_role(connection)
            connection.execute(
                text("SELECT set_config('ai_fde.operator_id', :operator_id, true)"),
                {"operator_id": str(operator_id)},
            )
            _verify_rls_table(connection, "audit_events")
            audit = _one_row(
                connection,
                """
                SELECT id, engagement_id, actor_type, actor_id, action, target_type, target_id,
                       detail, correlation_id, created_at
                FROM audit_events
                WHERE id = :record_id AND engagement_id = :engagement_id
                """,
                audit_event_id,
                engagement_id,
                subject="known durable audit event",
            )
            if package_version_id is not None:
                _verify_rls_table(connection, "factory_deployment_package_versions")
                digest_subject = _package_snapshot(connection, package_version_id, engagement_id)
            else:
                _verify_rls_table(connection, "implementation_artifacts")
                digest_subject = _artifact_snapshot(connection, artifact_id, engagement_id)
    except (SQLAlchemyError, RestoreDrillFailure) as error:
        if isinstance(error, RestoreDrillFailure):
            raise
        raise RestoreDrillFailure(
            f"The {label} database could not produce a read-only restore snapshot."
        ) from None
    finally:
        engine.dispose()

    return {
        "database_role": database_role,
        "audit_event_id": str(audit_event_id),
        "audit_fingerprint": _fingerprint(audit),
        "digest_subject": digest_subject,
    }


def compare_restore_snapshots(
    source: Mapping[str, object],
    target: Mapping[str, object],
    *,
    expected_subject_digest: str,
) -> dict[str, object]:
    """Compare only identifiers and cryptographic fingerprints, never raw durable content."""

    if source.get("database_role") != "ai_fde_app" or target.get("database_role") != "ai_fde_app":
        raise RestoreDrillFailure(
            "The restore comparison did not use the application database role."
        )
    if _DIGEST_PATTERN.fullmatch(expected_subject_digest) is None:
        raise RestoreDrillFailure("The expected package or artifact digest is not valid sha256.")
    if source.get("audit_event_id") != target.get("audit_event_id"):
        raise RestoreDrillFailure("The known durable audit event identifier changed after restore.")
    if source.get("audit_fingerprint") != target.get("audit_fingerprint"):
        raise RestoreDrillFailure("The known durable audit event changed after restore.")
    source_subject = source.get("digest_subject")
    target_subject = target.get("digest_subject")
    if not isinstance(source_subject, dict) or not isinstance(target_subject, dict):
        raise RestoreDrillFailure("The package or artifact digest snapshot is incomplete.")
    for key in ("type", "id", "stored_digest", "row_fingerprint"):
        if source_subject.get(key) != target_subject.get(key):
            raise RestoreDrillFailure(f"The restored digest subject changed field {key}.")
    if source_subject.get("stored_digest") != expected_subject_digest:
        raise RestoreDrillFailure(
            "The source and restored digest do not match the independently recorded digest."
        )
    return {
        "database_role": "ai_fde_app",
        "audit_event_id": source["audit_event_id"],
        "audit_fingerprint": source["audit_fingerprint"],
        "digest_subject_type": source_subject["type"],
        "digest_subject_id": source_subject["id"],
        "stored_digest": source_subject["stored_digest"],
        "row_fingerprint": source_subject["row_fingerprint"],
    }


def _package_snapshot(
    connection: Connection, package_version_id: uuid.UUID, engagement_id: uuid.UUID
) -> dict[str, object]:
    row = _one_row(
        connection,
        """
        SELECT id, engagement_id, package_id, package_version, schema_version, status, issuer_id,
               issuer_type, issuer_environment, issuer_authority_scope,
               customer_factory_model_id, customer_factory_model_version, current_workflow_ref,
               target_workflow_ref, readiness_assessment_id, readiness_assessment_version,
               factory_opportunity_id, factory_opportunity_version, target, contract, digest,
               issued_at, approved_by_id, approval_binding, approved_at, published_at
        FROM factory_deployment_package_versions
        WHERE id = :record_id AND engagement_id = :engagement_id
        """,
        package_version_id,
        engagement_id,
        subject="published deployment package",
    )
    if row.get("status") != "PUBLISHED":
        raise RestoreDrillFailure("The known deployment package is not immutable and published.")
    digest = row.get("digest")
    if not isinstance(digest, str) or _DIGEST_PATTERN.fullmatch(digest) is None:
        raise RestoreDrillFailure("The known deployment package has no valid sha256 digest.")
    return {
        "type": "deployment-package",
        "id": str(package_version_id),
        "stored_digest": digest,
        "row_fingerprint": _fingerprint(row),
    }


def _artifact_snapshot(
    connection: Connection, artifact_id: uuid.UUID | None, engagement_id: uuid.UUID
) -> dict[str, object]:
    if artifact_id is None:
        raise RestoreDrillFailure("A package version or artifact identifier is required.")
    row = _one_row(
        connection,
        """
        SELECT id, engagement_id, artifact_type, packet_version, version_number, status, title,
               content, content_hash, source_current_workflow_id, source_target_workflow_id,
               economic_case_id, source_assertion_ids, generated_by_id, generated_at
        FROM implementation_artifacts
        WHERE id = :record_id AND engagement_id = :engagement_id
        """,
        artifact_id,
        engagement_id,
        subject="implementation artifact",
    )
    digest = row.get("content_hash")
    content = row.get("content")
    if not isinstance(digest, str) or _ARTIFACT_HASH_PATTERN.fullmatch(digest) is None:
        raise RestoreDrillFailure("The known implementation artifact has no valid content hash.")
    if not isinstance(content, str) or not _constant_digest_match(
        digest, hashlib.sha256(content.encode("utf-8")).hexdigest()
    ):
        raise RestoreDrillFailure("The implementation artifact content hash is invalid.")
    return {
        "type": "implementation-artifact",
        "id": str(artifact_id),
        "stored_digest": f"sha256:{digest}",
        "row_fingerprint": _fingerprint(row),
    }


def _one_row(
    connection: Connection,
    query: str,
    record_id: uuid.UUID,
    engagement_id: uuid.UUID,
    *,
    subject: str,
) -> dict[str, object]:
    rows = (
        connection.execute(
            text(query),
            {"record_id": str(record_id), "engagement_id": str(engagement_id)},
        )
        .mappings()
        .all()
    )
    if len(rows) != 1:
        raise RestoreDrillFailure(
            f"The {subject} was missing or not uniquely visible through the runtime role."
        )
    return dict(rows[0])


def _verify_application_role(connection: Connection) -> str:
    rows = (
        connection.execute(
            text(
                """
                SELECT rolname, rolsuper, rolbypassrls
                FROM pg_roles
                WHERE rolname = current_user
                """
            )
        )
        .mappings()
        .all()
    )
    if (
        len(rows) != 1
        or rows[0].get("rolname") != "ai_fde_app"
        or rows[0].get("rolsuper") is not False
        or rows[0].get("rolbypassrls") is not False
    ):
        raise RestoreDrillFailure(
            "Restore verification requires the non-superuser, non-bypass ai_fde_app role."
        )
    return "ai_fde_app"


def _verify_rls_table(connection: Connection, table_name: str) -> None:
    rows = (
        connection.execute(
            text(
                """
                SELECT class.relrowsecurity, pg_get_userbyid(class.relowner) AS owner
                FROM pg_class AS class
                JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace
                WHERE namespace.nspname = 'public' AND class.relname = :table_name
                """
            ),
            {"table_name": table_name},
        )
        .mappings()
        .all()
    )
    if (
        len(rows) != 1
        or rows[0].get("relrowsecurity") is not True
        or rows[0].get("owner") == "ai_fde_app"
    ):
        raise RestoreDrillFailure(f"RLS is not active for restored table {table_name}.")


def _validated_postgres_url(value: str, *, label: str) -> URL:
    try:
        url = make_url(value)
    except Exception:  # noqa: BLE001 - keep credentials out of failures
        raise RestoreDrillFailure(f"The {label} database URL is invalid.") from None
    if (
        url.get_backend_name() != "postgresql"
        or not url.host
        or not url.database
        or url.username != "ai_fde_app"
    ):
        raise RestoreDrillFailure(
            f"The {label} must be a named PostgreSQL database using the ai_fde_app role."
        )
    query = dict(url.query)
    if query.get("sslmode") != "verify-full":
        raise RestoreDrillFailure(f"The {label} database URL must enforce sslmode=verify-full.")
    return url


def _fingerprint(value: Mapping[str, object]) -> str:
    canonical = json.dumps(
        value,
        default=_json_default,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    raise TypeError(f"Unsupported durable value type: {type(value).__name__}.")


def _constant_digest_match(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)


def _read_database_url(path: Path, *, label: str) -> str:
    try:
        stat = path.lstat()
        if path.is_symlink() or not path.is_file():
            raise RestoreDrillFailure(f"The {label} database URL file must be a regular file.")
        if stat.st_mode & 0o077:
            raise RestoreDrillFailure(
                f"The {label} database URL file must not be readable by group or other users."
            )
        raw = path.read_bytes()
    except OSError as error:
        raise RestoreDrillFailure(f"The {label} database URL file is unreadable.") from error
    if not raw or len(raw) > 8192 or b"\x00" in raw:
        raise RestoreDrillFailure(f"The {label} database URL file is empty or oversized.")
    try:
        value = raw.decode("utf-8").strip()
    except UnicodeDecodeError as error:
        raise RestoreDrillFailure(f"The {label} database URL file is not UTF-8.") from error
    if "\n" in value or "\r" in value:
        raise RestoreDrillFailure(f"The {label} database URL file must contain one value.")
    return value


def _validate_evidence_identity(
    *, release_revision: str, deployment_id: str, record_id: str
) -> None:
    if _REVISION_PATTERN.fullmatch(release_revision) is None or release_revision == "0" * 40:
        raise RestoreDrillFailure(
            "The release revision must be a non-placeholder exact lowercase Git SHA."
        )
    for label, value in (("deployment ID", deployment_id), ("record ID", record_id)):
        if _RECORD_ID_PATTERN.fullmatch(value) is None:
            raise RestoreDrillFailure(f"The {label} is not a bounded stable identifier.")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only comparison of a production source and an isolated RDS restore."
    )
    parser.add_argument("--source-database-url-file", required=True, type=Path)
    parser.add_argument("--target-database-url-file", required=True, type=Path)
    parser.add_argument("--source-identifier", required=True)
    parser.add_argument("--target-identifier", required=True)
    parser.add_argument("--target-designation", required=True, choices=[RESTORE_DESIGNATION])
    parser.add_argument("--operator-id", required=True, type=uuid.UUID)
    parser.add_argument("--engagement-id", required=True, type=uuid.UUID)
    parser.add_argument("--audit-event-id", required=True, type=uuid.UUID)
    subject = parser.add_mutually_exclusive_group(required=True)
    subject.add_argument("--package-version-id", type=uuid.UUID)
    subject.add_argument("--artifact-id", type=uuid.UUID)
    parser.add_argument("--expected-subject-digest", required=True)
    parser.add_argument("--release-revision", required=True)
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument("--record-id", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--evidence-issuer-role-arn", required=True)
    parser.add_argument("--evidence-signing-key-arn", required=True)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main() -> None:
    args = _parser().parse_args()
    _validate_evidence_identity(
        release_revision=args.release_revision,
        deployment_id=args.deployment_id,
        record_id=args.record_id,
    )
    if _DIGEST_PATTERN.fullmatch(args.expected_subject_digest) is None:
        raise RestoreDrillFailure("The expected package or artifact digest is not valid sha256.")
    if args.output.exists() or args.output.is_symlink():
        raise RestoreDrillFailure("The restore evidence output already exists; refusing overwrite.")
    source_database_url = _read_database_url(args.source_database_url_file, label="source")
    target_database_url = _read_database_url(args.target_database_url_file, label="target")
    source_url, target_url = validate_restore_targets(
        source_database_url=source_database_url,
        target_database_url=target_database_url,
        source_identifier=args.source_identifier,
        target_identifier=args.target_identifier,
        target_designation=args.target_designation,
    )
    source = capture_restore_snapshot(
        source_url,
        label="source",
        operator_id=args.operator_id,
        engagement_id=args.engagement_id,
        audit_event_id=args.audit_event_id,
        package_version_id=args.package_version_id,
        artifact_id=args.artifact_id,
    )
    target = capture_restore_snapshot(
        target_url,
        label="restore target",
        operator_id=args.operator_id,
        engagement_id=args.engagement_id,
        audit_event_id=args.audit_event_id,
        package_version_id=args.package_version_id,
        artifact_id=args.artifact_id,
    )
    comparison = compare_restore_snapshots(
        source,
        target,
        expected_subject_digest=args.expected_subject_digest,
    )
    session = boto3.Session(region_name=args.region)
    principal_arn = str(session.client("sts").get_caller_identity()["Arn"])
    try:
        record = build_signed_evidence_record(
            record_id=args.record_id,
            evidence_type="isolated-restore-rehearsal",
            release_revision=args.release_revision,
            deployment_id=args.deployment_id,
            completed_at=datetime.now(UTC),
            results={
                "source_identifier": args.source_identifier,
                "target_identifier": args.target_identifier,
                **comparison,
                "source_target_isolated": True,
                "durable_record_matched": True,
                "digest_matched": True,
            },
            issuer_role_arn=args.evidence_issuer_role_arn,
            signing_key_arn=args.evidence_signing_key_arn,
            caller_principal_arn=principal_arn,
            kms_client=session.client("kms"),
        )
    except EvidenceRecordError as error:
        raise RestoreDrillFailure(
            f"The restore evidence could not be authenticated: {error}"
        ) from error
    try:
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(record, output, indent=2, sort_keys=True)
            output.write("\n")
    except FileExistsError as error:
        raise RestoreDrillFailure(
            "The restore evidence output already exists; refusing overwrite."
        ) from error
    print(json.dumps(record, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
