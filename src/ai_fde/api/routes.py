from __future__ import annotations

from datetime import datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import RedirectResponse

from ai_fde.api.dependencies import (
    EngagementReadDependency,
    EngagementWriteDependency,
    EvidenceStoreDependency,
    OperatorDependency,
    PrincipalDependency,
    SessionDependency,
    SettingsDependency,
)
from ai_fde.api.schemas import (
    AssertionResponse,
    AuthenticatedOperatorResponse,
    ClaimResponse,
    ClaimReviewRequest,
    ClaimReviewResponse,
    ContradictionResolveRequest,
    ContradictionResponse,
    EconomicCalculateRequest,
    EconomicCaseResponse,
    EngagementCreate,
    EngagementResponse,
    EngagementWorkspaceResponse,
    EntityResponse,
    EvidenceResponse,
    HealthResponse,
    ImplementationArtifactResponse,
    OperatingModelResponse,
    OperatorNoteCreate,
    ProvenanceResponse,
    WorkflowApproveRequest,
    WorkflowResponse,
    WorkflowStepResponse,
    WorkflowStepUpdateRequest,
    WorkflowWorkspaceResponse,
)
from ai_fde.models import WorkflowVersion
from ai_fde.modules.artifacts.service import (
    ArtifactStageGateError,
    generate_implementation_specification,
    get_latest_artifact,
)
from ai_fde.modules.economics.service import (
    EconomicCaseNotFoundError,
    EconomicStageGateError,
    approve_economic_case,
    calculate_economic_case,
    get_latest_economic_case,
)
from ai_fde.modules.engagements.service import (
    EngagementNotFoundError,
    create_engagement,
    get_engagement,
    get_engagement_counts,
    list_engagements,
)
from ai_fde.modules.evidence.service import (
    EvidenceValidationError,
    create_evidence_asset,
    list_evidence,
)
from ai_fde.modules.identity.oidc import OIDCProvider, OIDCProviderError
from ai_fde.modules.identity.sessions import (
    InvalidLoginAttemptError,
    OperatorEnrollmentDeniedError,
    consume_login_attempt,
    create_login_attempt,
    create_operator_session,
    enroll_operator,
    identity_session,
    revoke_operator_session,
)
from ai_fde.modules.knowledge.contradictions import (
    ContradictionAlreadyResolvedError,
    ContradictionNotFoundError,
    list_contradictions,
    resolve_contradiction,
)
from ai_fde.modules.knowledge.review import (
    ClaimAlreadyReviewedError,
    ClaimNotFoundError,
    evidence_for_claim,
    list_claims,
    review_claim,
)
from ai_fde.modules.operating_model.service import list_entities, list_verified_assertions
from ai_fde.modules.workflows.service import (
    WorkflowNotFoundError,
    WorkflowStageGateError,
    approve_workflow,
    generate_current_workflow,
    generate_target_workflow,
    list_latest_workflows,
    list_workflow_steps,
    update_workflow_step,
)

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="ai-fde-api")


@router.get("/auth/login", response_class=RedirectResponse)
async def login_endpoint(
    request: Request,
    settings: SettingsDependency,
    return_to: str = Query(default="/", max_length=1024),
) -> RedirectResponse:
    if settings.auth_mode != "oidc":
        return RedirectResponse(settings.cockpit_url, status_code=status.HTTP_303_SEE_OTHER)
    with identity_session() as session:
        attempt = create_login_attempt(
            session,
            redirect_uri=settings.oidc_redirect_uri,
            return_to=_validated_return_to(return_to),
            ttl_seconds=settings.oidc_login_ttl_seconds,
        )
    try:
        authorization_url = await _oidc_provider(request).build_authorization_url(
            state=attempt.state,
            nonce=attempt.nonce,
            code_verifier=attempt.code_verifier,
            redirect_uri=attempt.redirect_uri,
        )
    except OIDCProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The identity provider is unavailable.",
        ) from exc
    return RedirectResponse(authorization_url, status_code=status.HTTP_302_FOUND)


@router.get("/auth/callback", response_class=RedirectResponse)
async def auth_callback_endpoint(
    request: Request,
    settings: SettingsDependency,
    code: str | None = Query(default=None),
    state_value: str | None = Query(default=None, alias="state"),
    provider_error: str | None = Query(default=None, alias="error"),
) -> RedirectResponse:
    if settings.auth_mode != "oidc":
        raise HTTPException(status_code=404, detail="Authentication callback is not configured.")
    if provider_error or not code or not state_value:
        raise HTTPException(status_code=401, detail="Authentication was not completed.")
    try:
        with identity_session() as session:
            attempt = consume_login_attempt(session, state_value)
    except InvalidLoginAttemptError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        identity = await _oidc_provider(request).exchange_code(
            code=code,
            code_verifier=attempt.code_verifier,
            nonce=attempt.nonce,
            redirect_uri=attempt.redirect_uri,
        )
    except OIDCProviderError as exc:
        raise HTTPException(
            status_code=401,
            detail="Authentication could not be verified.",
        ) from exc
    try:
        with identity_session() as session:
            operator = enroll_operator(
                session,
                identity,
                allowed_emails=settings.oidc_allowed_emails,
            )
            session_token = create_operator_session(
                session,
                operator=operator,
                ttl_seconds=settings.session_ttl_seconds,
            )
    except OperatorEnrollmentDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    destination = settings.cockpit_url.rstrip("/")
    if attempt.return_to != "/":
        destination = f"{destination}{attempt.return_to}"
    response = RedirectResponse(destination, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        settings.session_cookie_name,
        session_token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.env != "development",
        samesite="lax",
        path="/",
    )
    return response


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout_endpoint(
    request: Request,
    settings: SettingsDependency,
) -> Response:
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        with identity_session() as session:
            revoke_operator_session(session, token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        secure=settings.env != "development",
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/auth/me", response_model=AuthenticatedOperatorResponse)
def authenticated_operator_endpoint(
    operator: OperatorDependency,
    principal: PrincipalDependency,
) -> AuthenticatedOperatorResponse:
    return AuthenticatedOperatorResponse(
        id=operator.id,
        display_name=operator.display_name,
        auth_mode=principal.auth_mode,
        sanitized_data_allowed=principal.sanitized_data_allowed,
    )


@router.post("/engagements", response_model=EngagementResponse, status_code=status.HTTP_201_CREATED)
def create_engagement_endpoint(
    payload: EngagementCreate,
    session: SessionDependency,
    operator: OperatorDependency,
    principal: PrincipalDependency,
) -> EngagementResponse:
    if payload.data_classification == "sanitized" and not principal.sanitized_data_allowed:
        raise HTTPException(
            status_code=403,
            detail="Sanitized engagements require production OIDC authentication.",
        )
    engagement = create_engagement(
        session,
        operator=operator,
        name=payload.name,
        primary_outcome=payload.primary_outcome,
        data_classification=payload.data_classification,
    )
    return EngagementResponse.model_validate(engagement)


@router.get("/engagements", response_model=list[EngagementResponse])
def list_engagements_endpoint(
    session: SessionDependency,
    operator: OperatorDependency,
    principal: PrincipalDependency,
) -> list[EngagementResponse]:
    return [
        EngagementResponse.model_validate(item)
        for item in list_engagements(
            session,
            operator.id,
            include_sanitized=principal.sanitized_data_allowed,
        )
    ]


@router.get("/engagements/{engagement_id}", response_model=EngagementWorkspaceResponse)
def get_engagement_endpoint(
    engagement_id: UUID,
    session: SessionDependency,
    _access: EngagementReadDependency,
) -> EngagementWorkspaceResponse:
    try:
        engagement = get_engagement(session, engagement_id)
    except EngagementNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Engagement not found.") from exc
    return EngagementWorkspaceResponse(
        engagement=EngagementResponse.model_validate(engagement),
        counts=get_engagement_counts(session, engagement_id),
    )


@router.post(
    "/engagements/{engagement_id}/evidence",
    response_model=EvidenceResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_evidence_endpoint(
    engagement_id: UUID,
    session: SessionDependency,
    operator: OperatorDependency,
    _access: EngagementWriteDependency,
    store: EvidenceStoreDependency,
    file: Annotated[UploadFile, File()],
    source_timestamp: Annotated[datetime | None, Form()] = None,
) -> EvidenceResponse:
    content = await file.read()
    try:
        asset = create_evidence_asset(
            session,
            store,
            engagement_id=engagement_id,
            operator=operator,
            file_name=file.filename or "evidence.txt",
            content_type=file.content_type or "application/octet-stream",
            content=content,
            source_timestamp=source_timestamp,
        )
    except EvidenceValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return EvidenceResponse.model_validate(asset)


@router.post(
    "/engagements/{engagement_id}/notes",
    response_model=EvidenceResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_note_endpoint(
    engagement_id: UUID,
    payload: OperatorNoteCreate,
    session: SessionDependency,
    operator: OperatorDependency,
    _access: EngagementWriteDependency,
    store: EvidenceStoreDependency,
) -> EvidenceResponse:
    safe_title = "-".join(payload.title.casefold().split())
    asset = create_evidence_asset(
        session,
        store,
        engagement_id=engagement_id,
        operator=operator,
        file_name=f"operator-note-{safe_title}.md",
        content_type="text/markdown",
        content=payload.content.encode("utf-8"),
        source_type="operator_note",
        source_timestamp=payload.source_timestamp,
    )
    return EvidenceResponse.model_validate(asset)


@router.get("/engagements/{engagement_id}/evidence", response_model=list[EvidenceResponse])
def list_evidence_endpoint(
    engagement_id: UUID,
    session: SessionDependency,
    _access: EngagementReadDependency,
) -> list[EvidenceResponse]:
    return [EvidenceResponse.model_validate(item) for item in list_evidence(session, engagement_id)]


@router.get("/engagements/{engagement_id}/claims", response_model=list[ClaimResponse])
def list_claims_endpoint(
    engagement_id: UUID,
    session: SessionDependency,
    _access: EngagementReadDependency,
    claim_status: str | None = Query(default=None, alias="status"),
) -> list[ClaimResponse]:
    response: list[ClaimResponse] = []
    for claim in list_claims(session, engagement_id, claim_status):
        provenance = [
            ProvenanceResponse.model_validate(item)
            for item in evidence_for_claim(session, claim.id)
        ]
        response.append(
            ClaimResponse(
                id=claim.id,
                claim_kind=claim.claim_kind,
                subject_text=claim.subject_text,
                predicate=claim.predicate,
                object_text=claim.object_text,
                summary=claim.summary,
                normalized_payload=claim.normalized_payload,
                confidence=claim.confidence,
                materiality=claim.materiality,
                status=claim.status,
                created_at=claim.created_at,
                provenance=provenance,
            )
        )
    return response


@router.post(
    "/engagements/{engagement_id}/claims/{claim_id}/review",
    response_model=ClaimReviewResponse,
)
def review_claim_endpoint(
    engagement_id: UUID,
    claim_id: UUID,
    payload: ClaimReviewRequest,
    session: SessionDependency,
    operator: OperatorDependency,
    _access: EngagementWriteDependency,
) -> ClaimReviewResponse:
    try:
        assertion = review_claim(
            session,
            engagement_id=engagement_id,
            claim_id=claim_id,
            operator=operator,
            decision=payload.decision,
            reason=payload.reason,
        )
    except ClaimNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Claim not found.") from exc
    except ClaimAlreadyReviewedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ClaimReviewResponse(
        claim_id=claim_id,
        decision=payload.decision,
        assertion_id=assertion.id if assertion else None,
    )


@router.get("/engagements/{engagement_id}/operating-model", response_model=OperatingModelResponse)
def get_operating_model_endpoint(
    engagement_id: UUID,
    session: SessionDependency,
    _access: EngagementReadDependency,
) -> OperatingModelResponse:
    entities = [
        EntityResponse.model_validate(item) for item in list_entities(session, engagement_id)
    ]
    assertions = [
        AssertionResponse.model_validate(item)
        for item in list_verified_assertions(session, engagement_id)
    ]
    return OperatingModelResponse(entities=entities, assertions=assertions)


@router.get(
    "/engagements/{engagement_id}/contradictions",
    response_model=list[ContradictionResponse],
)
def list_contradictions_endpoint(
    engagement_id: UUID,
    session: SessionDependency,
    _access: EngagementReadDependency,
) -> list[ContradictionResponse]:
    return [
        ContradictionResponse.model_validate(item)
        for item in list_contradictions(session, engagement_id)
    ]


@router.post(
    "/engagements/{engagement_id}/contradictions/{contradiction_id}/resolve",
    response_model=ContradictionResponse,
)
def resolve_contradiction_endpoint(
    engagement_id: UUID,
    contradiction_id: UUID,
    payload: ContradictionResolveRequest,
    session: SessionDependency,
    operator: OperatorDependency,
    _access: EngagementWriteDependency,
) -> ContradictionResponse:
    try:
        contradiction = resolve_contradiction(
            session,
            engagement_id=engagement_id,
            contradiction_id=contradiction_id,
            operator=operator,
            resolution_type=payload.resolution_type,
            reason=payload.reason,
        )
    except ContradictionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Contradiction not found.") from exc
    except ContradictionAlreadyResolvedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ContradictionResponse.model_validate(contradiction)


@router.get(
    "/engagements/{engagement_id}/workflows",
    response_model=WorkflowWorkspaceResponse,
)
def get_workflows_endpoint(
    engagement_id: UUID,
    session: SessionDependency,
    _access: EngagementReadDependency,
) -> WorkflowWorkspaceResponse:
    workflows = list_latest_workflows(session, engagement_id)
    return WorkflowWorkspaceResponse(
        current=_workflow_response(session, workflows["current"]),
        target=_workflow_response(session, workflows["target"]),
    )


@router.post(
    "/engagements/{engagement_id}/workflows/current/generate",
    response_model=WorkflowResponse,
)
def generate_current_workflow_endpoint(
    engagement_id: UUID,
    session: SessionDependency,
    operator: OperatorDependency,
    _access: EngagementWriteDependency,
) -> WorkflowResponse:
    try:
        workflow = generate_current_workflow(
            session, engagement_id=engagement_id, operator=operator
        )
    except WorkflowStageGateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    response = _workflow_response(session, workflow)
    assert response is not None
    return response


@router.post(
    "/engagements/{engagement_id}/workflows/target/generate",
    response_model=WorkflowResponse,
)
def generate_target_workflow_endpoint(
    engagement_id: UUID,
    session: SessionDependency,
    operator: OperatorDependency,
    _access: EngagementWriteDependency,
) -> WorkflowResponse:
    try:
        workflow = generate_target_workflow(session, engagement_id=engagement_id, operator=operator)
    except WorkflowStageGateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    response = _workflow_response(session, workflow)
    assert response is not None
    return response


@router.post(
    "/engagements/{engagement_id}/workflows/{workflow_id}/steps/{step_id}",
    response_model=WorkflowStepResponse,
)
def update_workflow_step_endpoint(
    engagement_id: UUID,
    workflow_id: UUID,
    step_id: UUID,
    payload: WorkflowStepUpdateRequest,
    session: SessionDependency,
    operator: OperatorDependency,
    _access: EngagementWriteDependency,
) -> WorkflowStepResponse:
    try:
        step = update_workflow_step(
            session,
            engagement_id=engagement_id,
            workflow_id=workflow_id,
            step_id=step_id,
            operator=operator,
            **payload.model_dump(exclude_unset=True),
        )
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Workflow step not found.") from exc
    except WorkflowStageGateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return WorkflowStepResponse.model_validate(step)


@router.post(
    "/engagements/{engagement_id}/workflows/{workflow_id}/approve",
    response_model=WorkflowResponse,
)
def approve_workflow_endpoint(
    engagement_id: UUID,
    workflow_id: UUID,
    payload: WorkflowApproveRequest,
    session: SessionDependency,
    operator: OperatorDependency,
    _access: EngagementWriteDependency,
) -> WorkflowResponse:
    try:
        workflow = approve_workflow(
            session,
            engagement_id=engagement_id,
            workflow_id=workflow_id,
            operator=operator,
            reason=payload.reason,
        )
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Workflow not found.") from exc
    except WorkflowStageGateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    response = _workflow_response(session, workflow)
    assert response is not None
    return response


@router.get(
    "/engagements/{engagement_id}/economics",
    response_model=EconomicCaseResponse | None,
)
def get_economics_endpoint(
    engagement_id: UUID,
    session: SessionDependency,
    _access: EngagementReadDependency,
) -> EconomicCaseResponse | None:
    economic_case = get_latest_economic_case(session, engagement_id)
    return EconomicCaseResponse.model_validate(economic_case) if economic_case else None


@router.post(
    "/engagements/{engagement_id}/economics/calculate",
    response_model=EconomicCaseResponse,
)
def calculate_economics_endpoint(
    engagement_id: UUID,
    payload: EconomicCalculateRequest,
    session: SessionDependency,
    operator: OperatorDependency,
    _access: EngagementWriteDependency,
) -> EconomicCaseResponse:
    input_payload = payload.model_dump(exclude={"assumptions"})
    try:
        economic_case = calculate_economic_case(
            session,
            engagement_id=engagement_id,
            operator=operator,
            values={key: item["value"] for key, item in input_payload.items()},
            classifications={key: item["classification"] for key, item in input_payload.items()},
            assumptions=payload.assumptions,
        )
    except EconomicStageGateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return EconomicCaseResponse.model_validate(economic_case)


@router.post(
    "/engagements/{engagement_id}/economics/{economic_case_id}/approve",
    response_model=EconomicCaseResponse,
)
def approve_economics_endpoint(
    engagement_id: UUID,
    economic_case_id: UUID,
    session: SessionDependency,
    operator: OperatorDependency,
    _access: EngagementWriteDependency,
) -> EconomicCaseResponse:
    try:
        economic_case = approve_economic_case(
            session,
            engagement_id=engagement_id,
            economic_case_id=economic_case_id,
            operator=operator,
        )
    except EconomicCaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Economic case not found.") from exc
    except EconomicStageGateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return EconomicCaseResponse.model_validate(economic_case)


@router.get(
    "/engagements/{engagement_id}/implementation-specifications",
    response_model=ImplementationArtifactResponse | None,
)
def get_implementation_specification_endpoint(
    engagement_id: UUID,
    session: SessionDependency,
    _access: EngagementReadDependency,
) -> ImplementationArtifactResponse | None:
    artifact = get_latest_artifact(session, engagement_id)
    return ImplementationArtifactResponse.model_validate(artifact) if artifact else None


@router.post(
    "/engagements/{engagement_id}/implementation-specifications/generate",
    response_model=ImplementationArtifactResponse,
)
def generate_implementation_specification_endpoint(
    engagement_id: UUID,
    session: SessionDependency,
    operator: OperatorDependency,
    _access: EngagementWriteDependency,
) -> ImplementationArtifactResponse:
    try:
        artifact = generate_implementation_specification(
            session, engagement_id=engagement_id, operator=operator
        )
    except ArtifactStageGateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ImplementationArtifactResponse.model_validate(artifact)


def _workflow_response(
    session: SessionDependency, workflow: WorkflowVersion | None
) -> WorkflowResponse | None:
    if workflow is None:
        return None
    return WorkflowResponse(
        id=workflow.id,
        workflow_kind=workflow.workflow_kind,
        version_number=workflow.version_number,
        name=workflow.name,
        objective=workflow.objective,
        status=workflow.status,
        source_workflow_id=workflow.source_workflow_id,
        source_assertion_ids=workflow.source_assertion_ids,
        generated_by=workflow.generated_by,
        approved_at=workflow.approved_at,
        approval_reason=workflow.approval_reason,
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
        steps=[
            WorkflowStepResponse.model_validate(step)
            for step in list_workflow_steps(session, workflow.id)
        ],
    )


def _oidc_provider(request: Request) -> OIDCProvider:
    provider = getattr(request.app.state, "oidc_provider", None)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The identity provider is not configured.",
        )
    return cast(OIDCProvider, provider)


def _validated_return_to(value: str) -> str:
    contains_control_character = any(ord(character) < 32 for character in value)
    if (
        not value.startswith("/")
        or value.startswith("//")
        or "\\" in value
        or contains_control_character
    ):
        raise HTTPException(status_code=400, detail="The post-login path is invalid.")
    return value
