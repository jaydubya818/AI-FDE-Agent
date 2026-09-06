from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, object_session

from ai_fde.config import get_settings
from ai_fde.models import (
    Assertion,
    EconomicCase,
    Engagement,
    EngagementMember,
    EvidenceAsset,
    ImplementationArtifact,
    Operator,
    WorkflowStep,
    WorkflowVersion,
)
from ai_fde.modules.design_partner.service import (
    DesignPartnerQualificationError,
    require_package_publication_eligibility,
)
from ai_fde.modules.factory_engineer.canonical import (
    CANONICALIZATION,
    canonical_json_bytes,
    canonical_sha256,
)
from ai_fde.modules.factory_engineer.models import (
    CustomerFactoryModelVersion,
    FactoryDeploymentPackageVersion,
    FactoryOpportunity,
    FDLCReadinessAssessment,
)
from ai_fde.modules.factory_engineer.readiness import evaluate_readiness
from ai_fde.modules.factory_engineer.schemas import (
    ApprovalBinding,
    CustomerFactoryModelInput,
    CustomerFactoryModelStatus,
    DeploymentTarget,
    FactoryDeploymentPackageInput,
    FactoryDeploymentPackageStatus,
    FactoryOpportunityInput,
    FactoryOpportunityStatus,
    ImmutablePackageDocument,
    ImmutableVersionReference,
    PackageAttestation,
    PackageIntegrity,
    PackageIssuer,
    PackageSourceLineage,
    ProvenanceKind,
    PublishedPackageEnvelope,
    ReadinessAssessmentInput,
    ReadinessAssessmentStatus,
    ReadinessStatus,
    SourceReference,
)
from ai_fde.modules.factory_engineer.scoring import score_factory_opportunity
from ai_fde.modules.shared import publish_domain_event, record_audit

PACKAGE_SCHEMA_VERSION = "fdlc.factory-deployment-package/v1"
MAX_PACKAGE_INPUT_BYTES = 240_000
MAX_PUBLISHED_ENVELOPE_BYTES = 256_000
MAX_FACTORY_AGGREGATE_BYTES = 512 * 1024
AGGREGATE_TYPE_BY_TABLE = {
    "customer_factory_model_versions": "customer_factory_model_version",
    "fdlc_readiness_assessments": "fdlc_readiness_assessment",
    "factory_opportunities": "factory_opportunity",
    "factory_deployment_package_versions": "factory_deployment_package_version",
}
MAX_FACTORY_SOURCE_REFERENCES = 200


class FactoryEngineerNotFoundError(LookupError):
    pass


class FactoryEngineerStateError(ValueError):
    pass


class FactoryEngineerIntegrityError(ValueError):
    pass


@dataclass(frozen=True)
class FactoryHandoffPrerequisites:
    engagement: Engagement
    evidence_refs: list[SourceReference]
    verified_claim_refs: list[SourceReference]
    current_workflow_ref: ImmutableVersionReference | None
    target_workflow_ref: ImmutableVersionReference | None
    economic_case_ref: SourceReference | None
    implementation_artifact_refs: list[SourceReference]


def get_factory_handoff_prerequisites(
    session: Session, engagement_id: UUID
) -> FactoryHandoffPrerequisites:
    """Return bounded, digest-valid inputs the operator may use for a draft."""

    engagement = session.get(Engagement, engagement_id)
    if engagement is None:
        raise FactoryEngineerNotFoundError(str(engagement_id))
    evidence = list(
        session.scalars(
            select(EvidenceAsset)
            .where(
                EvidenceAsset.engagement_id == engagement_id,
                EvidenceAsset.status == "complete",
            )
            .order_by(EvidenceAsset.created_at, EvidenceAsset.id)
            .limit(MAX_FACTORY_SOURCE_REFERENCES)
        )
    )
    assertions = list(
        session.scalars(
            select(Assertion)
            .where(
                Assertion.engagement_id == engagement_id,
                Assertion.status == "verified",
            )
            .order_by(Assertion.recorded_at, Assertion.id)
            .limit(MAX_FACTORY_SOURCE_REFERENCES)
        )
    )
    current = _latest_approved_workflow(session, engagement_id, "current")
    target = _latest_approved_workflow(session, engagement_id, "target")
    economics = session.scalar(
        select(EconomicCase)
        .where(
            EconomicCase.engagement_id == engagement_id,
            EconomicCase.status == "approved",
        )
        .order_by(EconomicCase.version_number.desc())
        .limit(1)
    )
    artifacts = list(
        session.scalars(
            select(ImplementationArtifact)
            .where(
                ImplementationArtifact.engagement_id == engagement_id,
                ImplementationArtifact.status == "current",
            )
            .order_by(ImplementationArtifact.artifact_type, ImplementationArtifact.id)
            .limit(MAX_FACTORY_SOURCE_REFERENCES)
        )
    )
    return FactoryHandoffPrerequisites(
        engagement=engagement,
        evidence_refs=[evidence_asset_reference(item) for item in evidence],
        verified_claim_refs=[assertion_reference(item) for item in assertions],
        current_workflow_ref=(
            workflow_version_reference(session, current) if current is not None else None
        ),
        target_workflow_ref=(
            workflow_version_reference(session, target) if target is not None else None
        ),
        economic_case_ref=(economic_case_reference(economics) if economics is not None else None),
        implementation_artifact_refs=[
            implementation_artifact_reference(item) for item in artifacts
        ],
    )


def create_customer_factory_model(
    session: Session,
    *,
    engagement_id: UUID,
    operator: Operator,
    model_input: CustomerFactoryModelInput,
) -> CustomerFactoryModelVersion:
    _lock_active_engagement(session, engagement_id)
    payload = model_input.model_dump(mode="json")
    if len(canonical_json_bytes(payload)) > MAX_FACTORY_AGGREGATE_BYTES:
        raise FactoryEngineerStateError("The customer factory model exceeds 512 KiB.")
    _validate_source_references(session, engagement_id, _collect_source_references(payload))
    model = CustomerFactoryModelVersion(
        engagement_id=engagement_id,
        version_number=_next_version(
            session, CustomerFactoryModelVersion, engagement_id, "version_number"
        ),
        status=CustomerFactoryModelStatus.DRAFT,
        organization=payload["organization"],
        systems=payload["systems"],
        repositories=payload["repositories"],
        environments=payload["environments"],
        workflows=payload["workflows"],
        policies=payload["policies"],
        authority_boundaries=payload["authority_boundaries"],
        constraints=payload["constraints"],
        risks=payload["risks"],
        baselines=payload["baselines"],
        evidence_refs=payload["evidence_refs"],
        verified_claim_refs=payload["verified_claim_refs"],
        assumption_refs=payload["assumption_refs"],
        factory_opportunity_refs=payload["factory_opportunity_refs"],
        content_digest=canonical_sha256(payload),
        created_by_id=operator.id,
    )
    session.add(model)
    session.flush()
    _record_event(session, model, operator, "customer_factory_model.drafted")
    return model


def approve_customer_factory_model(
    session: Session,
    *,
    engagement_id: UUID,
    model_id: UUID,
    operator: Operator,
    now: datetime | None = None,
) -> CustomerFactoryModelVersion:
    _require_human(operator, "Customer factory model approval")
    _lock_active_engagement(session, engagement_id)
    model = _customer_model(session, engagement_id, model_id, lock=True)
    if model.status != CustomerFactoryModelStatus.DRAFT:
        raise FactoryEngineerStateError("Only a draft customer factory model can be approved.")
    timestamp = now or datetime.now(UTC)
    older = list(
        session.scalars(
            select(CustomerFactoryModelVersion).where(
                CustomerFactoryModelVersion.engagement_id == engagement_id,
                CustomerFactoryModelVersion.id != model.id,
                CustomerFactoryModelVersion.status == CustomerFactoryModelStatus.APPROVED,
            )
        )
    )
    for previous in older:
        _stale_customer_model(
            session,
            previous,
            reason=f"Superseded by approved customer model version {model.version_number}.",
            now=timestamp,
            actor_id=operator.id,
        )
    session.flush()
    model.status = CustomerFactoryModelStatus.APPROVED
    model.approved_by_id = operator.id
    model.approved_at = timestamp
    _record_event(session, model, operator, "customer_factory_model.approved")
    session.flush()
    return model


def stale_models_for_upstream_reference(
    session: Session,
    *,
    engagement_id: UUID,
    upstream_ref: str,
    reason: str,
    now: datetime | None = None,
    actor_id: UUID | None = None,
) -> list[CustomerFactoryModelVersion]:
    _lock_active_engagement(session, engagement_id)
    timestamp = now or datetime.now(UTC)
    models = list(
        session.scalars(
            select(CustomerFactoryModelVersion).where(
                CustomerFactoryModelVersion.engagement_id == engagement_id,
                CustomerFactoryModelVersion.status.in_(
                    [CustomerFactoryModelStatus.DRAFT, CustomerFactoryModelStatus.APPROVED]
                ),
            )
        )
    )
    affected = [model for model in models if _model_contains_reference(model, upstream_ref)]
    for model in affected:
        _stale_customer_model(session, model, reason=reason, now=timestamp, actor_id=actor_id)
    return affected


def stale_all_customer_models(
    session: Session,
    *,
    engagement_id: UUID,
    reason: str,
    now: datetime | None = None,
    actor_id: UUID | None = None,
) -> list[CustomerFactoryModelVersion]:
    _lock_active_engagement(session, engagement_id)
    timestamp = now or datetime.now(UTC)
    affected = list(
        session.scalars(
            select(CustomerFactoryModelVersion).where(
                CustomerFactoryModelVersion.engagement_id == engagement_id,
                CustomerFactoryModelVersion.status.in_(
                    [CustomerFactoryModelStatus.DRAFT, CustomerFactoryModelStatus.APPROVED]
                ),
            )
        )
    )
    for model in affected:
        _stale_customer_model(session, model, reason=reason, now=timestamp, actor_id=actor_id)
    return affected


def stale_all_after_current_workflow_change(
    session: Session,
    *,
    engagement_id: UUID,
    reason: str,
    now: datetime | None = None,
    actor_id: UUID | None = None,
) -> tuple[list[FDLCReadinessAssessment], list[FactoryOpportunity]]:
    _lock_active_engagement(session, engagement_id)
    timestamp = now or datetime.now(UTC)
    readiness_rows = list(
        session.scalars(
            select(FDLCReadinessAssessment).where(
                FDLCReadinessAssessment.engagement_id == engagement_id,
                FDLCReadinessAssessment.status != ReadinessAssessmentStatus.STALE,
            )
        )
    )
    opportunities = list(
        session.scalars(
            select(FactoryOpportunity).where(
                FactoryOpportunity.engagement_id == engagement_id,
                FactoryOpportunity.status != FactoryOpportunityStatus.STALE,
            )
        )
    )
    for readiness in readiness_rows:
        _stale_readiness(session, readiness, reason=reason, now=timestamp, actor_id=actor_id)
    for opportunity in opportunities:
        _stale_opportunity(session, opportunity, reason=reason, now=timestamp, actor_id=actor_id)
    return readiness_rows, opportunities


def stale_all_after_target_workflow_change(
    session: Session,
    *,
    engagement_id: UUID,
    reason: str,
    now: datetime | None = None,
    actor_id: UUID | None = None,
) -> list[FDLCReadinessAssessment]:
    _lock_active_engagement(session, engagement_id)
    timestamp = now or datetime.now(UTC)
    affected = list(
        session.scalars(
            select(FDLCReadinessAssessment).where(
                FDLCReadinessAssessment.engagement_id == engagement_id,
                FDLCReadinessAssessment.status != ReadinessAssessmentStatus.STALE,
            )
        )
    )
    for readiness in affected:
        _stale_readiness(session, readiness, reason=reason, now=timestamp, actor_id=actor_id)
    return affected


def stale_all_after_economic_change(
    session: Session,
    *,
    engagement_id: UUID,
    reason: str,
    now: datetime | None = None,
    actor_id: UUID | None = None,
) -> list[FactoryOpportunity]:
    _lock_active_engagement(session, engagement_id)
    timestamp = now or datetime.now(UTC)
    affected = list(
        session.scalars(
            select(FactoryOpportunity).where(
                FactoryOpportunity.engagement_id == engagement_id,
                FactoryOpportunity.status != FactoryOpportunityStatus.STALE,
            )
        )
    )
    for opportunity in affected:
        _stale_opportunity(session, opportunity, reason=reason, now=timestamp, actor_id=actor_id)
    return affected


def stale_all_packages_after_artifact_change(
    session: Session,
    *,
    engagement_id: UUID,
    reason: str,
    now: datetime | None = None,
    actor_id: UUID | None = None,
) -> list[FactoryDeploymentPackageVersion]:
    _lock_active_engagement(session, engagement_id)
    timestamp = now or datetime.now(UTC)
    affected = list(
        session.scalars(
            select(FactoryDeploymentPackageVersion).where(
                FactoryDeploymentPackageVersion.engagement_id == engagement_id,
                FactoryDeploymentPackageVersion.status.not_in(
                    [
                        FactoryDeploymentPackageStatus.REVOKED,
                        FactoryDeploymentPackageStatus.STALE,
                        FactoryDeploymentPackageStatus.SUPERSEDED,
                        FactoryDeploymentPackageStatus.REJECTED,
                    ]
                ),
            )
        )
    )
    for package in affected:
        _stale_package(session, package, reason=reason, now=timestamp, actor_id=actor_id)
    return affected


def create_readiness_assessment(
    session: Session,
    *,
    engagement_id: UUID,
    operator: Operator,
    customer_factory_model_id: UUID,
    selected_opportunity_id: UUID,
    current_workflow_id: UUID,
    target_workflow_id: UUID,
    assessment_input: ReadinessAssessmentInput,
    now: datetime | None = None,
) -> FDLCReadinessAssessment:
    _lock_active_engagement(session, engagement_id)
    model = _customer_model(session, engagement_id, customer_factory_model_id)
    if model.status != CustomerFactoryModelStatus.APPROVED:
        raise FactoryEngineerStateError("Readiness requires an approved customer factory model.")
    opportunity = _opportunity(session, engagement_id, selected_opportunity_id)
    if (
        opportunity.status != FactoryOpportunityStatus.SELECTED
        or opportunity.customer_factory_model_id != model.id
    ):
        raise FactoryEngineerStateError(
            "Final readiness requires a selected opportunity from the same customer model."
        )
    _validate_opportunity_row_sources(session, opportunity)
    current = _approved_workflow(session, engagement_id, current_workflow_id, "current")
    target = _approved_workflow(session, engagement_id, target_workflow_id, "target")
    readiness_payload = assessment_input.model_dump(mode="json")
    if len(canonical_json_bytes(readiness_payload)) > MAX_FACTORY_AGGREGATE_BYTES:
        raise FactoryEngineerStateError("The readiness assessment exceeds 512 KiB.")
    _validate_source_references(
        session,
        engagement_id,
        _collect_source_references(readiness_payload),
    )
    timestamp = now or datetime.now(UTC)
    overall, stages = evaluate_readiness(assessment_input, now=timestamp)
    current_ref = workflow_version_reference(session, current)
    target_ref = workflow_version_reference(session, target)
    if ImmutableVersionReference.model_validate(opportunity.source_workflow_ref) != current_ref:
        raise FactoryEngineerStateError(
            "The selected opportunity does not reference this current workflow version."
        )
    stage_payload = [stage.model_dump(mode="json") for stage in stages]
    digest_payload = {
        "customer_factory_model": _model_ref(model).model_dump(mode="json"),
        "selected_opportunity": _opportunity_ref(opportunity).model_dump(mode="json"),
        "current_workflow": current_ref.model_dump(mode="json"),
        "target_workflow": target_ref.model_dump(mode="json"),
        "stages": stage_payload,
    }
    assessment = FDLCReadinessAssessment(
        engagement_id=engagement_id,
        version_number=_next_version(
            session, FDLCReadinessAssessment, engagement_id, "version_number"
        ),
        status=ReadinessAssessmentStatus.DRAFT,
        overall_status=overall,
        customer_factory_model_id=model.id,
        customer_factory_model_version=model.version_number,
        selected_opportunity_id=opportunity.id,
        selected_opportunity_version=opportunity.version_number,
        current_workflow_ref=current_ref.model_dump(mode="json"),
        target_workflow_ref=target_ref.model_dump(mode="json"),
        stages=stage_payload,
        content_digest=canonical_sha256(digest_payload),
        created_by_id=operator.id,
    )
    session.add(assessment)
    session.flush()
    _record_event(session, assessment, operator, "fdlc_readiness.assessed")
    return assessment


def approve_readiness_assessment(
    session: Session,
    *,
    engagement_id: UUID,
    assessment_id: UUID,
    operator: Operator,
    now: datetime | None = None,
) -> FDLCReadinessAssessment:
    _require_human(operator, "Readiness approval")
    _lock_active_engagement(session, engagement_id)
    assessment = _readiness(session, engagement_id, assessment_id, lock=True)
    if assessment.status != ReadinessAssessmentStatus.DRAFT:
        raise FactoryEngineerStateError("Only a draft readiness assessment can be approved.")
    if assessment.overall_status != ReadinessStatus.READY:
        raise FactoryEngineerStateError(
            "All seven FDLC stages must be READY before readiness approval."
        )
    model = _customer_model(session, engagement_id, assessment.customer_factory_model_id)
    if model.status != CustomerFactoryModelStatus.APPROVED:
        raise FactoryEngineerStateError("The readiness customer model is no longer current.")
    opportunity = _opportunity(session, engagement_id, assessment.selected_opportunity_id)
    if (
        opportunity.status != FactoryOpportunityStatus.SELECTED
        or opportunity.version_number != assessment.selected_opportunity_version
    ):
        raise FactoryEngineerStateError("The selected opportunity is no longer current.")
    _assert_workflow_ref_current(session, engagement_id, assessment.current_workflow_ref, "current")
    _assert_workflow_ref_current(session, engagement_id, assessment.target_workflow_ref, "target")
    timestamp = now or datetime.now(UTC)
    for previous in session.scalars(
        select(FDLCReadinessAssessment).where(
            FDLCReadinessAssessment.engagement_id == engagement_id,
            FDLCReadinessAssessment.id != assessment.id,
            FDLCReadinessAssessment.status == ReadinessAssessmentStatus.APPROVED,
        )
    ):
        _stale_readiness(
            session,
            previous,
            reason=f"Superseded by readiness version {assessment.version_number}.",
            now=timestamp,
            actor_id=operator.id,
        )
    session.flush()
    assessment.status = ReadinessAssessmentStatus.APPROVED
    assessment.approved_by_id = operator.id
    assessment.approved_at = timestamp
    _record_event(session, assessment, operator, "fdlc_readiness.approved")
    session.flush()
    return assessment


def create_factory_opportunity(
    session: Session,
    *,
    engagement_id: UUID,
    operator: Operator,
    customer_factory_model_id: UUID,
    opportunity_input: FactoryOpportunityInput,
) -> FactoryOpportunity:
    _lock_active_engagement(session, engagement_id)
    model = _customer_model(session, engagement_id, customer_factory_model_id)
    if model.status != CustomerFactoryModelStatus.APPROVED:
        raise FactoryEngineerStateError("Opportunity scoring requires a current customer model.")
    workflow = _approved_workflow(
        session, engagement_id, opportunity_input.source_workflow_ref.id, "current"
    )
    if workflow_version_reference(session, workflow) != opportunity_input.source_workflow_ref:
        raise FactoryEngineerStateError(
            "Opportunity scoring requires an exact current-workflow version reference."
        )
    opportunity_payload = opportunity_input.model_dump(mode="json")
    if len(canonical_json_bytes(opportunity_payload)) > MAX_FACTORY_AGGREGATE_BYTES:
        raise FactoryEngineerStateError("The factory opportunity exceeds 512 KiB.")
    _validate_source_reference(session, engagement_id, opportunity_input.economics_ref)
    _validate_source_references(session, engagement_id, opportunity_input.evidence_refs)
    score = score_factory_opportunity(
        opportunity_input.factors, blockers=opportunity_input.blockers
    )
    previous = list(
        session.scalars(
            select(FactoryOpportunity).where(
                FactoryOpportunity.engagement_id == engagement_id,
                FactoryOpportunity.opportunity_key == opportunity_input.opportunity_key,
                FactoryOpportunity.status != FactoryOpportunityStatus.STALE,
            )
        )
    )
    for item in previous:
        _stale_opportunity(
            session,
            item,
            reason="A new scored version was created.",
            actor_id=operator.id,
        )
    status = (
        FactoryOpportunityStatus.RECOMMENDED
        if score.recommendation.startswith("RECOMMEND")
        else FactoryOpportunityStatus.ASSESSED
    )
    payload = {
        "input": opportunity_input.model_dump(mode="json"),
        "score": score.model_dump(mode="json"),
        "customer_factory_model": _model_ref(model).model_dump(mode="json"),
    }
    opportunity = FactoryOpportunity(
        engagement_id=engagement_id,
        opportunity_key=opportunity_input.opportunity_key,
        version_number=_next_opportunity_version(
            session, engagement_id, opportunity_input.opportunity_key
        ),
        status=status,
        name=opportunity_input.name,
        description=opportunity_input.description,
        source_workflow_ref=opportunity_input.source_workflow_ref.model_dump(mode="json"),
        customer_factory_model_id=model.id,
        customer_factory_model_version=model.version_number,
        value_score=score.value_score,
        verifiability_score=score.verifiability_score,
        readiness_score=score.readiness_score,
        risk_score=score.risk_score,
        autonomy_potential=score.autonomy_potential,
        priority_score=score.priority_score,
        factors=opportunity_input.factors.model_dump(mode="json"),
        rubric=score.rubric,
        rubric_version=score.rubric_version,
        economics_ref=opportunity_input.economics_ref.model_dump(mode="json"),
        evidence_refs=[ref.model_dump(mode="json") for ref in opportunity_input.evidence_refs],
        rationale=score.rationale,
        blockers=opportunity_input.blockers,
        recommendation=score.recommendation,
        content_digest=canonical_sha256(payload),
        created_by_id=operator.id,
    )
    session.add(opportunity)
    session.flush()
    _record_event(session, opportunity, operator, "factory_opportunity.assessed")
    return opportunity


def select_factory_opportunity(
    session: Session,
    *,
    engagement_id: UUID,
    opportunity_id: UUID,
    operator: Operator,
    reason: str,
    now: datetime | None = None,
) -> FactoryOpportunity:
    _require_human(operator, "Opportunity selection")
    _lock_active_engagement(session, engagement_id)
    opportunity = _opportunity(session, engagement_id, opportunity_id, lock=True)
    if opportunity.status not in {
        FactoryOpportunityStatus.ASSESSED,
        FactoryOpportunityStatus.RECOMMENDED,
    }:
        raise FactoryEngineerStateError("Only a current assessed opportunity can be selected.")
    if opportunity.blockers:
        raise FactoryEngineerStateError("Resolve opportunity blockers before selection.")
    _validate_opportunity_row_sources(session, opportunity)
    clean_reason = reason.strip()
    if not clean_reason:
        raise FactoryEngineerStateError("Opportunity selection requires a recorded rationale.")
    timestamp = now or datetime.now(UTC)
    for selected in session.scalars(
        select(FactoryOpportunity).where(
            FactoryOpportunity.engagement_id == engagement_id,
            FactoryOpportunity.id != opportunity.id,
            FactoryOpportunity.status == FactoryOpportunityStatus.SELECTED,
        )
    ):
        _stale_opportunity(
            session,
            selected,
            reason=f"A different opportunity ({opportunity.id}) was selected.",
            now=timestamp,
            actor_id=operator.id,
        )
    session.flush()
    opportunity.status = FactoryOpportunityStatus.SELECTED
    opportunity.selected_by_id = operator.id
    opportunity.selected_at = timestamp
    opportunity.selection_reason = clean_reason
    _record_event(session, opportunity, operator, "factory_opportunity.selected")
    session.flush()
    return opportunity


def reject_factory_opportunity(
    session: Session,
    *,
    engagement_id: UUID,
    opportunity_id: UUID,
    operator: Operator,
    reason: str,
    now: datetime | None = None,
) -> FactoryOpportunity:
    _require_human(operator, "Opportunity rejection")
    _lock_active_engagement(session, engagement_id)
    opportunity = _opportunity(session, engagement_id, opportunity_id, lock=True)
    if opportunity.status not in {
        FactoryOpportunityStatus.CANDIDATE,
        FactoryOpportunityStatus.ASSESSED,
        FactoryOpportunityStatus.RECOMMENDED,
    }:
        raise FactoryEngineerStateError("Only a current unselected opportunity can be rejected.")
    clean_reason = reason.strip()
    if not clean_reason:
        raise FactoryEngineerStateError("Opportunity rejection requires a recorded rationale.")
    opportunity.status = FactoryOpportunityStatus.REJECTED
    opportunity.rejected_by_id = operator.id
    opportunity.rejected_at = now or datetime.now(UTC)
    opportunity.rejection_reason = clean_reason
    _record_event(
        session,
        opportunity,
        operator,
        "factory_opportunity.rejected",
        detail={"reason": clean_reason},
    )
    session.flush()
    return opportunity


def create_deployment_package(
    session: Session,
    *,
    engagement_id: UUID,
    operator: Operator,
    customer_factory_model_id: UUID,
    readiness_assessment_id: UUID,
    factory_opportunity_id: UUID,
    target: DeploymentTarget,
    package_input: FactoryDeploymentPackageInput,
    package_id: UUID | None = None,
) -> FactoryDeploymentPackageVersion:
    _lock_active_engagement(session, engagement_id)
    settings = get_settings()
    issuer = PackageIssuer(
        issuer_id=settings.factory_engineer_issuer_id,
        environment=settings.env,
    )
    model = _customer_model(session, engagement_id, customer_factory_model_id)
    readiness = _readiness(session, engagement_id, readiness_assessment_id)
    opportunity = _opportunity(session, engagement_id, factory_opportunity_id)
    _validate_package_sources(model, readiness, opportunity)
    package_payload = package_input.model_dump(mode="json")
    target_payload = target.model_dump(mode="json")
    bounded_package_input = {"target": target_payload, "contract": package_payload}
    if len(canonical_json_bytes(bounded_package_input)) > MAX_PACKAGE_INPUT_BYTES:
        raise FactoryEngineerStateError("The deployment package input exceeds 240,000 bytes.")
    _validate_source_references(session, engagement_id, _collect_source_references(package_payload))
    expected_scopes = target.requested_code_scopes
    if any(
        blueprint.requested_code_scopes != expected_scopes
        for blueprint in package_input.work_order_blueprints
    ):
        raise FactoryEngineerStateError(
            "V1 work-order code scopes must exactly equal the package target code scopes."
        )
    current_ref = ImmutableVersionReference.model_validate(readiness.current_workflow_ref)
    target_ref = ImmutableVersionReference.model_validate(readiness.target_workflow_ref)
    if package_id is None:
        stable_id = uuid.uuid4()
    else:
        existing = session.scalar(
            select(FactoryDeploymentPackageVersion)
            .where(FactoryDeploymentPackageVersion.package_id == package_id)
            .order_by(FactoryDeploymentPackageVersion.package_version.desc())
            .limit(1)
            .with_for_update()
        )
        if existing is None:
            raise FactoryEngineerStateError(
                "New package identities are server-generated; the requested package does not exist."
            )
        if existing.engagement_id != engagement_id or _issuer(existing) != issuer:
            raise FactoryEngineerStateError(
                "A package identity cannot move between engagements or issuers."
            )
        stable_id = package_id
    package = FactoryDeploymentPackageVersion(
        engagement_id=engagement_id,
        package_id=stable_id,
        package_version=_next_package_version(session, engagement_id, stable_id),
        schema_version=PACKAGE_SCHEMA_VERSION,
        status=FactoryDeploymentPackageStatus.DRAFT,
        issuer_id=issuer.issuer_id,
        issuer_type=issuer.issuer_type,
        issuer_environment=issuer.environment,
        issuer_authority_scope=issuer.authority_scope,
        customer_factory_model_id=model.id,
        customer_factory_model_version=model.version_number,
        current_workflow_ref=current_ref.model_dump(mode="json"),
        target_workflow_ref=target_ref.model_dump(mode="json"),
        readiness_assessment_id=readiness.id,
        readiness_assessment_version=readiness.version_number,
        factory_opportunity_id=opportunity.id,
        factory_opportunity_version=opportunity.version_number,
        target=target_payload,
        contract=package_payload,
        created_by_id=operator.id,
    )
    session.add(package)
    session.flush()
    _record_event(session, package, operator, "deployment_package.drafted")
    return package


def submit_deployment_package_for_review(
    session: Session,
    *,
    engagement_id: UUID,
    package_version_id: UUID,
    operator: Operator,
) -> FactoryDeploymentPackageVersion:
    _lock_active_engagement(session, engagement_id)
    package = _package(session, engagement_id, package_version_id, lock=True)
    if package.status != FactoryDeploymentPackageStatus.DRAFT:
        raise FactoryEngineerStateError("Only a draft package can be submitted for review.")
    _validate_package_row_sources(session, package)
    package.status = FactoryDeploymentPackageStatus.READY_FOR_REVIEW
    _record_event(session, package, operator, "deployment_package.ready_for_review")
    # Preserve the explicit lifecycle transition for the database trigger even when
    # review submission and approval occur in one transaction.
    session.flush()
    return package


def approve_deployment_package(
    session: Session,
    *,
    engagement_id: UUID,
    package_version_id: UUID,
    operator: Operator,
    authority_basis_ref: SourceReference,
    now: datetime | None = None,
) -> FactoryDeploymentPackageVersion:
    _require_human(operator, "Deployment package approval")
    _lock_active_engagement(session, engagement_id)
    _require_engagement_owner(session, engagement_id, operator, "Deployment package approval")
    package = _package(session, engagement_id, package_version_id, lock=True)
    if package.status != FactoryDeploymentPackageStatus.READY_FOR_REVIEW:
        raise FactoryEngineerStateError("Only a review-ready package can be approved.")
    _validate_package_row_sources(session, package)
    _validate_package_authority_basis(session, package, authority_basis_ref)
    timestamp = now or datetime.now(UTC)
    decision_ref = _package_approval_decision_reference(
        package,
        approved_by=operator.id,
        authority_basis_ref=authority_basis_ref,
        approved_at=timestamp,
    )
    approval = ApprovalBinding(
        decision_ref=decision_ref,
        approved_by=operator.id,
        authorized_by_ref=authority_basis_ref.ref,
        authority_basis_ref=authority_basis_ref,
        approved_at=timestamp,
    )
    package.status = FactoryDeploymentPackageStatus.APPROVED
    package.issued_at = timestamp
    package.approved_by_id = operator.id
    package.approval_binding = approval.model_dump(mode="json")
    package.approved_at = timestamp
    package.digest = _calculate_package_digest(package)
    _record_event(
        session,
        package,
        operator,
        "deployment_package.approved",
        detail={"digest": package.digest},
    )
    session.flush()
    return package


def publish_deployment_package(
    session: Session,
    *,
    engagement_id: UUID,
    package_version_id: UUID,
    operator: Operator,
    now: datetime | None = None,
) -> FactoryDeploymentPackageVersion:
    _require_human(operator, "Deployment package publication")
    _lock_active_engagement(session, engagement_id)
    _require_engagement_owner(session, engagement_id, operator, "Deployment package publication")
    package = _package(session, engagement_id, package_version_id, lock=True)
    if package.status != FactoryDeploymentPackageStatus.APPROVED:
        raise FactoryEngineerStateError("Only an approved package can be published.")
    _validate_package_row_sources(session, package)
    expected = _calculate_package_digest(package)
    if package.digest != expected:
        raise FactoryEngineerIntegrityError(
            "Approved package digest no longer matches its content."
        )
    timestamp = now or datetime.now(UTC)
    try:
        require_package_publication_eligibility(
            session,
            engagement_id=engagement_id,
            target=package.target,
            now=timestamp,
        )
    except DesignPartnerQualificationError as exc:
        raise FactoryEngineerStateError(str(exc)) from exc
    # This exact envelope gate is the producer/consumer seam. The earlier input cap
    # leaves room for immutable source, issuer, approval, and attestation metadata.
    published_package_envelope(
        package,
        published_at=timestamp,
        retrieved_at=timestamp,
        correlation_id=UUID(int=0),
    )
    for previous in session.scalars(
        select(FactoryDeploymentPackageVersion).where(
            FactoryDeploymentPackageVersion.engagement_id == engagement_id,
            FactoryDeploymentPackageVersion.id != package.id,
            FactoryDeploymentPackageVersion.status == FactoryDeploymentPackageStatus.PUBLISHED,
        )
    ):
        supersession_reason = f"Superseded by package version {package.package_version}."
        previous.status = FactoryDeploymentPackageStatus.SUPERSEDED
        previous.superseded_at = timestamp
        previous.state_reason = supersession_reason
        _record_derived_transition(
            session,
            aggregate=previous,
            event_type="deployment_package.superseded",
            reason=supersession_reason,
            actor_id=operator.id,
        )
    # Clear the partial unique index before publishing the replacement. The engagement
    # row lock serializes concurrent publishers; this flush orders the two transitions.
    session.flush()
    package.status = FactoryDeploymentPackageStatus.PUBLISHED
    package.published_at = timestamp
    _record_event(
        session,
        package,
        operator,
        "deployment_package.published",
        detail={"digest": package.digest},
    )
    session.flush()
    return package


def reject_deployment_package(
    session: Session,
    *,
    engagement_id: UUID,
    package_version_id: UUID,
    operator: Operator,
    reason: str,
    now: datetime | None = None,
) -> FactoryDeploymentPackageVersion:
    _require_human(operator, "Deployment package rejection")
    _lock_active_engagement(session, engagement_id)
    _require_engagement_owner(session, engagement_id, operator, "Deployment package rejection")
    package = _package(session, engagement_id, package_version_id, lock=True)
    if package.status not in {
        FactoryDeploymentPackageStatus.DRAFT,
        FactoryDeploymentPackageStatus.READY_FOR_REVIEW,
        FactoryDeploymentPackageStatus.APPROVED,
    }:
        raise FactoryEngineerStateError("Only a current unpublished package can be rejected.")
    clean_reason = reason.strip()
    if not clean_reason:
        raise FactoryEngineerStateError("Package rejection requires a reason.")
    package.status = FactoryDeploymentPackageStatus.REJECTED
    package.rejected_at = now or datetime.now(UTC)
    package.state_reason = clean_reason
    _record_event(
        session,
        package,
        operator,
        "deployment_package.rejected",
        detail={"reason": clean_reason},
    )
    session.flush()
    return package


def revoke_deployment_package(
    session: Session,
    *,
    engagement_id: UUID,
    package_version_id: UUID,
    operator: Operator,
    reason: str,
    now: datetime | None = None,
) -> FactoryDeploymentPackageVersion:
    _require_human(operator, "Deployment package revocation")
    _lock_active_engagement(session, engagement_id)
    _require_engagement_owner(session, engagement_id, operator, "Deployment package revocation")
    package = _package(session, engagement_id, package_version_id, lock=True)
    if package.status != FactoryDeploymentPackageStatus.PUBLISHED:
        raise FactoryEngineerStateError("Only a published package can be revoked.")
    clean_reason = reason.strip()
    if not clean_reason:
        raise FactoryEngineerStateError("Package revocation requires a reason.")
    package.status = FactoryDeploymentPackageStatus.REVOKED
    package.revoked_at = now or datetime.now(UTC)
    package.state_reason = clean_reason
    _record_event(session, package, operator, "deployment_package.revoked")
    return package


def immutable_package_document(
    package: FactoryDeploymentPackageVersion,
) -> ImmutablePackageDocument:
    if not package.digest:
        raise FactoryEngineerStateError("The package has not been approved and digested.")
    payload = _immutable_package_payload(package, digest=package.digest)
    return ImmutablePackageDocument.model_validate(payload)


def published_package_envelope(
    package: FactoryDeploymentPackageVersion,
    *,
    published_at: datetime,
    retrieved_at: datetime,
    correlation_id: UUID,
) -> PublishedPackageEnvelope:
    if package.status not in {
        FactoryDeploymentPackageStatus.APPROVED,
        FactoryDeploymentPackageStatus.PUBLISHED,
    }:
        raise FactoryEngineerStateError(
            "Only an approved or published package can form a retrieval envelope."
        )
    document = immutable_package_document(package)
    if package.digest is None or package.approval_binding is None:
        raise FactoryEngineerIntegrityError("Published package integrity metadata is incomplete.")
    envelope = PublishedPackageEnvelope(
        package=document,
        attestation=PackageAttestation(
            package_id=package.package_id,
            package_version=package.package_version,
            digest=package.digest,
            current_status=FactoryDeploymentPackageStatus.PUBLISHED,
            issuer=_issuer(package),
            approval=ApprovalBinding.model_validate(package.approval_binding),
            published_at=published_at,
            retrieved_at=retrieved_at,
            correlation_id=correlation_id,
        ),
    )
    if len(serialize_published_package_envelope(envelope)) > MAX_PUBLISHED_ENVELOPE_BYTES:
        raise FactoryEngineerStateError(
            "The full deployment package retrieval envelope exceeds 256,000 bytes."
        )
    return envelope


def serialize_published_package_envelope(envelope: PublishedPackageEnvelope) -> bytes:
    """Return the exact compact UTF-8 response body used by the retrieval route."""

    return envelope.model_dump_json().encode("utf-8")


def _calculate_package_digest(package: FactoryDeploymentPackageVersion) -> str:
    payload = _immutable_package_payload(package, digest=None)
    integrity = payload["integrity"]
    if not isinstance(integrity, dict):
        raise FactoryEngineerIntegrityError("Package integrity projection is invalid.")
    integrity.pop("digest", None)
    return canonical_sha256(payload)


def _immutable_package_payload(
    package: FactoryDeploymentPackageVersion, *, digest: str | None
) -> dict[str, Any]:
    if package.issued_at is None or package.approval_binding is None:
        raise FactoryEngineerStateError("Package approval binding is incomplete.")
    model_ref = ImmutableVersionReference(
        id=package.customer_factory_model_id,
        version=package.customer_factory_model_version,
        digest=_required_source_digest(package, "customer_model"),
    )
    readiness_ref = ImmutableVersionReference(
        id=package.readiness_assessment_id,
        version=package.readiness_assessment_version,
        digest=_required_source_digest(package, "readiness"),
    )
    opportunity_ref = ImmutableVersionReference(
        id=package.factory_opportunity_id,
        version=package.factory_opportunity_version,
        digest=_required_source_digest(package, "opportunity"),
    )
    source = PackageSourceLineage(
        engagement_id=package.engagement_id,
        customer_factory_model=model_ref,
        current_workflow=ImmutableVersionReference.model_validate(package.current_workflow_ref),
        target_workflow=ImmutableVersionReference.model_validate(package.target_workflow_ref),
        readiness_assessment=readiness_ref,
        factory_opportunity=opportunity_ref,
    )
    intent = FactoryDeploymentPackageInput.model_validate(package.contract)
    integrity = {
        "canonicalization": CANONICALIZATION,
        "algorithm": "sha256",
        "digest": digest or "sha256:" + "0" * 64,
    }
    approval = ApprovalBinding.model_validate(package.approval_binding)
    _validate_package_approval_binding(package, approval)
    approval_payload = approval.model_dump(mode="json")
    approval_payload["approved_at"] = _rfc3339_z(approval.approved_at)
    return {
        "schema_version": package.schema_version,
        "package_id": str(package.package_id),
        "package_version": package.package_version,
        "status": "PUBLISHED",
        "issuer": _issuer(package).model_dump(mode="json"),
        "issued_at": _rfc3339_z(package.issued_at),
        "approval": approval_payload,
        "integrity": PackageIntegrity.model_validate(integrity).model_dump(mode="json"),
        "source": source.model_dump(mode="json"),
        "target": DeploymentTarget.model_validate(package.target).model_dump(mode="json"),
        "deployment_intent": intent.model_dump(mode="json"),
    }


def _required_source_digest(package: FactoryDeploymentPackageVersion, source: str) -> str:
    session = object_session(package)
    if session is None:
        raise FactoryEngineerIntegrityError("Package source rows are not attached to a session.")
    if source == "customer_model":
        model = session.get(CustomerFactoryModelVersion, package.customer_factory_model_id)
        if model is not None:
            return _verified_content_digest(
                model.content_digest,
                _customer_model_digest(model),
                "customer model",
            )
    if source == "readiness":
        readiness = session.get(FDLCReadinessAssessment, package.readiness_assessment_id)
        if readiness is not None:
            return _verified_content_digest(
                readiness.content_digest,
                _readiness_digest(readiness),
                "readiness assessment",
            )
    if source == "opportunity":
        opportunity = session.get(FactoryOpportunity, package.factory_opportunity_id)
        if opportunity is not None:
            return _verified_content_digest(
                opportunity.content_digest,
                _opportunity_digest(opportunity),
                "factory opportunity",
            )
    raise FactoryEngineerIntegrityError(f"Package {source} source no longer exists.")


def _validate_package_sources(
    model: CustomerFactoryModelVersion,
    readiness: FDLCReadinessAssessment,
    opportunity: FactoryOpportunity,
) -> None:
    if model.status != CustomerFactoryModelStatus.APPROVED:
        raise FactoryEngineerStateError("Deployment package requires an approved customer model.")
    if (
        readiness.status != ReadinessAssessmentStatus.APPROVED
        or readiness.overall_status != ReadinessStatus.READY
        or readiness.customer_factory_model_id != model.id
        or readiness.selected_opportunity_id != opportunity.id
        or readiness.selected_opportunity_version != opportunity.version_number
    ):
        raise FactoryEngineerStateError("Deployment package requires current approved readiness.")
    if (
        opportunity.status != FactoryOpportunityStatus.SELECTED
        or opportunity.customer_factory_model_id != model.id
    ):
        raise FactoryEngineerStateError(
            "Deployment package requires a selected opportunity from the same source versions."
        )


def _validate_package_row_sources(
    session: Session, package: FactoryDeploymentPackageVersion
) -> None:
    model = _customer_model(session, package.engagement_id, package.customer_factory_model_id)
    readiness = _readiness(session, package.engagement_id, package.readiness_assessment_id)
    opportunity = _opportunity(session, package.engagement_id, package.factory_opportunity_id)
    _validate_package_sources(model, readiness, opportunity)
    _validate_opportunity_row_sources(session, opportunity)
    if model.version_number != package.customer_factory_model_version:
        raise FactoryEngineerStateError("Customer model version changed after package generation.")
    if readiness.version_number != package.readiness_assessment_version:
        raise FactoryEngineerStateError("Readiness version changed after package generation.")
    if opportunity.version_number != package.factory_opportunity_version:
        raise FactoryEngineerStateError("Opportunity version changed after package generation.")
    _assert_workflow_ref_current(
        session, package.engagement_id, package.current_workflow_ref, "current"
    )
    _assert_workflow_ref_current(
        session, package.engagement_id, package.target_workflow_ref, "target"
    )


def _validate_opportunity_row_sources(session: Session, opportunity: FactoryOpportunity) -> None:
    _assert_workflow_ref_current(
        session,
        opportunity.engagement_id,
        opportunity.source_workflow_ref,
        "current",
    )
    _validate_source_reference(
        session,
        opportunity.engagement_id,
        SourceReference.model_validate(opportunity.economics_ref),
    )
    _validate_source_references(
        session,
        opportunity.engagement_id,
        [SourceReference.model_validate(item) for item in opportunity.evidence_refs],
    )


def _stale_customer_model(
    session: Session,
    model: CustomerFactoryModelVersion,
    *,
    reason: str,
    now: datetime,
    actor_id: UUID | None = None,
) -> None:
    if model.status == CustomerFactoryModelStatus.STALE:
        return
    model.status = CustomerFactoryModelStatus.STALE
    model.stale_reason = reason
    model.staled_at = now
    _record_derived_transition(
        session,
        aggregate=model,
        event_type="customer_factory_model.staled",
        reason=reason,
        actor_id=actor_id,
    )
    for readiness in session.scalars(
        select(FDLCReadinessAssessment).where(
            FDLCReadinessAssessment.engagement_id == model.engagement_id,
            FDLCReadinessAssessment.customer_factory_model_id == model.id,
            FDLCReadinessAssessment.status != ReadinessAssessmentStatus.STALE,
        )
    ):
        _stale_readiness(session, readiness, reason=reason, now=now, actor_id=actor_id)
    for opportunity in session.scalars(
        select(FactoryOpportunity).where(
            FactoryOpportunity.engagement_id == model.engagement_id,
            FactoryOpportunity.customer_factory_model_id == model.id,
            FactoryOpportunity.status != FactoryOpportunityStatus.STALE,
        )
    ):
        _stale_opportunity(session, opportunity, reason=reason, now=now, actor_id=actor_id)


def _stale_readiness(
    session: Session,
    readiness: FDLCReadinessAssessment,
    *,
    reason: str,
    now: datetime,
    actor_id: UUID | None = None,
) -> None:
    if readiness.status == ReadinessAssessmentStatus.STALE:
        return
    readiness.status = ReadinessAssessmentStatus.STALE
    readiness.overall_status = ReadinessStatus.STALE
    readiness.stale_reason = reason
    readiness.staled_at = now
    _record_derived_transition(
        session,
        aggregate=readiness,
        event_type="fdlc_readiness.staled",
        reason=reason,
        actor_id=actor_id,
    )
    for package in session.scalars(
        select(FactoryDeploymentPackageVersion).where(
            FactoryDeploymentPackageVersion.engagement_id == readiness.engagement_id,
            FactoryDeploymentPackageVersion.readiness_assessment_id == readiness.id,
            FactoryDeploymentPackageVersion.status.not_in(
                [
                    FactoryDeploymentPackageStatus.REVOKED,
                    FactoryDeploymentPackageStatus.STALE,
                    FactoryDeploymentPackageStatus.SUPERSEDED,
                    FactoryDeploymentPackageStatus.REJECTED,
                ]
            ),
        )
    ):
        _stale_package(session, package, reason=reason, now=now, actor_id=actor_id)


def _stale_opportunity(
    session: Session,
    opportunity: FactoryOpportunity,
    *,
    reason: str,
    now: datetime | None = None,
    actor_id: UUID | None = None,
) -> None:
    timestamp = now or datetime.now(UTC)
    if opportunity.status in {
        FactoryOpportunityStatus.STALE,
        FactoryOpportunityStatus.REJECTED,
    }:
        return
    opportunity.status = FactoryOpportunityStatus.STALE
    opportunity.stale_reason = reason
    opportunity.staled_at = timestamp
    _record_derived_transition(
        session,
        aggregate=opportunity,
        event_type="factory_opportunity.staled",
        reason=reason,
        actor_id=actor_id,
    )
    for readiness in session.scalars(
        select(FDLCReadinessAssessment).where(
            FDLCReadinessAssessment.engagement_id == opportunity.engagement_id,
            FDLCReadinessAssessment.selected_opportunity_id == opportunity.id,
            FDLCReadinessAssessment.status != ReadinessAssessmentStatus.STALE,
        )
    ):
        _stale_readiness(session, readiness, reason=reason, now=timestamp, actor_id=actor_id)
    for package in session.scalars(
        select(FactoryDeploymentPackageVersion).where(
            FactoryDeploymentPackageVersion.engagement_id == opportunity.engagement_id,
            FactoryDeploymentPackageVersion.factory_opportunity_id == opportunity.id,
            FactoryDeploymentPackageVersion.status.not_in(
                [
                    FactoryDeploymentPackageStatus.REVOKED,
                    FactoryDeploymentPackageStatus.STALE,
                    FactoryDeploymentPackageStatus.SUPERSEDED,
                    FactoryDeploymentPackageStatus.REJECTED,
                ]
            ),
        )
    ):
        _stale_package(session, package, reason=reason, now=timestamp, actor_id=actor_id)


def _stale_package(
    session: Session,
    package: FactoryDeploymentPackageVersion,
    *,
    reason: str,
    now: datetime,
    actor_id: UUID | None = None,
) -> None:
    if package.status in {
        FactoryDeploymentPackageStatus.REVOKED,
        FactoryDeploymentPackageStatus.STALE,
        FactoryDeploymentPackageStatus.SUPERSEDED,
        FactoryDeploymentPackageStatus.REJECTED,
    }:
        return
    package.status = FactoryDeploymentPackageStatus.STALE
    package.staled_at = now
    package.state_reason = reason
    _record_derived_transition(
        session,
        aggregate=package,
        event_type="deployment_package.staled",
        reason=reason,
        actor_id=actor_id,
    )


def _model_contains_reference(model: CustomerFactoryModelVersion, ref: str) -> bool:
    values: list[Any] = [
        model.organization,
        model.systems,
        model.repositories,
        model.environments,
        model.workflows,
        model.policies,
        model.authority_boundaries,
        model.constraints,
        model.risks,
        model.baselines,
        model.evidence_refs,
        model.verified_claim_refs,
        model.assumption_refs,
        model.factory_opportunity_refs,
    ]
    return any(_contains_reference(value, ref) for value in values)


def _contains_reference(value: Any, ref: str) -> bool:
    if isinstance(value, dict):
        if value.get("ref") == ref or str(value.get("id")) == ref:
            return True
        return any(_contains_reference(item, ref) for item in value.values())
    if isinstance(value, list):
        return any(_contains_reference(item, ref) for item in value)
    return False


def workflow_version_reference(
    session: Session, workflow: WorkflowVersion
) -> ImmutableVersionReference:
    steps = list(
        session.scalars(
            select(WorkflowStep)
            .where(WorkflowStep.workflow_version_id == workflow.id)
            .order_by(WorkflowStep.position, WorkflowStep.id)
        )
    )
    payload = {
        "id": str(workflow.id),
        "kind": workflow.workflow_kind,
        "version": workflow.version_number,
        "name": workflow.name,
        "objective": workflow.objective,
        "source_workflow_id": str(workflow.source_workflow_id)
        if workflow.source_workflow_id
        else None,
        "source_assertion_ids": workflow.source_assertion_ids,
        "steps": [
            {
                "step_key": step.step_key,
                "position": step.position,
                "name": step.name,
                "description": step.description,
                "step_type": step.step_type,
                "actor_label": step.actor_label,
                "system_label": step.system_label,
                "allocation": step.allocation,
                "rationale": step.rationale,
                "controls": step.controls,
                "source_assertion_id": str(step.source_assertion_id)
                if step.source_assertion_id
                else None,
            }
            for step in steps
        ],
    }
    return ImmutableVersionReference(
        id=workflow.id,
        version=workflow.version_number,
        digest=canonical_sha256(payload),
    )


def _latest_approved_workflow(
    session: Session, engagement_id: UUID, kind: str
) -> WorkflowVersion | None:
    return session.scalar(
        select(WorkflowVersion)
        .where(
            WorkflowVersion.engagement_id == engagement_id,
            WorkflowVersion.workflow_kind == kind,
            WorkflowVersion.status == "approved",
        )
        .order_by(WorkflowVersion.version_number.desc())
        .limit(1)
    )


def _assert_workflow_ref_current(
    session: Session,
    engagement_id: UUID,
    raw_ref: dict[str, Any],
    expected_kind: str,
) -> WorkflowVersion:
    expected = ImmutableVersionReference.model_validate(raw_ref)
    workflow = _approved_workflow(session, engagement_id, expected.id, expected_kind)
    actual = workflow_version_reference(session, workflow)
    if actual != expected:
        raise FactoryEngineerStateError(
            f"The {expected_kind} workflow content no longer matches its pinned package source."
        )
    return workflow


def _approved_workflow(
    session: Session, engagement_id: UUID, workflow_id: UUID, kind: str
) -> WorkflowVersion:
    workflow = session.scalar(
        select(WorkflowVersion).where(
            WorkflowVersion.id == workflow_id,
            WorkflowVersion.engagement_id == engagement_id,
            WorkflowVersion.workflow_kind == kind,
        )
    )
    if workflow is None:
        raise FactoryEngineerNotFoundError(str(workflow_id))
    if workflow.status != "approved":
        raise FactoryEngineerStateError(f"The {kind} workflow must be approved and current.")
    return workflow


def evidence_asset_reference(evidence: EvidenceAsset) -> SourceReference:
    return SourceReference(
        kind=ProvenanceKind.EVIDENCE,
        ref=f"evidence_asset:{evidence.id}",
        sha256=f"sha256:{evidence.content_hash}",
    )


def assertion_reference(assertion: Assertion) -> SourceReference:
    return SourceReference(
        kind=ProvenanceKind.VERIFIED_CLAIM,
        ref=f"assertion:{assertion.id}",
        version=1,
        sha256=_assertion_digest(assertion),
    )


def economic_case_reference(economic_case: EconomicCase) -> SourceReference:
    if economic_case.status != "approved":
        raise FactoryEngineerStateError("Economic-case provenance requires an approved version.")
    return SourceReference(
        kind=ProvenanceKind.APPROVED_INPUT,
        ref=f"economic_case:{economic_case.id}",
        version=economic_case.version_number,
        sha256=_economic_case_digest(economic_case),
    )


def implementation_artifact_reference(
    artifact: ImplementationArtifact,
) -> SourceReference:
    if artifact.status != "current":
        raise FactoryEngineerStateError("Implementation provenance requires a current artifact.")
    return SourceReference(
        kind=ProvenanceKind.APPROVED_INPUT,
        ref=f"implementation_artifact:{artifact.id}",
        version=artifact.version_number,
        sha256=f"sha256:{artifact.content_hash}",
    )


def customer_factory_model_authority_reference(
    model: CustomerFactoryModelVersion,
) -> SourceReference:
    if model.status != CustomerFactoryModelStatus.APPROVED:
        raise FactoryEngineerStateError(
            "Package authority requires an approved customer factory model."
        )
    return SourceReference(
        kind=ProvenanceKind.APPROVED_INPUT,
        ref=f"customer_factory_model:{model.id}",
        version=model.version_number,
        sha256=_model_ref(model).digest,
    )


def _validate_source_references(
    session: Session,
    engagement_id: UUID,
    references: list[SourceReference],
) -> None:
    for reference in references:
        _validate_source_reference(session, engagement_id, reference)


def _collect_source_references(value: Any) -> list[SourceReference]:
    references: list[SourceReference] = []
    if isinstance(value, dict):
        if {"kind", "ref", "sha256"}.issubset(value):
            references.append(SourceReference.model_validate(value))
        else:
            for item in value.values():
                references.extend(_collect_source_references(item))
    elif isinstance(value, list):
        for item in value:
            references.extend(_collect_source_references(item))
    return references


def _validate_source_reference(
    session: Session,
    engagement_id: UUID,
    reference: SourceReference,
) -> None:
    source_id = _source_reference_id(reference.ref)
    if reference.kind in {ProvenanceKind.EVIDENCE, ProvenanceKind.ASSUMPTION}:
        evidence = session.scalar(
            select(EvidenceAsset).where(
                EvidenceAsset.id == source_id,
                EvidenceAsset.engagement_id == engagement_id,
            )
        )
        if evidence is None or evidence.status != "complete":
            raise FactoryEngineerStateError(
                "Evidence and assumption provenance must resolve to a complete same-tenant asset."
            )
        _require_reference_digest(reference, f"sha256:{evidence.content_hash}")
        return
    if reference.kind == ProvenanceKind.VERIFIED_CLAIM:
        assertion = session.scalar(
            select(Assertion).where(
                Assertion.id == source_id,
                Assertion.engagement_id == engagement_id,
            )
        )
        if assertion is None or assertion.status != "verified" or reference.version != 1:
            raise FactoryEngineerIntegrityError(
                "Claim provenance must resolve to a current exact same-tenant assertion."
            )
        _require_reference_digest(reference, _assertion_digest(assertion))
        return
    if reference.kind != ProvenanceKind.APPROVED_INPUT:
        raise FactoryEngineerStateError("Unsupported provenance kind.")
    if reference.version is None:
        raise FactoryEngineerIntegrityError("Approved inputs must pin an immutable version.")

    source_type = reference.ref.split(":", 1)[0]
    expected_digest: str | None = None
    if source_type == "workflow":
        workflow = session.scalar(
            select(WorkflowVersion).where(
                WorkflowVersion.id == source_id,
                WorkflowVersion.engagement_id == engagement_id,
                WorkflowVersion.version_number == reference.version,
                WorkflowVersion.status == "approved",
            )
        )
        if workflow is not None:
            expected_digest = workflow_version_reference(session, workflow).digest
    elif source_type == "economic_case":
        economic_case = session.scalar(
            select(EconomicCase)
            .where(EconomicCase.engagement_id == engagement_id)
            .order_by(EconomicCase.version_number.desc())
            .limit(1)
        )
        if (
            economic_case is not None
            and economic_case.id == source_id
            and economic_case.version_number == reference.version
            and economic_case.status == "approved"
        ):
            expected_digest = _economic_case_digest(economic_case)
    elif source_type == "implementation_artifact":
        artifact = session.scalar(
            select(ImplementationArtifact).where(
                ImplementationArtifact.id == source_id,
                ImplementationArtifact.engagement_id == engagement_id,
                ImplementationArtifact.version_number == reference.version,
                ImplementationArtifact.status == "current",
            )
        )
        if artifact is not None:
            expected_digest = f"sha256:{artifact.content_hash}"
    elif source_type == "customer_factory_model":
        model = session.scalar(
            select(CustomerFactoryModelVersion).where(
                CustomerFactoryModelVersion.id == source_id,
                CustomerFactoryModelVersion.engagement_id == engagement_id,
                CustomerFactoryModelVersion.version_number == reference.version,
                CustomerFactoryModelVersion.status == CustomerFactoryModelStatus.APPROVED,
            )
        )
        if model is not None:
            expected_digest = _model_ref(model).digest
    elif source_type == "fdlc_readiness":
        readiness = session.scalar(
            select(FDLCReadinessAssessment).where(
                FDLCReadinessAssessment.id == source_id,
                FDLCReadinessAssessment.engagement_id == engagement_id,
                FDLCReadinessAssessment.version_number == reference.version,
                FDLCReadinessAssessment.status == ReadinessAssessmentStatus.APPROVED,
            )
        )
        if readiness is not None:
            expected_digest = _readiness_ref(readiness).digest
    elif source_type == "factory_opportunity":
        opportunity = session.scalar(
            select(FactoryOpportunity).where(
                FactoryOpportunity.id == source_id,
                FactoryOpportunity.engagement_id == engagement_id,
                FactoryOpportunity.version_number == reference.version,
                FactoryOpportunity.status == FactoryOpportunityStatus.SELECTED,
            )
        )
        if opportunity is not None:
            expected_digest = _opportunity_ref(opportunity).digest
    if expected_digest is None:
        raise FactoryEngineerStateError(
            "Approved-input provenance must resolve to a current same-tenant source."
        )
    _require_reference_digest(reference, expected_digest)


def _require_reference_digest(reference: SourceReference, expected: str) -> None:
    if reference.sha256 != expected:
        raise FactoryEngineerIntegrityError(
            "Provenance digest does not match its exact same-tenant source."
        )


def _validate_package_authority_basis(
    session: Session,
    package: FactoryDeploymentPackageVersion,
    authority_basis_ref: SourceReference,
) -> None:
    model = _customer_model(session, package.engagement_id, package.customer_factory_model_id)
    if not model.authority_boundaries:
        raise FactoryEngineerStateError(
            "Package approval requires an evidence-backed authority boundary in the customer model."
        )
    expected = customer_factory_model_authority_reference(model)
    if authority_basis_ref != expected:
        raise FactoryEngineerIntegrityError(
            "Package approval authority must pin its exact approved customer model."
        )
    _validate_source_reference(session, package.engagement_id, authority_basis_ref)


def _package_approval_decision_reference(
    package: FactoryDeploymentPackageVersion,
    *,
    approved_by: UUID,
    authority_basis_ref: SourceReference,
    approved_at: datetime,
) -> SourceReference:
    payload = {
        "package_version_id": str(package.id),
        "package_id": str(package.package_id),
        "package_version": package.package_version,
        "decision": "APPROVED",
        "approved_by": str(approved_by),
        "authority_basis_ref": authority_basis_ref.model_dump(mode="json"),
        "approved_at": _rfc3339_z(approved_at),
    }
    return SourceReference(
        kind=ProvenanceKind.APPROVED_INPUT,
        ref=f"factory_deployment_package_approval:{package.id}",
        version=1,
        sha256=canonical_sha256(payload),
    )


def _validate_package_approval_binding(
    package: FactoryDeploymentPackageVersion,
    approval: ApprovalBinding,
) -> None:
    if (
        package.approved_by_id != approval.approved_by
        or package.approved_at is None
        or package.issued_at is None
        or _rfc3339_z(package.approved_at) != _rfc3339_z(approval.approved_at)
        or package.approved_at > package.issued_at
    ):
        raise FactoryEngineerIntegrityError(
            "Package approval columns contradict the immutable approval binding."
        )
    expected = _package_approval_decision_reference(
        package,
        approved_by=approval.approved_by,
        authority_basis_ref=approval.authority_basis_ref,
        approved_at=approval.approved_at,
    )
    if approval.decision_ref != expected:
        raise FactoryEngineerIntegrityError(
            "Package approval decision reference does not match its immutable binding."
        )
    if approval.authorized_by_ref != approval.authority_basis_ref.ref:
        raise FactoryEngineerIntegrityError(
            "Package approval authority label does not match its exact authority source."
        )
    session = object_session(package)
    if session is None:
        raise FactoryEngineerIntegrityError("Package approval is not attached to a session.")
    _validate_package_authority_basis(session, package, approval.authority_basis_ref)


def _source_reference_id(reference: str) -> UUID:
    candidate = reference.rsplit(":", 1)[-1].rsplit("/", 1)[-1]
    try:
        return UUID(candidate)
    except ValueError as exc:
        raise FactoryEngineerStateError(
            "Provenance references must end with a source UUID."
        ) from exc


def _economic_case_digest(economic_case: EconomicCase) -> str:
    return canonical_sha256(
        {
            "id": str(economic_case.id),
            "version": economic_case.version_number,
            "source_target_workflow_id": str(economic_case.source_target_workflow_id),
            "formula_version": economic_case.formula_version,
            "inputs": economic_case.inputs,
            "outputs": economic_case.outputs,
            "scenarios": economic_case.scenarios,
            "assumptions": economic_case.assumptions,
        }
    )


def _assertion_digest(assertion: Assertion) -> str:
    return canonical_sha256(
        {
            "id": str(assertion.id),
            "subject_entity_id": str(assertion.subject_entity_id),
            "predicate": assertion.predicate,
            "object_entity_id": str(assertion.object_entity_id)
            if assertion.object_entity_id
            else None,
            "value": assertion.value,
            "confidence": str(assertion.confidence),
            "valid_from": assertion.valid_from.isoformat() if assertion.valid_from else None,
            "valid_until": assertion.valid_until.isoformat() if assertion.valid_until else None,
            "candidate_claim_id": str(assertion.candidate_claim_id),
            "verified_by_id": str(assertion.verified_by_id),
            "recorded_at": _rfc3339_z(assertion.recorded_at),
        }
    )


def _customer_model_digest(model: CustomerFactoryModelVersion) -> str:
    return canonical_sha256(
        {
            "organization": model.organization,
            "systems": model.systems,
            "repositories": model.repositories,
            "environments": model.environments,
            "workflows": model.workflows,
            "policies": model.policies,
            "authority_boundaries": model.authority_boundaries,
            "constraints": model.constraints,
            "risks": model.risks,
            "baselines": model.baselines,
            "evidence_refs": model.evidence_refs,
            "verified_claim_refs": model.verified_claim_refs,
            "assumption_refs": model.assumption_refs,
            "factory_opportunity_refs": model.factory_opportunity_refs,
        }
    )


def _readiness_digest(readiness: FDLCReadinessAssessment) -> str:
    session = object_session(readiness)
    if session is None:
        raise FactoryEngineerIntegrityError("Readiness source is not attached to a session.")
    model = session.get(CustomerFactoryModelVersion, readiness.customer_factory_model_id)
    opportunity = session.get(FactoryOpportunity, readiness.selected_opportunity_id)
    if model is None or opportunity is None:
        raise FactoryEngineerIntegrityError("Readiness exact source version no longer exists.")
    return canonical_sha256(
        {
            "customer_factory_model": _model_ref(model).model_dump(mode="json"),
            "selected_opportunity": _opportunity_ref(opportunity).model_dump(mode="json"),
            "current_workflow": readiness.current_workflow_ref,
            "target_workflow": readiness.target_workflow_ref,
            "stages": readiness.stages,
        }
    )


def _opportunity_digest(opportunity: FactoryOpportunity) -> str:
    session = object_session(opportunity)
    if session is None:
        raise FactoryEngineerIntegrityError("Opportunity source is not attached to a session.")
    model = session.get(CustomerFactoryModelVersion, opportunity.customer_factory_model_id)
    if model is None:
        raise FactoryEngineerIntegrityError("Opportunity customer model no longer exists.")
    return canonical_sha256(
        {
            "input": {
                "opportunity_key": opportunity.opportunity_key,
                "name": opportunity.name,
                "description": opportunity.description,
                "source_workflow_ref": opportunity.source_workflow_ref,
                "factors": opportunity.factors,
                "economics_ref": opportunity.economics_ref,
                "evidence_refs": opportunity.evidence_refs,
                "blockers": opportunity.blockers,
            },
            "score": {
                "value_score": opportunity.value_score,
                "verifiability_score": opportunity.verifiability_score,
                "readiness_score": opportunity.readiness_score,
                "risk_score": opportunity.risk_score,
                "autonomy_potential": opportunity.autonomy_potential,
                "priority_score": opportunity.priority_score,
                "rationale": opportunity.rationale,
                "recommendation": opportunity.recommendation,
                "rubric_version": opportunity.rubric_version,
                "rubric": opportunity.rubric,
            },
            "customer_factory_model": _model_ref(model).model_dump(mode="json"),
        }
    )


def _verified_content_digest(stored: str, expected: str, source: str) -> str:
    if stored != expected:
        raise FactoryEngineerIntegrityError(
            f"Stored {source} digest does not match its immutable content."
        )
    return expected


def _rfc3339_z(value: datetime) -> str:
    if value.tzinfo is None:
        raise FactoryEngineerIntegrityError("Canonical package timestamps must include a timezone.")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _model_ref(model: CustomerFactoryModelVersion) -> ImmutableVersionReference:
    return ImmutableVersionReference(
        id=model.id,
        version=model.version_number,
        digest=_verified_content_digest(
            model.content_digest,
            _customer_model_digest(model),
            "customer model",
        ),
    )


def _readiness_ref(readiness: FDLCReadinessAssessment) -> ImmutableVersionReference:
    return ImmutableVersionReference(
        id=readiness.id,
        version=readiness.version_number,
        digest=_verified_content_digest(
            readiness.content_digest,
            _readiness_digest(readiness),
            "readiness assessment",
        ),
    )


def _opportunity_ref(opportunity: FactoryOpportunity) -> ImmutableVersionReference:
    return ImmutableVersionReference(
        id=opportunity.id,
        version=opportunity.version_number,
        digest=_verified_content_digest(
            opportunity.content_digest,
            _opportunity_digest(opportunity),
            "factory opportunity",
        ),
    )


def _issuer(package: FactoryDeploymentPackageVersion) -> PackageIssuer:
    return PackageIssuer(
        issuer_id=package.issuer_id,
        issuer_type="FDLC_FACTORY_ENGINEER",
        environment=package.issuer_environment,
        authority_scope="DEPLOYMENT_PACKAGE_PUBLISH",
    )


def _lock_engagement(session: Session, engagement_id: UUID) -> Engagement:
    engagement = session.scalar(
        select(Engagement).where(Engagement.id == engagement_id).with_for_update()
    )
    if engagement is None:
        raise FactoryEngineerNotFoundError(str(engagement_id))
    return engagement


def _lock_active_engagement(session: Session, engagement_id: UUID) -> Engagement:
    engagement = _lock_engagement(session, engagement_id)
    if engagement.data_lifecycle_status != "active":
        raise FactoryEngineerStateError(
            "Factory package issuance is unavailable while engagement deletion is "
            "pending or failed."
        )
    return engagement


def _customer_model(
    session: Session, engagement_id: UUID, model_id: UUID, *, lock: bool = False
) -> CustomerFactoryModelVersion:
    statement = select(CustomerFactoryModelVersion).where(
        CustomerFactoryModelVersion.id == model_id,
        CustomerFactoryModelVersion.engagement_id == engagement_id,
    )
    if lock:
        statement = statement.with_for_update()
    model = session.scalar(statement)
    if model is None:
        raise FactoryEngineerNotFoundError(str(model_id))
    return model


def _readiness(
    session: Session, engagement_id: UUID, assessment_id: UUID, *, lock: bool = False
) -> FDLCReadinessAssessment:
    statement = select(FDLCReadinessAssessment).where(
        FDLCReadinessAssessment.id == assessment_id,
        FDLCReadinessAssessment.engagement_id == engagement_id,
    )
    if lock:
        statement = statement.with_for_update()
    assessment = session.scalar(statement)
    if assessment is None:
        raise FactoryEngineerNotFoundError(str(assessment_id))
    return assessment


def _opportunity(
    session: Session, engagement_id: UUID, opportunity_id: UUID, *, lock: bool = False
) -> FactoryOpportunity:
    statement = select(FactoryOpportunity).where(
        FactoryOpportunity.id == opportunity_id,
        FactoryOpportunity.engagement_id == engagement_id,
    )
    if lock:
        statement = statement.with_for_update()
    opportunity = session.scalar(statement)
    if opportunity is None:
        raise FactoryEngineerNotFoundError(str(opportunity_id))
    return opportunity


def _package(
    session: Session, engagement_id: UUID, package_version_id: UUID, *, lock: bool = False
) -> FactoryDeploymentPackageVersion:
    statement = select(FactoryDeploymentPackageVersion).where(
        FactoryDeploymentPackageVersion.id == package_version_id,
        FactoryDeploymentPackageVersion.engagement_id == engagement_id,
    )
    if lock:
        statement = statement.with_for_update()
    package = session.scalar(statement)
    if package is None:
        raise FactoryEngineerNotFoundError(str(package_version_id))
    return package


def _next_version(
    session: Session, model: type[Any], engagement_id: UUID, attribute_name: str
) -> int:
    attribute = getattr(model, attribute_name)
    latest = session.scalar(select(func.max(attribute)).where(model.engagement_id == engagement_id))
    return int(latest or 0) + 1


def _next_opportunity_version(session: Session, engagement_id: UUID, key: str) -> int:
    latest = session.scalar(
        select(func.max(FactoryOpportunity.version_number)).where(
            FactoryOpportunity.engagement_id == engagement_id,
            FactoryOpportunity.opportunity_key == key,
        )
    )
    return int(latest or 0) + 1


def _next_package_version(session: Session, engagement_id: UUID, package_id: UUID) -> int:
    latest = session.scalar(
        select(func.max(FactoryDeploymentPackageVersion.package_version)).where(
            FactoryDeploymentPackageVersion.engagement_id == engagement_id,
            FactoryDeploymentPackageVersion.package_id == package_id,
        )
    )
    return int(latest or 0) + 1


def _record_event(
    session: Session,
    aggregate: Any,
    operator: Operator,
    action: str,
    *,
    detail: dict[str, Any] | None = None,
) -> None:
    target_type = AGGREGATE_TYPE_BY_TABLE[aggregate.__tablename__]
    record_audit(
        session,
        engagement_id=aggregate.engagement_id,
        actor_id=operator.id,
        action=action,
        target_type=target_type,
        target_id=aggregate.id,
        detail=detail,
    )
    publish_domain_event(
        session,
        engagement_id=aggregate.engagement_id,
        event_type=action,
        aggregate_type=target_type,
        aggregate_id=aggregate.id,
        payload=detail,
    )


def _record_derived_transition(
    session: Session,
    *,
    aggregate: Any,
    event_type: str,
    reason: str,
    actor_id: UUID | None,
) -> None:
    target_type = AGGREGATE_TYPE_BY_TABLE[aggregate.__tablename__]
    detail = {"reason": reason, "derived_transition": True}
    if actor_id is not None:
        record_audit(
            session,
            engagement_id=aggregate.engagement_id,
            actor_id=actor_id,
            action=event_type,
            target_type=target_type,
            target_id=aggregate.id,
            detail=detail,
        )
    publish_domain_event(
        session,
        engagement_id=aggregate.engagement_id,
        event_type=event_type,
        aggregate_type=target_type,
        aggregate_id=aggregate.id,
        payload=detail,
    )


def _require_human(operator: Operator, action: str) -> None:
    if operator.identity_kind != "human" or not operator.is_active:
        raise FactoryEngineerStateError(f"{action} requires a human operator identity.")


def _require_engagement_owner(
    session: Session, engagement_id: UUID, operator: Operator, action: str
) -> None:
    membership = session.scalar(
        select(EngagementMember).where(
            EngagementMember.engagement_id == engagement_id,
            EngagementMember.operator_id == operator.id,
            EngagementMember.role == "owner",
        )
    )
    if membership is None:
        raise FactoryEngineerStateError(f"{action} requires the engagement owner.")
