from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from threading import Event, Thread
from typing import Literal, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import create_engine, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

import ai_fde.modules.design_partner.service as design_partner_service
from ai_fde.adapters.storage import (
    EvidencePrefixPurgeReceipt,
    EvidenceStore,
    InMemoryEvidenceStore,
    StoredObjectVersion,
)
from ai_fde.api.dependencies import AuthenticatedPrincipal, get_principal
from ai_fde.api.routes import router
from ai_fde.config import BedrockDataClassification, get_settings
from ai_fde.db import operator_session
from ai_fde.models import (
    AuditEvent,
    CandidateClaim,
    Engagement,
    EvidenceAsset,
    EvidenceSegment,
    ExtractionRun,
    Job,
    Operator,
)
from ai_fde.modules.data_lifecycle.service import DataLifecycleError, set_retention_deadline
from ai_fde.modules.design_partner.models import (
    CustomerDataAccessEvent,
    DesignPartnerQualification,
)
from ai_fde.modules.design_partner.service import (
    CustomerDataProcessingDeniedError,
    authorize_qualified_document_upload,
    provision_design_partner_qualification,
    require_package_publication_eligibility,
    require_qualified_evidence_processing,
    transition_design_partner_qualification,
)
from ai_fde.modules.engagements.service import create_engagement
from ai_fde.modules.knowledge.extractor import ExtractionResult
from ai_fde.modules.knowledge.jobs import (
    EvidenceIntegrityError,
    fail_job,
    lease_next_job,
    process_job,
)
from ai_fde.worker import public_job_failure
from tests.conftest import OperatorFixture

SOURCE_KEY = "approved-manual-document"
REPOSITORY_REF = "github.com/sellerfi/marketplace"
WORKFLOW_CLASS = "software-change/verified-pr/v1"
AUTHORIZATION_BASIS = "qualification-record:sellerfi-phase-3"


class TrackingEvidenceStore:
    def __init__(self) -> None:
        self._store = InMemoryEvidenceStore()
        self.objects = self._store.objects
        self.get_calls = 0
        self.requested_version_ids: list[str | None] = []
        self.read_override: bytes | None = None

    def check_ready(self) -> None:
        return None

    def put(
        self,
        key: str,
        content: bytes,
        content_type: str,
    ) -> StoredObjectVersion:
        return self._store.put(key, content, content_type)

    def get(self, key: str, *, version_id: str | None = None) -> bytes:
        self.get_calls += 1
        self.requested_version_ids.append(version_id)
        if self.read_override is not None:
            return self.read_override
        return self._store.get(key, version_id=version_id)

    def delete(self, key: str) -> None:
        self._store.delete(key)

    def delete_version(self, version: StoredObjectVersion) -> None:
        self._store.delete_version(version)

    def purge_engagement_evidence(
        self, engagement_id: uuid.UUID
    ) -> EvidencePrefixPurgeReceipt:
        return self._store.purge_engagement_evidence(engagement_id)


@dataclass
class QualifiedRouteSettings:
    bedrock_allowed_data_classifications: list[BedrockDataClassification]
    deployment_expires_at: datetime | None = None
    extraction_provider: Literal["bedrock"] = "bedrock"
    deployment_decision_times: list[datetime] = field(default_factory=list)

    def verified_deployment_qualification(self, *, now: datetime | None = None) -> object:
        if now is None:
            raise AssertionError("Upload reauthorization must supply its decision time.")
        self.deployment_decision_times.append(now)
        if self.deployment_expires_at is not None and now >= self.deployment_expires_at:
            raise ValueError("The deployment qualification record has expired.")
        return object()


@dataclass
class NoCallBedrockExtractor:
    name: str = "amazon-bedrock-converse"
    version: str = "1.0.0-test"
    schema_version: str = "claim-v1"
    prompt_version: str = "qualified-recheck-test"
    model_id: str | None = "qualified-model"
    max_output_tokens: int = 512
    calls: int = 0

    def extract(
        self,
        text: str,
        *,
        image_bytes: bytes | None = None,
        image_format: Literal["png", "jpeg"] | None = None,
        max_output_tokens: int | None = None,
    ) -> ExtractionResult:
        del text, image_bytes, image_format, max_output_tokens
        self.calls += 1
        return ExtractionResult(
            claims=[],
            provider_name=self.name,
            model_id=self.model_id,
            prompt_version=self.prompt_version,
            schema_version=self.schema_version,
        )


@dataclass
class BlockingBedrockExtractor:
    entered: Event
    release: Event
    after_first_call: Callable[[], None] | None = None
    name: str = "amazon-bedrock-converse"
    version: str = "1.0.0-test"
    schema_version: str = "claim-v1"
    prompt_version: str = "qualified-mid-job-recheck-test"
    model_id: str | None = "qualified-model"
    max_output_tokens: int = 512
    calls: int = 0

    def extract(
        self,
        text: str,
        *,
        image_bytes: bytes | None = None,
        image_format: Literal["png", "jpeg"] | None = None,
        max_output_tokens: int | None = None,
    ) -> ExtractionResult:
        del text, image_bytes, image_format, max_output_tokens
        self.calls += 1
        if self.calls == 1:
            self.entered.set()
            if not self.release.wait(timeout=5):
                raise TimeoutError("The mid-job authority test did not finish.")
            if self.after_first_call is not None:
                self.after_first_call()
        return ExtractionResult(
            claims=[],
            provider_name=self.name,
            model_id=self.model_id,
            prompt_version=self.prompt_version,
            schema_version=self.schema_version,
        )


def _settings(
    *allowed: BedrockDataClassification,
    deployment_expires_at: datetime | None = None,
) -> QualifiedRouteSettings:
    return QualifiedRouteSettings(
        bedrock_allowed_data_classifications=list(allowed),
        deployment_expires_at=deployment_expires_at,
    )


def _app(
    operator: OperatorFixture,
    store: EvidenceStore,
    settings: QualifiedRouteSettings,
) -> FastAPI:
    app = FastAPI()
    app.state.evidence_store = store
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_principal] = lambda: AuthenticatedPrincipal(
        operator_id=operator.id,
        auth_mode="oidc",
        sanitized_data_allowed=True,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    return app


def _create_sanitized_engagement(operator: OperatorFixture, label: str) -> uuid.UUID:
    with operator_session(operator.id) as session:
        engagement = create_engagement(
            session,
            operator=session.get_one(Operator, operator.id),
            name=f"{label} {uuid.uuid4()}",
            workflow_name="Qualified document analysis",
            primary_outcome="Prove one bounded design-partner customer-data path.",
            data_classification="sanitized",
        )
        return engagement.id


def _provision_and_qualify(
    engagement_id: uuid.UUID,
    owner_operator_id: uuid.UUID,
    *,
    data_classification: str = "CONFIDENTIAL",
    retention_days: int = 30,
    now: datetime | None = None,
) -> None:
    engine = create_engine(get_settings().migration_database_url)
    try:
        with Session(engine) as session, session.begin():
            provision_design_partner_qualification(
                session,
                engagement_id=engagement_id,
                partner_key=f"partner-{engagement_id.hex}",
                organization="SellerFi Design Partner",
                authorized_data_source_keys=[SOURCE_KEY],
                authorized_repository_refs=[REPOSITORY_REF],
                allowed_workflow_classes=[WORKFLOW_CLASS],
                data_classification=data_classification,
                retention_days=retention_days,
                authorization_basis_ref=AUTHORIZATION_BASIS,
                configured_by_id=owner_operator_id,
                now=now,
            )
            transition_design_partner_qualification(
                session,
                engagement_id=engagement_id,
                qualification_state="IN_PROGRESS",
                authorization_basis_ref=AUTHORIZATION_BASIS,
                actor_id=owner_operator_id,
                now=now,
            )
            transition_design_partner_qualification(
                session,
                engagement_id=engagement_id,
                qualification_state="QUALIFIED",
                authorization_basis_ref=AUTHORIZATION_BASIS,
                actor_id=owner_operator_id,
                now=now,
            )
    finally:
        engine.dispose()


def _transition(
    engagement_id: uuid.UUID,
    owner_operator_id: uuid.UUID,
    *,
    status: str | None = None,
    qualification_state: str | None = None,
) -> None:
    engine = create_engine(get_settings().migration_database_url)
    try:
        with Session(engine) as session, session.begin():
            transition_design_partner_qualification(
                session,
                engagement_id=engagement_id,
                status=status,
                qualification_state=qualification_state,
                authorization_basis_ref=AUTHORIZATION_BASIS,
                actor_id=owner_operator_id,
            )
    finally:
        engine.dispose()


def _upload(
    client: TestClient,
    engagement_id: uuid.UUID,
    *,
    file_name: str = "bounded.md",
    source_key: str = SOURCE_KEY,
    workflow_class: str = WORKFLOW_CLASS,
    data_classification: str = "CONFIDENTIAL",
    content_type: str = "text/markdown",
    content: bytes = b"Bounded customer context: approvals require two reviewers.",
) -> Response:
    return cast(
        Response,
        client.post(
            f"/api/engagements/{engagement_id}/evidence",
            data={
                "source_key": source_key,
                "workflow_class": workflow_class,
                "data_classification": data_classification,
            },
            files={"file": (file_name, content, content_type)},
            headers={"X-Correlation-ID": "30000000-0000-4000-8000-000000000003"},
        ),
    )


@pytest.mark.integration
@pytest.mark.isolation
def test_qualified_manual_document_upload_is_bounded_and_attributable(
    postgres_available: None,
    test_operator: OperatorFixture,
) -> None:
    engagement_id = _create_sanitized_engagement(test_operator, "Qualified partner")
    _provision_and_qualify(engagement_id, test_operator.id)
    store = InMemoryEvidenceStore()

    with TestClient(_app(test_operator, store, _settings("CONFIDENTIAL"))) as client:
        qualification = client.get(f"/api/engagements/{engagement_id}/design-partner-qualification")
        assert qualification.status_code == 200
        assert qualification.json()["qualification_state"] == "QUALIFIED"
        assert qualification.json()["authorized_users"] == [
            {
                "operator_id": str(test_operator.id),
                "display_name": test_operator.display_name,
                "role": "owner",
            }
        ]

        response = _upload(client, engagement_id)
        binary_disguised_as_text = _upload(
            client,
            engagement_id,
            content=b"\xff\xfe\x00\x01",
        )

    assert response.status_code == 202
    assert binary_disguised_as_text.status_code == 422
    assert response.headers["x-correlation-id"] == ("30000000-0000-4000-8000-000000000003")
    body = response.json()
    assert body["authorized_source_key"] == SOURCE_KEY
    assert body["authorized_workflow_class"] == WORKFLOW_CLASS
    assert body["data_classification"] == "CONFIDENTIAL"
    with operator_session(test_operator.id) as session:
        asset = session.scalar(
            select(EvidenceAsset).where(EvidenceAsset.engagement_id == engagement_id)
        )
        event = session.scalar(
            select(CustomerDataAccessEvent).where(
                CustomerDataAccessEvent.engagement_id == engagement_id,
                CustomerDataAccessEvent.outcome == "AUTHORIZED",
            )
        )
        rejected_event = session.scalar(
            select(CustomerDataAccessEvent).where(
                CustomerDataAccessEvent.engagement_id == engagement_id,
                CustomerDataAccessEvent.decision_code == "EVIDENCE_VALIDATION_FAILED",
            )
        )
        assert asset is not None
        assert event is not None
        assert asset.storage_version_id is not None
        assert asset.design_partner_qualification_id == event.qualification_id
        assert asset.authorized_source_key == SOURCE_KEY
        assert asset.authorized_workflow_class == WORKFLOW_CLASS
        assert asset.data_classification == "CONFIDENTIAL"
        assert event.outcome == "AUTHORIZED"
        assert event.decision_code == "AUTHORIZED"
        assert event.operator_id == test_operator.id
        assert event.source_key == SOURCE_KEY
        assert event.workflow_class == WORKFLOW_CLASS
        assert event.data_classification == "CONFIDENTIAL"
        assert event.authorization_basis_ref == AUTHORIZATION_BASIS
        assert event.evidence_asset_id == asset.id
        assert rejected_event is not None
        assert rejected_event.outcome == "DENIED"
        assert rejected_event.evidence_asset_id is None
        serialized_event = " ".join(str(value) for value in vars(event).values())
        assert "approvals require two reviewers" not in serialized_event


@pytest.mark.integration
@pytest.mark.isolation
def test_qualified_upload_rejects_path_and_control_character_file_names(
    postgres_available: None,
    test_operator: OperatorFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engagement_id = _create_sanitized_engagement(test_operator, "Unsafe upload names")
    _provision_and_qualify(engagement_id, test_operator.id)
    store = InMemoryEvidenceStore()
    unsafe_names = (
        "../../evil.md",
        "..\\..\\evil.md",
        "folder/subdirectory\\evil.md",
        "control\x01character.md",
    )

    async def fail_if_sensitive_body_is_read(_upload: object) -> bytes:
        raise AssertionError("Unsafe file metadata must fail before reading the body.")

    monkeypatch.setattr(
        "ai_fde.api.routes.read_evidence_upload",
        fail_if_sensitive_body_is_read,
    )

    with TestClient(_app(test_operator, store, _settings("CONFIDENTIAL"))) as client:
        responses = [
            _upload(client, engagement_id, file_name=file_name)
            for file_name in unsafe_names
        ]

    assert [response.status_code for response in responses] == [422, 422, 422, 422]
    assert all(
        response.json()["detail"] == "Evidence needs one safe file basename."
        for response in responses
    )
    assert store.objects == {}
    assert store.stored_version_count == 0
    with operator_session(test_operator.id) as session:
        assert list(
            session.scalars(
                select(EvidenceAsset).where(EvidenceAsset.engagement_id == engagement_id)
            )
        ) == []


@pytest.mark.integration
@pytest.mark.isolation
def test_customer_data_gate_denies_unqualified_scope_provider_and_inactive_partner(
    postgres_available: None,
    test_operator: OperatorFixture,
) -> None:
    unqualified_id = _create_sanitized_engagement(test_operator, "Unqualified partner")
    store = InMemoryEvidenceStore()
    untrusted_source = "sk_live_do_not_persist_12345"
    untrusted_workflow = "private-token-value/workflow"
    untrusted_content = b"customer-secret-that-must-not-enter-audit"
    with TestClient(_app(test_operator, store, _settings("CONFIDENTIAL"))) as client:
        missing = _upload(
            client,
            unqualified_id,
            source_key=untrusted_source,
            workflow_class=untrusted_workflow,
            content=untrusted_content,
        )
        assert missing.status_code == 403
        assert missing.json()["code"] == "QUALIFICATION_REQUIRED"

    with operator_session(test_operator.id) as session:
        denial = session.scalar(
            select(AuditEvent).where(
                AuditEvent.engagement_id == unqualified_id,
                AuditEvent.action == "customer_data.access_denied",
            )
        )
        assert denial is not None
        assert denial.actor_id == test_operator.id
        assert denial.detail == {
            "operation": "MANUAL_DOCUMENT_UPLOAD",
            "decision_code": "QUALIFICATION_REQUIRED",
            "source_key": "unqualified-source",
            "workflow_class": "unqualified-workflow",
            "data_classification": "CONFIDENTIAL",
            "authorization_basis_ref": "none",
            "qualification_present": False,
        }
        serialized_denial = str(vars(denial))
        assert untrusted_source not in serialized_denial
        assert untrusted_workflow not in serialized_denial
        assert untrusted_content.decode() not in serialized_denial

    engagement_id = _create_sanitized_engagement(test_operator, "Scoped partner")
    _provision_and_qualify(engagement_id, test_operator.id)
    with TestClient(_app(test_operator, store, _settings("PUBLIC"))) as client:
        missing_context = client.post(
            f"/api/engagements/{engagement_id}/evidence",
            files={"file": ("bounded.md", b"Missing qualification context.", "text/markdown")},
        )
        assert missing_context.status_code == 403
        assert missing_context.json()["code"] == "QUALIFICATION_CONTEXT_REQUIRED"

        wrong_source = _upload(client, engagement_id, source_key=untrusted_source)
        assert wrong_source.status_code == 403
        assert wrong_source.json()["code"] == "SOURCE_NOT_AUTHORIZED"

        wrong_workflow = _upload(
            client,
            engagement_id,
            workflow_class=untrusted_workflow,
        )
        assert wrong_workflow.status_code == 403
        assert wrong_workflow.json()["code"] == "WORKFLOW_NOT_AUTHORIZED"

        provider_denied = _upload(client, engagement_id)
        assert provider_denied.status_code == 403
        assert provider_denied.json()["code"] == "PROVIDER_CLASSIFICATION_DENIED"

        unsupported = _upload(client, engagement_id, content_type="application/pdf")
        assert unsupported.status_code == 403
        assert unsupported.json()["code"] == "UNSUPPORTED_QUALIFIED_MEDIA_TYPE"

        note = client.post(
            f"/api/engagements/{engagement_id}/notes",
            json={
                "title": "Side door",
                "content": "Customer content must not bypass qualification metadata.",
            },
        )
        assert note.status_code == 403

    _transition(engagement_id, test_operator.id, status="SUSPENDED")
    with TestClient(_app(test_operator, store, _settings("CONFIDENTIAL"))) as client:
        suspended = _upload(client, engagement_id)
        assert suspended.status_code == 403
        assert suspended.json()["code"] == "QUALIFICATION_INACTIVE"
    _transition(engagement_id, test_operator.id, status="REVOKED")
    with TestClient(_app(test_operator, store, _settings("CONFIDENTIAL"))) as client:
        revoked = _upload(client, engagement_id)
        assert revoked.status_code == 403
        assert revoked.json()["code"] == "QUALIFICATION_INACTIVE"

    with operator_session(test_operator.id) as session:
        events = list(
            session.scalars(
                select(CustomerDataAccessEvent)
                .where(CustomerDataAccessEvent.engagement_id == engagement_id)
                .order_by(CustomerDataAccessEvent.created_at)
            )
        )
        assert [event.decision_code for event in events] == [
            "QUALIFICATION_CONTEXT_REQUIRED",
            "SOURCE_NOT_AUTHORIZED",
            "WORKFLOW_NOT_AUTHORIZED",
            "PROVIDER_CLASSIFICATION_DENIED",
            "UNSUPPORTED_QUALIFIED_MEDIA_TYPE",
            "QUALIFICATION_INACTIVE",
            "QUALIFICATION_INACTIVE",
        ]
        serialized_events = " ".join(
            str(value) for event in events for value in vars(event).values()
        )
        assert untrusted_source not in serialized_events
        assert untrusted_workflow not in serialized_events


@pytest.mark.integration
@pytest.mark.isolation
def test_restricted_and_expired_customer_data_fail_closed(
    postgres_available: None,
    test_operator: OperatorFixture,
) -> None:
    restricted_id = _create_sanitized_engagement(test_operator, "Restricted partner")
    _provision_and_qualify(
        restricted_id,
        test_operator.id,
        data_classification="RESTRICTED",
    )
    store = InMemoryEvidenceStore()
    with TestClient(_app(test_operator, store, _settings("CONFIDENTIAL"))) as client:
        denied = _upload(client, restricted_id, data_classification="RESTRICTED")
        assert denied.status_code == 403
        assert denied.json()["code"] == "PROVIDER_CLASSIFICATION_DENIED"

    with operator_session(test_operator.id) as session:
        engagement = session.get_one(Engagement, restricted_id)
        operator = session.get_one(Operator, test_operator.id)
        expired = authorize_qualified_document_upload(
            session,
            engagement=engagement,
            operator=operator,
            source_key=SOURCE_KEY,
            workflow_class=WORKFLOW_CLASS,
            data_classification="RESTRICTED",
            content_type="text/plain",
            extraction_provider="bedrock",
            provider_allowed_classifications={"PUBLIC", "INTERNAL", "CONFIDENTIAL"},
            now=datetime.now(UTC) + timedelta(days=31),
        )
        # Classification remains the earlier fail-closed reason for a restricted qualification.
        assert expired.decision_code == "PROVIDER_CLASSIFICATION_DENIED"

    expiring_id = _create_sanitized_engagement(test_operator, "Expired partner")
    _provision_and_qualify(
        expiring_id,
        test_operator.id,
        data_classification="CONFIDENTIAL",
    )
    with operator_session(test_operator.id) as session:
        engagement = session.get_one(Engagement, expiring_id)
        operator = session.get_one(Operator, test_operator.id)
        expired = authorize_qualified_document_upload(
            session,
            engagement=engagement,
            operator=operator,
            source_key=SOURCE_KEY,
            workflow_class=WORKFLOW_CLASS,
            data_classification="CONFIDENTIAL",
            content_type="text/plain",
            extraction_provider="bedrock",
            provider_allowed_classifications={"CONFIDENTIAL"},
            now=datetime.now(UTC) + timedelta(days=31),
        )
        assert expired.allowed is False
        assert expired.decision_code == "RETENTION_EXPIRED"


@pytest.mark.integration
@pytest.mark.isolation
def test_design_partner_retention_ceiling_is_immutable_and_db_gates_refresh_stale_state(
    postgres_available: None,
    test_operator: OperatorFixture,
) -> None:
    timestamp = datetime.now(UTC)
    engagement_id = _create_sanitized_engagement(test_operator, "Retention ceiling")
    _provision_and_qualify(
        engagement_id,
        test_operator.id,
        retention_days=30,
        now=timestamp,
    )
    store = InMemoryEvidenceStore()
    with TestClient(_app(test_operator, store, _settings("CONFIDENTIAL"))) as client:
        uploaded = _upload(client, engagement_id)
    assert uploaded.status_code == 202

    with operator_session(test_operator.id) as session:
        engagement = session.get_one(Engagement, engagement_id)
        qualification = session.scalar(
            select(DesignPartnerQualification).where(
                DesignPartnerQualification.engagement_id == engagement_id
            )
        )
        asset = session.scalar(
            select(EvidenceAsset).where(EvidenceAsset.engagement_id == engagement_id)
        )
        assert qualification is not None
        assert asset is not None
        assert qualification.retention_expires_at == timestamp + timedelta(days=30)

        with pytest.raises(DataLifecycleError, match="immutable design-partner"):
            set_retention_deadline(
                session,
                engagement=engagement,
                operator=session.get_one(Operator, test_operator.id),
                retain_until=qualification.retention_expires_at + timedelta(seconds=1),
                now=timestamp,
            )

        # A request-scoped preflight rejects an invalid in-memory deadline. The worker and
        # publication gates deliberately refresh from PostgreSQL, so stale identity-map
        # state cannot override the valid canonical authorization below.
        engagement.retention_expires_at = qualification.retention_expires_at + timedelta(days=1)
        with session.no_autoflush:
            upload_decision = authorize_qualified_document_upload(
                session,
                engagement=engagement,
                operator=session.get_one(Operator, test_operator.id),
                source_key=SOURCE_KEY,
                workflow_class=WORKFLOW_CLASS,
                data_classification="CONFIDENTIAL",
                content_type="text/markdown",
                extraction_provider="bedrock",
                provider_allowed_classifications={"CONFIDENTIAL"},
                now=timestamp,
            )
            assert upload_decision.allowed is False
            assert upload_decision.decision_code == "RETENTION_OUTSIDE_QUALIFICATION"
            processing_time = require_qualified_evidence_processing(
                session,
                asset=asset,
                provider_name="amazon-bedrock-converse",
                provider_allowed_data_classifications={"CONFIDENTIAL"},
                now=timestamp,
            )
            assert processing_time == timestamp
            require_package_publication_eligibility(
                session,
                engagement_id=engagement_id,
                target={
                    "repository_ref": REPOSITORY_REF,
                    "semantic_execution_workflow_ref": WORKFLOW_CLASS,
                },
                now=timestamp,
            )
            assert engagement.retention_expires_at == qualification.retention_expires_at
        session.expire(engagement, ["retention_expires_at"])

    with pytest.raises(DBAPIError), operator_session(test_operator.id) as session:
        engagement = session.get_one(Engagement, engagement_id)
        qualification = session.scalar(
            select(DesignPartnerQualification).where(
                DesignPartnerQualification.engagement_id == engagement_id
            )
        )
        assert qualification is not None
        engagement.retention_expires_at = qualification.retention_expires_at + timedelta(seconds=1)
        session.flush()

    engine = create_engine(get_settings().migration_database_url)
    try:
        with pytest.raises(DBAPIError), Session(engine) as session, session.begin():
            qualification = session.scalar(
                select(DesignPartnerQualification).where(
                    DesignPartnerQualification.engagement_id == engagement_id
                )
            )
            assert qualification is not None
            qualification.retention_days += 1
            session.flush()
    finally:
        engine.dispose()


@pytest.mark.integration
@pytest.mark.isolation
@pytest.mark.parametrize("revocation", ["qualification", "provider-allowlist"])
def test_worker_rechecks_customer_data_authority_before_object_or_provider_access(
    postgres_available: None,
    test_operator: OperatorFixture,
    revocation: str,
) -> None:
    engagement_id = _create_sanitized_engagement(
        test_operator,
        f"Worker recheck {revocation}",
    )
    _provision_and_qualify(engagement_id, test_operator.id)
    store = TrackingEvidenceStore()
    with TestClient(_app(test_operator, store, _settings("CONFIDENTIAL"))) as client:
        uploaded = _upload(client, engagement_id)
    assert uploaded.status_code == 202

    if revocation == "qualification":
        _transition(engagement_id, test_operator.id, status="SUSPENDED")
        processing_allowlist = {"CONFIDENTIAL"}
    else:
        processing_allowlist = set()

    extractor = NoCallBedrockExtractor()
    with pytest.raises(CustomerDataProcessingDeniedError), operator_session(
        test_operator.id
    ) as session:
        job = lease_next_job(session, engagement_id, lease_seconds=30)
        assert job is not None
        assert job.lease_token is not None
        process_job(
            session,
            store,
            job,
            lease_token=job.lease_token,
            extractor=extractor,
            provider_allowed_data_classifications=processing_allowlist,
            runtime_authority_check=lambda _timestamp: None,
        )

    assert store.get_calls == 0
    assert extractor.calls == 0
    with operator_session(test_operator.id) as session:
        assert (
            list(
                session.scalars(
                    select(EvidenceSegment).where(EvidenceSegment.engagement_id == engagement_id)
                )
            )
            == []
        )
        assert (
            list(
                session.scalars(
                    select(CandidateClaim).where(CandidateClaim.engagement_id == engagement_id)
                )
            )
            == []
        )


@pytest.mark.integration
@pytest.mark.isolation
def test_worker_reads_the_persisted_version_when_a_new_current_version_exists(
    postgres_available: None,
    test_operator: OperatorFixture,
) -> None:
    engagement_id = _create_sanitized_engagement(test_operator, "Worker pinned version")
    _provision_and_qualify(engagement_id, test_operator.id)
    store = TrackingEvidenceStore()
    with TestClient(_app(test_operator, store, _settings("CONFIDENTIAL"))) as client:
        uploaded = _upload(client, engagement_id)
    assert uploaded.status_code == 202

    with operator_session(test_operator.id) as session:
        asset = session.scalar(
            select(EvidenceAsset).where(EvidenceAsset.engagement_id == engagement_id)
        )
        assert asset is not None
        assert asset.storage_version_id is not None
        pinned_version_id = asset.storage_version_id
        store.put(
            asset.storage_key,
            b"\xffcurrent object was replaced after the accepted upload",
            "text/markdown",
        )

    extractor = NoCallBedrockExtractor()
    with operator_session(test_operator.id) as session:
        job = lease_next_job(session, engagement_id, lease_seconds=30)
        assert job is not None
        assert job.lease_token is not None
        process_job(
            session,
            store,
            job,
            lease_token=job.lease_token,
            extractor=extractor,
            provider_allowed_data_classifications={"CONFIDENTIAL"},
            runtime_authority_check=lambda _timestamp: None,
        )

    assert extractor.calls == 1
    assert store.requested_version_ids == [pinned_version_id]
    with operator_session(test_operator.id) as session:
        run = session.scalar(
            select(ExtractionRun).where(ExtractionRun.engagement_id == engagement_id)
        )
        assert run is not None
        assert run.status == "complete"


@pytest.mark.integration
@pytest.mark.isolation
def test_worker_denies_a_tampered_pinned_version_before_provider_or_output(
    postgres_available: None,
    test_operator: OperatorFixture,
) -> None:
    engagement_id = _create_sanitized_engagement(test_operator, "Worker version digest")
    _provision_and_qualify(engagement_id, test_operator.id)
    store = TrackingEvidenceStore()
    with TestClient(_app(test_operator, store, _settings("CONFIDENTIAL"))) as client:
        uploaded = _upload(client, engagement_id)
    assert uploaded.status_code == 202
    store.read_override = b"different bytes returned for the persisted version"
    extractor = NoCallBedrockExtractor()

    with operator_session(test_operator.id) as session:
        job = lease_next_job(session, engagement_id, lease_seconds=30)
        assert job is not None
        assert job.lease_token is not None
        job_id = job.id
        lease_token = job.lease_token

    with pytest.raises(EvidenceIntegrityError) as caught, operator_session(
        test_operator.id
    ) as session:
        process_job(
            session,
            store,
            session.get_one(Job, job_id),
            lease_token=lease_token,
            extractor=extractor,
            actor=session.get_one(Operator, test_operator.id),
            provider_allowed_data_classifications={"CONFIDENTIAL"},
            runtime_authority_check=lambda _timestamp: None,
        )

    failure = public_job_failure(caught.value)
    with operator_session(test_operator.id) as session:
        assert fail_job(
            session,
            job_id,
            failure.message,
            lease_token=lease_token,
            retryable=failure.retryable,
            result_code=failure.code,
            extractor=extractor,
        )

    assert store.get_calls == 1
    assert all(version_id is not None for version_id in store.requested_version_ids)
    assert extractor.calls == 0
    with operator_session(test_operator.id) as session:
        runs = list(
            session.scalars(
                select(ExtractionRun).where(ExtractionRun.engagement_id == engagement_id)
            )
        )
        assert len(runs) == 1
        assert runs[0].status == "failed"
        assert runs[0].result_code == "evidence_integrity_failed"
        assert runs[0].error_message == (
            "The immutable evidence object failed integrity verification."
        )
        assert list(
            session.scalars(
                select(EvidenceSegment).where(EvidenceSegment.engagement_id == engagement_id)
            )
        ) == []
        assert list(
            session.scalars(
                select(CandidateClaim).where(CandidateClaim.engagement_id == engagement_id)
            )
        ) == []
        assert list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.engagement_id == engagement_id,
                    AuditEvent.action == "extraction.completed",
                )
            )
        ) == []


@pytest.mark.integration
@pytest.mark.isolation
def test_worker_denies_qualified_legacy_evidence_without_a_version_pin(
    postgres_available: None,
    test_operator: OperatorFixture,
) -> None:
    engagement_id = _create_sanitized_engagement(test_operator, "Worker missing version")
    _provision_and_qualify(engagement_id, test_operator.id)
    store = TrackingEvidenceStore()
    with TestClient(_app(test_operator, store, _settings("CONFIDENTIAL"))) as client:
        uploaded = _upload(client, engagement_id)
    assert uploaded.status_code == 202

    with operator_session(test_operator.id) as session:
        asset = session.scalar(
            select(EvidenceAsset).where(EvidenceAsset.engagement_id == engagement_id)
        )
        assert asset is not None
        asset.storage_version_id = None

    extractor = NoCallBedrockExtractor()
    with pytest.raises(EvidenceIntegrityError), operator_session(test_operator.id) as session:
        job = lease_next_job(session, engagement_id, lease_seconds=30)
        assert job is not None
        assert job.lease_token is not None
        process_job(
            session,
            store,
            job,
            lease_token=job.lease_token,
            extractor=extractor,
            provider_allowed_data_classifications={"CONFIDENTIAL"},
            runtime_authority_check=lambda _timestamp: None,
        )

    assert store.get_calls == 0
    assert extractor.calls == 0


@pytest.mark.integration
@pytest.mark.isolation
@pytest.mark.parametrize("late_status", ["SUSPENDED", "REVOKED"])
def test_worker_discards_inflight_provider_output_after_qualification_change(
    postgres_available: None,
    test_operator: OperatorFixture,
    late_status: str,
) -> None:
    engagement_id = _create_sanitized_engagement(
        test_operator,
        f"Worker mid-job {late_status.casefold()}",
    )
    _provision_and_qualify(engagement_id, test_operator.id)
    store = TrackingEvidenceStore()
    with TestClient(_app(test_operator, store, _settings("CONFIDENTIAL"))) as client:
        uploaded = _upload(
            client,
            engagement_id,
            content=b"First bounded segment.\n\nSecond bounded segment.",
        )
    assert uploaded.status_code == 202

    with operator_session(test_operator.id) as session:
        job = lease_next_job(session, engagement_id, lease_seconds=30)
        assert job is not None
        assert job.lease_token is not None
        job_id = uuid.UUID(str(job.id))
        lease_token = uuid.UUID(str(job.lease_token))

    provider_entered = Event()
    release_provider = Event()
    extractor = BlockingBedrockExtractor(provider_entered, release_provider)
    processing_errors: list[BaseException] = []

    def process() -> None:
        try:
            with operator_session(test_operator.id) as session:
                process_job(
                    session,
                    store,
                    session.get_one(Job, job_id),
                    lease_token=lease_token,
                    extractor=extractor,
                    provider_allowed_data_classifications={"CONFIDENTIAL"},
                    runtime_authority_check=lambda _timestamp: None,
                )
        except BaseException as exc:  # pragma: no cover - asserted below
            processing_errors.append(exc)

    processing_thread = Thread(target=process, daemon=True)
    processing_thread.start()
    try:
        assert provider_entered.wait(timeout=5)
        _transition(
            engagement_id,
            test_operator.id,
            status=late_status,
        )
    finally:
        release_provider.set()
        processing_thread.join(timeout=5)

    assert not processing_thread.is_alive()
    assert len(processing_errors) == 1
    assert isinstance(processing_errors[0], CustomerDataProcessingDeniedError)
    assert store.get_calls == 1
    assert extractor.calls == 1
    with operator_session(test_operator.id) as session:
        assert list(
            session.scalars(
                select(ExtractionRun).where(ExtractionRun.engagement_id == engagement_id)
            )
        ) == []
        assert list(
            session.scalars(
                select(EvidenceSegment).where(EvidenceSegment.engagement_id == engagement_id)
            )
        ) == []
        assert list(
            session.scalars(
                select(CandidateClaim).where(CandidateClaim.engagement_id == engagement_id)
            )
        ) == []


@pytest.mark.integration
@pytest.mark.isolation
def test_worker_discards_provider_output_when_retention_expires_mid_job(
    postgres_available: None,
    test_operator: OperatorFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    qualification_time = datetime.now(UTC)
    engagement_id = _create_sanitized_engagement(test_operator, "Worker retention expiry")
    _provision_and_qualify(
        engagement_id,
        test_operator.id,
        now=qualification_time,
    )
    store = TrackingEvidenceStore()
    with TestClient(_app(test_operator, store, _settings("CONFIDENTIAL"))) as client:
        uploaded = _upload(
            client,
            engagement_id,
            content=b"First bounded segment.\n\nSecond bounded segment.",
        )
    assert uploaded.status_code == 202

    class _AuthorityClock:
        current = qualification_time + timedelta(hours=1)

        @classmethod
        def now(cls, timezone: object) -> datetime:
            assert timezone is UTC
            return cls.current

    monkeypatch.setattr(design_partner_service, "datetime", _AuthorityClock)
    release_provider = Event()
    release_provider.set()
    extractor = BlockingBedrockExtractor(
        Event(),
        release_provider,
        after_first_call=lambda: setattr(
            _AuthorityClock,
            "current",
            qualification_time + timedelta(days=31),
        ),
    )

    with operator_session(test_operator.id) as session:
        job = lease_next_job(session, engagement_id, lease_seconds=30)
        assert job is not None
        assert job.lease_token is not None
        with pytest.raises(CustomerDataProcessingDeniedError):
            process_job(
                session,
                store,
                job,
                lease_token=job.lease_token,
                extractor=extractor,
                provider_allowed_data_classifications={"CONFIDENTIAL"},
                runtime_authority_check=lambda _timestamp: None,
            )

    assert store.get_calls == 1
    assert extractor.calls == 1
    with operator_session(test_operator.id) as session:
        assert list(
            session.scalars(
                select(ExtractionRun).where(ExtractionRun.engagement_id == engagement_id)
            )
        ) == []
        assert list(
            session.scalars(
                select(EvidenceSegment).where(EvidenceSegment.engagement_id == engagement_id)
            )
        ) == []


@pytest.mark.integration
@pytest.mark.isolation
def test_worker_discards_provider_output_when_deployment_qualification_expires_mid_job(
    postgres_available: None,
    test_operator: OperatorFixture,
) -> None:
    engagement_id = _create_sanitized_engagement(
        test_operator,
        "Worker deployment expiry",
    )
    _provision_and_qualify(engagement_id, test_operator.id)
    store = TrackingEvidenceStore()
    with TestClient(_app(test_operator, store, _settings("CONFIDENTIAL"))) as client:
        uploaded = _upload(
            client,
            engagement_id,
            content=b"First bounded segment.\n\nSecond bounded segment.",
        )
    assert uploaded.status_code == 202
    release_provider = Event()
    release_provider.set()
    extractor = BlockingBedrockExtractor(Event(), release_provider)
    runtime_checks: list[datetime] = []

    def require_current_deployment(timestamp: datetime) -> None:
        runtime_checks.append(timestamp)
        if extractor.calls > 0:
            raise ValueError("The deployment qualification expired during provider work.")

    with operator_session(test_operator.id) as session:
        job = lease_next_job(session, engagement_id, lease_seconds=30)
        assert job is not None
        assert job.lease_token is not None
        with pytest.raises(CustomerDataProcessingDeniedError):
            process_job(
                session,
                store,
                job,
                lease_token=job.lease_token,
                extractor=extractor,
                provider_allowed_data_classifications={"CONFIDENTIAL"},
                runtime_authority_check=require_current_deployment,
            )

    assert len(runtime_checks) == 4
    assert store.get_calls == 1
    assert extractor.calls == 1
    with operator_session(test_operator.id) as session:
        assert list(
            session.scalars(
                select(ExtractionRun).where(ExtractionRun.engagement_id == engagement_id)
            )
        ) == []
        assert list(
            session.scalars(
                select(EvidenceSegment).where(EvidenceSegment.engagement_id == engagement_id)
            )
        ) == []


@pytest.mark.integration
@pytest.mark.isolation
def test_worker_rolls_back_staged_output_when_deployment_expires_before_commit(
    postgres_available: None,
    test_operator: OperatorFixture,
) -> None:
    engagement_id = _create_sanitized_engagement(
        test_operator,
        "Worker final deployment expiry",
    )
    _provision_and_qualify(engagement_id, test_operator.id)
    store = TrackingEvidenceStore()
    with TestClient(_app(test_operator, store, _settings("CONFIDENTIAL"))) as client:
        uploaded = _upload(
            client,
            engagement_id,
            content=b"One bounded segment whose staged result must roll back.",
        )
    assert uploaded.status_code == 202
    release_provider = Event()
    release_provider.set()
    extractor = BlockingBedrockExtractor(Event(), release_provider)
    runtime_checks: list[datetime] = []

    def require_current_deployment(timestamp: datetime) -> None:
        runtime_checks.append(timestamp)
        if len(runtime_checks) == 6:
            raise ValueError("The deployment qualification expired before commit.")

    with pytest.raises(CustomerDataProcessingDeniedError), operator_session(
        test_operator.id
    ) as session:
        job = lease_next_job(session, engagement_id, lease_seconds=30)
        assert job is not None
        assert job.lease_token is not None
        process_job(
            session,
            store,
            job,
            lease_token=job.lease_token,
            extractor=extractor,
            provider_allowed_data_classifications={"CONFIDENTIAL"},
            runtime_authority_check=require_current_deployment,
        )

    assert len(runtime_checks) == 6
    assert extractor.calls == 1
    with operator_session(test_operator.id) as session:
        assert list(
            session.scalars(
                select(ExtractionRun).where(ExtractionRun.engagement_id == engagement_id)
            )
        ) == []
        assert list(
            session.scalars(
                select(EvidenceSegment).where(EvidenceSegment.engagement_id == engagement_id)
            )
        ) == []
        assert list(
            session.scalars(
                select(CandidateClaim).where(CandidateClaim.engagement_id == engagement_id)
            )
        ) == []
