from __future__ import annotations

import uuid
from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Path, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_fde.api.dependencies import (
    EngagementOwnerDependency,
    EngagementReadDependency,
    EngagementWriteDependency,
    OperatorDependency,
    SessionDependency,
)
from ai_fde.api.factory_engineer_schemas import (
    CustomerFactoryModelCreateRequest,
    CustomerFactoryModelResponse,
    DeploymentPackageApprovalRequest,
    DeploymentPackageCreateRequest,
    DeploymentPackageResponse,
    FactoryHandoffWorkspaceResponse,
    FactoryOpportunityCreateRequest,
    FactoryOpportunityResponse,
    FDLCReadinessAssessmentResponse,
    IssuedRetrievalGrantResponse,
    PackageRetrievalEventResponse,
    ReadinessAssessmentCreateRequest,
    ReasonRequest,
    RetrievalGrantCreateRequest,
    RetrievalGrantResponse,
)
from ai_fde.db import operator_session
from ai_fde.models import Operator
from ai_fde.modules.factory_engineer.models import (
    CustomerFactoryModelVersion,
    FactoryDeploymentPackageVersion,
    FactoryOpportunity,
    FDLCReadinessAssessment,
    PackageRetrievalEvent,
)
from ai_fde.modules.factory_engineer.retrieval import (
    authenticate_retrieval_token,
    issue_retrieval_grant,
    parse_retrieval_token_subject,
    provision_retrieval_service_identity,
    retrieve_published_package,
    revoke_retrieval_grant,
)
from ai_fde.modules.factory_engineer.schemas import (
    ApprovalBinding,
    DeploymentTarget,
    FactoryDeploymentPackageInput,
    FactoryDeploymentPackageStatus,
    ImmutableVersionReference,
    PackageIssuer,
    PackageSourceLineage,
)
from ai_fde.modules.factory_engineer.service import (
    FactoryEngineerIntegrityError,
    FactoryEngineerNotFoundError,
    FactoryEngineerStateError,
    approve_customer_factory_model,
    approve_deployment_package,
    approve_readiness_assessment,
    create_customer_factory_model,
    create_deployment_package,
    create_factory_opportunity,
    create_readiness_assessment,
    publish_deployment_package,
    reject_deployment_package,
    reject_factory_opportunity,
    revoke_deployment_package,
    select_factory_opportunity,
    serialize_published_package_envelope,
    submit_deployment_package_for_review,
)

router = APIRouter()

PACKAGE_MEDIA_TYPE = "application/vnd.fdlc.factory-deployment-package+json;version=1"
MAX_WORKSPACE_HISTORY = 100


@router.get(
    "/engagements/{engagement_id}/factory-handoff",
    response_model=FactoryHandoffWorkspaceResponse,
)
def get_factory_handoff_workspace_endpoint(
    engagement_id: UUID,
    session: SessionDependency,
    _access: EngagementReadDependency,
) -> FactoryHandoffWorkspaceResponse:
    customer_model = session.scalar(
        select(CustomerFactoryModelVersion)
        .where(CustomerFactoryModelVersion.engagement_id == engagement_id)
        .order_by(CustomerFactoryModelVersion.version_number.desc())
        .limit(1)
    )
    opportunities = list(
        session.scalars(
            select(FactoryOpportunity)
            .where(FactoryOpportunity.engagement_id == engagement_id)
            .order_by(FactoryOpportunity.created_at.desc())
            .limit(MAX_WORKSPACE_HISTORY)
        )
    )
    readiness = session.scalar(
        select(FDLCReadinessAssessment)
        .where(FDLCReadinessAssessment.engagement_id == engagement_id)
        .order_by(FDLCReadinessAssessment.version_number.desc())
        .limit(1)
    )
    packages = list(
        session.scalars(
            select(FactoryDeploymentPackageVersion)
            .where(FactoryDeploymentPackageVersion.engagement_id == engagement_id)
            .order_by(FactoryDeploymentPackageVersion.created_at.desc())
            .limit(MAX_WORKSPACE_HISTORY)
        )
    )
    latest_retrieval = session.scalar(
        select(PackageRetrievalEvent)
        .where(PackageRetrievalEvent.engagement_id == engagement_id)
        .order_by(PackageRetrievalEvent.created_at.desc())
        .limit(1)
    )
    return FactoryHandoffWorkspaceResponse(
        customer_model=(
            CustomerFactoryModelResponse.model_validate(customer_model)
            if customer_model is not None
            else None
        ),
        opportunities=[FactoryOpportunityResponse.model_validate(item) for item in opportunities],
        readiness=(
            FDLCReadinessAssessmentResponse.model_validate(readiness)
            if readiness is not None
            else None
        ),
        packages=_package_responses(session, packages),
        latest_retrieval=(
            PackageRetrievalEventResponse.model_validate(latest_retrieval)
            if latest_retrieval is not None
            else None
        ),
    )


@router.post(
    "/engagements/{engagement_id}/customer-factory-models",
    response_model=CustomerFactoryModelResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_customer_factory_model_endpoint(
    engagement_id: UUID,
    payload: CustomerFactoryModelCreateRequest,
    session: SessionDependency,
    operator: OperatorDependency,
    _access: EngagementWriteDependency,
) -> CustomerFactoryModelResponse:
    try:
        model = create_customer_factory_model(
            session,
            engagement_id=engagement_id,
            operator=operator,
            model_input=payload,
        )
    except (FactoryEngineerStateError, FactoryEngineerIntegrityError) as exc:
        _raise_domain_error(exc)
    return CustomerFactoryModelResponse.model_validate(model)


@router.post(
    "/engagements/{engagement_id}/customer-factory-models/{model_id}/approve",
    response_model=CustomerFactoryModelResponse,
)
def approve_customer_factory_model_endpoint(
    engagement_id: UUID,
    model_id: UUID,
    session: SessionDependency,
    operator: OperatorDependency,
    _access: EngagementWriteDependency,
) -> CustomerFactoryModelResponse:
    try:
        model = approve_customer_factory_model(
            session,
            engagement_id=engagement_id,
            model_id=model_id,
            operator=operator,
        )
    except (
        FactoryEngineerNotFoundError,
        FactoryEngineerStateError,
        FactoryEngineerIntegrityError,
    ) as exc:
        _raise_domain_error(exc)
    return CustomerFactoryModelResponse.model_validate(model)


@router.post(
    "/engagements/{engagement_id}/factory-opportunities",
    response_model=FactoryOpportunityResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_factory_opportunity_endpoint(
    engagement_id: UUID,
    payload: FactoryOpportunityCreateRequest,
    session: SessionDependency,
    operator: OperatorDependency,
    _access: EngagementWriteDependency,
) -> FactoryOpportunityResponse:
    try:
        opportunity = create_factory_opportunity(
            session,
            engagement_id=engagement_id,
            operator=operator,
            customer_factory_model_id=payload.customer_factory_model_id,
            opportunity_input=payload.opportunity,
        )
    except (
        FactoryEngineerNotFoundError,
        FactoryEngineerStateError,
        FactoryEngineerIntegrityError,
    ) as exc:
        _raise_domain_error(exc)
    return FactoryOpportunityResponse.model_validate(opportunity)


@router.post(
    "/engagements/{engagement_id}/factory-opportunities/{opportunity_id}/select",
    response_model=FactoryOpportunityResponse,
)
def select_factory_opportunity_endpoint(
    engagement_id: UUID,
    opportunity_id: UUID,
    payload: ReasonRequest,
    session: SessionDependency,
    operator: OperatorDependency,
    _access: EngagementWriteDependency,
) -> FactoryOpportunityResponse:
    try:
        opportunity = select_factory_opportunity(
            session,
            engagement_id=engagement_id,
            opportunity_id=opportunity_id,
            operator=operator,
            reason=payload.reason,
        )
    except (
        FactoryEngineerNotFoundError,
        FactoryEngineerStateError,
        FactoryEngineerIntegrityError,
    ) as exc:
        _raise_domain_error(exc)
    return FactoryOpportunityResponse.model_validate(opportunity)


@router.post(
    "/engagements/{engagement_id}/factory-opportunities/{opportunity_id}/reject",
    response_model=FactoryOpportunityResponse,
)
def reject_factory_opportunity_endpoint(
    engagement_id: UUID,
    opportunity_id: UUID,
    payload: ReasonRequest,
    session: SessionDependency,
    operator: OperatorDependency,
    _access: EngagementWriteDependency,
) -> FactoryOpportunityResponse:
    try:
        opportunity = reject_factory_opportunity(
            session,
            engagement_id=engagement_id,
            opportunity_id=opportunity_id,
            operator=operator,
            reason=payload.reason,
        )
    except (
        FactoryEngineerNotFoundError,
        FactoryEngineerStateError,
        FactoryEngineerIntegrityError,
    ) as exc:
        _raise_domain_error(exc)
    return FactoryOpportunityResponse.model_validate(opportunity)


@router.post(
    "/engagements/{engagement_id}/fdlc-readiness",
    response_model=FDLCReadinessAssessmentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_readiness_assessment_endpoint(
    engagement_id: UUID,
    payload: ReadinessAssessmentCreateRequest,
    session: SessionDependency,
    operator: OperatorDependency,
    _access: EngagementWriteDependency,
) -> FDLCReadinessAssessmentResponse:
    try:
        assessment = create_readiness_assessment(
            session,
            engagement_id=engagement_id,
            operator=operator,
            customer_factory_model_id=payload.customer_factory_model_id,
            selected_opportunity_id=payload.selected_opportunity_id,
            current_workflow_id=payload.current_workflow_id,
            target_workflow_id=payload.target_workflow_id,
            assessment_input=payload.assessment,
        )
    except (
        FactoryEngineerNotFoundError,
        FactoryEngineerStateError,
        FactoryEngineerIntegrityError,
    ) as exc:
        _raise_domain_error(exc)
    return FDLCReadinessAssessmentResponse.model_validate(assessment)


@router.post(
    "/engagements/{engagement_id}/fdlc-readiness/{assessment_id}/approve",
    response_model=FDLCReadinessAssessmentResponse,
)
def approve_readiness_assessment_endpoint(
    engagement_id: UUID,
    assessment_id: UUID,
    session: SessionDependency,
    operator: OperatorDependency,
    _access: EngagementWriteDependency,
) -> FDLCReadinessAssessmentResponse:
    try:
        assessment = approve_readiness_assessment(
            session,
            engagement_id=engagement_id,
            assessment_id=assessment_id,
            operator=operator,
        )
    except (
        FactoryEngineerNotFoundError,
        FactoryEngineerStateError,
        FactoryEngineerIntegrityError,
    ) as exc:
        _raise_domain_error(exc)
    return FDLCReadinessAssessmentResponse.model_validate(assessment)


@router.post(
    "/engagements/{engagement_id}/deployment-packages",
    response_model=DeploymentPackageResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_deployment_package_endpoint(
    engagement_id: UUID,
    payload: DeploymentPackageCreateRequest,
    session: SessionDependency,
    operator: OperatorDependency,
    _access: EngagementWriteDependency,
) -> DeploymentPackageResponse:
    try:
        package = create_deployment_package(
            session,
            engagement_id=engagement_id,
            operator=operator,
            customer_factory_model_id=payload.customer_factory_model_id,
            readiness_assessment_id=payload.readiness_assessment_id,
            factory_opportunity_id=payload.factory_opportunity_id,
            target=payload.target,
            package_input=payload.deployment_intent,
            package_id=payload.package_id,
        )
    except (
        FactoryEngineerNotFoundError,
        FactoryEngineerStateError,
        FactoryEngineerIntegrityError,
    ) as exc:
        _raise_domain_error(exc)
    return _package_responses(session, [package])[0]


@router.post(
    "/engagements/{engagement_id}/deployment-packages/{package_version_id}/review",
    response_model=DeploymentPackageResponse,
)
def submit_deployment_package_for_review_endpoint(
    engagement_id: UUID,
    package_version_id: UUID,
    session: SessionDependency,
    operator: OperatorDependency,
    _access: EngagementWriteDependency,
) -> DeploymentPackageResponse:
    try:
        package = submit_deployment_package_for_review(
            session,
            engagement_id=engagement_id,
            package_version_id=package_version_id,
            operator=operator,
        )
    except (
        FactoryEngineerNotFoundError,
        FactoryEngineerStateError,
        FactoryEngineerIntegrityError,
    ) as exc:
        _raise_domain_error(exc)
    return _package_responses(session, [package])[0]


@router.post(
    "/engagements/{engagement_id}/deployment-packages/{package_version_id}/approve",
    response_model=DeploymentPackageResponse,
)
def approve_deployment_package_endpoint(
    engagement_id: UUID,
    package_version_id: UUID,
    payload: DeploymentPackageApprovalRequest,
    session: SessionDependency,
    operator: OperatorDependency,
    _access: EngagementWriteDependency,
) -> DeploymentPackageResponse:
    try:
        package = approve_deployment_package(
            session,
            engagement_id=engagement_id,
            package_version_id=package_version_id,
            operator=operator,
            authority_basis_ref=payload.authority_basis_ref,
        )
    except (
        FactoryEngineerNotFoundError,
        FactoryEngineerStateError,
        FactoryEngineerIntegrityError,
    ) as exc:
        _raise_domain_error(exc)
    return _package_responses(session, [package])[0]


@router.post(
    "/engagements/{engagement_id}/deployment-packages/{package_version_id}/publish",
    response_model=DeploymentPackageResponse,
)
def publish_deployment_package_endpoint(
    engagement_id: UUID,
    package_version_id: UUID,
    session: SessionDependency,
    operator: OperatorDependency,
    _access: EngagementWriteDependency,
) -> DeploymentPackageResponse:
    try:
        package = publish_deployment_package(
            session,
            engagement_id=engagement_id,
            package_version_id=package_version_id,
            operator=operator,
        )
    except (
        FactoryEngineerNotFoundError,
        FactoryEngineerStateError,
        FactoryEngineerIntegrityError,
    ) as exc:
        _raise_domain_error(exc)
    return _package_responses(session, [package])[0]


@router.post(
    "/engagements/{engagement_id}/deployment-packages/{package_version_id}/reject",
    response_model=DeploymentPackageResponse,
)
def reject_deployment_package_endpoint(
    engagement_id: UUID,
    package_version_id: UUID,
    payload: ReasonRequest,
    session: SessionDependency,
    operator: OperatorDependency,
    _access: EngagementWriteDependency,
) -> DeploymentPackageResponse:
    try:
        package = reject_deployment_package(
            session,
            engagement_id=engagement_id,
            package_version_id=package_version_id,
            operator=operator,
            reason=payload.reason,
        )
    except (
        FactoryEngineerNotFoundError,
        FactoryEngineerStateError,
        FactoryEngineerIntegrityError,
    ) as exc:
        _raise_domain_error(exc)
    return _package_responses(session, [package])[0]


@router.post(
    "/engagements/{engagement_id}/deployment-packages/{package_version_id}/revoke",
    response_model=DeploymentPackageResponse,
)
def revoke_deployment_package_endpoint(
    engagement_id: UUID,
    package_version_id: UUID,
    payload: ReasonRequest,
    session: SessionDependency,
    operator: OperatorDependency,
    _access: EngagementOwnerDependency,
) -> DeploymentPackageResponse:
    try:
        package = revoke_deployment_package(
            session,
            engagement_id=engagement_id,
            package_version_id=package_version_id,
            operator=operator,
            reason=payload.reason,
        )
    except (
        FactoryEngineerNotFoundError,
        FactoryEngineerStateError,
        FactoryEngineerIntegrityError,
    ) as exc:
        _raise_domain_error(exc)
    return _package_responses(session, [package])[0]


@router.post(
    "/engagements/{engagement_id}/deployment-package-retrieval-grants",
    response_model=IssuedRetrievalGrantResponse,
    status_code=status.HTTP_201_CREATED,
)
def issue_retrieval_grant_endpoint(
    engagement_id: UUID,
    payload: RetrievalGrantCreateRequest,
    session: SessionDependency,
    operator: OperatorDependency,
    _access: EngagementOwnerDependency,
) -> IssuedRetrievalGrantResponse:
    try:
        if payload.service_operator_id is not None:
            existing_service_operator = session.get(Operator, payload.service_operator_id)
            if existing_service_operator is None:
                raise HTTPException(status_code=404, detail="Service operator not found.")
            service_operator = existing_service_operator
        else:
            service_operator = provision_retrieval_service_identity(
                session,
                engagement_id=engagement_id,
                created_by=operator,
            )
        issued = issue_retrieval_grant(
            session,
            engagement_id=engagement_id,
            service_operator=service_operator,
            created_by=operator,
            requester_identity=payload.requester_identity,
            requester_system=payload.requester_system,
            expires_at=payload.expires_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return IssuedRetrievalGrantResponse.model_validate(
        {**RetrievalGrantResponse.model_validate(issued.grant).model_dump(), "token": issued.token}
    )


@router.post(
    "/engagements/{engagement_id}/deployment-package-retrieval-grants/{grant_id}/revoke",
    response_model=RetrievalGrantResponse,
)
def revoke_retrieval_grant_endpoint(
    engagement_id: UUID,
    grant_id: UUID,
    session: SessionDependency,
    operator: OperatorDependency,
    _access: EngagementOwnerDependency,
) -> RetrievalGrantResponse:
    try:
        grant = revoke_retrieval_grant(
            session,
            engagement_id=engagement_id,
            grant_id=grant_id,
            revoked_by=operator,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Retrieval grant not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RetrievalGrantResponse.model_validate(grant)


@router.get("/deployment-packages/{package_id}/versions/{package_version}")
def retrieve_published_package_endpoint(
    package_id: UUID,
    package_version: Annotated[int, Path(ge=1, le=2_147_483_647)],
    authorization: Annotated[str | None, Header()] = None,
    x_correlation_id: Annotated[UUID | None, Header()] = None,
) -> Response:
    correlation_id = x_correlation_id or uuid.uuid4()
    token = _bearer_token(authorization)
    if token is None:
        return _retrieval_error(
            status.HTTP_401_UNAUTHORIZED,
            code="AUTHENTICATION_REQUIRED",
            message="A valid package-retrieval bearer credential is required.",
            correlation_id=correlation_id,
        )
    subject = parse_retrieval_token_subject(token)
    if subject is None:
        return _retrieval_error(
            status.HTTP_401_UNAUTHORIZED,
            code="INVALID_TOKEN",
            message="The package-retrieval credential is invalid.",
            correlation_id=correlation_id,
        )
    with operator_session(subject.operator_id) as session:
        authentication = authenticate_retrieval_token(session, token=token)
        if not authentication.authenticated or authentication.principal is None:
            error_status = (
                status.HTTP_403_FORBIDDEN
                if authentication.result == "INVALID_SCOPE"
                else status.HTTP_401_UNAUTHORIZED
            )
            return _retrieval_error(
                error_status,
                code=authentication.result,
                message="The package-retrieval credential is not authorized.",
                correlation_id=correlation_id,
            )
        decision = retrieve_published_package(
            session,
            package_id=package_id,
            package_version=package_version,
            principal=authentication.principal,
            correlation_id=correlation_id,
        )
        if decision.allowed and decision.package is not None:
            return Response(
                content=serialize_published_package_envelope(decision.package),
                status_code=status.HTTP_200_OK,
                headers={
                    "Cache-Control": "no-store",
                    "Content-Type": PACKAGE_MEDIA_TYPE,
                    "X-Correlation-ID": str(correlation_id),
                },
            )
        error_status, code, message = _retrieval_denial(decision.result)
        return _retrieval_error(
            error_status,
            code=code,
            message=message,
            correlation_id=correlation_id,
        )


def _package_responses(
    session: Session,
    packages: list[FactoryDeploymentPackageVersion],
) -> list[DeploymentPackageResponse]:
    if not packages:
        return []
    model_ids = {item.customer_factory_model_id for item in packages}
    readiness_ids = {item.readiness_assessment_id for item in packages}
    opportunity_ids = {item.factory_opportunity_id for item in packages}
    models = {
        item.id: item
        for item in session.scalars(
            select(CustomerFactoryModelVersion).where(CustomerFactoryModelVersion.id.in_(model_ids))
        )
    }
    readiness = {
        item.id: item
        for item in session.scalars(
            select(FDLCReadinessAssessment).where(FDLCReadinessAssessment.id.in_(readiness_ids))
        )
    }
    opportunities = {
        item.id: item
        for item in session.scalars(
            select(FactoryOpportunity).where(FactoryOpportunity.id.in_(opportunity_ids))
        )
    }
    return [
        _package_response(
            item,
            models[item.customer_factory_model_id],
            readiness[item.readiness_assessment_id],
            opportunities[item.factory_opportunity_id],
        )
        for item in packages
    ]


def _package_response(
    package: FactoryDeploymentPackageVersion,
    customer_model: CustomerFactoryModelVersion,
    readiness: FDLCReadinessAssessment,
    opportunity: FactoryOpportunity,
) -> DeploymentPackageResponse:
    source = PackageSourceLineage(
        engagement_id=package.engagement_id,
        customer_factory_model=ImmutableVersionReference(
            id=customer_model.id,
            version=customer_model.version_number,
            digest=customer_model.content_digest,
        ),
        current_workflow=ImmutableVersionReference.model_validate(package.current_workflow_ref),
        target_workflow=ImmutableVersionReference.model_validate(package.target_workflow_ref),
        readiness_assessment=ImmutableVersionReference(
            id=readiness.id,
            version=readiness.version_number,
            digest=readiness.content_digest,
        ),
        factory_opportunity=ImmutableVersionReference(
            id=opportunity.id,
            version=opportunity.version_number,
            digest=opportunity.content_digest,
        ),
    )
    return DeploymentPackageResponse(
        id=package.id,
        engagement_id=package.engagement_id,
        package_id=package.package_id,
        package_version=package.package_version,
        schema_version=package.schema_version,
        status=FactoryDeploymentPackageStatus(package.status),
        issuer=PackageIssuer.model_validate(
            {
                "issuer_id": package.issuer_id,
                "issuer_type": package.issuer_type,
                "environment": package.issuer_environment,
                "authority_scope": package.issuer_authority_scope,
            }
        ),
        source=source,
        target=DeploymentTarget.model_validate(package.target),
        deployment_intent=FactoryDeploymentPackageInput.model_validate(package.contract),
        digest=package.digest,
        approval=(
            ApprovalBinding.model_validate(package.approval_binding)
            if package.approval_binding is not None
            else None
        ),
        issued_at=package.issued_at,
        approved_at=package.approved_at,
        published_at=package.published_at,
        state_reason=package.state_reason,
        created_at=package.created_at,
    )


def _raise_domain_error(
    error: FactoryEngineerNotFoundError | FactoryEngineerStateError | FactoryEngineerIntegrityError,
) -> NoReturn:
    if isinstance(error, FactoryEngineerNotFoundError):
        raise HTTPException(status_code=404, detail="Factory Engineer record not found.") from error
    if isinstance(error, FactoryEngineerIntegrityError):
        raise HTTPException(
            status_code=503,
            detail="Factory Engineer integrity validation failed.",
        ) from error
    raise HTTPException(status_code=409, detail=str(error)) from error


def _bearer_token(authorization: str | None) -> str | None:
    if authorization is None:
        return None
    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme.casefold() != "bearer" or not token or token.strip() != token:
        return None
    return token


def _retrieval_denial(result: str) -> tuple[int, str, str]:
    if result in {"NOT_FOUND", "ENGAGEMENT_UNAVAILABLE"}:
        return 404, "PACKAGE_NOT_FOUND", "The package version is unavailable."
    if result == "DENIED_STALE":
        return 410, "PACKAGE_STALE", "The package version is stale."
    if result == "DENIED_REVOKED":
        return 410, "PACKAGE_REVOKED", "The package version is revoked."
    if result == "DENIED_NOT_PUBLISHED":
        return 409, "PACKAGE_NOT_PUBLISHED", "The package version is not published."
    return 503, "PACKAGE_INTEGRITY_FAILED", "The package integrity check failed."


def _retrieval_error(
    status_code: int,
    *,
    code: str,
    message: str,
    correlation_id: UUID,
) -> JSONResponse:
    headers = {
        "Cache-Control": "no-store",
        "X-Correlation-ID": str(correlation_id),
    }
    if status_code == status.HTTP_401_UNAUTHORIZED:
        headers["WWW-Authenticate"] = "Bearer"
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "correlation_id": str(correlation_id),
            }
        },
        headers=headers,
    )
