from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text

from ai_fde.adapters.storage import InMemoryEvidenceStore
from ai_fde.db import SessionFactory, apply_operator_context, operator_session
from ai_fde.models import Engagement, EvidenceAsset, Operator, WorkflowVersion
from ai_fde.modules.engagements.service import create_engagement
from ai_fde.modules.evidence.service import create_evidence_asset
from tests.conftest import OperatorFixture


def _create_operator() -> OperatorFixture:
    token = uuid.uuid4()
    operator = OperatorFixture(token, f"isolation-{token}", "Isolation FDE")
    session = SessionFactory()
    try:
        with session.begin():
            apply_operator_context(session, operator.id)
            session.add(
                Operator(
                    id=operator.id,
                    external_subject=operator.subject,
                    display_name=operator.display_name,
                )
            )
    finally:
        session.close()
    return operator


@pytest.mark.integration
@pytest.mark.isolation
def test_runtime_role_cannot_bypass_row_level_security(
    postgres_available: None,
) -> None:
    operator_a = _create_operator()
    operator_b = _create_operator()
    store = InMemoryEvidenceStore()

    with operator_session(operator_a.id) as session:
        operator = session.get_one(Operator, operator_a.id)
        engagement = create_engagement(
            session,
            operator=operator,
            name="Tenant A Manufacturing",
            primary_outcome="Prove tenant A evidence cannot be observed by tenant B.",
        )
        engagement_id = engagement.id
        evidence = create_evidence_asset(
            session,
            store,
            engagement_id=engagement.id,
            operator=operator,
            file_name="tenant-a-policy.md",
            content_type="text/markdown",
            content=b"Invoices over $50,000 require CFO approval.",
        )
        evidence_id = evidence.id
        workflow = WorkflowVersion(
            engagement_id=engagement.id,
            workflow_kind="current",
            version_number=1,
            name="Tenant A workflow",
            objective="Prove new lifecycle tables remain isolated.",
            source_assertion_ids=[],
            generated_by="operator",
            created_by_id=operator.id,
        )
        session.add(workflow)
        session.flush()
        workflow_id = workflow.id

    with operator_session(operator_b.id) as session:
        assert session.get(Engagement, engagement_id) is None
        assert session.get(EvidenceAsset, evidence_id) is None
        assert session.get(WorkflowVersion, workflow_id) is None
        assert list(session.scalars(select(EvidenceAsset))) == []
        assert list(session.scalars(select(WorkflowVersion))) == []

        runtime_role = session.execute(
            text("SELECT current_user, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        ).one()
        assert runtime_role.current_user == "ai_fde_app"
        assert runtime_role.rolbypassrls is False


@pytest.mark.integration
@pytest.mark.isolation
def test_each_operator_only_lists_their_own_engagements(
    postgres_available: None,
) -> None:
    operator_a = _create_operator()
    operator_b = _create_operator()

    with operator_session(operator_a.id) as session:
        operator = session.get_one(Operator, operator_a.id)
        engagement_a = create_engagement(
            session,
            operator=operator,
            name="Shared Name",
            primary_outcome="Keep the first engagement isolated from the second operator.",
        )
        engagement_a_id = engagement_a.id

    with operator_session(operator_b.id) as session:
        operator = session.get_one(Operator, operator_b.id)
        engagement_b = create_engagement(
            session,
            operator=operator,
            name="Shared Name",
            primary_outcome="Allow tenant-local slugs without leaking global engagement names.",
        )
        engagement_b_id = engagement_b.id

    with operator_session(operator_a.id) as session:
        visible_ids = set(session.scalars(select(Engagement.id)))
        assert engagement_a_id in visible_ids
        assert engagement_b_id not in visible_ids

    with operator_session(operator_b.id) as session:
        visible_ids = set(session.scalars(select(Engagement.id)))
        assert engagement_b_id in visible_ids
        assert engagement_a_id not in visible_ids
