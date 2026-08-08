from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EngagementCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    primary_outcome: str = Field(min_length=10, max_length=2000)
    data_classification: Literal["synthetic", "sanitized"] = "synthetic"


class EngagementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    primary_outcome: str
    lifecycle_stage: str
    data_classification: str
    created_at: datetime
    updated_at: datetime


class EngagementWorkspaceResponse(BaseModel):
    engagement: EngagementResponse
    counts: dict[str, int]


class EvidenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    engagement_id: UUID
    file_name: str
    content_type: str
    content_hash: str
    byte_count: int
    source_type: str
    source_timestamp: datetime | None
    status: str
    error_message: str | None
    created_at: datetime


class OperatorNoteCreate(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    content: str = Field(min_length=1, max_length=100_000)
    source_timestamp: datetime | None = None


class ProvenanceResponse(BaseModel):
    claim_evidence_id: UUID
    evidence_segment_id: UUID
    evidence_asset_id: UUID
    file_name: str
    source_type: str
    source_timestamp: datetime | None
    locator: dict[str, Any]
    quote: str
    start_offset: int
    end_offset: int


class ClaimResponse(BaseModel):
    id: UUID
    claim_kind: str
    subject_text: str
    predicate: str
    object_text: str | None
    summary: str
    normalized_payload: dict[str, Any]
    confidence: Decimal
    materiality: str
    status: str
    created_at: datetime
    provenance: list[ProvenanceResponse]


class ClaimReviewRequest(BaseModel):
    decision: Literal["accepted", "rejected", "deferred"]
    reason: str | None = Field(default=None, max_length=2000)


class ClaimReviewResponse(BaseModel):
    claim_id: UUID
    decision: str
    assertion_id: UUID | None


class EntityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    entity_type: str
    canonical_key: str
    display_name: str
    status: str
    created_at: datetime


class AssertionProvenanceResponse(BaseModel):
    file_name: str
    source_type: str
    source_timestamp: datetime | None
    locator: dict[str, Any]
    quote: str
    segment_id: UUID


class AssertionResponse(BaseModel):
    id: UUID
    subject: str
    subject_entity_id: UUID
    predicate: str
    object: str | None
    object_entity_id: UUID | None
    value: dict[str, Any]
    status: str
    confidence: Decimal
    recorded_at: datetime
    evidence: AssertionProvenanceResponse


class OperatingModelResponse(BaseModel):
    entities: list[EntityResponse]
    assertions: list[AssertionResponse]


class ContradictionResponse(BaseModel):
    id: UUID
    summary: str
    status: str
    blocking: bool
    left_claim_id: UUID
    right_claim_id: UUID
    created_at: datetime


class HealthResponse(BaseModel):
    status: str
    service: str
