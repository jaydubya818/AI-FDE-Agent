from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import NamedTuple

import pytest
from sqlalchemy import create_engine, func, insert, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from ai_fde.config import get_settings
from ai_fde.db import SessionFactory, operator_session
from ai_fde.models import AuditEvent, Operator
from ai_fde.modules.engagements.service import create_engagement
from ai_fde.modules.factory_engineer.models import (
    CustomerFactoryModelVersion,
    FactoryDeploymentPackageVersion,
    FactoryOpportunity,
    FDLCReadinessAssessment,
    PackageRetrievalEvent,
)
from ai_fde.modules.factory_engineer.service import approve_customer_factory_model
from tests.conftest import OperatorFixture


class Phase2Graph(NamedTuple):
    model: CustomerFactoryModelVersion
    opportunity: FactoryOpportunity
    readiness: FDLCReadinessAssessment
    package: FactoryDeploymentPackageVersion


def _seed_phase2_graph(
    session: Session, *, engagement_id: uuid.UUID, operator_id: uuid.UUID
) -> Phase2Graph:
    # The helper intentionally uses the ORM directly so these tests exercise the
    # migration's database constraints independently of the domain service.
    model = CustomerFactoryModelVersion(
        engagement_id=engagement_id,
        version_number=1,
        status="DRAFT",
        organization={"key": "test"},
        systems=[],
        repositories=[],
        environments=[],
        workflows=[],
        policies=[],
        authority_boundaries=[],
        constraints=[],
        risks=[],
        baselines=[],
        evidence_refs=[],
        verified_claim_refs=[],
        assumption_refs=[],
        factory_opportunity_refs=[],
        content_digest="sha256:" + "1" * 64,
        created_by_id=operator_id,
    )
    session.add(model)
    session.flush()
    opportunity = FactoryOpportunity(
        engagement_id=engagement_id,
        opportunity_key="integrity-check",
        version_number=1,
        status="CANDIDATE",
        name="Integrity check",
        description="Exercise exact version and cascade constraints.",
        source_workflow_ref={
            "id": str(uuid.uuid4()),
            "version": 1,
            "digest": "sha256:" + "2" * 64,
        },
        customer_factory_model_id=model.id,
        customer_factory_model_version=model.version_number,
        value_score=50,
        verifiability_score=50,
        readiness_score=50,
        risk_score=50,
        autonomy_potential=50,
        priority_score=50,
        factors={},
        rubric={},
        rubric_version="test/v1",
        economics_ref={},
        evidence_refs=[],
        rationale=[],
        blockers=[],
        recommendation="ASSESS",
        content_digest="sha256:" + "3" * 64,
        created_by_id=operator_id,
    )
    session.add(opportunity)
    session.flush()
    readiness = FDLCReadinessAssessment(
        engagement_id=engagement_id,
        version_number=1,
        status="DRAFT",
        overall_status="READY",
        customer_factory_model_id=model.id,
        customer_factory_model_version=model.version_number,
        selected_opportunity_id=opportunity.id,
        selected_opportunity_version=opportunity.version_number,
        current_workflow_ref={
            "id": str(uuid.uuid4()),
            "version": 1,
            "digest": "sha256:" + "4" * 64,
        },
        target_workflow_ref={
            "id": str(uuid.uuid4()),
            "version": 1,
            "digest": "sha256:" + "5" * 64,
        },
        stages=[],
        content_digest="sha256:" + "6" * 64,
        created_by_id=operator_id,
    )
    session.add(readiness)
    session.flush()
    package = FactoryDeploymentPackageVersion(
        engagement_id=engagement_id,
        package_id=uuid.uuid4(),
        package_version=1,
        schema_version="fdlc.factory-deployment-package/v1",
        status="DRAFT",
        issuer_id="factory-engineer-test",
        issuer_type="FDLC_FACTORY_ENGINEER",
        issuer_environment="test",
        issuer_authority_scope="DEPLOYMENT_PACKAGE_PUBLISH",
        customer_factory_model_id=model.id,
        customer_factory_model_version=model.version_number,
        current_workflow_ref=readiness.current_workflow_ref,
        target_workflow_ref=readiness.target_workflow_ref,
        readiness_assessment_id=readiness.id,
        readiness_assessment_version=readiness.version_number,
        factory_opportunity_id=opportunity.id,
        factory_opportunity_version=opportunity.version_number,
        target={},
        contract={},
        created_by_id=operator_id,
    )
    session.add(package)
    session.flush()
    return Phase2Graph(model, opportunity, readiness, package)


@pytest.mark.integration
@pytest.mark.isolation
def test_runtime_privileges_keep_versions_and_audits_append_only(
    postgres_available: None,
) -> None:
    tables_without_delete = (
        "customer_factory_model_versions",
        "fdlc_readiness_assessments",
        "factory_opportunities",
        "factory_deployment_package_versions",
        "package_retrieval_grants",
        "package_retrieval_events",
        "audit_events",
    )
    with SessionFactory() as session:
        assert all(
            session.scalar(
                text("SELECT has_table_privilege('ai_fde_app', :table_name, 'DELETE')"),
                {"table_name": table_name},
            )
            is False
            for table_name in tables_without_delete
        )
        assert (
            session.scalar(
                text(
                    "SELECT has_table_privilege('ai_fde_app', 'package_retrieval_events', 'UPDATE')"
                )
            )
            is False
        )
        assert (
            session.scalar(
                text("SELECT has_table_privilege('ai_fde_app', 'audit_events', 'UPDATE')")
            )
            is False
        )


@pytest.mark.integration
@pytest.mark.isolation
def test_database_blocks_content_mutation_and_forged_retrieval_events(
    test_operator: OperatorFixture,
) -> None:
    with operator_session(test_operator.id) as session:
        operator = session.get_one(Operator, test_operator.id)
        engagement = create_engagement(
            session,
            operator=operator,
            name=f"Factory integrity {uuid.uuid4()}",
            primary_outcome="Prove immutable versions and append-only retrieval audit.",
        )
        graph = _seed_phase2_graph(session, engagement_id=engagement.id, operator_id=operator.id)
        approve_customer_factory_model(
            session,
            engagement_id=engagement.id,
            model_id=graph.model.id,
            operator=operator,
        )

        with pytest.raises(DBAPIError, match="content is immutable"), session.begin_nested():
            session.execute(
                text(
                    "UPDATE customer_factory_model_versions "
                    "SET organization = '{\"tampered\": true}'::jsonb WHERE id = :model_id"
                ),
                {"model_id": graph.model.id},
            )
        with pytest.raises(DBAPIError, match="immutable"), session.begin_nested():
            session.execute(
                text(
                    "UPDATE factory_deployment_package_versions "
                    "SET contract = '{\"tampered\": true}'::jsonb "
                    "WHERE id = :package_id"
                ),
                {"package_id": graph.package.id},
            )

        invalid_common = {
            "engagement_id": engagement.id,
            "package_id": graph.package.package_id,
            "package_version": graph.package.package_version,
            "requester_identity": "mission-control-workspace:test",
            "requester_system": "mission-control",
            "correlation_id": uuid.uuid4(),
            "created_at": datetime.now(UTC),
        }
        with pytest.raises(DBAPIError, match="valid_package_binding"), session.begin_nested():
            session.execute(
                insert(PackageRetrievalEvent).values(
                    **invalid_common,
                    package_version_id=None,
                    result="RETRIEVED",
                    digest=None,
                )
            )
        with pytest.raises(DBAPIError, match="valid_package_binding"), session.begin_nested():
            session.execute(
                insert(PackageRetrievalEvent).values(
                    **invalid_common,
                    package_version_id=graph.package.id,
                    result="NOT_FOUND",
                    digest=None,
                )
            )

        session.execute(
            insert(PackageRetrievalEvent).values(
                **invalid_common,
                package_version_id=None,
                result="NOT_FOUND",
                digest=None,
            )
        )
        session.flush()
        event_id = session.scalar(
            select(PackageRetrievalEvent.id).where(
                PackageRetrievalEvent.correlation_id == invalid_common["correlation_id"]
            )
        )
        assert event_id is not None
        with pytest.raises(DBAPIError, match="permission denied"), session.begin_nested():
            session.execute(
                text("UPDATE package_retrieval_events SET result = 'RETRIEVED' WHERE id = :id"),
                {"id": event_id},
            )

        audit_id = session.scalar(
            select(AuditEvent.id)
            .where(AuditEvent.engagement_id == engagement.id)
            .order_by(AuditEvent.created_at)
            .limit(1)
        )
        assert audit_id is not None
        with pytest.raises(DBAPIError, match="permission denied"), session.begin_nested():
            session.execute(
                text("UPDATE audit_events SET detail = '{}'::jsonb WHERE id = :id"),
                {"id": audit_id},
            )


@pytest.mark.integration
@pytest.mark.isolation
def test_engagement_delete_cascades_through_exact_phase2_graph(
    test_operator: OperatorFixture,
) -> None:
    with operator_session(test_operator.id) as session:
        operator = session.get_one(Operator, test_operator.id)
        engagement = create_engagement(
            session,
            operator=operator,
            name=f"Factory cascade {uuid.uuid4()}",
            primary_outcome="Prove Phase 2 foreign keys do not block engagement deletion.",
        )
        engagement_id = engagement.id
        graph = _seed_phase2_graph(session, engagement_id=engagement_id, operator_id=operator.id)
        graph_ids = tuple(row.id for row in graph)

    owner_engine = create_engine(get_settings().migration_database_url)
    try:
        with owner_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM engagements WHERE id = :engagement_id"),
                {"engagement_id": engagement_id},
            )
            counts = (
                connection.scalar(
                    select(func.count())
                    .select_from(CustomerFactoryModelVersion)
                    .where(CustomerFactoryModelVersion.id == graph_ids[0])
                ),
                connection.scalar(
                    select(func.count())
                    .select_from(FactoryOpportunity)
                    .where(FactoryOpportunity.id == graph_ids[1])
                ),
                connection.scalar(
                    select(func.count())
                    .select_from(FDLCReadinessAssessment)
                    .where(FDLCReadinessAssessment.id == graph_ids[2])
                ),
                connection.scalar(
                    select(func.count())
                    .select_from(FactoryDeploymentPackageVersion)
                    .where(FactoryDeploymentPackageVersion.id == graph_ids[3])
                ),
            )
    finally:
        owner_engine.dispose()
    assert counts == (0, 0, 0, 0)
