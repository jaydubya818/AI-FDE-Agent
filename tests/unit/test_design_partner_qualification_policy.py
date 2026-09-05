from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

import ai_fde.modules.design_partner.service as design_partner_service
from ai_fde.config import Settings
from ai_fde.modules.design_partner.service import (
    DesignPartnerQualificationError,
    normalize_data_classification,
    normalize_partner_key,
    normalize_reference,
    normalize_source_key,
)


def test_qualification_identifiers_are_bounded_and_not_arbitrary_urls() -> None:
    assert normalize_partner_key(" SellerFi-Pilot ") == "sellerfi-pilot"
    assert normalize_source_key(" Approved-Manual ") == "approved-manual"
    assert normalize_reference("github.com/sellerfi/marketplace") == (
        "github.com/sellerfi/marketplace"
    )
    assert normalize_data_classification("confidential") == "CONFIDENTIAL"

    for unsafe in (
        "https://customer.example/private",
        "repo with whitespace",
        "token@example.com",
    ):
        with pytest.raises(DesignPartnerQualificationError):
            normalize_reference(unsafe)


def test_bedrock_classification_allowlist_excludes_restricted() -> None:
    settings = Settings(
        extraction_provider="bedrock",
        bedrock_model_id="us.anthropic.claude-qualified-v1:0",
        bedrock_allowed_data_classifications=["CONFIDENTIAL", "PUBLIC", "PUBLIC"],
    )
    assert settings.bedrock_allowed_data_classifications == ["CONFIDENTIAL", "PUBLIC"]

    with pytest.raises(ValidationError):
        Settings(
            extraction_provider="bedrock",
            bedrock_model_id="us.anthropic.claude-qualified-v1:0",
            bedrock_allowed_data_classifications=["RESTRICTED"],  # type: ignore[list-item]
        )


def test_qualification_transition_locks_the_engagement_before_the_qualification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engagement_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    engagement = SimpleNamespace(id=engagement_id)
    qualification = SimpleNamespace(
        id=uuid.uuid4(),
        engagement_id=engagement_id,
        status="ACTIVE",
        qualification_state="QUALIFIED",
        authorization_basis_ref="qualification-record:existing",
    )
    actor = SimpleNamespace(id=actor_id)
    session = MagicMock(spec=Session)
    session.scalar.side_effect = [engagement, qualification]
    monkeypatch.setattr(
        design_partner_service,
        "_require_active_human_owner",
        lambda _session, _engagement_id, _actor_id: actor,
    )
    monkeypatch.setattr(
        design_partner_service,
        "_record_qualification_change",
        lambda *_args, **_kwargs: None,
    )

    result = design_partner_service.transition_design_partner_qualification(
        session,
        engagement_id=engagement_id,
        status="SUSPENDED",
        authorization_basis_ref="qualification-record:suspension",
        actor_id=actor_id,
    )

    statements = [call.args[0] for call in session.scalar.call_args_list]
    assert len(statements) == 2
    engagement_lock_sql = str(statements[0])
    qualification_lock_sql = str(statements[1])
    assert "FROM engagements" in engagement_lock_sql
    assert "FOR UPDATE" in engagement_lock_sql
    assert "FROM design_partner_qualifications" in qualification_lock_sql
    assert "FOR UPDATE" in qualification_lock_sql
    assert result.status == "SUSPENDED"


def test_upload_reauthorization_refreshes_aggregate_then_qualification_before_time_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engagement_id = uuid.uuid4()
    operator_id = uuid.uuid4()
    decision_time = datetime(2026, 9, 4, 20, 0, tzinfo=UTC)
    engagement = SimpleNamespace(
        id=engagement_id,
        data_classification="sanitized",
        data_lifecycle_status="active",
        retention_expires_at=decision_time + timedelta(hours=1),
    )
    qualification = SimpleNamespace(
        id=uuid.uuid4(),
        engagement_id=engagement_id,
        partner_key="sellerfi-phase-3",
        status="ACTIVE",
        qualification_state="QUALIFIED",
        authorized_data_source_keys=["bounded-document"],
        allowed_workflow_classes=["software-change/verified-pr/v1"],
        data_classification="CONFIDENTIAL",
        retention_expires_at=decision_time + timedelta(hours=1),
        authorization_basis_ref="qualification-record:phase-3",
    )
    operator = SimpleNamespace(id=operator_id)
    session = MagicMock(spec=Session)
    order: list[str] = []

    class _DecisionClock:
        @classmethod
        def now(cls, timezone: object) -> datetime:
            assert timezone is UTC
            order.append("decision-time")
            return decision_time

    def scalar(statement: object) -> object:
        if not order:
            order.append("aggregate-lock")
            return True
        if order == ["aggregate-lock"]:
            order.append("engagement-refresh")
            return engagement
        order.append("qualification-refresh")
        return qualification

    session.scalar.side_effect = scalar
    monkeypatch.setattr(design_partner_service, "datetime", _DecisionClock)

    def verify_deployment(*, now: datetime) -> object:
        assert now == decision_time
        order.append("deployment-check")
        return object()

    decision = design_partner_service.reauthorize_qualified_document_upload(
        session,
        engagement_id=engagement_id,
        operator=operator,  # type: ignore[arg-type]
        source_key="bounded-document",
        workflow_class="software-change/verified-pr/v1",
        data_classification="CONFIDENTIAL",
        content_type="text/markdown",
        extraction_provider="bedrock",
        provider_allowed_classifications={"CONFIDENTIAL"},
        correlation_id=uuid.uuid4(),
        deployment_authority_check=verify_deployment,
    )

    statements = [call.args[0] for call in session.scalar.call_args_list]
    assert order == [
        "aggregate-lock",
        "engagement-refresh",
        "qualification-refresh",
        "decision-time",
        "deployment-check",
    ]
    assert "ai_fde_lock_design_partner_authority" in str(statements[0])
    assert "write" in statements[0].compile().params.values()
    assert "FROM engagements" in str(statements[1])
    assert "FOR UPDATE" not in str(statements[1])
    assert statements[1].get_execution_options()["populate_existing"] is True
    assert "FROM design_partner_qualifications" in str(statements[2])
    assert "FOR UPDATE" not in str(statements[2])
    assert statements[2].get_execution_options()["populate_existing"] is True
    assert decision.allowed is True
    assert decision.context is not None


def test_upload_reauthorization_fails_closed_when_aggregate_lock_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engagement_id = uuid.uuid4()
    operator_id = uuid.uuid4()
    decision_time = datetime(2026, 9, 4, 20, 0, tzinfo=UTC)
    engagement = SimpleNamespace(
        id=engagement_id,
        data_classification="sanitized",
        data_lifecycle_status="active",
        retention_expires_at=decision_time + timedelta(hours=1),
    )
    qualification = SimpleNamespace(
        id=uuid.uuid4(),
        engagement_id=engagement_id,
        partner_key="sellerfi-phase-3",
        status="ACTIVE",
        qualification_state="QUALIFIED",
        authorized_data_source_keys=["bounded-document"],
        allowed_workflow_classes=["software-change/verified-pr/v1"],
        data_classification="CONFIDENTIAL",
        retention_expires_at=decision_time + timedelta(hours=1),
        authorization_basis_ref="qualification-record:phase-3",
    )
    operator = SimpleNamespace(id=operator_id)
    session = MagicMock(spec=Session)
    session.scalar.side_effect = [False, engagement, qualification]
    monkeypatch.setattr(
        design_partner_service,
        "record_audit",
        lambda *_args, **_kwargs: None,
    )
    deployment_authority_check = MagicMock()

    decision = design_partner_service.reauthorize_qualified_document_upload(
        session,
        engagement_id=engagement_id,
        operator=operator,  # type: ignore[arg-type]
        source_key="bounded-document",
        workflow_class="software-change/verified-pr/v1",
        data_classification="CONFIDENTIAL",
        content_type="text/markdown",
        extraction_provider="bedrock",
        provider_allowed_classifications={"CONFIDENTIAL"},
        correlation_id=uuid.uuid4(),
        deployment_authority_check=deployment_authority_check,
        now=decision_time,
    )

    assert decision.allowed is False
    assert decision.decision_code == "QUALIFICATION_REQUIRED"
    assert decision.context is None
    deployment_authority_check.assert_not_called()
