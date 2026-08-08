from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import select

from ai_fde.api.dependencies import (
    EvidenceStoreDependency,
    OperatorDependency,
    SessionDependency,
)
from ai_fde.api.schemas import (
    AssertionResponse,
    ClaimResponse,
    ClaimReviewRequest,
    ClaimReviewResponse,
    ContradictionResponse,
    EngagementCreate,
    EngagementResponse,
    EngagementWorkspaceResponse,
    EntityResponse,
    EvidenceResponse,
    HealthResponse,
    OperatingModelResponse,
    OperatorNoteCreate,
    ProvenanceResponse,
)
from ai_fde.models import Contradiction
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
from ai_fde.modules.knowledge.review import (
    ClaimAlreadyReviewedError,
    ClaimNotFoundError,
    evidence_for_claim,
    list_claims,
    review_claim,
)
from ai_fde.modules.operating_model.service import list_entities, list_verified_assertions

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="ai-fde-api")


@router.post("/engagements", response_model=EngagementResponse, status_code=status.HTTP_201_CREATED)
def create_engagement_endpoint(
    payload: EngagementCreate,
    session: SessionDependency,
    operator: OperatorDependency,
) -> EngagementResponse:
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
) -> list[EngagementResponse]:
    return [
        EngagementResponse.model_validate(item) for item in list_engagements(session, operator.id)
    ]


@router.get("/engagements/{engagement_id}", response_model=EngagementWorkspaceResponse)
def get_engagement_endpoint(
    engagement_id: UUID,
    session: SessionDependency,
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
    store: EvidenceStoreDependency,
    file: Annotated[UploadFile, File()],
    source_timestamp: Annotated[datetime | None, Form()] = None,
) -> EvidenceResponse:
    _require_engagement(session, engagement_id)
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
    store: EvidenceStoreDependency,
) -> EvidenceResponse:
    _require_engagement(session, engagement_id)
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
    engagement_id: UUID, session: SessionDependency
) -> list[EvidenceResponse]:
    _require_engagement(session, engagement_id)
    return [EvidenceResponse.model_validate(item) for item in list_evidence(session, engagement_id)]


@router.get("/engagements/{engagement_id}/claims", response_model=list[ClaimResponse])
def list_claims_endpoint(
    engagement_id: UUID,
    session: SessionDependency,
    claim_status: str | None = Query(default=None, alias="status"),
) -> list[ClaimResponse]:
    _require_engagement(session, engagement_id)
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
) -> ClaimReviewResponse:
    _require_engagement(session, engagement_id)
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
    engagement_id: UUID, session: SessionDependency
) -> OperatingModelResponse:
    _require_engagement(session, engagement_id)
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
    engagement_id: UUID, session: SessionDependency
) -> list[ContradictionResponse]:
    _require_engagement(session, engagement_id)
    items = session.scalars(
        select(Contradiction)
        .where(Contradiction.engagement_id == engagement_id)
        .order_by(Contradiction.created_at.desc())
    )
    return [ContradictionResponse.model_validate(item, from_attributes=True) for item in items]


def _require_engagement(session: SessionDependency, engagement_id: UUID) -> None:
    try:
        get_engagement(session, engagement_id)
    except EngagementNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Engagement not found.") from exc
