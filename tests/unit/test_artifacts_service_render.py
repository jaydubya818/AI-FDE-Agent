"""Characterization tests for the pure rendering helpers in artifacts/service.py.

Extends docs/NIGHTLY-BACKLOG.md's 2026-09-01 coverage-gap entry
("Service-layer coverage is gated on Docker"), which named
`artifacts/service.py` as having "a larger pure surface
(`_artifact_title`, `_pins`, `_header`, and several `_render_*`
functions)" than the single-function passes already closed for
`economics/service.py` and `workflows/service.py`.

`_artifact_title`, `_pins`, `_header`, `_render_assertions`, and
`_render_steps` take no `Session` and touch no database -- they are
plain string/list builders over already-loaded model attributes.
`_render_prd`, `_render_architecture`, `_render_business_rules`,
`_render_integrations`, and `_render_approval_controls` are pure too,
and -- unlike `_render_evaluation_plan` and `_render_implementation_spec`
-- none of them read `EconomicCase.scenarios`/`.inputs`/`.outputs`, so
they only need the same minimal `EconomicCase` fixture `_pins`/`_header`
already require, not the elaborate nested scenario JSON. That made this
a case where "breadth of coverage per unit of fixture complexity" could
cover ten functions, not one, from one shared set of builders below.

`_render_evaluation_plan` and `_render_implementation_spec` are left
untested here: both index into `EconomicCase.scenarios["low"/"base"/"high"]`
and `.inputs`/`.outputs`, which need a disproportionately elaborate
fixture relative to the rest of this pass, matching the original entry's
"bigger lift" framing. They remain Docker-gated.

None of these ten functions are modified by this change; only tests
are added.
"""

from __future__ import annotations

import uuid

from ai_fde.models import EconomicCase, Engagement, WorkflowStep, WorkflowVersion
from ai_fde.modules.artifacts.service import (
    _artifact_title,
    _header,
    _pins,
    _render_approval_controls,
    _render_architecture,
    _render_assertions,
    _render_business_rules,
    _render_integrations,
    _render_prd,
    _render_steps,
)

CURRENT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
TARGET_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
ECONOMIC_CASE_ID = uuid.UUID("00000000-0000-0000-0000-000000000003")
ASSERTION_ID_1 = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
ASSERTION_ID_2 = uuid.UUID("00000000-0000-0000-0000-0000000000a2")
STEP_SOURCE_ASSERTION_ID = uuid.UUID("00000000-0000-0000-0000-0000000000b1")


def _engagement(**overrides: object) -> Engagement:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "name": "Acme Corp",
        "slug": "acme-corp",
        "workflow_name": "Invoice Approval",
        "primary_outcome": "Cut invoice approval cycle time.",
        "created_by_id": uuid.uuid4(),
    }
    defaults.update(overrides)
    return Engagement(**defaults)


def _workflow_version(kind: str, version_number: int, **overrides: object) -> WorkflowVersion:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "engagement_id": uuid.uuid4(),
        "workflow_kind": kind,
        "version_number": version_number,
        "name": f"{kind} workflow",
        "objective": "Do the thing.",
        "created_by_id": uuid.uuid4(),
    }
    defaults.update(overrides)
    return WorkflowVersion(**defaults)


def _economic_case(**overrides: object) -> EconomicCase:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "engagement_id": uuid.uuid4(),
        "version_number": 1,
        "source_target_workflow_id": uuid.uuid4(),
        "formula_version": "2026.1",
        "inputs": {},
        "outputs": {},
        "created_by_id": uuid.uuid4(),
    }
    defaults.update(overrides)
    return EconomicCase(**defaults)


def _step(**overrides: object) -> WorkflowStep:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "engagement_id": uuid.uuid4(),
        "workflow_version_id": uuid.uuid4(),
        "step_key": "step",
        "position": 1,
        "name": "Step",
        "description": "A step.",
        "step_type": "human_task",
        "actor_label": None,
        "system_label": None,
        "allocation": "human",
        "rationale": "",
        "controls": [],
        "source_assertion_id": None,
    }
    defaults.update(overrides)
    return WorkflowStep(**defaults)


def _current() -> WorkflowVersion:
    return _workflow_version("current", 2, id=CURRENT_ID)


def _target() -> WorkflowVersion:
    return _workflow_version("target", 3, id=TARGET_ID)


def _economics() -> EconomicCase:
    return _economic_case(id=ECONOMIC_CASE_ID)


def _assertions() -> list[dict[str, object]]:
    return [
        {
            "id": ASSERTION_ID_1,
            "subject": "Finance",
            "predicate": "requires approval of",
            "object": "invoices over $5,000",
            "evidence": {
                "quote": "All invoices over five thousand require manager sign-off.",
                "file_name": "policy.pdf",
                "segment_id": "seg-1",
            },
        },
        {
            "id": ASSERTION_ID_2,
            "subject": "Billing Ledger",
            "predicate": "is the system of record",
            "object": None,
            "evidence": {
                "quote": "The ledger is authoritative.",
                "file_name": "notes.pdf",
                "segment_id": "seg-2",
            },
        },
    ]


def test_artifact_title_joins_engagement_name_workflow_name_and_label() -> None:
    engagement = _engagement(name="Acme Corp", workflow_name="Invoice Approval")
    assert _artifact_title(engagement, "prd") == "Acme Corp Invoice Approval Product Requirements"
    assert (
        _artifact_title(engagement, "implementation_spec")
        == "Acme Corp Invoice Approval Implementation Specification"
    )
    assert (
        _artifact_title(engagement, "approval_controls")
        == "Acme Corp Invoice Approval Approval and Control Matrix"
    )


def test_pins_lists_current_target_and_economic_case_identity() -> None:
    pins = _pins(_current(), _target(), _economics())
    assert pins == [
        "## Version pins",
        "",
        "- Current workflow: `00000000-0000-0000-0000-000000000001` (v2)",
        "- Target workflow: `00000000-0000-0000-0000-000000000002` (v3)",
        "- Economic case: `00000000-0000-0000-0000-000000000003` (v1)",
        "- Formula version: `2026.1`",
    ]


def test_header_prepends_title_and_trailing_blank_line_to_pins() -> None:
    header = _header("My Title", _current(), _target(), _economics())
    assert header[0] == "# My Title"
    assert header[1] == ""
    assert header[2:-1] == _pins(_current(), _target(), _economics())
    assert header[-1] == ""


def test_render_assertions_includes_object_only_when_present() -> None:
    lines = _render_assertions(_assertions())
    assert lines == [
        "- **Finance requires approval of invoices over $5,000**",
        "  - Evidence: “All invoices over five thousand require manager sign-off.”",
        "  - Source: `policy.pdf` / segment `seg-1`",
        "  - Assertion: `00000000-0000-0000-0000-0000000000a1`",
        "- **Billing Ledger is the system of record**",
        "  - Evidence: “The ledger is authoritative.”",
        "  - Source: `notes.pdf` / segment `seg-2`",
        "  - Assertion: `00000000-0000-0000-0000-0000000000a2`",
    ]


def test_render_steps_with_allocation_includes_rationale_and_controls() -> None:
    fully_specified = _step(
        position=1,
        name="Review invoice",
        description="Check amounts match PO.",
        actor_label="AP Clerk",
        system_label="Billing Ledger",
        allocation="software",
        rationale="Deterministic match.",
        controls=["Two-way match"],
        source_assertion_id=STEP_SOURCE_ASSERTION_ID,
    )
    minimal = _step(
        position=2,
        name="Approve invoice",
        description="Confirm authority.",
        allocation="human",
        rationale="Needs human sign-off.",
    )
    lines = _render_steps([fully_specified, minimal], include_allocation=True)
    assert lines == [
        "1. **Review invoice** — Check amounts match PO.",
        "   - Actor: AP Clerk",
        "   - System: Billing Ledger",
        "   - Allocation: **software**",
        "   - Rationale: Deterministic match.",
        "   - Controls: Two-way match",
        "   - Source assertion: `00000000-0000-0000-0000-0000000000b1`",
        "2. **Approve invoice** — Confirm authority.",
        "   - Allocation: **human**",
        "   - Rationale: Needs human sign-off.",
        "   - Controls: ",
    ]


def test_render_steps_without_allocation_omits_allocation_fields() -> None:
    step = _step(
        position=1,
        name="Review invoice",
        description="Check amounts match PO.",
        actor_label="AP Clerk",
        system_label="Billing Ledger",
        allocation="software",
        rationale="Deterministic match.",
        controls=["Two-way match"],
        source_assertion_id=STEP_SOURCE_ASSERTION_ID,
    )
    lines = _render_steps([step], include_allocation=False)
    assert lines == [
        "1. **Review invoice** — Check amounts match PO.",
        "   - Actor: AP Clerk",
        "   - System: Billing Ledger",
        "   - Source assertion: `00000000-0000-0000-0000-0000000000b1`",
    ]


def test_render_steps_omits_optional_lines_when_fields_are_absent() -> None:
    step = _step(position=2, name="Approve invoice", description="Confirm authority.")
    lines = _render_steps([step], include_allocation=False)
    assert lines == ["2. **Approve invoice** — Confirm authority."]


def test_render_prd_lists_target_steps_as_required_capabilities_and_omits_current_steps() -> None:
    engagement = _engagement(name="Acme Corp", workflow_name="Invoice Approval")
    target_steps = [
        _step(position=1, name="Review invoice", description="Check amounts match PO."),
        _step(position=2, name="Approve invoice", description="Confirm authority."),
    ]
    current_steps = [_step(position=1, name="Manual review", description="Clerk checks by hand.")]
    content = _render_prd(
        engagement=engagement,
        assertions=_assertions(),
        current=_current(),
        current_steps=current_steps,
        target=_target(),
        target_steps=target_steps,
        economics=_economics(),
    )
    assert content.startswith("# Acme Corp Invoice Approval Product Requirements\n")
    assert "Cut invoice approval cycle time." in content
    assert "- Review invoice: Check amounts match PO." in content
    assert "- Approve invoice: Confirm authority." in content
    # Current-state steps are deliberately not rendered into the PRD.
    assert "Manual review" not in content
    assert "Clerk checks by hand." not in content


def test_render_architecture_renders_static_runtime_data_flow_and_failure_sections() -> None:
    engagement = _engagement(name="Acme Corp", workflow_name="Invoice Approval")
    content = _render_architecture(
        engagement=engagement,
        assertions=_assertions(),
        current=_current(),
        current_steps=[],
        target=_target(),
        target_steps=[],
        economics=_economics(),
    )
    assert content == (
        "# Acme Corp Invoice Approval Architecture\n"
        "\n"
        "## Version pins\n"
        "\n"
        "- Current workflow: `00000000-0000-0000-0000-000000000001` (v2)\n"
        "- Target workflow: `00000000-0000-0000-0000-000000000002` (v3)\n"
        "- Economic case: `00000000-0000-0000-0000-000000000003` (v1)\n"
        "- Formula version: `2026.1`\n"
        "\n"
        "## Runtime boundaries\n"
        "\n"
        "- Web client authenticates human operators through OIDC authorization code + PKCE.\n"
        "- API enforces engagement membership and PostgreSQL row-level security.\n"
        "- Worker uses a separate service identity and explicit engagement memberships.\n"
        "- Evidence objects remain private and are addressed by immutable content hash.\n"
        "- Extraction uses a provider-neutral contract; production is configured for Bedrock.\n"
        "\n"
        "## Data flow\n"
        "\n"
        "1. Validate evidence type and bounds before durable storage.\n"
        "2. Parse content into source-addressable segments.\n"
        "3. Extract bounded structured claims from untrusted content.\n"
        "4. Require human verification before assertions affect workflows.\n"
        "5. Generate version-pinned workflows, scenarios, and this artifact packet.\n"
        "\n"
        "## Failure posture\n"
        "\n"
        "- Provider, schema, provenance, authorization, and isolation failures fail closed.\n"
        "- Production extraction never falls back to fixture rules.\n"
        "- Sanitized data remains disabled until the deployment validation gate is recorded.\n"
    )


def test_render_business_rules_renders_verified_assertions_between_fixed_sections() -> None:
    engagement = _engagement(name="Acme Corp", workflow_name="Invoice Approval")
    content = _render_business_rules(
        engagement=engagement,
        assertions=_assertions(),
        current=_current(),
        current_steps=[],
        target=_target(),
        target_steps=[],
        economics=_economics(),
    )
    assert content.startswith("# Acme Corp Invoice Approval Business Rules\n")
    assert "## Verified rules" in content
    assert "- **Finance requires approval of invoices over $5,000**" in content
    assert "- **Billing Ledger is the system of record**" in content
    assert "- Preserve assertion identifiers with each implemented rule." in content
    assert "- Stale downstream artifacts after any verified model change." in content


def test_render_integrations_lists_named_systems_sorted_and_deduplicated() -> None:
    engagement = _engagement(name="Acme Corp", workflow_name="Invoice Approval")
    target_steps = [
        _step(position=1, name="a", description="b", system_label="ERP"),
        _step(position=2, name="c", description="d", system_label="Billing Ledger"),
        _step(position=3, name="e", description="f", system_label="ERP"),
        _step(position=4, name="g", description="h", system_label=None),
    ]
    content = _render_integrations(
        engagement=engagement,
        assertions=_assertions(),
        current=_current(),
        current_steps=[],
        target=_target(),
        target_steps=target_steps,
        economics=_economics(),
    )
    named_systems_section = content.split("## Named systems\n\n", 1)[1].split("\n\n", 1)[0]
    assert named_systems_section == (
        "- **Billing Ledger** remains a system of record.\n"
        "- **ERP** remains a system of record."
    )


def test_render_integrations_falls_back_when_no_system_is_verified() -> None:
    engagement = _engagement(name="Acme Corp", workflow_name="Invoice Approval")
    target_steps = [_step(position=1, name="a", description="b", system_label=None)]
    content = _render_integrations(
        engagement=engagement,
        assertions=_assertions(),
        current=_current(),
        current_steps=[],
        target=_target(),
        target_steps=target_steps,
        economics=_economics(),
    )
    assert "- No external system has been verified for this workflow." in content
    assert "remains a system of record" not in content


def test_render_approval_controls_lists_control_matrix_with_fallbacks_for_missing_fields() -> None:
    engagement = _engagement(name="Acme Corp", workflow_name="Invoice Approval")
    fully_specified = _step(
        position=1,
        name="Review invoice",
        description="Check amounts match PO.",
        actor_label="AP Clerk",
        allocation="software",
        rationale="Deterministic match.",
        controls=["Two-way match"],
        source_assertion_id=STEP_SOURCE_ASSERTION_ID,
    )
    minimal = _step(
        position=2,
        name="Approve invoice",
        description="Confirm authority.",
        allocation="human",
        rationale="Needs human sign-off.",
    )
    content = _render_approval_controls(
        engagement=engagement,
        assertions=_assertions(),
        current=_current(),
        current_steps=[],
        target=_target(),
        target_steps=[fully_specified, minimal],
        economics=_economics(),
    )
    assert "### 1. Review invoice" in content
    assert "- Accountable actor: AP Clerk" in content
    assert "- Controls: Two-way match" in content
    assert "- Source assertion: `00000000-0000-0000-0000-0000000000b1`" in content
    assert "### 2. Approve invoice" in content
    assert "- Accountable actor: Unassigned; resolve before build" in content
    assert "- Controls: None; resolve before build" in content
    assert "- Source assertion: `none`" in content
    assert (
        "- AI may recommend but may not approve, execute code, or remediate autonomously "
        "in V1." in content
    )
