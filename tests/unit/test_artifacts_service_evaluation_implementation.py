"""Characterization tests for the two pure render helpers left Docker-gated
by docs/NIGHTLY-BACKLOG.md's 2026-09-01 coverage-gap entry.

`_render_evaluation_plan` and `_render_implementation_spec` (in
`artifacts/service.py`) are pure -- no Session, no I/O -- but both index into
`EconomicCase.scenarios["low"/"base"/"high"]` and `.inputs`/`.outputs`, which
the 2026-11-19 pass on this same item left untested because building that
nested JSON by hand would have been "a disproportionately elaborate fixture
relative to the rest of this pass."

The fixture here is not hand-written: `economics/service.py` already exports
`_render_inputs`, `_calculate_outputs`, and `_scenario_values`, the exact pure
helpers `calculate_economic_case` itself uses to build that nested structure
from a plain `values`/`classifications` pair. Reusing them produces the real
shape (including the low/base/high sensitivity adjustments) without a second,
hand-maintained copy of that logic drifting out of sync with the original.

Neither render function is modified by this change; only tests are added.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from ai_fde.models import EconomicCase, Engagement, WorkflowStep, WorkflowVersion
from ai_fde.modules.artifacts.service import _render_evaluation_plan, _render_implementation_spec
from ai_fde.modules.economics.service import _calculate_outputs, _render_inputs, _scenario_values

CURRENT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
TARGET_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
ECONOMIC_CASE_ID = uuid.UUID("00000000-0000-0000-0000-000000000003")
ASSERTION_ID_1 = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
STEP_SOURCE_ASSERTION_ID = uuid.UUID("00000000-0000-0000-0000-0000000000b1")

VALUES: dict[str, Decimal] = {
    "annual_volume": Decimal("12000"),
    "current_minutes_per_item": Decimal("18"),
    "target_minutes_per_item": Decimal("6"),
    "loaded_hourly_cost": Decimal("42"),
    "implementation_cost": Decimal("65000"),
    "annual_operating_cost": Decimal("18000"),
}
CLASSIFICATIONS: dict[str, str] = {
    "annual_volume": "measured",
    "current_minutes_per_item": "measured",
    "target_minutes_per_item": "estimated",
    "loaded_hourly_cost": "measured",
    "implementation_cost": "estimated",
    "annual_operating_cost": "estimated",
}


def _engagement() -> Engagement:
    return Engagement(
        id=uuid.uuid4(),
        name="Acme Corp",
        slug="acme-corp",
        workflow_name="Invoice Approval",
        primary_outcome="Cut invoice approval cycle time.",
        created_by_id=uuid.uuid4(),
    )


def _workflow_version(kind: str, version_number: int, version_id: uuid.UUID) -> WorkflowVersion:
    return WorkflowVersion(
        id=version_id,
        engagement_id=uuid.uuid4(),
        workflow_kind=kind,
        version_number=version_number,
        name=f"{kind} workflow",
        objective="Do the thing.",
        created_by_id=uuid.uuid4(),
    )


def _step(**overrides: object) -> WorkflowStep:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "engagement_id": uuid.uuid4(),
        "workflow_version_id": uuid.uuid4(),
        "step_key": "step",
        "position": 1,
        "name": "Review invoice",
        "description": "Check amounts match PO.",
        "step_type": "human_task",
        "actor_label": "AP Clerk",
        "system_label": None,
        "allocation": "human",
        "rationale": "",
        "controls": [],
        "source_assertion_id": None,
    }
    defaults.update(overrides)
    return WorkflowStep(**defaults)


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
        }
    ]


def _economics_with_scenarios(**overrides: object) -> EconomicCase:
    """Build a real EconomicCase.inputs/.outputs/.scenarios via the same pure
    helpers calculate_economic_case uses, instead of a hand-written literal."""
    scenario_values = _scenario_values(VALUES)
    scenarios = {
        name: {
            "label": name.title(),
            "description": description,
            "inputs": _render_inputs(adjusted, CLASSIFICATIONS, scenario_name=name),
            "outputs": _calculate_outputs(adjusted),
        }
        for name, (description, adjusted) in scenario_values.items()
    }
    defaults: dict[str, object] = {
        "id": ECONOMIC_CASE_ID,
        "engagement_id": uuid.uuid4(),
        "version_number": 1,
        "source_target_workflow_id": uuid.uuid4(),
        "formula_version": "2026.1",
        "inputs": _render_inputs(VALUES, CLASSIFICATIONS, scenario_name="base"),
        "outputs": _calculate_outputs(VALUES),
        "scenarios": scenarios,
        "assumptions": [],
        "created_by_id": uuid.uuid4(),
    }
    defaults.update(overrides)
    return EconomicCase(**defaults)


def test_render_evaluation_plan_includes_sensitivity_table_and_fixed_sections() -> None:
    engagement = _engagement()
    current = _workflow_version("current", 2, CURRENT_ID)
    target = _workflow_version("target", 3, TARGET_ID)
    economics = _economics_with_scenarios()

    text = _render_evaluation_plan(
        engagement=engagement,
        assertions=_assertions(),
        current=current,
        current_steps=[_step()],
        target=target,
        target_steps=[_step()],
        economics=economics,
    )

    assert text.startswith("# Acme Corp Invoice Approval Evaluation Plan\n")
    assert (
        "| Scenario | Annual hours saved | Annual net benefit | Payback months |" in text
    )
    assert "| Low | 1728.00 | 45518.40 | 18.85 |" in text
    assert "| Base | 2400.00 | 82800.00 | 9.42 |" in text
    assert "| High | 3168.00 | 130161.60 | 5.39 |" in text
    assert "## Quality gates" in text
    assert (
        "- Extraction: exact-source provenance for every accepted claim; invalid schemas fail."
        in text
    )
    assert "## Go/no-go rule" in text
    assert "a deployment validation identifier is recorded." in text


def test_render_evaluation_plan_reports_not_achievable_when_no_payback() -> None:
    # annual_operating_cost exceeds gross labor value, so annual_net_benefit <= 0
    # and _calculate_outputs leaves payback_months as None for every scenario.
    loss_making_values = dict(VALUES)
    loss_making_values["annual_operating_cost"] = Decimal("500000")
    economics = _economics_with_scenarios(
        inputs=_render_inputs(loss_making_values, CLASSIFICATIONS, scenario_name="base"),
        outputs=_calculate_outputs(loss_making_values),
        scenarios={
            name: {
                "label": name.title(),
                "description": description,
                "inputs": _render_inputs(adjusted, CLASSIFICATIONS, scenario_name=name),
                "outputs": _calculate_outputs(adjusted),
            }
            for name, (description, adjusted) in _scenario_values(loss_making_values).items()
        },
    )

    text = _render_evaluation_plan(
        engagement=_engagement(),
        assertions=[],
        current=_workflow_version("current", 2, CURRENT_ID),
        current_steps=[],
        target=_workflow_version("target", 3, TARGET_ID),
        target_steps=[],
        economics=economics,
    )

    for scenario_name in ("Low", "Base", "High"):
        assert f"| {scenario_name} |" in text
    assert "not achievable |" in text
    assert text.count("not achievable |") == 3


def test_render_implementation_spec_includes_inputs_outputs_scenarios_and_fixed_sections() -> None:
    engagement = _engagement()
    current = _workflow_version("current", 2, CURRENT_ID)
    target = _workflow_version("target", 3, TARGET_ID)
    current_step = _step(system_label=None, allocation="human", rationale="", controls=[])
    target_step = _step(
        system_label="Billing Ledger",
        allocation="software",
        rationale="Deterministic match.",
        controls=["Two-way match"],
        source_assertion_id=STEP_SOURCE_ASSERTION_ID,
    )
    economics = _economics_with_scenarios()

    text = _render_implementation_spec(
        engagement=engagement,
        assertions=_assertions(),
        current=current,
        current_steps=[current_step],
        target=target,
        target_steps=[target_step],
        economics=economics,
    )

    assert text.startswith("# Acme Corp Invoice Approval Implementation Specification\n")
    assert "## Business outcome" in text
    assert "Cut invoice approval cycle time." in text
    assert "- **Finance requires approval of invoices over $5,000**" in text
    assert "## Approved current workflow" in text
    assert "## Approved target workflow and allocation" in text
    assert "   - System: Billing Ledger" in text
    assert "### Base inputs" in text
    assert "- `annual_volume`: 12000.00 items/year (**measured**)" in text
    assert "- `target_minutes_per_item`: 6.00 minutes/item (**estimated**)" in text
    assert "### Base calculated outputs" in text
    assert "- `annual_net_benefit`: 82800.00 USD/year (**calculated**)" in text
    assert "  - Formula: `annual_gross_labor_value − annual_operating_cost`" in text
    assert "- `payback_months`: 9.42 months (**calculated**)" in text
    assert "### Sensitivity scenarios" in text
    assert "- **Low**: 45518.40 USD/year net; payback: 18.85 months." in text
    assert "- **Base**: 82800.00 USD/year net; payback: 9.42 months." in text
    assert "- **High**: 130161.60 USD/year net; payback: 5.39 months." in text
    # No assumptions were supplied, so the optional section must not appear.
    assert "### Assumptions" not in text
    assert "## Implementation requirements" in text
    assert "## Acceptance criteria" in text
    assert (
        "- No production deployment, coding-agent execution, or autonomous remediation is "
        "implied by this specification."
        in text
    )


def test_render_implementation_spec_includes_assumptions_section_when_present() -> None:
    economics = _economics_with_scenarios(assumptions=["Volumes are stable year over year."])

    text = _render_implementation_spec(
        engagement=_engagement(),
        assertions=[],
        current=_workflow_version("current", 2, CURRENT_ID),
        current_steps=[],
        target=_workflow_version("target", 3, TARGET_ID),
        target_steps=[],
        economics=economics,
    )

    assert "### Assumptions" in text
    assert "- Volumes are stable year over year." in text


def test_render_implementation_spec_reports_not_achievable_outputs_and_scenarios() -> None:
    loss_making_values = dict(VALUES)
    loss_making_values["annual_operating_cost"] = Decimal("500000")
    economics = _economics_with_scenarios(
        inputs=_render_inputs(loss_making_values, CLASSIFICATIONS, scenario_name="base"),
        outputs=_calculate_outputs(loss_making_values),
        scenarios={
            name: {
                "label": name.title(),
                "description": description,
                "inputs": _render_inputs(adjusted, CLASSIFICATIONS, scenario_name=name),
                "outputs": _calculate_outputs(adjusted),
            }
            for name, (description, adjusted) in _scenario_values(loss_making_values).items()
        },
    )

    text = _render_implementation_spec(
        engagement=_engagement(),
        assertions=[],
        current=_workflow_version("current", 2, CURRENT_ID),
        current_steps=[],
        target=_workflow_version("target", 3, TARGET_ID),
        target_steps=[],
        economics=economics,
    )

    assert "- `payback_months`: not achievable months (**calculated**)" in text
    assert "payback: not achievable." in text
    assert text.count("payback: not achievable.") == 3
