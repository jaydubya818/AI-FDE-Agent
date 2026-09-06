from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EngagementCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    workflow_name: str = Field(default="Primary Workflow", min_length=2, max_length=255)
    primary_outcome: str = Field(min_length=10, max_length=2000)
    data_classification: Literal["synthetic", "sanitized"] = "synthetic"


class EngagementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    workflow_name: str
    primary_outcome: str
    lifecycle_stage: str
    data_classification: str
    data_lifecycle_status: str
    retention_expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


class EngagementWorkspaceResponse(BaseModel):
    engagement: EngagementResponse
    counts: dict[str, int]


class DesignPartnerAuthorizedUserResponse(BaseModel):
    operator_id: UUID
    display_name: str
    role: Literal["owner", "operator", "viewer"]


class DesignPartnerQualificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    engagement_id: UUID
    partner_key: str
    organization: str
    status: Literal["ACTIVE", "SUSPENDED", "REVOKED"]
    qualification_state: Literal["CONFIGURED", "IN_PROGRESS", "BLOCKED", "QUALIFIED"]
    authorized_users: list[DesignPartnerAuthorizedUserResponse]
    authorized_data_source_keys: list[str]
    authorized_repository_refs: list[str]
    allowed_workflow_classes: list[str]
    data_classification: Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]
    retention_days: int
    authorization_basis_ref: str
    created_at: datetime
    updated_at: datetime


class EngagementAssessmentCreate(BaseModel):
    delivery_method: Literal["ai_fde", "conventional"]
    perspective: Literal["operator", "engineering"]
    outcome: Literal["completed", "blocked", "abandoned"]
    duration_minutes: int = Field(ge=1, le=10_080)
    usefulness_score: int = Field(ge=1, le=5)
    clarification_count: int = Field(default=0, ge=0, le=10_000)
    rework_count: int = Field(default=0, ge=0, le=10_000)
    workaround_count: int = Field(default=0, ge=0, le=10_000)
    trust_failure_count: int = Field(default=0, ge=0, le=10_000)
    notes: str | None = Field(default=None, max_length=2000)


class EngagementAssessmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    engagement_id: UUID
    evaluator_id: UUID
    delivery_method: str
    perspective: str
    outcome: str
    duration_minutes: int
    usefulness_score: int
    clarification_count: int
    rework_count: int
    workaround_count: int
    trust_failure_count: int
    notes: str | None
    created_at: datetime
    updated_at: datetime


class DeliveryScorecardResponse(BaseModel):
    engagement: dict[str, Any]
    milestones: dict[str, bool]
    claims: dict[str, int]
    contradictions: dict[str, int]
    packet: dict[str, Any]
    provider: dict[str, Any]
    assessments: list[dict[str, Any]]


class InternalAlphaScorecardResponse(BaseModel):
    program: str
    profile_count: int
    packet_complete_count: int
    accepted_material_claim_count: int
    total_provider_tokens: int
    engagements: list[DeliveryScorecardResponse]
    comparison: dict[str, Any]


class AuthenticatedOperatorResponse(BaseModel):
    id: UUID
    display_name: str
    auth_mode: str
    sanitized_data_allowed: bool


class RetentionUpdateRequest(BaseModel):
    retain_until: datetime


class EngagementExportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    schema_version: str
    source_fingerprint: str
    archive_hash: str
    byte_count: int
    record_count: int
    evidence_object_count: int
    exported_at: datetime


class EngagementDataLifecycleResponse(BaseModel):
    status: str
    retention_expires_at: datetime | None
    membership_role: str
    latest_export: EngagementExportResponse | None
    export_current: bool
    retention_blocked: bool
    can_delete: bool


class EngagementDeletionRequest(BaseModel):
    export_id: UUID
    confirmation_name: str = Field(min_length=2, max_length=255)


class EngagementDeletionReceiptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    engagement_id: UUID
    status: str
    data_classification: str
    export_id: UUID
    source_fingerprint: str
    archive_hash: str
    database_row_count: int
    evidence_object_count: int
    failure_code: str | None
    requested_at: datetime
    completed_at: datetime | None


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
    design_partner_qualification_id: UUID | None
    authorized_source_key: str | None
    authorized_workflow_class: str | None
    data_classification: str | None
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
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    summary: str
    status: str
    blocking: bool
    left_claim_id: UUID
    right_claim_id: UUID
    resolution_type: str | None
    resolution_reason: str | None
    resolved_by_id: UUID | None
    resolved_at: datetime | None
    created_at: datetime


class ContradictionResolveRequest(BaseModel):
    resolution_type: Literal["accepted_exception", "not_a_conflict", "superseded", "override"]
    reason: str = Field(min_length=5, max_length=2000)


class WorkflowStepResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    step_key: str
    position: int
    name: str
    description: str
    step_type: str
    actor_label: str | None
    system_label: str | None
    allocation: str
    rationale: str
    controls: list[str]
    source_assertion_id: UUID | None


class WorkflowResponse(BaseModel):
    id: UUID
    workflow_kind: str
    version_number: int
    name: str
    objective: str
    status: str
    source_workflow_id: UUID | None
    source_assertion_ids: list[str]
    generated_by: str
    approved_at: datetime | None
    approval_reason: str | None
    created_at: datetime
    updated_at: datetime
    steps: list[WorkflowStepResponse]


class WorkflowWorkspaceResponse(BaseModel):
    current: WorkflowResponse | None
    target: WorkflowResponse | None


class WorkflowStepUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    description: str | None = Field(default=None, min_length=2, max_length=4000)
    actor_label: str | None = Field(default=None, max_length=255)
    allocation: Literal["human", "software", "ai", "ai_human"] | None = None
    rationale: str | None = Field(default=None, min_length=2, max_length=4000)
    controls: list[str] | None = Field(default=None, max_length=20)


class WorkflowApproveRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


EvidenceClassification = Literal["measured", "calculated", "estimated", "synthetic", "simulated"]


class EconomicInputValue(BaseModel):
    value: Decimal = Field(ge=0, max_digits=18, decimal_places=4)
    classification: EvidenceClassification


class EconomicCalculateRequest(BaseModel):
    annual_volume: EconomicInputValue
    current_minutes_per_item: EconomicInputValue
    target_minutes_per_item: EconomicInputValue
    loaded_hourly_cost: EconomicInputValue
    implementation_cost: EconomicInputValue
    annual_operating_cost: EconomicInputValue
    assumptions: list[str] = Field(default_factory=list, max_length=20)


class EconomicCaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    version_number: int
    status: str
    source_target_workflow_id: UUID
    formula_version: str
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    scenarios: dict[str, Any]
    assumptions: list[str]
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ImplementationArtifactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    artifact_type: str
    packet_version: int
    version_number: int
    status: str
    title: str
    content: str
    content_hash: str
    source_current_workflow_id: UUID
    source_target_workflow_id: UUID
    economic_case_id: UUID
    source_assertion_ids: list[str]
    generated_at: datetime


class HealthResponse(BaseModel):
    status: str
    service: str
