from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

MAX_CONTRACT_ARRAY_ITEMS = 200
MAX_CODE_SCOPES = 50
BoundedListText = Annotated[str, Field(min_length=1, max_length=4000)]
CodeScope = Annotated[str, Field(min_length=1, max_length=1024)]


class CustomerFactoryModelStatus(StrEnum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    STALE = "STALE"


class ReadinessAssessmentStatus(StrEnum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    STALE = "STALE"


class ReadinessStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    READY = "READY"
    CONDITIONALLY_READY = "CONDITIONALLY_READY"
    NOT_READY = "NOT_READY"
    STALE = "STALE"


class FDLCStage(StrEnum):
    DISCOVER = "DISCOVER"
    DESIGN = "DESIGN"
    ASSEMBLE = "ASSEMBLE"
    VALIDATE = "VALIDATE"
    DEPLOY = "DEPLOY"
    OPERATE = "OPERATE"
    IMPROVE = "IMPROVE"


class FactoryOpportunityStatus(StrEnum):
    CANDIDATE = "CANDIDATE"
    ASSESSED = "ASSESSED"
    RECOMMENDED = "RECOMMENDED"
    SELECTED = "SELECTED"
    REJECTED = "REJECTED"
    STALE = "STALE"


class FactoryDeploymentPackageStatus(StrEnum):
    DRAFT = "DRAFT"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"
    STALE = "STALE"


class ProvenanceKind(StrEnum):
    EVIDENCE = "EVIDENCE"
    VERIFIED_CLAIM = "VERIFIED_CLAIM"
    APPROVED_INPUT = "APPROVED_INPUT"
    ASSUMPTION = "ASSUMPTION"


class SourceReference(BaseModel):
    kind: ProvenanceKind
    ref: str = Field(min_length=1, max_length=1024)
    version: int | None = Field(default=None, ge=1)
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def require_versioned_decisions(self) -> Self:
        if (
            self.kind in {ProvenanceKind.VERIFIED_CLAIM, ProvenanceKind.APPROVED_INPUT}
            and self.version is None
        ):
            raise ValueError(f"{self.kind} references must pin an immutable version")
        return self


class TraceableFact(BaseModel):
    key: str = Field(min_length=1, max_length=160)
    label: str = Field(min_length=1, max_length=512)
    description: str = Field(min_length=1, max_length=4000)
    provenance_refs: list[SourceReference] = Field(
        min_length=1, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    attributes: dict[str, Any] = Field(default_factory=dict)


class CustomerFactoryModelInput(BaseModel):
    organization: TraceableFact
    systems: list[TraceableFact] = Field(
        default_factory=list, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    repositories: list[TraceableFact] = Field(
        default_factory=list, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    environments: list[TraceableFact] = Field(
        default_factory=list, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    workflows: list[TraceableFact] = Field(
        min_length=1, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    policies: list[TraceableFact] = Field(
        default_factory=list, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    authority_boundaries: list[TraceableFact] = Field(
        default_factory=list, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    constraints: list[TraceableFact] = Field(
        default_factory=list, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    risks: list[TraceableFact] = Field(
        default_factory=list, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    baselines: list[TraceableFact] = Field(
        default_factory=list, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    evidence_refs: list[SourceReference] = Field(
        default_factory=list, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    verified_claim_refs: list[SourceReference] = Field(
        default_factory=list, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    assumption_refs: list[SourceReference] = Field(
        default_factory=list, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    factory_opportunity_refs: list[SourceReference] = Field(
        default_factory=list, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )

    @model_validator(mode="after")
    def require_customer_truth_sources(self) -> Self:
        if not self.evidence_refs:
            raise ValueError("A customer factory model requires at least one evidence reference")
        if not self.verified_claim_refs:
            raise ValueError(
                "A customer factory model requires at least one verified claim reference"
            )
        return self


class ReadinessCriterionInput(BaseModel):
    key: str = Field(min_length=1, max_length=160)
    label: str = Field(min_length=1, max_length=512)
    satisfied: bool
    blocking: bool = True
    explanation: str = Field(min_length=1, max_length=4000)
    basis_refs: list[SourceReference] = Field(
        default_factory=list, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    next_action: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def require_basis_for_satisfied_criterion(self) -> Self:
        if self.satisfied and not self.basis_refs:
            raise ValueError("A satisfied readiness criterion requires a provenance basis")
        if not self.satisfied and not self.next_action:
            raise ValueError("An unsatisfied readiness criterion requires a next action")
        return self


class ReadinessStageInput(BaseModel):
    stage: FDLCStage
    criteria: list[ReadinessCriterionInput] = Field(
        min_length=1, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    risks: list[BoundedListText] = Field(
        default_factory=list, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    decisions: list[SourceReference] = Field(
        default_factory=list, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    required_artifacts: list[BoundedListText] = Field(
        default_factory=list, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    owner: str | None = Field(default=None, max_length=512)


class ReadinessStageSnapshot(BaseModel):
    stage: FDLCStage
    status: ReadinessStatus
    score: int = Field(ge=0, le=100)
    evidence_refs: list[SourceReference]
    blockers: list[str]
    risks: list[str]
    decisions: list[SourceReference]
    required_artifacts: list[str]
    owner: str | None
    next_actions: list[str]
    criteria: list[ReadinessCriterionInput]
    explanation: str
    updated_at: datetime


class ReadinessAssessmentInput(BaseModel):
    stages: list[ReadinessStageInput] = Field(min_length=7, max_length=7)

    @field_validator("stages")
    @classmethod
    def require_each_fdlc_stage_once(
        cls, stages: list[ReadinessStageInput]
    ) -> list[ReadinessStageInput]:
        actual = [stage.stage for stage in stages]
        expected = set(FDLCStage)
        if len(set(actual)) != len(actual) or set(actual) != expected:
            raise ValueError("Readiness requires each of the seven FDLC stages exactly once")
        return stages


class OpportunityFactors(BaseModel):
    workflow_frequency: int = Field(ge=0, le=5)
    human_effort: int = Field(ge=0, le=5)
    cycle_time: int = Field(ge=0, le=5)
    repeatability: int = Field(ge=0, le=5)
    standardization: int = Field(ge=0, le=5)
    evidence_quality: int = Field(ge=0, le=5)
    deterministic_verifiability: int = Field(ge=0, le=5)
    blast_radius: int = Field(ge=0, le=5)
    system_accessibility: int = Field(ge=0, le=5)
    data_sensitivity: int = Field(ge=0, le=5)
    implementation_complexity: int = Field(ge=0, le=5)
    expected_economic_value: int = Field(ge=0, le=5)
    autonomy_potential: int = Field(ge=0, le=5)


class ImmutableVersionReference(BaseModel):
    id: UUID
    version: int = Field(ge=1)
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class FactoryOpportunityInput(BaseModel):
    opportunity_key: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=512)
    description: str = Field(min_length=1, max_length=4000)
    source_workflow_ref: ImmutableVersionReference
    factors: OpportunityFactors
    economics_ref: SourceReference
    evidence_refs: list[SourceReference] = Field(
        min_length=1, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    blockers: list[BoundedListText] = Field(
        default_factory=list, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )


class FactoryOpportunityScore(BaseModel):
    value_score: int = Field(ge=0, le=100)
    verifiability_score: int = Field(ge=0, le=100)
    readiness_score: int = Field(ge=0, le=100)
    risk_score: int = Field(ge=0, le=100)
    autonomy_potential: int = Field(ge=0, le=100)
    priority_score: int = Field(ge=0, le=100)
    rationale: list[str]
    recommendation: str
    rubric_version: str
    rubric: dict[str, Any]


class PackageIssuer(BaseModel):
    issuer_id: str = Field(min_length=1, max_length=255)
    issuer_type: Literal["FDLC_FACTORY_ENGINEER"] = "FDLC_FACTORY_ENGINEER"
    environment: str = Field(min_length=1, max_length=120)
    authority_scope: Literal["DEPLOYMENT_PACKAGE_PUBLISH"] = "DEPLOYMENT_PACKAGE_PUBLISH"


class ApprovalBinding(BaseModel):
    decision_ref: SourceReference
    approved_by: UUID
    authorized_by_ref: str = Field(min_length=1, max_length=1024)
    authority_basis_ref: SourceReference
    approved_at: datetime

    @model_validator(mode="after")
    def require_approved_input_refs(self) -> Self:
        if self.decision_ref.kind != ProvenanceKind.APPROVED_INPUT:
            raise ValueError("Approval decisions must use an APPROVED_INPUT reference")
        if self.authority_basis_ref.kind != ProvenanceKind.APPROVED_INPUT:
            raise ValueError("Approval authority must use an APPROVED_INPUT reference")
        return self


class PackageIntegrity(BaseModel):
    canonicalization: Literal["fdlc-canonical-json/v1"] = "fdlc-canonical-json/v1"
    algorithm: Literal["sha256"] = "sha256"
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ContractRequirement(BaseModel):
    key: str = Field(min_length=1, max_length=160)
    statement: str = Field(min_length=1, max_length=4000)


class AcceptanceCriterion(ContractRequirement):
    verification_method: str = Field(min_length=1, max_length=2000)


class AuthorityBoundary(BaseModel):
    key: str = Field(min_length=1, max_length=160)
    subject: str = Field(min_length=1, max_length=512)
    maximum_authority: str = Field(min_length=1, max_length=2000)
    prohibited_actions: list[BoundedListText] = Field(
        min_length=1, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )


class VerificationRequirement(ContractRequirement):
    evidence_required: list[BoundedListText] = Field(
        min_length=1, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    independent: bool = True


class VerificationMethod(StrEnum):
    COMMAND = "COMMAND"
    TEST = "TEST"
    BROWSER = "BROWSER"
    MANUAL = "MANUAL"
    CHECKLIST = "CHECKLIST"


class PlanAssertion(BaseModel):
    assertion_id: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=512)
    outcome: str = Field(min_length=1, max_length=4000)
    verification_method: VerificationMethod
    pass_condition: str = Field(min_length=1, max_length=2000)
    required_evidence: str = Field(min_length=1, max_length=2000)
    requires_independent_validation: bool
    waiver_allowed: bool


class ExecutionRole(StrEnum):
    WORKER = "WORKER"
    VALIDATOR = "VALIDATOR"


class WorkOrderBlueprint(BaseModel):
    key: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=512)
    outcome: str = Field(min_length=1, max_length=4000)
    requirements: list[BoundedListText] = Field(
        min_length=1, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    acceptance_criterion_refs: list[BoundedListText] = Field(
        min_length=1, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    constraints: list[BoundedListText] = Field(
        default_factory=list, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    requested_code_scopes: list[CodeScope] = Field(
        min_length=1, max_length=MAX_CODE_SCOPES
    )
    capability_requirement_refs: list[BoundedListText] = Field(
        min_length=1, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    verification_requirement_refs: list[BoundedListText] = Field(
        min_length=1, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    authority_boundary_refs: list[BoundedListText] = Field(
        min_length=1, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    sequence: int = Field(ge=1)
    execution_role: ExecutionRole
    is_mutating: bool
    priority: int = Field(ge=1, le=4)
    risk_level: str = Field(pattern=r"^(LOW|MEDIUM|HIGH|CRITICAL)$")
    required_approvals: list[BoundedListText] = Field(
        default_factory=list, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    dependencies: list[BoundedListText] = Field(
        default_factory=list, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    assertion_ids: list[BoundedListText] = Field(
        min_length=1, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )


class FactoryDeploymentPackageInput(BaseModel):
    mission_title: str = Field(min_length=1, max_length=512)
    mission_context: str = Field(min_length=1, max_length=8000)
    stop_condition: str = Field(min_length=1, max_length=4000)
    plan_summary: str = Field(min_length=1, max_length=8000)
    rollback_approach: str = Field(min_length=1, max_length=4000)
    objective: str = Field(min_length=1, max_length=4000)
    intent: str = Field(min_length=1, max_length=4000)
    specification: str = Field(min_length=1, max_length=20_000)
    acceptance_criteria: list[AcceptanceCriterion] = Field(
        min_length=1, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    constraints: list[ContractRequirement] = Field(
        min_length=1, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    required_capabilities: list[ContractRequirement] = Field(
        min_length=1, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    required_agents: list[ContractRequirement] = Field(
        default_factory=list, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    required_skills: list[ContractRequirement] = Field(
        default_factory=list, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    required_tools: list[ContractRequirement] = Field(
        default_factory=list, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    model_requirements: list[ContractRequirement] = Field(
        default_factory=list, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    context_requirements: list[ContractRequirement] = Field(
        min_length=1, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    environment_requirements: list[ContractRequirement] = Field(
        min_length=1, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    authority_boundaries: list[AuthorityBoundary] = Field(
        min_length=1, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    policy_requirements: list[ContractRequirement] = Field(
        min_length=1, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    approval_requirements: list[ContractRequirement] = Field(
        min_length=1, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    verification_contract: list[VerificationRequirement] = Field(
        min_length=1, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    evaluation_requirements: list[ContractRequirement] = Field(
        min_length=1, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    rollback_requirements: list[ContractRequirement] = Field(
        min_length=1, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    observability_requirements: list[ContractRequirement] = Field(
        min_length=1, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    economics_baseline: dict[str, Any] = Field(max_length=128)
    risk_summary: list[ContractRequirement] = Field(
        min_length=1, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    evidence_refs: list[SourceReference] = Field(
        min_length=1, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    decision_refs: list[SourceReference] = Field(
        min_length=1, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    provenance: list[SourceReference] = Field(
        min_length=1, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    plan_assertions: list[PlanAssertion] = Field(
        min_length=1, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )
    work_order_blueprints: list[WorkOrderBlueprint] = Field(
        min_length=1, max_length=MAX_CONTRACT_ARRAY_ITEMS
    )

    @model_validator(mode="after")
    def validate_plan_reference_graph(self) -> Self:
        assertion_ids = {item.assertion_id for item in self.plan_assertions}
        criterion_keys = {item.key for item in self.acceptance_criteria}
        capability_keys = {item.key for item in self.required_capabilities}
        verification_keys = {item.key for item in self.verification_contract}
        authority_keys = {item.key for item in self.authority_boundaries}
        blueprint_keys = {item.key for item in self.work_order_blueprints}
        keyed_collections: tuple[tuple[str, list[str]], ...] = (
            ("plan assertion", [item.assertion_id for item in self.plan_assertions]),
            ("acceptance criterion", [item.key for item in self.acceptance_criteria]),
            ("constraint", [item.key for item in self.constraints]),
            ("capability requirement", [item.key for item in self.required_capabilities]),
            ("agent requirement", [item.key for item in self.required_agents]),
            ("skill requirement", [item.key for item in self.required_skills]),
            ("tool requirement", [item.key for item in self.required_tools]),
            ("model requirement", [item.key for item in self.model_requirements]),
            ("context requirement", [item.key for item in self.context_requirements]),
            ("environment requirement", [item.key for item in self.environment_requirements]),
            ("authority boundary", [item.key for item in self.authority_boundaries]),
            ("policy requirement", [item.key for item in self.policy_requirements]),
            ("approval requirement", [item.key for item in self.approval_requirements]),
            ("verification requirement", [item.key for item in self.verification_contract]),
            ("evaluation requirement", [item.key for item in self.evaluation_requirements]),
            ("rollback requirement", [item.key for item in self.rollback_requirements]),
            ("observability requirement", [item.key for item in self.observability_requirements]),
            ("risk", [item.key for item in self.risk_summary]),
            ("work-order blueprint", [item.key for item in self.work_order_blueprints]),
        )
        for label, keys in keyed_collections:
            if len(keys) != len(set(keys)):
                raise ValueError(f"{label.title()} keys must be unique")
        sequences = [item.sequence for item in self.work_order_blueprints]
        if len(sequences) != len(set(sequences)):
            raise ValueError("Work-order blueprint sequence values must be unique")
        for blueprint in self.work_order_blueprints:
            checks = (
                (set(blueprint.assertion_ids), assertion_ids, "assertion"),
                (
                    set(blueprint.acceptance_criterion_refs),
                    criterion_keys,
                    "acceptance criterion",
                ),
                (
                    set(blueprint.capability_requirement_refs),
                    capability_keys,
                    "capability requirement",
                ),
                (
                    set(blueprint.verification_requirement_refs),
                    verification_keys,
                    "verification requirement",
                ),
                (set(blueprint.authority_boundary_refs), authority_keys, "authority boundary"),
                (
                    set(blueprint.required_approvals),
                    {item.key for item in self.approval_requirements},
                    "approval requirement",
                ),
                (set(blueprint.dependencies), blueprint_keys, "blueprint dependency"),
            )
            for referenced, available, label in checks:
                missing = referenced - available
                if missing:
                    raise ValueError(
                        f"Blueprint {blueprint.key} has unknown {label} refs: {sorted(missing)}"
                    )
            if blueprint.key in blueprint.dependencies:
                raise ValueError(f"Blueprint {blueprint.key} cannot depend on itself")
            for label, refs in (
                ("assertion", blueprint.assertion_ids),
                ("acceptance criterion", blueprint.acceptance_criterion_refs),
                ("capability", blueprint.capability_requirement_refs),
                ("verification", blueprint.verification_requirement_refs),
                ("authority", blueprint.authority_boundary_refs),
                ("required approval", blueprint.required_approvals),
                ("dependency", blueprint.dependencies),
            ):
                if len(refs) != len(set(refs)):
                    raise ValueError(f"Blueprint {blueprint.key} has duplicate {label} refs")
        referenced_criteria = {
            criterion
            for blueprint in self.work_order_blueprints
            for criterion in blueprint.acceptance_criterion_refs
        }
        unreferenced_criteria = criterion_keys - referenced_criteria
        if unreferenced_criteria:
            raise ValueError(
                "Every acceptance criterion must be referenced by a work-order blueprint; "
                f"unreferenced={sorted(unreferenced_criteria)}"
            )
        dependencies = {item.key: set(item.dependencies) for item in self.work_order_blueprints}
        sequence_by_key = {item.key: item.sequence for item in self.work_order_blueprints}
        for blueprint in self.work_order_blueprints:
            if any(
                sequence_by_key[dependency] >= blueprint.sequence
                for dependency in blueprint.dependencies
            ):
                raise ValueError(
                    f"Blueprint {blueprint.key} dependencies must have an earlier sequence"
                )
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(key: str) -> None:
            if key in visiting:
                raise ValueError("Work-order blueprint dependencies must be acyclic")
            if key in visited:
                return
            visiting.add(key)
            for dependency in dependencies[key]:
                visit(dependency)
            visiting.remove(key)
            visited.add(key)

        for key in dependencies:
            visit(key)
        return self


class DeploymentTarget(BaseModel):
    workspace_ref: str = Field(min_length=1, max_length=1024)
    repository_ref: str = Field(min_length=1, max_length=1024)
    requested_code_scopes: list[CodeScope] = Field(min_length=1, max_length=MAX_CODE_SCOPES)
    semantic_execution_workflow_ref: str = Field(min_length=1, max_length=1024)
    environment_class: str = Field(min_length=1, max_length=160)

    @field_validator("requested_code_scopes")
    @classmethod
    def require_unique_code_scopes(cls, scopes: list[str]) -> list[str]:
        if len(scopes) != len(set(scopes)):
            raise ValueError("Requested code scopes must be unique")
        return scopes


class PackageSourceLineage(BaseModel):
    engagement_id: UUID
    customer_factory_model: ImmutableVersionReference
    current_workflow: ImmutableVersionReference
    target_workflow: ImmutableVersionReference
    readiness_assessment: ImmutableVersionReference
    factory_opportunity: ImmutableVersionReference


class ImmutablePackageDocument(BaseModel):
    schema_version: str
    package_id: UUID
    package_version: int
    status: Literal["PUBLISHED"] = "PUBLISHED"
    issuer: PackageIssuer
    issued_at: datetime
    approval: ApprovalBinding
    integrity: PackageIntegrity
    source: PackageSourceLineage
    target: DeploymentTarget
    deployment_intent: FactoryDeploymentPackageInput

    @model_validator(mode="after")
    def require_approval_before_issuance(self) -> Self:
        if self.approval.approved_at > self.issued_at:
            raise ValueError("Package approval must occur no later than issuance")
        return self


class PackageAttestation(BaseModel):
    package_id: UUID
    package_version: int
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    current_status: FactoryDeploymentPackageStatus
    issuer: PackageIssuer
    approval: ApprovalBinding
    published_at: datetime
    retrieved_at: datetime
    correlation_id: UUID


class PublishedPackageEnvelope(BaseModel):
    package: ImmutablePackageDocument
    attestation: PackageAttestation

    @model_validator(mode="after")
    def require_matching_current_attestation(self) -> Self:
        if (
            self.attestation.package_id != self.package.package_id
            or self.attestation.package_version != self.package.package_version
            or self.attestation.digest != self.package.integrity.digest
            or self.attestation.issuer != self.package.issuer
            or self.attestation.approval != self.package.approval
        ):
            raise ValueError("Attestation must repeat the immutable package identity and approval")
        if self.attestation.current_status != FactoryDeploymentPackageStatus.PUBLISHED:
            raise ValueError("Only a currently published package can be retrieved")
        if not (
            self.package.approval.approved_at
            <= self.package.issued_at
            <= self.attestation.published_at
            <= self.attestation.retrieved_at
        ):
            raise ValueError(
                "Package timestamps must order approval, issuance, publication, then retrieval"
            )
        return self


class RetrievalDecision(BaseModel):
    allowed: bool
    result: str
    correlation_id: UUID
    package: PublishedPackageEnvelope | None = None
