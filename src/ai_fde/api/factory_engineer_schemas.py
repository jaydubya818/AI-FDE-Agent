from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ai_fde.modules.factory_engineer.schemas import (
    ApprovalBinding,
    CustomerFactoryModelInput,
    DeploymentTarget,
    FactoryDeploymentPackageInput,
    FactoryDeploymentPackageStatus,
    FactoryOpportunityInput,
    FactoryOpportunityStatus,
    ImmutableVersionReference,
    PackageIssuer,
    PackageSourceLineage,
    ReadinessAssessmentInput,
    ReadinessAssessmentStatus,
    ReadinessStageSnapshot,
    ReadinessStatus,
    SourceReference,
)


class CustomerFactoryModelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    engagement_id: UUID
    version_number: int
    status: str
    organization: dict[str, Any]
    systems: list[dict[str, Any]]
    repositories: list[dict[str, Any]]
    environments: list[dict[str, Any]]
    workflows: list[dict[str, Any]]
    policies: list[dict[str, Any]]
    authority_boundaries: list[dict[str, Any]]
    constraints: list[dict[str, Any]]
    risks: list[dict[str, Any]]
    baselines: list[dict[str, Any]]
    evidence_refs: list[SourceReference]
    verified_claim_refs: list[SourceReference]
    assumption_refs: list[SourceReference]
    factory_opportunity_refs: list[SourceReference]
    content_digest: str
    approved_at: datetime | None
    stale_reason: str | None
    created_at: datetime


class FactoryOpportunityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    engagement_id: UUID
    opportunity_key: str
    version_number: int
    status: FactoryOpportunityStatus
    name: str
    description: str
    source_workflow_ref: ImmutableVersionReference
    customer_factory_model_id: UUID
    customer_factory_model_version: int
    value_score: int
    verifiability_score: int
    readiness_score: int
    risk_score: int
    autonomy_potential: int
    priority_score: int
    factors: dict[str, int]
    rubric: dict[str, Any]
    rubric_version: str
    economics_ref: SourceReference
    evidence_refs: list[SourceReference]
    rationale: list[str]
    blockers: list[str]
    recommendation: str
    content_digest: str
    selection_reason: str | None
    selected_at: datetime | None
    rejection_reason: str | None
    rejected_at: datetime | None
    stale_reason: str | None
    created_at: datetime


class FDLCReadinessAssessmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    engagement_id: UUID
    version_number: int
    status: ReadinessAssessmentStatus
    overall_status: ReadinessStatus
    customer_factory_model_id: UUID
    customer_factory_model_version: int
    selected_opportunity_id: UUID
    selected_opportunity_version: int
    current_workflow_ref: ImmutableVersionReference
    target_workflow_ref: ImmutableVersionReference
    stages: list[ReadinessStageSnapshot]
    content_digest: str
    approved_at: datetime | None
    stale_reason: str | None
    created_at: datetime


class DeploymentPackageResponse(BaseModel):
    id: UUID
    engagement_id: UUID
    package_id: UUID
    package_version: int
    schema_version: str
    status: FactoryDeploymentPackageStatus
    issuer: PackageIssuer
    source: PackageSourceLineage
    target: DeploymentTarget
    deployment_intent: FactoryDeploymentPackageInput
    digest: str | None
    approval: ApprovalBinding | None
    issued_at: datetime | None
    approved_at: datetime | None
    published_at: datetime | None
    state_reason: str | None
    created_at: datetime


class PackageRetrievalEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    engagement_id: UUID
    package_id: UUID
    package_version: int
    requester_identity: str
    requester_system: str
    result: str
    digest: str | None
    correlation_id: UUID
    created_at: datetime


class FactoryHandoffWorkspaceResponse(BaseModel):
    customer_model: CustomerFactoryModelResponse | None
    opportunities: list[FactoryOpportunityResponse]
    readiness: FDLCReadinessAssessmentResponse | None
    packages: list[DeploymentPackageResponse]
    latest_retrieval: PackageRetrievalEventResponse | None


class FactoryHandoffPrerequisitesResponse(BaseModel):
    engagement_id: UUID
    organization_key: str
    organization_label: str
    workflow_name: str
    primary_outcome: str
    evidence_refs: list[SourceReference]
    verified_claim_refs: list[SourceReference]
    current_workflow_ref: ImmutableVersionReference | None
    target_workflow_ref: ImmutableVersionReference | None
    economic_case_ref: SourceReference | None
    implementation_artifact_refs: list[SourceReference]


class FactoryOpportunityCreateRequest(BaseModel):
    customer_factory_model_id: UUID
    opportunity: FactoryOpportunityInput


class ReadinessAssessmentCreateRequest(BaseModel):
    customer_factory_model_id: UUID
    selected_opportunity_id: UUID
    current_workflow_id: UUID
    target_workflow_id: UUID
    assessment: ReadinessAssessmentInput


class DeploymentPackageCreateRequest(BaseModel):
    customer_factory_model_id: UUID
    readiness_assessment_id: UUID
    factory_opportunity_id: UUID
    target: DeploymentTarget
    deployment_intent: FactoryDeploymentPackageInput
    package_id: UUID | None = None


class ReasonRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=4000)


class DeploymentPackageApprovalRequest(BaseModel):
    authority_basis_ref: SourceReference


class RetrievalGrantCreateRequest(BaseModel):
    service_operator_id: UUID | None = Field(
        default=None,
        description=(
            "Optional existing dedicated retrieval identity. When omitted, Factory "
            "Engineer provisions or reuses the engagement's viewer-only service identity."
        ),
    )
    requester_identity: str = Field(min_length=1, max_length=255)
    requester_system: str = Field(min_length=1, max_length=255)
    expires_at: datetime


class RetrievalGrantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    engagement_id: UUID
    service_operator_id: UUID
    requester_identity: str
    requester_system: str
    scope: str
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime


class IssuedRetrievalGrantResponse(RetrievalGrantResponse):
    token: str = Field(description="Returned once. Only its SHA-256 digest is stored.")


class CustomerFactoryModelCreateRequest(CustomerFactoryModelInput):
    """Named API type for the Customer Factory Model draft payload."""
