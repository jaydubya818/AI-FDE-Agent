from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from threading import Event, Thread

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import create_engine, delete, event, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

import ai_fde.api.routes as api_routes
import ai_fde.modules.design_partner.service as design_partner_service
from ai_fde.adapters.storage import InMemoryEvidenceStore
from ai_fde.api.dependencies import AuthenticatedPrincipal, get_principal, get_session
from ai_fde.api.routes import router
from ai_fde.api.upload_limits import read_evidence_upload
from ai_fde.config import get_settings
from ai_fde.db import SessionFactory, apply_operator_context, operator_session
from ai_fde.models import AuditEvent, Engagement, EngagementMember, EvidenceAsset, Operator
from ai_fde.modules.design_partner.models import (
    CustomerDataAccessEvent,
    DesignPartnerQualification,
)
from ai_fde.modules.design_partner.service import (
    authorize_qualified_document_upload,
    lock_design_partner_authority,
    provision_design_partner_qualification,
    record_customer_data_access_outcome,
    transition_design_partner_qualification,
)
from ai_fde.modules.engagements.service import create_engagement
from ai_fde.modules.evidence.service import create_evidence_asset
from tests.conftest import OperatorFixture

SOURCE_KEY = "bounded-document"
WORKFLOW_CLASS = "software-change/verified-pr/v1"
REPOSITORY_REF = "github.com/sellerfi/marketplace"
BASIS_REF = "qualification-record:phase-3-isolation"


@dataclass
class _QualifiedRouteSettings:
    deployment_expires_at: datetime | None = None
    extraction_provider: str = "bedrock"
    bedrock_allowed_data_classifications: list[str] = field(
        default_factory=lambda: ["CONFIDENTIAL"]
    )
    deployment_decision_times: list[datetime] = field(default_factory=list)

    def verified_deployment_qualification(self, *, now: datetime | None = None) -> object:
        if now is None:
            raise AssertionError("Upload reauthorization must supply its decision time.")
        self.deployment_decision_times.append(now)
        if self.deployment_expires_at is not None and now >= self.deployment_expires_at:
            raise ValueError("The deployment qualification record has expired.")
        return object()


def _create_operator(label: str) -> OperatorFixture:
    operator_id = uuid.uuid4()
    fixture = OperatorFixture(
        operator_id,
        f"{label}-{operator_id}",
        f"{label.title()} FDE",
    )
    session = SessionFactory()
    try:
        with session.begin():
            apply_operator_context(session, operator_id)
            session.add(
                Operator(
                    id=fixture.id,
                    external_subject=fixture.subject,
                    display_name=fixture.display_name,
                )
            )
    finally:
        session.close()
    return fixture


def _create_sanitized_engagement(owner: OperatorFixture, label: str) -> uuid.UUID:
    with operator_session(owner.id) as session:
        engagement = create_engagement(
            session,
            operator=session.get_one(Operator, owner.id),
            name=f"{label} {uuid.uuid4()}",
            workflow_name="Bounded document qualification",
            primary_outcome="Prove tenant-safe customer-data authorization.",
            data_classification="sanitized",
        )
        return uuid.UUID(str(engagement.id))


def _qualify(
    engagement_id: uuid.UUID,
    owner_operator_id: uuid.UUID,
) -> tuple[uuid.UUID, str]:
    engine = create_engine(get_settings().migration_database_url)
    try:
        with Session(engine) as session, session.begin():
            partner_key = f"partner-{engagement_id.hex}"
            qualification = provision_design_partner_qualification(
                session,
                engagement_id=engagement_id,
                partner_key=partner_key,
                organization="Tenant-isolated design partner",
                authorized_data_source_keys=[SOURCE_KEY],
                authorized_repository_refs=[REPOSITORY_REF],
                allowed_workflow_classes=[WORKFLOW_CLASS],
                data_classification="CONFIDENTIAL",
                retention_days=30,
                authorization_basis_ref=BASIS_REF,
                configured_by_id=owner_operator_id,
            )
            transition_design_partner_qualification(
                session,
                engagement_id=engagement_id,
                qualification_state="IN_PROGRESS",
                authorization_basis_ref=BASIS_REF,
                actor_id=owner_operator_id,
            )
            transition_design_partner_qualification(
                session,
                engagement_id=engagement_id,
                qualification_state="QUALIFIED",
                authorization_basis_ref=BASIS_REF,
                actor_id=owner_operator_id,
            )
            return qualification.id, partner_key
    finally:
        engine.dispose()


def _transition(
    engagement_id: uuid.UUID,
    owner_operator_id: uuid.UUID,
    *,
    status: str,
) -> None:
    engine = create_engine(get_settings().migration_database_url)
    try:
        with Session(engine) as session, session.begin():
            transition_design_partner_qualification(
                session,
                engagement_id=engagement_id,
                status=status,
                authorization_basis_ref="qualification-record:upload-race",
                actor_id=owner_operator_id,
            )
    finally:
        engine.dispose()


def _set_membership_role(
    engagement_id: uuid.UUID,
    operator_id: uuid.UUID,
    *,
    role: str,
) -> None:
    engine = create_engine(get_settings().migration_database_url)
    try:
        with Session(engine) as session, session.begin():
            membership = session.scalar(
                select(EngagementMember).where(
                    EngagementMember.engagement_id == engagement_id,
                    EngagementMember.operator_id == operator_id,
                )
            )
            assert membership is not None
            membership.role = role
    finally:
        engine.dispose()


def _upload_while_body_is_paused(
    monkeypatch: pytest.MonkeyPatch,
    *,
    app: FastAPI,
    engagement_id: uuid.UUID,
    sensitive_content: bytes,
    during_pause: Callable[[], None],
) -> Response:
    content_read = Event()
    release_upload = Event()
    original_reader = read_evidence_upload

    async def blocking_reader(file: object) -> bytes:
        content = await original_reader(file)  # type: ignore[arg-type]
        content_read.set()
        if not release_upload.wait(timeout=5):
            raise TimeoutError("The upload reauthorization race did not finish.")
        return content

    monkeypatch.setattr(api_routes, "read_evidence_upload", blocking_reader)
    responses: list[Response] = []
    request_errors: list[BaseException] = []

    def upload() -> None:
        try:
            with TestClient(app) as client:
                responses.append(
                    client.post(
                        f"/api/engagements/{engagement_id}/evidence",
                        data={
                            "source_key": SOURCE_KEY,
                            "workflow_class": WORKFLOW_CLASS,
                            "data_classification": "CONFIDENTIAL",
                        },
                        files={"file": ("bounded.md", sensitive_content, "text/markdown")},
                    )
                )
        except BaseException as exc:  # pragma: no cover - reported below
            request_errors.append(exc)

    request_thread = Thread(target=upload, daemon=True)
    request_thread.start()
    try:
        assert content_read.wait(timeout=5)
        during_pause()
    finally:
        release_upload.set()
        request_thread.join(timeout=5)

    assert not request_thread.is_alive()
    assert request_errors == []
    assert len(responses) == 1
    return responses[0]


@pytest.mark.integration
@pytest.mark.isolation
def test_aggregate_lock_is_membership_scoped_without_qualification_update_privilege(
    postgres_available: None,
) -> None:
    owner = _create_operator("aggregate-lock-owner")
    viewer = _create_operator("aggregate-lock-viewer")
    outsider = _create_operator("aggregate-lock-outsider")
    engagement_id = _create_sanitized_engagement(owner, "Aggregate lock privilege")
    _qualify(engagement_id, owner.id)

    engine = create_engine(get_settings().migration_database_url)
    try:
        with Session(engine) as session, session.begin():
            session.add(
                EngagementMember(
                    engagement_id=engagement_id,
                    operator_id=viewer.id,
                    role="viewer",
                )
            )
    finally:
        engine.dispose()

    with operator_session(owner.id) as session:
        assert (
            lock_design_partner_authority(
                session,
                engagement_id=engagement_id,
                required_access="read",
            )
            is True
        )
        assert (
            lock_design_partner_authority(
                session,
                engagement_id=engagement_id,
                required_access="write",
            )
            is True
        )

    with operator_session(viewer.id) as session:
        assert (
            lock_design_partner_authority(
                session,
                engagement_id=engagement_id,
                required_access="read",
            )
            is True
        )
        assert (
            lock_design_partner_authority(
                session,
                engagement_id=engagement_id,
                required_access="write",
            )
            is False
        )
        assert (
            session.scalar(
                text("SELECT ai_fde_lock_design_partner_authority(:engagement_id, 'admin')"),
                {"engagement_id": engagement_id},
            )
            is False
        )

    with operator_session(outsider.id) as session:
        assert (
            lock_design_partner_authority(
                session,
                engagement_id=engagement_id,
                required_access="read",
            )
            is False
        )

    engine = create_engine(get_settings().migration_database_url)
    try:
        with Session(engine) as session:
            app_execute, public_execute, app_update = session.execute(
                text(
                    "SELECT "
                    "has_function_privilege('ai_fde_app', "
                    "'ai_fde_lock_design_partner_authority(uuid,text)', 'EXECUTE'), "
                    "EXISTS ("
                    "SELECT 1 FROM pg_proc AS procedure "
                    "CROSS JOIN LATERAL aclexplode(COALESCE("
                    "procedure.proacl, acldefault('f', procedure.proowner)"
                    ")) AS privilege "
                    "WHERE procedure.oid = "
                    "'ai_fde_lock_design_partner_authority(uuid,text)'::regprocedure "
                    "AND privilege.grantee = 0 "
                    "AND privilege.privilege_type = 'EXECUTE'), "
                    "has_table_privilege('ai_fde_app', "
                    "'design_partner_qualifications', 'UPDATE')"
                )
            ).one()
    finally:
        engine.dispose()

    assert app_execute is True
    assert public_execute is False
    assert app_update is False


@pytest.mark.integration
@pytest.mark.isolation
def test_wrong_partner_binding_fails_and_nonmember_sees_nothing(
    postgres_available: None,
) -> None:
    owner = _create_operator("qualification-owner")
    outsider = _create_operator("qualification-outsider")
    engagement_a = _create_sanitized_engagement(owner, "Partner A")
    engagement_b = _create_sanitized_engagement(owner, "Partner B")
    qualification_a_id, _ = _qualify(engagement_a, owner.id)
    qualification_b_id, partner_b_key = _qualify(engagement_b, owner.id)

    engine = create_engine(get_settings().migration_database_url)
    try:
        with Session(engine) as session, session.begin():
            owner_record = session.get_one(Operator, owner.id)
            asset = create_evidence_asset(
                session,
                InMemoryEvidenceStore(),
                engagement_id=engagement_a,
                operator=owner_record,
                file_name="bounded.md",
                content_type="text/markdown",
                content=b"Tenant A content.",
                design_partner_qualification_id=qualification_a_id,
                authorized_source_key=SOURCE_KEY,
                authorized_workflow_class=WORKFLOW_CLASS,
                data_classification="CONFIDENTIAL",
            )
            with pytest.raises(IntegrityError), session.begin_nested():
                session.add(
                    CustomerDataAccessEvent(
                        engagement_id=engagement_a,
                        qualification_id=qualification_b_id,
                        partner_key=partner_b_key,
                        operator_id=owner.id,
                        evidence_asset_id=asset.id,
                        source_key=SOURCE_KEY,
                        workflow_class=WORKFLOW_CLASS,
                        data_classification="CONFIDENTIAL",
                        operation="MANUAL_DOCUMENT_UPLOAD",
                        outcome="AUTHORIZED",
                        decision_code="AUTHORIZED",
                        authorization_basis_ref=BASIS_REF,
                        correlation_id=uuid.uuid4(),
                    )
                )
                session.flush()
    finally:
        engine.dispose()

    app = FastAPI()
    app.state.evidence_store = InMemoryEvidenceStore()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_principal] = lambda: AuthenticatedPrincipal(
        operator_id=outsider.id,
        auth_mode="oidc",
        sanitized_data_allowed=True,
    )
    with TestClient(app) as client:
        hidden = client.get(f"/api/engagements/{engagement_a}/design-partner-qualification")
        assert hidden.status_code == 404
        assert hidden.json() == {"detail": "Engagement not found."}

    with operator_session(outsider.id) as session:
        assert list(session.scalars(select(DesignPartnerQualification))) == []
        assert list(session.scalars(select(CustomerDataAccessEvent))) == []


@pytest.mark.integration
@pytest.mark.isolation
def test_prequalification_denial_audit_is_metadata_only_and_tenant_hidden(
    postgres_available: None,
) -> None:
    owner = _create_operator("prequalification-owner")
    outsider = _create_operator("prequalification-outsider")
    engagement_id = _create_sanitized_engagement(owner, "Prequalification audit")
    app = FastAPI()
    app.state.evidence_store = InMemoryEvidenceStore()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_principal] = lambda: AuthenticatedPrincipal(
        operator_id=owner.id,
        auth_mode="oidc",
        sanitized_data_allowed=True,
    )
    sensitive_marker = "customer-secret-must-not-be-audited"

    with TestClient(app) as client:
        denied = client.post(
            f"/api/engagements/{engagement_id}/evidence",
            data={
                "source_key": "unconfigured-source",
                "workflow_class": "unconfigured-workflow",
                "data_classification": "CONFIDENTIAL",
            },
            files={"file": ("customer.md", sensitive_marker.encode(), "text/markdown")},
        )
    assert denied.status_code == 403
    assert denied.json()["code"] == "QUALIFICATION_REQUIRED"

    with operator_session(owner.id) as session:
        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.engagement_id == engagement_id,
                AuditEvent.action == "customer_data.access_denied",
            )
        )
        assert audit is not None
        assert audit.detail == {
            "operation": "MANUAL_DOCUMENT_UPLOAD",
            "decision_code": "QUALIFICATION_REQUIRED",
            "source_key": "unqualified-source",
            "workflow_class": "unqualified-workflow",
            "data_classification": "CONFIDENTIAL",
            "authorization_basis_ref": "none",
            "qualification_present": False,
        }
        assert sensitive_marker not in str(vars(audit))

    with operator_session(outsider.id) as session:
        assert (
            list(
                session.scalars(select(AuditEvent).where(AuditEvent.engagement_id == engagement_id))
            )
            == []
        )


@pytest.mark.integration
@pytest.mark.isolation
def test_customer_data_access_event_is_append_only_for_runtime_role(
    postgres_available: None,
) -> None:
    owner = _create_operator("append-only-owner")
    forged_operator = _create_operator("forged-event-actor")
    engagement_id = _create_sanitized_engagement(owner, "Append-only partner")
    _qualify(engagement_id, owner.id)
    store = InMemoryEvidenceStore()
    timestamp = datetime.now(UTC)

    with operator_session(owner.id) as session:
        engagement = session.get_one(Engagement, engagement_id)
        operator = session.get_one(Operator, owner.id)
        decision = authorize_qualified_document_upload(
            session,
            engagement=engagement,
            operator=operator,
            source_key=SOURCE_KEY,
            workflow_class=WORKFLOW_CLASS,
            data_classification="CONFIDENTIAL",
            content_type="text/plain",
            extraction_provider="bedrock",
            provider_allowed_classifications={"CONFIDENTIAL"},
            now=timestamp,
        )
        assert decision.context is not None
        asset = create_evidence_asset(
            session,
            store,
            engagement_id=engagement_id,
            operator=operator,
            file_name="bounded.txt",
            content_type="text/plain",
            content=b"Append-only access proof.",
            design_partner_qualification_id=decision.context.qualification_id,
            authorized_source_key=decision.context.source_key,
            authorized_workflow_class=decision.context.workflow_class,
            data_classification=decision.context.data_classification,
        )
        event = record_customer_data_access_outcome(
            session,
            context=decision.context,
            outcome="AUTHORIZED",
            decision_code="AUTHORIZED",
            evidence_asset_id=asset.id,
        )
        event_id = event.id
        authorized_context = decision.context

    with pytest.raises(DBAPIError), operator_session(owner.id) as session:
        record_customer_data_access_outcome(
            session,
            context=replace(authorized_context, operator_id=forged_operator.id),
            outcome="DENIED",
            decision_code="FORGED_ACTOR",
        )
        session.flush()

    with pytest.raises(DBAPIError), operator_session(owner.id) as session:
        event = session.get_one(CustomerDataAccessEvent, event_id)
        event.decision_code = "TAMPERED"
        session.flush()

    with pytest.raises(DBAPIError), operator_session(owner.id) as session:
        session.execute(
            delete(CustomerDataAccessEvent).where(CustomerDataAccessEvent.id == event_id)
        )
        session.flush()

    with operator_session(owner.id) as session:
        event = session.get_one(CustomerDataAccessEvent, event_id)
        assert event.decision_code == "AUTHORIZED"
        assert event.created_at <= timestamp + timedelta(minutes=1)


@pytest.mark.integration
@pytest.mark.isolation
def test_qualification_transition_holds_the_engagement_serialization_lock(
    postgres_available: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _create_operator("qualification-lock-owner")
    engagement_id = _create_sanitized_engagement(owner, "Qualification lock")
    _qualify(engagement_id, owner.id)
    transition_reached_audit = Event()
    release_transition = Event()
    transition_errors: list[BaseException] = []
    original_record_change = design_partner_service._record_qualification_change

    def blocking_record_change(
        session: Session,
        *,
        qualification: DesignPartnerQualification,
        actor_id: uuid.UUID,
        action: str,
        detail: dict[str, object],
    ) -> None:
        original_record_change(
            session,
            qualification=qualification,
            actor_id=actor_id,
            action=action,
            detail=detail,
        )
        transition_reached_audit.set()
        if not release_transition.wait(timeout=5):
            raise TimeoutError("The qualification transition lock probe did not finish.")

    monkeypatch.setattr(
        design_partner_service,
        "_record_qualification_change",
        blocking_record_change,
    )

    def suspend_qualification() -> None:
        engine = create_engine(get_settings().migration_database_url)
        try:
            with Session(engine) as session, session.begin():
                transition_design_partner_qualification(
                    session,
                    engagement_id=engagement_id,
                    status="SUSPENDED",
                    authorization_basis_ref="qualification-record:concurrent-suspension",
                    actor_id=owner.id,
                )
        except BaseException as exc:  # pragma: no cover - reported by the parent assertion
            transition_errors.append(exc)
        finally:
            engine.dispose()

    transition_thread = Thread(target=suspend_qualification, daemon=True)
    transition_thread.start()
    try:
        assert transition_reached_audit.wait(timeout=5)
        engine = create_engine(get_settings().migration_database_url)
        try:
            with pytest.raises(DBAPIError), Session(engine) as session, session.begin():
                session.scalar(
                    select(Engagement)
                    .where(Engagement.id == engagement_id)
                    .with_for_update(nowait=True)
                )
        finally:
            engine.dispose()
    finally:
        release_transition.set()
        transition_thread.join(timeout=5)

    assert not transition_thread.is_alive()
    assert transition_errors == []
    with operator_session(owner.id) as session:
        qualification = session.scalar(
            select(DesignPartnerQualification).where(
                DesignPartnerQualification.engagement_id == engagement_id
            )
        )
        assert qualification is not None
        assert qualification.status == "SUSPENDED"


@pytest.mark.integration
@pytest.mark.isolation
@pytest.mark.parametrize("late_status", ["SUSPENDED", "REVOKED"])
def test_upload_reauthorization_denies_after_qualification_change_wins_the_race(
    postgres_available: None,
    monkeypatch: pytest.MonkeyPatch,
    late_status: str,
) -> None:
    owner = _create_operator(f"upload-race-{late_status.casefold()}")
    engagement_id = _create_sanitized_engagement(owner, "Upload reauthorization")
    _qualify(engagement_id, owner.id)
    store = InMemoryEvidenceStore()
    app = FastAPI()
    app.state.evidence_store = store
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_principal] = lambda: AuthenticatedPrincipal(
        operator_id=owner.id,
        auth_mode="oidc",
        sanitized_data_allowed=True,
    )
    app.dependency_overrides[get_settings] = lambda: _QualifiedRouteSettings()
    sensitive_content = b"customer-secret-must-not-survive-late-reauthorization"
    response = _upload_while_body_is_paused(
        monkeypatch,
        app=app,
        engagement_id=engagement_id,
        sensitive_content=sensitive_content,
        during_pause=lambda: _transition(engagement_id, owner.id, status=late_status),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "QUALIFICATION_INACTIVE"
    assert store.objects == {}
    with operator_session(owner.id) as session:
        assert (
            session.scalar(
                select(EvidenceAsset).where(EvidenceAsset.engagement_id == engagement_id)
            )
            is None
        )
        events = list(
            session.scalars(
                select(CustomerDataAccessEvent).where(
                    CustomerDataAccessEvent.engagement_id == engagement_id
                )
            )
        )
        assert len(events) == 1
        assert events[0].outcome == "DENIED"
        assert events[0].decision_code == "QUALIFICATION_INACTIVE"
        assert events[0].evidence_asset_id is None
        assert sensitive_content.decode() not in str(vars(events[0]))


@pytest.mark.integration
@pytest.mark.isolation
def test_upload_reauthorization_denies_when_operator_is_downgraded_to_viewer_during_read(
    postgres_available: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _create_operator("upload-viewer-downgrade")
    engagement_id = _create_sanitized_engagement(owner, "Upload viewer downgrade")
    _qualify(engagement_id, owner.id)
    store = InMemoryEvidenceStore()
    app = FastAPI()
    app.state.evidence_store = store
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_principal] = lambda: AuthenticatedPrincipal(
        operator_id=owner.id,
        auth_mode="oidc",
        sanitized_data_allowed=True,
    )
    app.dependency_overrides[get_settings] = lambda: _QualifiedRouteSettings()
    sensitive_content = b"customer-secret-must-not-survive-viewer-downgrade"

    response = _upload_while_body_is_paused(
        monkeypatch,
        app=app,
        engagement_id=engagement_id,
        sensitive_content=sensitive_content,
        during_pause=lambda: _set_membership_role(
            engagement_id,
            owner.id,
            role="viewer",
        ),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "QUALIFICATION_REQUIRED"
    assert store.objects == {}
    assert store.stored_version_count == 0
    with operator_session(owner.id) as session:
        assert session.scalar(
            select(EvidenceAsset).where(EvidenceAsset.engagement_id == engagement_id)
        ) is None
        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.engagement_id == engagement_id,
                AuditEvent.action == "customer_data.access_denied",
            )
        )
        assert audit is not None
        assert audit.detail["decision_code"] == "QUALIFICATION_REQUIRED"
        assert sensitive_content.decode() not in str(vars(audit))


@pytest.mark.integration
@pytest.mark.isolation
def test_upload_reauthorization_denies_at_exact_deployment_expiry_after_body_read(
    postgres_available: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _create_operator("upload-deployment-expiry")
    engagement_id = _create_sanitized_engagement(owner, "Upload deployment expiry")
    _qualify(engagement_id, owner.id)
    expiry = datetime.now(UTC) + timedelta(hours=1)

    class _UploadClock:
        current = expiry - timedelta(microseconds=1)

        @classmethod
        def now(cls, timezone: object) -> datetime:
            assert timezone is UTC
            return cls.current

    monkeypatch.setattr(design_partner_service, "datetime", _UploadClock)
    settings = _QualifiedRouteSettings(deployment_expires_at=expiry)
    store = InMemoryEvidenceStore()
    app = FastAPI()
    app.state.evidence_store = store
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_principal] = lambda: AuthenticatedPrincipal(
        operator_id=owner.id,
        auth_mode="oidc",
        sanitized_data_allowed=True,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    sensitive_content = b"customer-secret-must-not-survive-deployment-expiry"

    response = _upload_while_body_is_paused(
        monkeypatch,
        app=app,
        engagement_id=engagement_id,
        sensitive_content=sensitive_content,
        during_pause=lambda: setattr(_UploadClock, "current", expiry),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "DEPLOYMENT_QUALIFICATION_INACTIVE"
    assert settings.deployment_decision_times == [expiry]
    assert store.objects == {}
    assert store.stored_version_count == 0
    with operator_session(owner.id) as session:
        assert session.scalar(
            select(EvidenceAsset).where(EvidenceAsset.engagement_id == engagement_id)
        ) is None
        event_record = session.scalar(
            select(CustomerDataAccessEvent).where(
                CustomerDataAccessEvent.engagement_id == engagement_id
            )
        )
        assert event_record is not None
        assert event_record.outcome == "DENIED"
        assert event_record.decision_code == "DEPLOYMENT_QUALIFICATION_INACTIVE"
        assert event_record.evidence_asset_id is None
        assert sensitive_content.decode() not in str(vars(event_record))


@pytest.mark.integration
@pytest.mark.isolation
@pytest.mark.parametrize("failure_stage", ["post-put-flush", "request-commit"])
def test_failed_upload_transaction_compensates_the_exact_stored_version(
    postgres_available: None,
    failure_stage: str,
) -> None:
    owner = _create_operator(f"upload-compensation-{failure_stage}")
    engagement_id = _create_sanitized_engagement(owner, "Upload compensation")
    _qualify(engagement_id, owner.id)
    store = InMemoryEvidenceStore()
    app = FastAPI()
    app.state.evidence_store = store
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_principal] = lambda: AuthenticatedPrincipal(
        operator_id=owner.id,
        auth_mode="oidc",
        sanitized_data_allowed=True,
    )
    app.dependency_overrides[get_settings] = lambda: _QualifiedRouteSettings()
    failure_message = f"forced {failure_stage} failure"

    def fail_post_put_flush(
        session: Session,
        _flush_context: object,
        _instances: object,
    ) -> None:
        if any(isinstance(record, EvidenceAsset) for record in session.new):
            raise RuntimeError(failure_message)

    def fail_request_commit(_session: Session) -> None:
        raise RuntimeError(failure_message)

    def failing_session() -> Iterator[Session]:
        with operator_session(owner.id) as session:
            if failure_stage == "post-put-flush":
                event.listen(session, "before_flush", fail_post_put_flush)
            else:
                event.listen(session, "before_commit", fail_request_commit)
            yield session

    app.dependency_overrides[get_session] = failing_session
    sensitive_content = b"customer-secret-must-not-survive-transaction-failure"
    with pytest.raises(RuntimeError, match=failure_message), TestClient(app) as client:
        client.post(
            f"/api/engagements/{engagement_id}/evidence",
            data={
                "source_key": SOURCE_KEY,
                "workflow_class": WORKFLOW_CLASS,
                "data_classification": "CONFIDENTIAL",
            },
            files={"file": ("bounded.md", sensitive_content, "text/markdown")},
        )

    assert store.objects == {}
    assert store.stored_version_count == 0
    with operator_session(owner.id) as session:
        assert session.scalar(
            select(EvidenceAsset).where(EvidenceAsset.engagement_id == engagement_id)
        ) is None
        assert list(
            session.scalars(
                select(CustomerDataAccessEvent).where(
                    CustomerDataAccessEvent.engagement_id == engagement_id
                )
            )
        ) == []


@pytest.mark.integration
@pytest.mark.isolation
def test_qualified_records_delete_only_with_their_parent_engagement(
    postgres_available: None,
) -> None:
    owner = _create_operator("cascade-owner")
    engagement_id = _create_sanitized_engagement(owner, "Cascade partner")
    qualification_id, _ = _qualify(engagement_id, owner.id)

    with operator_session(owner.id) as session:
        engagement = session.get_one(Engagement, engagement_id)
        operator = session.get_one(Operator, owner.id)
        decision = authorize_qualified_document_upload(
            session,
            engagement=engagement,
            operator=operator,
            source_key=SOURCE_KEY,
            workflow_class=WORKFLOW_CLASS,
            data_classification="CONFIDENTIAL",
            content_type="text/plain",
            extraction_provider="bedrock",
            provider_allowed_classifications={"CONFIDENTIAL"},
        )
        assert decision.context is not None
        asset = create_evidence_asset(
            session,
            InMemoryEvidenceStore(),
            engagement_id=engagement_id,
            operator=operator,
            file_name="cascade.txt",
            content_type="text/plain",
            content=b"Delete only with the parent engagement.",
            design_partner_qualification_id=qualification_id,
            authorized_source_key=SOURCE_KEY,
            authorized_workflow_class=WORKFLOW_CLASS,
            data_classification="CONFIDENTIAL",
        )
        event = record_customer_data_access_outcome(
            session,
            context=decision.context,
            outcome="AUTHORIZED",
            decision_code="AUTHORIZED",
            evidence_asset_id=asset.id,
        )
        asset_id = asset.id
        event_id = event.id

    with operator_session(owner.id) as session:
        session.delete(session.get_one(Engagement, engagement_id))
        session.flush()

    engine = create_engine(get_settings().migration_database_url)
    try:
        with Session(engine) as session:
            assert session.get(DesignPartnerQualification, qualification_id) is None
            assert session.get(EvidenceAsset, asset_id) is None
            assert session.get(CustomerDataAccessEvent, event_id) is None
    finally:
        engine.dispose()
