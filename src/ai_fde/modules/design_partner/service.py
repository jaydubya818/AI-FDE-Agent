from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ai_fde.models import Engagement, EngagementMember, EvidenceAsset, Operator
from ai_fde.modules.design_partner.models import (
    CustomerDataAccessEvent,
    DesignPartnerQualification,
)
from ai_fde.modules.shared import publish_domain_event, record_audit

QualificationStatus = Literal["ACTIVE", "SUSPENDED", "REVOKED"]
QualificationState = Literal["CONFIGURED", "IN_PROGRESS", "BLOCKED", "QUALIFIED"]
DataClassification = Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]
AuthorityLockAccess = Literal["read", "write"]

QUALIFICATION_STATUSES = {"ACTIVE", "SUSPENDED", "REVOKED"}
QUALIFICATION_STATES = {"CONFIGURED", "IN_PROGRESS", "BLOCKED", "QUALIFIED"}
DATA_CLASSIFICATIONS = {"PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"}
QUALIFIED_DOCUMENT_MEDIA_TYPES = {"text/plain", "text/markdown"}
SOURCE_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,119}$")
MAX_AUTHORIZATION_ITEMS = 100

STATUS_TRANSITIONS: dict[str, set[str]] = {
    "ACTIVE": {"SUSPENDED", "REVOKED"},
    "SUSPENDED": {"ACTIVE", "REVOKED"},
    "REVOKED": set(),
}
STATE_TRANSITIONS: dict[str, set[str]] = {
    "CONFIGURED": {"IN_PROGRESS", "BLOCKED"},
    "IN_PROGRESS": {"BLOCKED", "QUALIFIED"},
    "BLOCKED": {"IN_PROGRESS"},
    "QUALIFIED": {"BLOCKED"},
}


class DesignPartnerQualificationError(ValueError):
    """The requested operation is outside the controlled qualification boundary."""


class DesignPartnerQualificationNotFoundError(LookupError):
    pass


class CustomerDataProcessingDeniedError(PermissionError):
    """A queued customer-data job no longer satisfies its qualification."""


class DeploymentAuthorityCheck(Protocol):
    def __call__(self, *, now: datetime) -> object: ...


@dataclass(frozen=True)
class AuthorizedUser:
    operator_id: UUID
    display_name: str
    role: str


@dataclass(frozen=True)
class AuthorizedCustomerDataContext:
    engagement_id: UUID
    qualification_id: UUID
    partner_key: str
    operator_id: UUID
    source_key: str
    workflow_class: str
    data_classification: str
    authorization_basis_ref: str
    correlation_id: UUID


@dataclass(frozen=True)
class CustomerDataAccessDecision:
    allowed: bool
    decision_code: str
    message: str
    correlation_id: UUID
    event_id: UUID | None
    context: AuthorizedCustomerDataContext | None = None


def provision_design_partner_qualification(
    session: Session,
    *,
    engagement_id: UUID,
    partner_key: str,
    organization: str,
    authorized_data_source_keys: list[str],
    authorized_repository_refs: list[str],
    allowed_workflow_classes: list[str],
    data_classification: str,
    retention_days: int,
    authorization_basis_ref: str,
    configured_by_id: UUID,
    now: datetime | None = None,
) -> DesignPartnerQualification:
    timestamp = now or datetime.now(UTC)
    engagement = session.scalar(
        select(Engagement).where(Engagement.id == engagement_id).with_for_update()
    )
    if engagement is None:
        raise DesignPartnerQualificationError("The engagement does not exist.")
    if engagement.data_classification != "sanitized":
        raise DesignPartnerQualificationError(
            "Design-partner qualification is available only for sanitized engagements."
        )
    owner = _require_active_human_owner(session, engagement_id, configured_by_id)

    normalized_partner_key = normalize_partner_key(partner_key)
    normalized_organization = _required_text(organization, "organization", 255)
    normalized_sources = _normalized_items(
        authorized_data_source_keys,
        "authorized data-source key",
        normalizer=normalize_source_key,
    )
    normalized_repositories = _normalized_items(
        authorized_repository_refs,
        "authorized repository reference",
        normalizer=normalize_reference,
    )
    normalized_workflows = _normalized_items(
        allowed_workflow_classes,
        "allowed workflow class",
        normalizer=normalize_reference,
    )
    normalized_classification = normalize_data_classification(data_classification)
    normalized_basis = normalize_reference(authorization_basis_ref)
    if not 1 <= retention_days <= 3650:
        raise DesignPartnerQualificationError("Retention days must be between 1 and 3650.")

    values = {
        "partner_key": normalized_partner_key,
        "organization": normalized_organization,
        "authorized_data_source_keys": normalized_sources,
        "authorized_repository_refs": normalized_repositories,
        "allowed_workflow_classes": normalized_workflows,
        "data_classification": normalized_classification,
        "retention_days": retention_days,
        "authorization_basis_ref": normalized_basis,
    }
    existing = session.scalar(
        select(DesignPartnerQualification).where(
            DesignPartnerQualification.engagement_id == engagement_id
        )
    )
    if existing is not None:
        if all(getattr(existing, key) == value for key, value in values.items()):
            return existing
        raise DesignPartnerQualificationError(
            "The engagement already has a different design-partner qualification."
        )

    maximum_retention = timestamp + timedelta(days=retention_days)
    if engagement.retention_expires_at is None:
        engagement.retention_expires_at = maximum_retention
    else:
        current_retention = _aware_utc(engagement.retention_expires_at)
        if current_retention <= timestamp:
            raise DesignPartnerQualificationError("The engagement retention period has expired.")
        if current_retention > maximum_retention:
            raise DesignPartnerQualificationError(
                "The engagement retention deadline exceeds the qualification policy."
            )

    qualification = DesignPartnerQualification(
        engagement_id=engagement_id,
        status="ACTIVE",
        qualification_state="CONFIGURED",
        configured_by_id=owner.id,
        retention_expires_at=maximum_retention,
        created_at=timestamp,
        updated_at=timestamp,
        **values,
    )
    session.add(qualification)
    session.flush()
    _record_qualification_change(
        session,
        qualification=qualification,
        actor_id=owner.id,
        action="design_partner.qualification_configured",
        detail={
            "status": qualification.status,
            "qualification_state": qualification.qualification_state,
            "data_classification": qualification.data_classification,
            "retention_days": qualification.retention_days,
        },
    )
    return qualification


def transition_design_partner_qualification(
    session: Session,
    *,
    engagement_id: UUID,
    status: str | None = None,
    qualification_state: str | None = None,
    authorization_basis_ref: str,
    actor_id: UUID,
    now: datetime | None = None,
) -> DesignPartnerQualification:
    if status is None and qualification_state is None:
        raise DesignPartnerQualificationError(
            "A status or qualification-state transition is required."
        )
    # Package publication and retrieval use the engagement row as the aggregate
    # serialization boundary. Take that lock before the qualification row so a
    # suspension, revocation, or blocked transition cannot commit between an
    # eligibility decision and the package operation it authorizes.
    engagement = session.scalar(
        select(Engagement).where(Engagement.id == engagement_id).with_for_update()
    )
    if engagement is None:
        raise DesignPartnerQualificationNotFoundError(str(engagement_id))
    qualification = session.scalar(
        select(DesignPartnerQualification)
        .where(DesignPartnerQualification.engagement_id == engagement_id)
        .with_for_update()
    )
    if qualification is None:
        raise DesignPartnerQualificationNotFoundError(str(engagement_id))
    actor = _require_active_human_owner(session, engagement_id, actor_id)
    basis = normalize_reference(authorization_basis_ref)
    previous_status = qualification.status
    previous_state = qualification.qualification_state

    if status is not None:
        normalized_status = status.strip().upper()
        if normalized_status not in QUALIFICATION_STATUSES:
            raise DesignPartnerQualificationError("The qualification status is invalid.")
        if normalized_status != qualification.status:
            if normalized_status not in STATUS_TRANSITIONS[qualification.status]:
                raise DesignPartnerQualificationError(
                    f"Qualification status cannot transition from {qualification.status} "
                    f"to {normalized_status}."
                )
            qualification.status = normalized_status

    if qualification_state is not None:
        normalized_state = qualification_state.strip().upper()
        if normalized_state not in QUALIFICATION_STATES:
            raise DesignPartnerQualificationError("The qualification state is invalid.")
        if normalized_state != qualification.qualification_state:
            if normalized_state not in STATE_TRANSITIONS[qualification.qualification_state]:
                raise DesignPartnerQualificationError(
                    "Qualification state cannot transition from "
                    f"{qualification.qualification_state} to {normalized_state}."
                )
            qualification.qualification_state = normalized_state

    if qualification.qualification_state == "QUALIFIED" and previous_state != "QUALIFIED":
        if qualification.status != "ACTIVE":
            raise DesignPartnerQualificationError(
                "Only an active design partner can become qualified."
            )
        if not qualification_retention_is_authorized(
            engagement,
            qualification,
            now=now,
        ):
            raise DesignPartnerQualificationError(
                "Qualification requires an unexpired engagement retention deadline "
                "within its immutable qualification ceiling."
            )

    qualification.authorization_basis_ref = basis
    _record_qualification_change(
        session,
        qualification=qualification,
        actor_id=actor.id,
        action="design_partner.qualification_transitioned",
        detail={
            "previous_status": previous_status,
            "status": qualification.status,
            "previous_qualification_state": previous_state,
            "qualification_state": qualification.qualification_state,
        },
    )
    session.flush()
    return qualification


def get_design_partner_qualification(
    session: Session, engagement_id: UUID
) -> DesignPartnerQualification:
    qualification = session.scalar(
        select(DesignPartnerQualification).where(
            DesignPartnerQualification.engagement_id == engagement_id
        )
    )
    if qualification is None:
        raise DesignPartnerQualificationNotFoundError(str(engagement_id))
    return qualification


def list_authorized_human_users(session: Session, engagement_id: UUID) -> list[AuthorizedUser]:
    rows = session.execute(
        select(Operator.id, Operator.display_name, EngagementMember.role)
        .join(EngagementMember, EngagementMember.operator_id == Operator.id)
        .where(
            EngagementMember.engagement_id == engagement_id,
            Operator.identity_kind == "human",
            Operator.is_active.is_(True),
        )
        .order_by(Operator.id)
    ).all()
    return [
        AuthorizedUser(operator_id=row.id, display_name=row.display_name, role=row.role)
        for row in rows
    ]


def authorize_qualified_document_upload(
    session: Session,
    *,
    engagement: Engagement,
    operator: Operator,
    source_key: str | None,
    workflow_class: str | None,
    data_classification: str | None,
    content_type: str,
    extraction_provider: str,
    provider_allowed_classifications: set[str],
    correlation_id: UUID | None = None,
    now: datetime | None = None,
) -> CustomerDataAccessDecision:
    qualification = session.scalar(
        select(DesignPartnerQualification).where(
            DesignPartnerQualification.engagement_id == engagement.id
        )
    )
    return _evaluate_qualified_document_upload(
        session,
        engagement=engagement,
        qualification=qualification,
        operator=operator,
        source_key=source_key,
        workflow_class=workflow_class,
        data_classification=data_classification,
        content_type=content_type,
        extraction_provider=extraction_provider,
        provider_allowed_classifications=provider_allowed_classifications,
        correlation_id=correlation_id,
        now=now,
    )


def reauthorize_qualified_document_upload(
    session: Session,
    *,
    engagement_id: UUID,
    operator: Operator,
    source_key: str | None,
    workflow_class: str | None,
    data_classification: str | None,
    content_type: str,
    extraction_provider: str,
    provider_allowed_classifications: set[str],
    correlation_id: UUID,
    deployment_authority_check: DeploymentAuthorityCheck,
    now: datetime | None = None,
) -> CustomerDataAccessDecision:
    """Refresh and lock the authorization aggregate before customer bytes persist."""

    authority_locked = lock_design_partner_authority(
        session,
        engagement_id=engagement_id,
        required_access="write",
    )
    engagement = session.scalar(
        select(Engagement)
        .where(Engagement.id == engagement_id)
        .execution_options(populate_existing=True)
    )
    qualification = session.scalar(
        select(DesignPartnerQualification)
        .where(DesignPartnerQualification.engagement_id == engagement_id)
        .execution_options(populate_existing=True)
    )
    timestamp = now or datetime.now(UTC)
    if engagement is None:
        return CustomerDataAccessDecision(
            False,
            "QUALIFICATION_REQUIRED",
            "This engagement is not configured for design-partner customer data.",
            correlation_id,
            None,
        )
    decision = _evaluate_qualified_document_upload(
        session,
        engagement=engagement,
        qualification=qualification if authority_locked else None,
        operator=operator,
        source_key=source_key,
        workflow_class=workflow_class,
        data_classification=data_classification,
        content_type=content_type,
        extraction_provider=extraction_provider,
        provider_allowed_classifications=provider_allowed_classifications,
        correlation_id=correlation_id,
        now=timestamp,
    )
    if not decision.allowed or decision.context is None:
        return decision
    try:
        deployment_authority_check(now=timestamp)
    except ValueError:
        decision_code = "DEPLOYMENT_QUALIFICATION_INACTIVE"
        event = record_customer_data_access_outcome(
            session,
            context=decision.context,
            outcome="DENIED",
            decision_code=decision_code,
        )
        return CustomerDataAccessDecision(
            False,
            decision_code,
            "The deployment qualification is no longer current.",
            correlation_id,
            event.id,
        )
    return decision


def lock_design_partner_authority(
    session: Session,
    *,
    engagement_id: UUID,
    required_access: AuthorityLockAccess,
) -> bool:
    """Lock the engagement and qualification without granting runtime table updates."""

    return (
        session.scalar(
            select(
                func.ai_fde_lock_design_partner_authority(
                    engagement_id,
                    required_access,
                )
            )
        )
        is True
    )


def _evaluate_qualified_document_upload(
    session: Session,
    *,
    engagement: Engagement,
    qualification: DesignPartnerQualification | None,
    operator: Operator,
    source_key: str | None,
    workflow_class: str | None,
    data_classification: str | None,
    content_type: str,
    extraction_provider: str,
    provider_allowed_classifications: set[str],
    correlation_id: UUID | None = None,
    now: datetime | None = None,
) -> CustomerDataAccessDecision:
    correlation = correlation_id or uuid.uuid4()
    source_candidate = (source_key or "").strip().casefold()
    source_valid = bool(SOURCE_KEY_PATTERN.fullmatch(source_candidate))
    workflow_candidate = (workflow_class or "").strip()
    workflow_valid = (
        bool(workflow_candidate)
        and len(workflow_candidate) <= 160
        and "://" not in workflow_candidate
        and not any(marker in workflow_candidate for marker in ("@", "?", "#"))
        and not any(character.isspace() for character in workflow_candidate)
    )
    classification_candidate = (data_classification or "").strip().upper()
    classification_valid = classification_candidate in DATA_CLASSIFICATIONS
    if qualification is None:
        record_audit(
            session,
            engagement_id=engagement.id,
            actor_id=operator.id,
            action="customer_data.access_denied",
            target_type="engagement",
            target_id=engagement.id,
            correlation_id=correlation,
            detail={
                "operation": "MANUAL_DOCUMENT_UPLOAD",
                "decision_code": "QUALIFICATION_REQUIRED",
                "source_key": (
                    "missing-source"
                    if source_key is None
                    else "unqualified-source"
                    if source_valid
                    else "invalid-source"
                ),
                "workflow_class": (
                    "missing-workflow"
                    if workflow_class is None
                    else "unqualified-workflow"
                    if workflow_valid
                    else "invalid-workflow"
                ),
                "data_classification": (
                    classification_candidate
                    if classification_valid
                    else "missing-classification"
                    if data_classification is None
                    else "invalid-classification"
                ),
                "authorization_basis_ref": "none",
                "qualification_present": False,
            },
        )
        return CustomerDataAccessDecision(
            False,
            "QUALIFICATION_REQUIRED",
            "This engagement is not configured for design-partner customer data.",
            correlation,
            None,
        )

    source_authorized = (
        source_valid and source_candidate in qualification.authorized_data_source_keys
    )
    requested_source = (
        source_candidate
        if source_authorized
        else "missing-source"
        if source_key is None
        else "invalid-source"
        if not source_valid
        else "unauthorized-source"
    )
    workflow_authorized = (
        workflow_valid and workflow_candidate in qualification.allowed_workflow_classes
    )
    requested_workflow = (
        workflow_candidate
        if workflow_authorized
        else "missing-workflow"
        if workflow_class is None
        else "invalid-workflow"
        if not workflow_valid
        else "unauthorized-workflow"
    )
    requested_classification = (
        classification_candidate if classification_valid else qualification.data_classification
    )

    decision_code = "AUTHORIZED"
    message = "The bounded customer-data access is authorized."
    if (
        engagement.data_classification != "sanitized"
        or engagement.data_lifecycle_status != "active"
    ) or qualification.status != "ACTIVE":
        decision_code = "QUALIFICATION_INACTIVE"
        message = "The design-partner qualification is not active."
    elif qualification.qualification_state != "QUALIFIED":
        decision_code = "QUALIFICATION_INCOMPLETE"
        message = "The design-partner qualification has not completed."
    elif source_key is None or workflow_class is None or data_classification is None:
        decision_code = "QUALIFICATION_CONTEXT_REQUIRED"
        message = "Source, workflow, and data classification are required."
    elif not source_valid:
        decision_code = "INVALID_SOURCE_KEY"
        message = "The customer-data source key is invalid."
    elif not workflow_valid:
        decision_code = "INVALID_WORKFLOW_CLASS"
        message = "The customer-data workflow class is invalid."
    elif _media_type(content_type) not in QUALIFIED_DOCUMENT_MEDIA_TYPES:
        decision_code = "UNSUPPORTED_QUALIFIED_MEDIA_TYPE"
        message = "Qualified customer data is limited to plain text and Markdown documents."
    elif not source_authorized:
        decision_code = "SOURCE_NOT_AUTHORIZED"
        message = "The customer-data source is not authorized for this design partner."
    elif not workflow_authorized:
        decision_code = "WORKFLOW_NOT_AUTHORIZED"
        message = "The workflow is not authorized for this design partner."
    elif data_classification is None or not classification_valid:
        decision_code = "INVALID_DATA_CLASSIFICATION"
        message = "The customer-data classification is invalid."
    elif requested_classification != qualification.data_classification:
        decision_code = "CLASSIFICATION_OUTSIDE_QUALIFICATION"
        message = "The data classification is outside this qualification boundary."
    elif requested_classification == "RESTRICTED":
        decision_code = "PROVIDER_CLASSIFICATION_DENIED"
        message = "Restricted customer data is not eligible for model processing."
    elif extraction_provider != "bedrock":
        decision_code = "PROVIDER_NOT_QUALIFIED"
        message = "The configured extraction provider is not qualified for customer data."
    elif requested_classification not in provider_allowed_classifications:
        decision_code = "PROVIDER_CLASSIFICATION_DENIED"
        message = "The configured provider is not approved for this data classification."
    else:
        retention_failure = qualification_retention_failure(
            engagement,
            qualification,
            now=now,
        )
        if retention_failure is not None:
            decision_code = retention_failure
            message = (
                "The engagement retention deadline is outside its qualification ceiling."
                if retention_failure == "RETENTION_OUTSIDE_QUALIFICATION"
                else "The qualified retention period is missing or expired."
            )

    context = AuthorizedCustomerDataContext(
        engagement_id=engagement.id,
        qualification_id=qualification.id,
        partner_key=qualification.partner_key,
        operator_id=operator.id,
        source_key=requested_source,
        workflow_class=requested_workflow,
        data_classification=requested_classification,
        authorization_basis_ref=qualification.authorization_basis_ref,
        correlation_id=correlation,
    )
    if decision_code == "AUTHORIZED":
        return CustomerDataAccessDecision(
            True,
            decision_code,
            message,
            correlation,
            None,
            context,
        )

    event = record_customer_data_access_outcome(
        session,
        context=context,
        outcome="DENIED",
        decision_code=decision_code,
    )
    return CustomerDataAccessDecision(
        False,
        decision_code,
        message,
        correlation,
        event.id,
    )


def record_customer_data_access_outcome(
    session: Session,
    *,
    context: AuthorizedCustomerDataContext,
    outcome: Literal["AUTHORIZED", "DENIED"],
    decision_code: str,
    evidence_asset_id: UUID | None = None,
) -> CustomerDataAccessEvent:
    if (outcome == "AUTHORIZED") != (evidence_asset_id is not None):
        raise DesignPartnerQualificationError(
            "Authorized customer-data access must identify its evidence asset."
        )
    event = CustomerDataAccessEvent(
        id=uuid.uuid4(),
        engagement_id=context.engagement_id,
        qualification_id=context.qualification_id,
        partner_key=context.partner_key,
        operator_id=context.operator_id,
        evidence_asset_id=evidence_asset_id,
        source_key=context.source_key,
        workflow_class=context.workflow_class,
        data_classification=context.data_classification,
        operation="MANUAL_DOCUMENT_UPLOAD",
        outcome=outcome,
        decision_code=decision_code,
        authorization_basis_ref=context.authorization_basis_ref,
        correlation_id=context.correlation_id,
    )
    session.add(event)
    return event


def require_package_publication_eligibility(
    session: Session,
    *,
    engagement_id: UUID,
    target: dict[str, object],
    now: datetime | None = None,
    lock_for_update: bool = False,
) -> None:
    authority_locked = not lock_for_update or lock_design_partner_authority(
        session,
        engagement_id=engagement_id,
        required_access="write",
    )
    engagement_statement = (
        select(Engagement)
        .where(Engagement.id == engagement_id)
        .execution_options(populate_existing=True)
    )
    engagement = session.scalar(engagement_statement)
    if engagement is None or not authority_locked:
        raise DesignPartnerQualificationError(
            "A sanitized deployment package requires an active completed qualification."
        )
    if engagement.data_classification != "sanitized":
        return
    qualification_statement = (
        select(DesignPartnerQualification)
        .where(DesignPartnerQualification.engagement_id == engagement_id)
        .execution_options(populate_existing=True)
    )
    qualification = session.scalar(qualification_statement)
    if qualification is None:
        raise DesignPartnerQualificationError(
            "A sanitized deployment package requires an active completed qualification."
        )
    if qualification.status != "ACTIVE" or qualification.qualification_state != "QUALIFIED":
        raise DesignPartnerQualificationError(
            "A sanitized deployment package requires an active completed qualification."
        )
    if qualification.data_classification == "RESTRICTED":
        raise DesignPartnerQualificationError(
            "Restricted design-partner data is not eligible for Mission Control handoff."
        )
    if not qualification_retention_is_authorized(
        engagement,
        qualification,
        now=now,
    ):
        raise DesignPartnerQualificationError(
            "The design-partner retention period is missing, expired, or outside its "
            "immutable qualification ceiling."
        )
    repository_ref = target.get("repository_ref")
    workflow_class = target.get("semantic_execution_workflow_ref")
    if repository_ref not in qualification.authorized_repository_refs:
        raise DesignPartnerQualificationError(
            "The deployment-package repository is outside the design-partner authorization."
        )
    if workflow_class not in qualification.allowed_workflow_classes:
        raise DesignPartnerQualificationError(
            "The deployment-package workflow is outside the design-partner authorization."
        )


def require_qualified_evidence_processing(
    session: Session,
    *,
    asset: EvidenceAsset,
    provider_name: str,
    provider_allowed_data_classifications: set[str],
    now: datetime | None = None,
    lock_for_update: bool = False,
) -> datetime | None:
    """Freshly revalidate persisted customer-data authority at a sensitive boundary."""

    authority_locked = not lock_for_update or lock_design_partner_authority(
        session,
        engagement_id=asset.engagement_id,
        required_access="write",
    )
    engagement_statement = (
        select(Engagement)
        .where(Engagement.id == asset.engagement_id)
        .execution_options(populate_existing=True)
    )
    engagement = session.scalar(engagement_statement)
    if engagement is None or not authority_locked:
        raise CustomerDataProcessingDeniedError(
            "Customer-data processing authorization is no longer valid."
        )

    qualification_context = (
        asset.design_partner_qualification_id,
        asset.authorized_source_key,
        asset.authorized_workflow_class,
        asset.data_classification,
    )
    if engagement.data_classification == "synthetic" and all(
        value is None for value in qualification_context
    ):
        return None
    if engagement.data_classification != "sanitized" or any(
        value is None for value in qualification_context
    ):
        raise CustomerDataProcessingDeniedError(
            "Customer-data processing authorization is no longer valid."
        )

    qualification_statement = (
        select(DesignPartnerQualification)
        .where(
            DesignPartnerQualification.id == asset.design_partner_qualification_id,
            DesignPartnerQualification.engagement_id == asset.engagement_id,
        )
        .execution_options(populate_existing=True)
    )
    qualification = session.scalar(qualification_statement)
    timestamp = now or datetime.now(UTC)
    allowed = (
        qualification is not None
        and engagement is not None
        and engagement.data_classification == "sanitized"
        and engagement.data_lifecycle_status == "active"
        and qualification_retention_is_authorized(
            engagement,
            qualification,
            now=timestamp,
        )
        and qualification.status == "ACTIVE"
        and qualification.qualification_state == "QUALIFIED"
        and asset.authorized_source_key in qualification.authorized_data_source_keys
        and asset.authorized_workflow_class in qualification.allowed_workflow_classes
        and asset.data_classification == qualification.data_classification
        and asset.data_classification != "RESTRICTED"
        and asset.data_classification in provider_allowed_data_classifications
        and provider_name == "amazon-bedrock-converse"
    )
    if not allowed:
        raise CustomerDataProcessingDeniedError(
            "Customer-data processing authorization is no longer valid."
        )
    return timestamp


def qualification_retention_failure(
    engagement: Engagement,
    qualification: DesignPartnerQualification,
    *,
    now: datetime | None = None,
) -> Literal["RETENTION_EXPIRED", "RETENTION_OUTSIDE_QUALIFICATION"] | None:
    """Return the fail-closed reason for the current qualified retention window."""

    timestamp = now or datetime.now(UTC)
    engagement_expiry = engagement.retention_expires_at
    qualification_expiry = qualification.retention_expires_at
    if engagement_expiry is None or qualification_expiry is None:
        return "RETENTION_EXPIRED"
    engagement_ceiling = _aware_utc(engagement_expiry)
    qualification_ceiling = _aware_utc(qualification_expiry)
    if engagement_ceiling > qualification_ceiling:
        return "RETENTION_OUTSIDE_QUALIFICATION"
    if engagement_ceiling <= timestamp or qualification_ceiling <= timestamp:
        return "RETENTION_EXPIRED"
    return None


def qualification_retention_is_authorized(
    engagement: Engagement,
    qualification: DesignPartnerQualification,
    *,
    now: datetime | None = None,
) -> bool:
    return qualification_retention_failure(engagement, qualification, now=now) is None


def normalize_partner_key(value: str) -> str:
    normalized = value.strip().casefold()
    if not SOURCE_KEY_PATTERN.fullmatch(normalized):
        raise DesignPartnerQualificationError(
            "Partner keys must use lowercase letters, numbers, dots, underscores, or hyphens."
        )
    return normalized


def normalize_source_key(value: str) -> str:
    normalized = value.strip().casefold()
    if not SOURCE_KEY_PATTERN.fullmatch(normalized):
        raise DesignPartnerQualificationError("The authorized data-source key is invalid.")
    return normalized


def normalize_reference(value: str) -> str:
    normalized = _required_text(value, "authorization reference", 512)
    if (
        "://" in normalized
        or any(marker in normalized for marker in ("@", "?", "#"))
        or any(character.isspace() for character in normalized)
    ):
        raise DesignPartnerQualificationError(
            "Authorization references must be stable identifiers, not URLs or credentials."
        )
    return normalized


def normalize_data_classification(value: str) -> str:
    normalized = value.strip().upper()
    if normalized not in DATA_CLASSIFICATIONS:
        raise DesignPartnerQualificationError("The data classification is invalid.")
    return normalized


def _normalized_items(
    values: list[str],
    label: str,
    *,
    normalizer: Callable[[str], str],
) -> list[str]:
    if not values or len(values) > MAX_AUTHORIZATION_ITEMS:
        raise DesignPartnerQualificationError(
            f"At least one and no more than {MAX_AUTHORIZATION_ITEMS} {label}s are required."
        )
    normalized = [normalizer(value) for value in values]
    if len(normalized) != len(set(normalized)):
        raise DesignPartnerQualificationError(f"Duplicate {label}s are not allowed.")
    return sorted(normalized)


def _required_text(value: str, label: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise DesignPartnerQualificationError(
            f"The {label} must contain between 1 and {maximum} characters."
        )
    return normalized


def _media_type(value: str) -> str:
    return value.partition(";")[0].strip().casefold()


def _require_active_human_owner(
    session: Session,
    engagement_id: UUID,
    operator_id: UUID,
) -> Operator:
    owner = session.scalar(
        select(Operator)
        .join(EngagementMember, EngagementMember.operator_id == Operator.id)
        .where(
            Operator.id == operator_id,
            EngagementMember.engagement_id == engagement_id,
            EngagementMember.role == "owner",
            Operator.identity_kind == "human",
            Operator.is_active.is_(True),
        )
    )
    if owner is None:
        raise DesignPartnerQualificationError(
            "Qualification administration requires an active human engagement owner."
        )
    return owner


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise DesignPartnerQualificationError("Qualification timestamps must include a timezone.")
    return value.astimezone(UTC)


def _record_qualification_change(
    session: Session,
    *,
    qualification: DesignPartnerQualification,
    actor_id: UUID,
    action: str,
    detail: dict[str, object],
) -> None:
    record_audit(
        session,
        engagement_id=qualification.engagement_id,
        actor_id=actor_id,
        action=action,
        target_type="design_partner_qualification",
        target_id=qualification.id,
        detail=detail,
    )
    publish_domain_event(
        session,
        engagement_id=qualification.engagement_id,
        event_type=action,
        aggregate_type="design_partner_qualification",
        aggregate_id=qualification.id,
        payload=detail,
    )
