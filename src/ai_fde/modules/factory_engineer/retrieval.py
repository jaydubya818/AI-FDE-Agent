from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_fde.models import Engagement, EngagementMember, Operator
from ai_fde.modules.factory_engineer.models import (
    FactoryDeploymentPackageVersion,
    PackageRetrievalEvent,
    PackageRetrievalGrant,
)
from ai_fde.modules.factory_engineer.schemas import (
    FactoryDeploymentPackageStatus,
    RetrievalDecision,
)
from ai_fde.modules.factory_engineer.service import (
    _calculate_package_digest,
    _require_engagement_owner,
    _require_human,
    published_package_envelope,
)
from ai_fde.modules.shared import record_audit

TOKEN_PREFIX = "fdp1"
RETRIEVAL_SCOPE = "deployment-packages:retrieve"


@dataclass(frozen=True)
class RetrievalTokenSubject:
    operator_id: UUID
    grant_id: UUID


@dataclass(frozen=True)
class AuthenticatedRetrievalPrincipal:
    operator_id: UUID
    grant_id: UUID
    engagement_id: UUID
    requester_identity: str
    requester_system: str


@dataclass(frozen=True)
class IssuedRetrievalGrant:
    grant: PackageRetrievalGrant
    token: str


@dataclass(frozen=True)
class RetrievalAuthenticationDecision:
    authenticated: bool
    result: str
    principal: AuthenticatedRetrievalPrincipal | None


def provision_retrieval_service_identity(
    session: Session,
    *,
    engagement_id: UUID,
    created_by: Operator,
) -> Operator:
    """Provision or reuse the one least-privilege retrieval identity for an engagement."""

    engagement = session.scalar(
        select(Engagement).where(Engagement.id == engagement_id).with_for_update()
    )
    if engagement is None or engagement.data_lifecycle_status != "active":
        raise ValueError(
            "Retrieval identity provisioning is unavailable while deletion is pending or failed."
        )
    # create_engagement may have staged the owner's membership in this transaction.
    session.flush()
    _require_human(created_by, "Retrieval identity provisioning")
    _require_engagement_owner(
        session, engagement_id, created_by, "Retrieval identity provisioning"
    )
    external_subject = f"factory-package-retrieval:{engagement_id}"
    service_operator = session.scalar(
        select(Operator).where(Operator.external_subject == external_subject)
    )
    created = False
    if service_operator is None:
        service_operator = Operator(
            external_subject=external_subject,
            display_name=f"Package retrieval — {engagement.name}"[:255],
            identity_kind="service",
            is_active=True,
        )
        session.add(service_operator)
        session.flush()
        created = True
    if service_operator.identity_kind != "service" or not service_operator.is_active:
        raise ValueError("The engagement retrieval identity is not an active service identity.")
    foreign_membership = session.scalar(
        select(EngagementMember).where(
            EngagementMember.operator_id == service_operator.id,
            EngagementMember.engagement_id != engagement_id,
        )
    )
    if foreign_membership is not None:
        raise ValueError("A package retrieval identity cannot be shared between engagements.")
    membership = session.scalar(
        select(EngagementMember).where(
            EngagementMember.engagement_id == engagement_id,
            EngagementMember.operator_id == service_operator.id,
        )
    )
    if membership is None:
        session.add(
            EngagementMember(
                engagement_id=engagement_id,
                operator_id=service_operator.id,
                role="viewer",
            )
        )
        session.flush()
        created = True
    elif membership.role != "viewer":
        raise ValueError("A package retrieval identity must have viewer-only membership.")
    if created:
        record_audit(
            session,
            engagement_id=engagement_id,
            actor_id=created_by.id,
            action="deployment_package.retrieval_identity_provisioned",
            target_type="service_identity",
            target_id=service_operator.id,
            detail={"role": "viewer"},
        )
    return service_operator


def issue_retrieval_grant(
    session: Session,
    *,
    engagement_id: UUID,
    service_operator: Operator,
    created_by: Operator,
    requester_identity: str,
    requester_system: str,
    expires_at: datetime,
    now: datetime | None = None,
) -> IssuedRetrievalGrant:
    timestamp = now or datetime.now(UTC)
    if service_operator.identity_kind != "service" or not service_operator.is_active:
        raise ValueError("Package retrieval grants require an active service operator.")
    engagement = session.scalar(
        select(Engagement).where(Engagement.id == engagement_id).with_for_update()
    )
    if engagement is None or engagement.data_lifecycle_status != "active":
        raise ValueError(
            "Retrieval grants are unavailable while engagement deletion is pending or failed."
        )
    _require_human(created_by, "Retrieval grant issuance")
    _require_engagement_owner(session, engagement_id, created_by, "Retrieval grant issuance")
    membership = session.scalar(
        select(EngagementMember).where(
            EngagementMember.engagement_id == engagement_id,
            EngagementMember.operator_id == service_operator.id,
        )
    )
    if membership is None or membership.role != "viewer":
        raise ValueError(
            "The service operator must have viewer-only membership in the engagement."
        )
    if session.scalar(
        select(EngagementMember.id).where(
            EngagementMember.operator_id == service_operator.id,
            EngagementMember.engagement_id != engagement_id,
        )
    ) is not None:
        raise ValueError("A package retrieval identity cannot be shared between engagements.")
    if expires_at <= timestamp:
        raise ValueError("Retrieval grant expiry must be in the future.")
    clean_identity = requester_identity.strip()
    clean_system = requester_system.strip()
    if not clean_identity or not clean_system:
        raise ValueError("Requester identity and system are required.")

    grant_id = uuid.uuid4()
    secret = secrets.token_urlsafe(32)
    token = f"{TOKEN_PREFIX}.{service_operator.id.hex}.{grant_id.hex}.{secret}"
    grant = PackageRetrievalGrant(
        id=grant_id,
        engagement_id=engagement_id,
        service_operator_id=service_operator.id,
        requester_identity=clean_identity,
        requester_system=clean_system,
        token_digest=_token_digest(token),
        scope=RETRIEVAL_SCOPE,
        expires_at=expires_at,
        created_by_id=created_by.id,
    )
    session.add(grant)
    session.flush()
    record_audit(
        session,
        engagement_id=engagement_id,
        actor_id=created_by.id,
        action="deployment_package.retrieval_grant_issued",
        target_type="package_retrieval_grant",
        target_id=grant.id,
        detail={
            "service_operator_id": str(service_operator.id),
            "requester_identity": clean_identity,
            "requester_system": clean_system,
            "expires_at": expires_at.isoformat(),
        },
    )
    return IssuedRetrievalGrant(grant=grant, token=token)


def parse_retrieval_token_subject(token: str) -> RetrievalTokenSubject | None:
    if len(token) > 512:
        return None
    parts = token.split(".")
    if len(parts) != 4 or parts[0] != TOKEN_PREFIX or not parts[3]:
        return None
    try:
        return RetrievalTokenSubject(
            operator_id=UUID(hex=parts[1]),
            grant_id=UUID(hex=parts[2]),
        )
    except ValueError:
        return None


def authenticate_retrieval_token(
    session: Session, *, token: str, now: datetime | None = None
) -> RetrievalAuthenticationDecision:
    """Validate a token after the caller has applied its embedded operator RLS context."""

    subject = parse_retrieval_token_subject(token)
    if subject is None:
        return RetrievalAuthenticationDecision(False, "INVALID_TOKEN", None)
    candidate_digest = _token_digest(token)
    grant_engagement_id = session.scalar(
        select(PackageRetrievalGrant.engagement_id).where(
            PackageRetrievalGrant.id == subject.grant_id,
            PackageRetrievalGrant.service_operator_id == subject.operator_id,
        )
    )
    if grant_engagement_id is None:
        hmac.compare_digest("0" * 64, candidate_digest)
        return RetrievalAuthenticationDecision(False, "INVALID_TOKEN", None)
    engagement = session.scalar(
        select(Engagement).where(Engagement.id == grant_engagement_id).with_for_update()
    )
    if engagement is None or engagement.data_lifecycle_status != "active":
        return RetrievalAuthenticationDecision(False, "ENGAGEMENT_UNAVAILABLE", None)
    grant = session.scalar(
        select(PackageRetrievalGrant)
        .where(
            PackageRetrievalGrant.id == subject.grant_id,
            PackageRetrievalGrant.service_operator_id == subject.operator_id,
            PackageRetrievalGrant.engagement_id == grant_engagement_id,
        )
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if grant is None:
        hmac.compare_digest("0" * 64, candidate_digest)
        return RetrievalAuthenticationDecision(False, "INVALID_TOKEN", None)
    digest_matches = hmac.compare_digest(grant.token_digest, candidate_digest)
    if not digest_matches:
        _record_authentication_denial(session, grant, "INVALID_TOKEN", authenticated=False)
        return RetrievalAuthenticationDecision(False, "INVALID_TOKEN", None)
    timestamp = now or datetime.now(UTC)
    if grant.revoked_at is not None:
        _record_authentication_denial(session, grant, "REVOKED_TOKEN")
        return RetrievalAuthenticationDecision(False, "REVOKED_TOKEN", None)
    if grant.expires_at <= timestamp:
        _record_authentication_denial(session, grant, "EXPIRED_TOKEN")
        return RetrievalAuthenticationDecision(False, "EXPIRED_TOKEN", None)
    if grant.scope != RETRIEVAL_SCOPE:
        _record_authentication_denial(session, grant, "INVALID_SCOPE")
        return RetrievalAuthenticationDecision(False, "INVALID_SCOPE", None)
    operator = session.get(Operator, grant.service_operator_id)
    if operator is None or operator.identity_kind != "service" or not operator.is_active:
        _record_authentication_denial(session, grant, "INACTIVE_SERVICE_IDENTITY")
        return RetrievalAuthenticationDecision(False, "INACTIVE_SERVICE_IDENTITY", None)
    membership = session.scalar(
        select(EngagementMember).where(
            EngagementMember.engagement_id == grant.engagement_id,
            EngagementMember.operator_id == grant.service_operator_id,
        )
    )
    if membership is None or membership.role != "viewer":
        _record_authentication_denial(session, grant, "INVALID_SERVICE_MEMBERSHIP")
        return RetrievalAuthenticationDecision(False, "INVALID_SERVICE_MEMBERSHIP", None)
    return RetrievalAuthenticationDecision(
        True,
        "AUTHENTICATED",
        AuthenticatedRetrievalPrincipal(
            operator_id=grant.service_operator_id,
            grant_id=grant.id,
            engagement_id=grant.engagement_id,
            requester_identity=grant.requester_identity,
            requester_system=grant.requester_system,
        ),
    )


def revoke_retrieval_grant(
    session: Session,
    *,
    engagement_id: UUID,
    grant_id: UUID,
    revoked_by: Operator,
    now: datetime | None = None,
) -> PackageRetrievalGrant:
    engagement = session.scalar(
        select(Engagement).where(Engagement.id == engagement_id).with_for_update()
    )
    if engagement is None or engagement.data_lifecycle_status != "active":
        raise ValueError(
            "Retrieval grants cannot change while engagement deletion is pending or failed."
        )
    _require_human(revoked_by, "Retrieval grant revocation")
    _require_engagement_owner(session, engagement_id, revoked_by, "Retrieval grant revocation")
    grant = session.scalar(
        select(PackageRetrievalGrant)
        .where(
            PackageRetrievalGrant.id == grant_id,
            PackageRetrievalGrant.engagement_id == engagement_id,
        )
        .with_for_update()
    )
    if grant is None:
        raise LookupError(str(grant_id))
    if grant.revoked_at is None:
        grant.revoked_at = now or datetime.now(UTC)
        record_audit(
            session,
            engagement_id=engagement_id,
            actor_id=revoked_by.id,
            action="deployment_package.retrieval_grant_revoked",
            target_type="package_retrieval_grant",
            target_id=grant.id,
            detail={"service_operator_id": str(grant.service_operator_id)},
        )
    return grant


def retrieve_published_package(
    session: Session,
    *,
    package_id: UUID,
    package_version: int,
    principal: AuthenticatedRetrievalPrincipal,
    correlation_id: UUID | None = None,
    now: datetime | None = None,
) -> RetrievalDecision:
    """Return a non-throwing decision and stage its audit event in the caller's transaction."""

    correlation = correlation_id or uuid.uuid4()
    timestamp = now or datetime.now(UTC)
    engagement = session.scalar(
        select(Engagement).where(Engagement.id == principal.engagement_id).with_for_update()
    )
    if engagement is None or engagement.data_lifecycle_status != "active":
        return RetrievalDecision(
            allowed=False,
            result="ENGAGEMENT_UNAVAILABLE",
            correlation_id=correlation,
        )
    package = session.scalar(
        select(FactoryDeploymentPackageVersion).where(
            FactoryDeploymentPackageVersion.engagement_id == principal.engagement_id,
            FactoryDeploymentPackageVersion.package_id == package_id,
            FactoryDeploymentPackageVersion.package_version == package_version,
        )
    )
    if package is None:
        _record_not_found(
            session,
            package_id=package_id,
            package_version=package_version,
            principal=principal,
            correlation_id=correlation,
        )
        return RetrievalDecision(
            allowed=False,
            result="NOT_FOUND",
            correlation_id=correlation,
        )
    if package.status == FactoryDeploymentPackageStatus.STALE:
        return _denied(session, package, principal, correlation, "DENIED_STALE")
    if package.status == FactoryDeploymentPackageStatus.REVOKED:
        return _denied(session, package, principal, correlation, "DENIED_REVOKED")
    if package.status != FactoryDeploymentPackageStatus.PUBLISHED:
        return _denied(session, package, principal, correlation, "DENIED_NOT_PUBLISHED")
    try:
        expected_digest = _calculate_package_digest(package)
        if package.digest is None or not hmac.compare_digest(package.digest, expected_digest):
            return _denied(session, package, principal, correlation, "DENIED_INTEGRITY")
        if package.approval_binding is None or package.published_at is None:
            return _denied(session, package, principal, correlation, "DENIED_INTEGRITY")
        envelope = published_package_envelope(
            package,
            published_at=package.published_at,
            retrieved_at=timestamp,
            correlation_id=correlation,
        )
    except (KeyError, TypeError, ValueError):
        return _denied(session, package, principal, correlation, "DENIED_INTEGRITY")
    _record_retrieval(session, package, principal, correlation, "RETRIEVED")
    return RetrievalDecision(
        allowed=True,
        result="RETRIEVED",
        correlation_id=correlation,
        package=envelope,
    )


def _denied(
    session: Session,
    package: FactoryDeploymentPackageVersion,
    principal: AuthenticatedRetrievalPrincipal,
    correlation_id: UUID,
    result: str,
) -> RetrievalDecision:
    _record_retrieval(session, package, principal, correlation_id, result)
    return RetrievalDecision(allowed=False, result=result, correlation_id=correlation_id)


def _record_retrieval(
    session: Session,
    package: FactoryDeploymentPackageVersion,
    principal: AuthenticatedRetrievalPrincipal,
    correlation_id: UUID,
    result: str,
) -> None:
    session.add(
        PackageRetrievalEvent(
            engagement_id=package.engagement_id,
            package_version_id=package.id,
            package_id=package.package_id,
            package_version=package.package_version,
            requester_identity=principal.requester_identity,
            requester_system=principal.requester_system,
            result=result,
            digest=package.digest,
            correlation_id=correlation_id,
        )
    )
    record_audit(
        session,
        engagement_id=package.engagement_id,
        actor_id=principal.operator_id,
        actor_type="service",
        action="deployment_package.retrieval_decided",
        target_type="factory_deployment_package_version",
        target_id=package.id,
        detail={
            "package_id": str(package.package_id),
            "package_version": package.package_version,
            "requester_system": principal.requester_system,
            "result": result,
            "digest": package.digest,
            "correlation_id": str(correlation_id),
        },
    )


def _record_not_found(
    session: Session,
    *,
    package_id: UUID,
    package_version: int,
    principal: AuthenticatedRetrievalPrincipal,
    correlation_id: UUID,
) -> None:
    session.add(
        PackageRetrievalEvent(
            engagement_id=principal.engagement_id,
            package_version_id=None,
            package_id=package_id,
            package_version=package_version,
            requester_identity=principal.requester_identity,
            requester_system=principal.requester_system,
            result="NOT_FOUND",
            digest=None,
            correlation_id=correlation_id,
        )
    )
    record_audit(
        session,
        engagement_id=principal.engagement_id,
        actor_id=principal.operator_id,
        actor_type="service",
        action="deployment_package.retrieval_decided",
        target_type="factory_deployment_package",
        target_id=package_id,
        detail={
            "package_id": str(package_id),
            "package_version": package_version,
            "requester_system": principal.requester_system,
            "result": "NOT_FOUND",
            "digest": None,
            "correlation_id": str(correlation_id),
        },
    )


def _record_authentication_denial(
    session: Session,
    grant: PackageRetrievalGrant,
    result: str,
    *,
    authenticated: bool = True,
) -> None:
    record_audit(
        session,
        engagement_id=grant.engagement_id,
        actor_id=grant.service_operator_id if authenticated else UUID(int=0),
        actor_type="service" if authenticated else "unauthenticated",
        action="deployment_package.retrieval_authentication_denied",
        target_type="package_retrieval_grant",
        target_id=grant.id,
        detail={
            "credential_authenticated": authenticated,
            "requester_system": grant.requester_system,
            "result": result,
        },
    )


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
