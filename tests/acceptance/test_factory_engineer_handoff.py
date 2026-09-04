from __future__ import annotations

import copy
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from ai_fde.adapters.storage import InMemoryEvidenceStore
from ai_fde.db import operator_session
from ai_fde.models import (
    Assertion,
    AuditEvent,
    CandidateClaim,
    EvidenceAsset,
    Operator,
    WorkflowStep,
    WorkflowVersion,
)
from ai_fde.modules.engagements.service import create_engagement
from ai_fde.modules.evidence.service import create_evidence_asset
from ai_fde.modules.factory_engineer.fixtures import SYNTHETIC_OPPORTUNITY_TEMPLATES
from ai_fde.modules.factory_engineer.models import (
    CustomerFactoryModelVersion,
    FactoryDeploymentPackageVersion,
    PackageRetrievalEvent,
    PackageRetrievalGrant,
)
from ai_fde.modules.factory_engineer.readiness import READINESS_CRITERIA
from ai_fde.modules.factory_engineer.retrieval import (
    authenticate_retrieval_token,
    issue_retrieval_grant,
    provision_retrieval_service_identity,
    retrieve_published_package,
    revoke_retrieval_grant,
)
from ai_fde.modules.factory_engineer.schemas import (
    CustomerFactoryModelInput,
    DeploymentTarget,
    FactoryDeploymentPackageInput,
    FactoryDeploymentPackageStatus,
    FactoryOpportunityInput,
    ProvenanceKind,
    ReadinessAssessmentInput,
    ReadinessCriterionInput,
    ReadinessStageInput,
    SourceReference,
    TraceableFact,
)
from ai_fde.modules.factory_engineer.service import (
    FactoryEngineerStateError,
    approve_customer_factory_model,
    approve_deployment_package,
    approve_readiness_assessment,
    assertion_reference,
    create_customer_factory_model,
    create_deployment_package,
    create_factory_opportunity,
    create_readiness_assessment,
    customer_factory_model_authority_reference,
    evidence_asset_reference,
    publish_deployment_package,
    reject_deployment_package,
    select_factory_opportunity,
    serialize_published_package_envelope,
    submit_deployment_package_for_review,
    workflow_version_reference,
)
from ai_fde.modules.knowledge.jobs import lease_next_job, process_job
from ai_fde.modules.knowledge.review import review_claim
from tests.conftest import OperatorFixture

PACKAGE_FIXTURE = Path("fixtures/contracts/factory-deployment-package-v1.json")


def _ready_assessment(basis: SourceReference) -> ReadinessAssessmentInput:
    return ReadinessAssessmentInput(
        stages=[
            ReadinessStageInput(
                stage=stage,
                criteria=[
                    ReadinessCriterionInput(
                        key=key,
                        label=key.replace("_", " ").title(),
                        satisfied=True,
                        explanation="Satisfied by the pinned source evidence.",
                        basis_refs=[basis],
                    )
                    for key in keys
                ],
                owner="Factory Engineer",
            )
            for stage, keys in READINESS_CRITERIA.items()
        ]
    )


def _approved_input_ref(
    prefix: str, row_id: uuid.UUID, version: int, digest: str
) -> SourceReference:
    return SourceReference(
        kind=ProvenanceKind.APPROVED_INPUT,
        ref=f"{prefix}:{row_id}",
        version=version,
        sha256=digest,
    )


@pytest.mark.integration
def test_trusted_factory_handoff_is_human_approved_retrievable_and_stale_safe(
    test_operator: OperatorFixture,
) -> None:
    store = InMemoryEvidenceStore()
    source = Path("fixtures/acme/evidence/01-accounts-payable-sop.md").read_bytes()
    timestamp = datetime.now(UTC)

    with operator_session(test_operator.id) as session:
        operator = session.get_one(Operator, test_operator.id)
        engagement = create_engagement(
            session,
            operator=operator,
            name=f"Factory handoff {uuid.uuid4()}",
            workflow_name="Invoice approval",
            primary_outcome="Prove a trusted package handoff and immediate stale propagation.",
        )
        engagement_id = engagement.id
        evidence = create_evidence_asset(
            session,
            store,
            engagement_id=engagement_id,
            operator=operator,
            file_name="accounts-payable-sop.md",
            content_type="text/markdown",
            content=source,
            source_type="fixture",
        )
        evidence_id = evidence.id
        service_operator = provision_retrieval_service_identity(
            session,
            engagement_id=engagement_id,
            created_by=operator,
        )
        assert (
            provision_retrieval_service_identity(
                session,
                engagement_id=engagement_id,
                created_by=operator,
            ).id
            == service_operator.id
        )
        service_operator_id = service_operator.id

    with operator_session(test_operator.id) as session:
        job = lease_next_job(session, engagement_id, lease_seconds=30)
        assert job is not None
        process_job(session, store, job)

    with operator_session(test_operator.id) as session:
        operator = session.get_one(Operator, test_operator.id)
        service_operator = session.get_one(Operator, service_operator_id)
        claims = list(
            session.scalars(
                select(CandidateClaim)
                .where(CandidateClaim.engagement_id == engagement_id)
                .order_by(CandidateClaim.id)
            )
        )
        assert claims
        assertion = review_claim(
            session,
            engagement_id=engagement_id,
            claim_id=claims[0].id,
            operator=operator,
            decision="accepted",
            reason="Pinned for the Factory Engineer acceptance case.",
        )
        assert isinstance(assertion, Assertion)
        for claim in claims[1:]:
            review_claim(
                session,
                engagement_id=engagement_id,
                claim_id=claim.id,
                operator=operator,
                decision="rejected",
                reason="Closed after human review for the acceptance case.",
            )
        # Retrieve the concrete row after all claims close so provenance is accepted as complete.
        evidence = session.get_one(EvidenceAsset, evidence_id)
        assert evidence.status == "complete"
        evidence_ref = evidence_asset_reference(evidence)
        assertion_ref = assertion_reference(assertion)
        fact = TraceableFact(
            key="invoice-approval",
            label="Invoice approval",
            description="Evidence-backed invoice approval factory context.",
            provenance_refs=[evidence_ref, assertion_ref],
        )
        model = create_customer_factory_model(
            session,
            engagement_id=engagement_id,
            operator=operator,
            model_input=CustomerFactoryModelInput(
                organization=TraceableFact(
                    key="acceptance-manufacturing",
                    label="Acceptance Manufacturing",
                    description="Synthetic Factory Engineer acceptance organization.",
                    provenance_refs=[evidence_ref],
                ),
                workflows=[fact],
                authority_boundaries=[
                    TraceableFact(
                        key="engagement-owner-publish",
                        label="Engagement owner publication authority",
                        description=(
                            "Only the active engagement owner may approve or publish a package."
                        ),
                        provenance_refs=[assertion_ref],
                    )
                ],
                evidence_refs=[evidence_ref],
                verified_claim_refs=[assertion_ref],
            ),
        )
        with pytest.raises(FactoryEngineerStateError, match="human operator"):
            approve_customer_factory_model(
                session,
                engagement_id=engagement_id,
                model_id=model.id,
                operator=service_operator,
                now=timestamp,
            )
        approve_customer_factory_model(
            session,
            engagement_id=engagement_id,
            model_id=model.id,
            operator=operator,
            now=timestamp,
        )

        current = WorkflowVersion(
            engagement_id=engagement_id,
            workflow_kind="current",
            version_number=1,
            name="Invoice approval current state",
            objective="Record the approved current workflow.",
            status="approved",
            source_assertion_ids=[str(assertion.id)],
            generated_by="operator",
            created_by_id=operator.id,
            approved_by_id=operator.id,
            approved_at=timestamp,
            approval_reason="Accepted for the Factory Engineer handoff.",
        )
        session.add(current)
        session.flush()
        session.add(
            WorkflowStep(
                engagement_id=engagement_id,
                workflow_version_id=current.id,
                step_key="review-invoice",
                position=1,
                name="Review invoice",
                description="Review invoice evidence and approval requirements.",
                step_type="human_task",
                actor_label="Controller",
                system_label="ERP",
                allocation="human",
                rationale="Current evidence requires human review.",
                controls=["CFO approval threshold"],
                source_assertion_id=assertion.id,
            )
        )
        target = WorkflowVersion(
            engagement_id=engagement_id,
            workflow_kind="target",
            version_number=1,
            name="Invoice approval target state",
            objective="Bound automation behind deterministic validation.",
            status="approved",
            source_workflow_id=current.id,
            source_assertion_ids=[str(assertion.id)],
            generated_by="operator",
            created_by_id=operator.id,
            approved_by_id=operator.id,
            approved_at=timestamp,
            approval_reason="Accepted for the Factory Engineer handoff.",
        )
        session.add(target)
        session.flush()
        session.add(
            WorkflowStep(
                engagement_id=engagement_id,
                workflow_version_id=target.id,
                step_key="validate-invoice",
                position=1,
                name="Validate invoice",
                description="Validate invoice inputs before human approval.",
                step_type="software_task",
                actor_label="Factory worker",
                system_label="SellerFi",
                allocation="software",
                rationale="The validation is deterministic and bounded.",
                controls=["No approval authority"],
                source_assertion_id=assertion.id,
            )
        )
        session.flush()

        current_ref = workflow_version_reference(session, current)
        template = SYNTHETIC_OPPORTUNITY_TEMPLATES[0]
        opportunity = create_factory_opportunity(
            session,
            engagement_id=engagement_id,
            operator=operator,
            customer_factory_model_id=model.id,
            opportunity_input=FactoryOpportunityInput(
                opportunity_key=template.opportunity_key,
                name=template.name,
                description=template.description,
                source_workflow_ref=current_ref,
                factors=template.factors,
                economics_ref=evidence_ref,
                evidence_refs=[evidence_ref],
            ),
        )
        with pytest.raises(FactoryEngineerStateError, match="human operator"):
            select_factory_opportunity(
                session,
                engagement_id=engagement_id,
                opportunity_id=opportunity.id,
                operator=service_operator,
                reason="A service identity must never select the deployment line.",
                now=timestamp,
            )
        select_factory_opportunity(
            session,
            engagement_id=engagement_id,
            opportunity_id=opportunity.id,
            operator=operator,
            reason="Best evidence-backed engineering opportunity.",
            now=timestamp,
        )

        readiness = create_readiness_assessment(
            session,
            engagement_id=engagement_id,
            operator=operator,
            customer_factory_model_id=model.id,
            selected_opportunity_id=opportunity.id,
            current_workflow_id=current.id,
            target_workflow_id=target.id,
            assessment_input=_ready_assessment(evidence_ref),
            now=timestamp,
        )
        with pytest.raises(FactoryEngineerStateError, match="human operator"):
            approve_readiness_assessment(
                session,
                engagement_id=engagement_id,
                assessment_id=readiness.id,
                operator=service_operator,
                now=timestamp,
            )
        approve_readiness_assessment(
            session,
            engagement_id=engagement_id,
            assessment_id=readiness.id,
            operator=operator,
            now=timestamp,
        )

        fixture = json.loads(PACKAGE_FIXTURE.read_text())
        contract_payload = copy.deepcopy(fixture["deployment_intent"])
        readiness_ref = _approved_input_ref(
            "fdlc_readiness", readiness.id, readiness.version_number, readiness.content_digest
        )
        authority_ref = customer_factory_model_authority_reference(model)
        contract_payload["evidence_refs"] = [evidence_ref.model_dump(mode="json")]
        contract_payload["decision_refs"] = [readiness_ref.model_dump(mode="json")]
        contract_payload["provenance"] = [assertion_ref.model_dump(mode="json")]
        rejected_package = create_deployment_package(
            session,
            engagement_id=engagement_id,
            operator=operator,
            customer_factory_model_id=model.id,
            readiness_assessment_id=readiness.id,
            factory_opportunity_id=opportunity.id,
            target=DeploymentTarget.model_validate(fixture["target"]),
            package_input=FactoryDeploymentPackageInput.model_validate(contract_payload),
        )
        reject_deployment_package(
            session,
            engagement_id=engagement_id,
            package_version_id=rejected_package.id,
            operator=operator,
            reason="Reject this draft to prove the terminal review path.",
            now=timestamp,
        )
        assert rejected_package.status == FactoryDeploymentPackageStatus.REJECTED
        package = create_deployment_package(
            session,
            engagement_id=engagement_id,
            operator=operator,
            customer_factory_model_id=model.id,
            readiness_assessment_id=readiness.id,
            factory_opportunity_id=opportunity.id,
            target=DeploymentTarget.model_validate(fixture["target"]),
            package_input=FactoryDeploymentPackageInput.model_validate(contract_payload),
        )
        submit_deployment_package_for_review(
            session,
            engagement_id=engagement_id,
            package_version_id=package.id,
            operator=operator,
        )
        with pytest.raises(FactoryEngineerStateError, match="human operator"):
            approve_deployment_package(
                session,
                engagement_id=engagement_id,
                package_version_id=package.id,
                operator=service_operator,
                authority_basis_ref=authority_ref,
                now=timestamp,
            )
        approve_deployment_package(
            session,
            engagement_id=engagement_id,
            package_version_id=package.id,
            operator=operator,
            authority_basis_ref=authority_ref,
            now=timestamp,
        )
        publish_deployment_package(
            session,
            engagement_id=engagement_id,
            package_version_id=package.id,
            operator=operator,
            now=timestamp + timedelta(seconds=1),
        )
        package_id = package.package_id
        package_version = package.package_version
        package_version_id = package.id
        issued = issue_retrieval_grant(
            session,
            engagement_id=engagement_id,
            service_operator=service_operator,
            created_by=operator,
            requester_identity="mission-control-workspace:sellerfi-production",
            requester_system="mission-control",
            expires_at=timestamp + timedelta(days=1),
            now=timestamp,
        )
        retrieval_token = issued.token
        retrieval_grant_id = issued.grant.id
        assert retrieval_token not in issued.grant.token_digest

    correlation_id = uuid.uuid4()
    with operator_session(service_operator_id) as session:
        authentication = authenticate_retrieval_token(
            session, token=retrieval_token, now=timestamp + timedelta(seconds=2)
        )
        assert authentication.authenticated is True
        assert authentication.principal is not None
        decision = retrieve_published_package(
            session,
            package_id=package_id,
            package_version=package_version,
            principal=authentication.principal,
            correlation_id=correlation_id,
            now=timestamp + timedelta(seconds=2),
        )
        assert decision.allowed is True
        assert decision.package is not None
        assert decision.package.attestation.correlation_id == correlation_id
        assert decision.package.package.integrity.digest == decision.package.attestation.digest
        assert len(serialize_published_package_envelope(decision.package)) <= 256_000

    forged_token = retrieval_token[:-1] + ("A" if retrieval_token[-1] != "A" else "B")
    with operator_session(service_operator_id) as session:
        invalid_authentication = authenticate_retrieval_token(
            session, token=forged_token, now=timestamp + timedelta(seconds=2)
        )
        assert invalid_authentication.authenticated is False
        assert invalid_authentication.result == "INVALID_TOKEN"
        session.flush()
        invalid_audit = session.scalar(
            select(AuditEvent)
            .where(
                AuditEvent.engagement_id == engagement_id,
                AuditEvent.action == "deployment_package.retrieval_authentication_denied",
                AuditEvent.detail["result"].as_string() == "INVALID_TOKEN",
            )
            .order_by(AuditEvent.created_at.desc())
        )
        assert invalid_audit is not None
        assert invalid_audit.actor_type == "unauthenticated"
        assert invalid_audit.actor_id == uuid.UUID(int=0)

    with operator_session(test_operator.id) as session:
        operator = session.get_one(Operator, test_operator.id)
        model = session.get_one(CustomerFactoryModelVersion, model.id)
        current = session.get_one(WorkflowVersion, current.id)
        evidence = session.get_one(EvidenceAsset, evidence_id)
        replacement = create_factory_opportunity(
            session,
            engagement_id=engagement_id,
            operator=operator,
            customer_factory_model_id=model.id,
            opportunity_input=FactoryOpportunityInput(
                opportunity_key="dependency-modernization-alternative",
                name="Dependency modernization alternative",
                description="A replacement selected line must stale its old package immediately.",
                source_workflow_ref=workflow_version_reference(session, current),
                factors=SYNTHETIC_OPPORTUNITY_TEMPLATES[1].factors,
                economics_ref=evidence_asset_reference(evidence),
                evidence_refs=[evidence_asset_reference(evidence)],
            ),
        )
        select_factory_opportunity(
            session,
            engagement_id=engagement_id,
            opportunity_id=replacement.id,
            operator=operator,
            reason="Replace the selected deployment line.",
            now=timestamp + timedelta(seconds=3),
        )
        package = session.get_one(FactoryDeploymentPackageVersion, package_version_id)
        assert package.status == FactoryDeploymentPackageStatus.STALE

    with operator_session(service_operator_id) as session:
        authentication = authenticate_retrieval_token(
            session, token=retrieval_token, now=timestamp + timedelta(seconds=4)
        )
        assert authentication.principal is not None
        stale_decision = retrieve_published_package(
            session,
            package_id=package_id,
            package_version=package_version,
            principal=authentication.principal,
            correlation_id=uuid.uuid4(),
            now=timestamp + timedelta(seconds=4),
        )
        assert stale_decision.allowed is False
        assert stale_decision.result == "DENIED_STALE"
        session.flush()
        assert (
            session.scalar(
                select(func.count())
                .select_from(PackageRetrievalEvent)
                .where(PackageRetrievalEvent.package_version_id == package_version_id)
            )
            == 2
        )

    with operator_session(service_operator_id) as session:
        cached_grant = session.get_one(PackageRetrievalGrant, retrieval_grant_id)
        assert cached_grant.revoked_at is None
        with operator_session(test_operator.id) as revocation_session:
            revoke_retrieval_grant(
                revocation_session,
                engagement_id=engagement_id,
                grant_id=retrieval_grant_id,
                revoked_by=revocation_session.get_one(Operator, test_operator.id),
                now=timestamp + timedelta(seconds=5),
            )
        revoked_authentication = authenticate_retrieval_token(
            session, token=retrieval_token, now=timestamp + timedelta(seconds=6)
        )
        assert revoked_authentication.authenticated is False
        assert revoked_authentication.result == "REVOKED_TOKEN"
        assert cached_grant.revoked_at == timestamp + timedelta(seconds=5)
        session.flush()
        denial = session.scalar(
            select(AuditEvent).where(
                AuditEvent.engagement_id == engagement_id,
                AuditEvent.action == "deployment_package.retrieval_authentication_denied",
                AuditEvent.detail["result"].as_string() == "REVOKED_TOKEN",
            )
        )
        assert denial is not None
        assert denial.detail["result"] == "REVOKED_TOKEN"
