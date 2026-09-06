from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy.orm import Session

import ai_fde.modules.factory_engineer.retrieval as retrieval
from ai_fde.modules.design_partner.service import DesignPartnerQualificationError
from ai_fde.modules.factory_engineer.retrieval import AuthenticatedRetrievalPrincipal
from ai_fde.modules.factory_engineer.schemas import FactoryDeploymentPackageStatus


class _ScalarSession:
    def __init__(self, values: list[object], labels: list[str], order: list[str]) -> None:
        self._values = iter(values)
        self._labels = iter(labels)
        self._order = order

    def scalar(self, _statement: object) -> object:
        self._order.append(next(self._labels))
        return next(self._values)


def test_retrieval_uses_a_fresh_decision_time_after_locks_and_integrity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    decision_time = datetime(2026, 9, 4, 20, 0, tzinfo=UTC)
    engagement_id = uuid.uuid4()
    digest = "sha256:" + ("a" * 64)
    engagement = SimpleNamespace(
        data_lifecycle_status="active",
        data_classification="synthetic",
    )
    package = SimpleNamespace(
        id=uuid.uuid4(),
        engagement_id=engagement_id,
        package_id=uuid.uuid4(),
        package_version=1,
        status=FactoryDeploymentPackageStatus.PUBLISHED,
        target={
            "repository_ref": "github.com/sellerfi/marketplace",
            "semantic_execution_workflow_ref": "software-change/verified-pr/v1",
        },
        digest=digest,
        approval_binding={},
        published_at=decision_time,
    )
    principal = AuthenticatedRetrievalPrincipal(
        operator_id=uuid.uuid4(),
        grant_id=uuid.uuid4(),
        engagement_id=engagement_id,
        requester_identity="mission-control-workspace:sellerfi-production",
        requester_system="mission-control",
    )
    grant = SimpleNamespace(
        id=principal.grant_id,
        service_operator_id=principal.operator_id,
        engagement_id=principal.engagement_id,
        revoked_at=None,
        expires_at=decision_time + timedelta(minutes=5),
        scope=retrieval.RETRIEVAL_SCOPE,
    )
    session = cast(
        Session,
        _ScalarSession(
            [engagement, package, grant],
            ["engagement-lock", "package-read", "grant-recheck"],
            order,
        ),
    )
    envelope = SimpleNamespace(package_id=package.package_id)

    class _DecisionClock:
        @classmethod
        def now(cls, timezone: object) -> datetime:
            assert timezone is UTC
            order.append("decision-time")
            return decision_time

    def _calculate_digest(_package: object) -> str:
        order.append("integrity")
        return digest

    def _require_eligibility(
        _session: object,
        *,
        engagement_id: uuid.UUID,
        target: dict[str, object],
        now: datetime,
    ) -> None:
        assert engagement_id == package.engagement_id
        assert target == package.target
        assert now == decision_time
        order.append("eligibility")

    def _build_envelope(
        _package: object,
        *,
        published_at: datetime,
        retrieved_at: datetime,
        correlation_id: uuid.UUID,
    ) -> object:
        assert published_at == package.published_at
        assert retrieved_at == decision_time
        assert isinstance(correlation_id, uuid.UUID)
        order.append("envelope")
        return envelope

    def _record(*_args: object, **_kwargs: object) -> None:
        order.append("audit")

    monkeypatch.setattr(retrieval, "datetime", _DecisionClock)
    monkeypatch.setattr(retrieval, "_calculate_package_digest", _calculate_digest)
    monkeypatch.setattr(retrieval, "require_package_publication_eligibility", _require_eligibility)
    monkeypatch.setattr(retrieval, "published_package_envelope", _build_envelope)
    monkeypatch.setattr(retrieval, "_record_retrieval", _record)
    monkeypatch.setattr(
        retrieval,
        "RetrievalDecision",
        lambda **values: SimpleNamespace(**values),
    )

    decision = retrieval.retrieve_published_package(
        session,
        package_id=package.package_id,
        package_version=package.package_version,
        principal=principal,
        runtime_authority_check=lambda _timestamp: None,
    )

    assert decision.allowed is True
    assert cast(object, decision.package) is envelope
    assert order == [
        "engagement-lock",
        "package-read",
        "integrity",
        "grant-recheck",
        "decision-time",
        "eligibility",
        "envelope",
        "audit",
    ]


def test_locked_retrieval_grant_expires_at_the_exact_decision_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decision_time = datetime(2026, 9, 4, 20, 0, tzinfo=UTC)
    principal = AuthenticatedRetrievalPrincipal(
        operator_id=uuid.uuid4(),
        grant_id=uuid.uuid4(),
        engagement_id=uuid.uuid4(),
        requester_identity="mission-control-workspace:sellerfi-production",
        requester_system="mission-control",
    )
    grant = SimpleNamespace(
        revoked_at=None,
        expires_at=decision_time,
        scope=retrieval.RETRIEVAL_SCOPE,
    )
    order: list[str] = []
    session = cast(Session, _ScalarSession([grant], ["grant-recheck"], order))
    denials: list[str] = []
    monkeypatch.setattr(
        retrieval,
        "_record_authentication_denial",
        lambda _session, _grant, result: denials.append(result),
    )

    result = retrieval._revalidate_locked_retrieval_grant(
        session,
        principal=principal,
        now=decision_time,
    )

    assert result == "EXPIRED_TOKEN"
    assert order == ["grant-recheck"]
    assert denials == ["EXPIRED_TOKEN"]


def test_retrieval_denies_a_grant_that_expires_during_integrity_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    expires_at = datetime(2026, 9, 4, 20, 0, tzinfo=UTC)
    request_started_at = expires_at - timedelta(microseconds=1)
    engagement_id = uuid.uuid4()
    digest = "sha256:" + ("b" * 64)
    engagement = SimpleNamespace(
        data_lifecycle_status="active",
        data_classification="synthetic",
    )
    package = SimpleNamespace(
        id=uuid.uuid4(),
        engagement_id=engagement_id,
        package_id=uuid.uuid4(),
        package_version=1,
        status=FactoryDeploymentPackageStatus.PUBLISHED,
        target={},
        digest=digest,
        approval_binding={},
        published_at=request_started_at,
    )
    principal = AuthenticatedRetrievalPrincipal(
        operator_id=uuid.uuid4(),
        grant_id=uuid.uuid4(),
        engagement_id=engagement_id,
        requester_identity="mission-control-workspace:sellerfi-production",
        requester_system="mission-control",
    )
    grant = SimpleNamespace(
        revoked_at=None,
        expires_at=expires_at,
        scope=retrieval.RETRIEVAL_SCOPE,
    )
    session = cast(
        Session,
        _ScalarSession(
            [engagement, package, grant],
            ["engagement-lock", "package-read", "grant-recheck"],
            order,
        ),
    )
    denials: list[str] = []

    class _AdvancingClock:
        @classmethod
        def now(cls, timezone: object) -> datetime:
            assert timezone is UTC
            timestamp = expires_at if "integrity" in order else request_started_at
            order.append("decision-time")
            return timestamp

    def _calculate_digest(_package: object) -> str:
        order.append("integrity")
        return digest

    monkeypatch.setattr(retrieval, "datetime", _AdvancingClock)
    monkeypatch.setattr(retrieval, "_calculate_package_digest", _calculate_digest)
    monkeypatch.setattr(
        retrieval,
        "_record_authentication_denial",
        lambda _session, _grant, result: denials.append(result),
    )
    monkeypatch.setattr(
        retrieval,
        "require_package_publication_eligibility",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Expired grants must fail before qualification access.")
        ),
    )
    monkeypatch.setattr(
        retrieval,
        "published_package_envelope",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Expired grants must not form a package envelope.")
        ),
    )
    monkeypatch.setattr(
        retrieval,
        "RetrievalDecision",
        lambda **values: SimpleNamespace(**values),
    )

    decision = retrieval.retrieve_published_package(
        session,
        package_id=package.package_id,
        package_version=package.package_version,
        principal=principal,
        runtime_authority_check=lambda _timestamp: None,
    )

    assert decision.allowed is False
    assert decision.result == "EXPIRED_TOKEN"
    assert not hasattr(decision, "package")
    assert denials == ["EXPIRED_TOKEN"]
    assert order == [
        "engagement-lock",
        "package-read",
        "integrity",
        "grant-recheck",
        "decision-time",
    ]


def test_sanitized_retrieval_rechecks_runtime_authority_at_the_locked_decision_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    decision_time = datetime(2026, 9, 4, 20, 0, tzinfo=UTC)
    engagement_id = uuid.uuid4()
    digest = "sha256:" + ("c" * 64)
    engagement = SimpleNamespace(
        id=engagement_id,
        data_lifecycle_status="active",
        data_classification="sanitized",
    )
    package = SimpleNamespace(
        id=uuid.uuid4(),
        engagement_id=engagement_id,
        package_id=uuid.uuid4(),
        package_version=1,
        status=FactoryDeploymentPackageStatus.PUBLISHED,
        target={},
        digest=digest,
        approval_binding={},
        published_at=decision_time,
    )
    principal = AuthenticatedRetrievalPrincipal(
        operator_id=uuid.uuid4(),
        grant_id=uuid.uuid4(),
        engagement_id=engagement_id,
        requester_identity="mission-control-workspace:sellerfi-production",
        requester_system="mission-control",
    )
    grant = SimpleNamespace(
        revoked_at=None,
        expires_at=decision_time + timedelta(minutes=5),
        scope=retrieval.RETRIEVAL_SCOPE,
    )
    session = cast(
        Session,
        _ScalarSession(
            [engagement, package, grant],
            [
                "engagement-lock",
                "package-read",
                "grant-recheck",
            ],
            order,
        ),
    )

    class _DecisionClock:
        @classmethod
        def now(cls, timezone: object) -> datetime:
            assert timezone is UTC
            order.append("decision-time")
            return decision_time

    def runtime_authority_check(now: datetime) -> None:
        assert now == decision_time
        order.append("runtime-authority")
        raise DesignPartnerQualificationError("expired deployment qualification")

    def calculate_digest(_package: object) -> str:
        order.append("integrity")
        return digest

    def lock_authority(*_args: object, **_kwargs: object) -> bool:
        order.append("qualification-lock")
        return True

    monkeypatch.setattr(retrieval, "datetime", _DecisionClock)
    monkeypatch.setattr(
        retrieval,
        "_calculate_package_digest",
        calculate_digest,
    )
    monkeypatch.setattr(
        retrieval,
        "require_package_publication_eligibility",
        lambda *_args, **_kwargs: order.append("qualification-eligibility"),
    )
    monkeypatch.setattr(
        retrieval,
        "lock_design_partner_authority",
        lock_authority,
    )
    monkeypatch.setattr(
        retrieval,
        "published_package_envelope",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("A denied runtime must not form a package envelope.")
        ),
    )
    monkeypatch.setattr(
        retrieval,
        "_record_retrieval",
        lambda *_args, **_kwargs: order.append("denial-audit"),
    )
    monkeypatch.setattr(
        retrieval,
        "RetrievalDecision",
        lambda **values: SimpleNamespace(**values),
    )

    decision = retrieval.retrieve_published_package(
        session,
        package_id=package.package_id,
        package_version=package.package_version,
        principal=principal,
        runtime_authority_check=runtime_authority_check,
    )

    assert decision.allowed is False
    assert decision.result == "DENIED_QUALIFICATION"
    assert not hasattr(decision, "package")
    assert order == [
        "engagement-lock",
        "package-read",
        "integrity",
        "grant-recheck",
        "qualification-lock",
        "decision-time",
        "qualification-eligibility",
        "runtime-authority",
        "denial-audit",
    ]
