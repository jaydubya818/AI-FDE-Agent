from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ai_fde.models import EconomicCase, Engagement, Operator, WorkflowVersion
from ai_fde.modules.lifecycle import stale_after_economic_change
from ai_fde.modules.shared import publish_domain_event, record_audit

FORMULA_VERSION = "labor-capacity-sensitivity-v2"
REQUIRED_INPUTS = {
    "annual_volume": "items/year",
    "current_minutes_per_item": "minutes/item",
    "target_minutes_per_item": "minutes/item",
    "loaded_hourly_cost": "USD/hour",
    "implementation_cost": "USD",
    "annual_operating_cost": "USD/year",
}
VALID_CLASSIFICATIONS = {"measured", "calculated", "estimated", "synthetic", "simulated"}
MONEY_QUANTUM = Decimal("0.01")


class EconomicCaseNotFoundError(LookupError):
    pass


class EconomicStageGateError(ValueError):
    pass


def get_latest_economic_case(session: Session, engagement_id: UUID) -> EconomicCase | None:
    return session.scalar(
        select(EconomicCase)
        .where(EconomicCase.engagement_id == engagement_id)
        .order_by(EconomicCase.version_number.desc())
        .limit(1)
    )


def calculate_economic_case(
    session: Session,
    *,
    engagement_id: UUID,
    operator: Operator,
    values: dict[str, Decimal],
    classifications: dict[str, str],
    assumptions: list[str] | None = None,
) -> EconomicCase:
    target = session.scalar(
        select(WorkflowVersion)
        .where(
            WorkflowVersion.engagement_id == engagement_id,
            WorkflowVersion.workflow_kind == "target",
            WorkflowVersion.status == "approved",
        )
        .order_by(WorkflowVersion.version_number.desc())
        .limit(1)
    )
    if target is None:
        raise EconomicStageGateError(
            "Approve a target workflow before calculating the economic case."
        )
    missing = set(REQUIRED_INPUTS) - set(values)
    if missing:
        raise ValueError(f"Missing economic inputs: {', '.join(sorted(missing))}.")
    for key, value in values.items():
        if value < 0:
            raise ValueError(f"{key} cannot be negative.")
        classification = classifications.get(key)
        if classification not in VALID_CLASSIFICATIONS:
            raise ValueError(f"{key} requires a valid evidence classification.")
    if values["target_minutes_per_item"] > values["current_minutes_per_item"]:
        raise ValueError("target_minutes_per_item cannot exceed current_minutes_per_item.")

    scenario_values = _scenario_values(values)
    scenarios: dict[str, dict[str, Any]] = {
        scenario_name: {
            "label": scenario_name.title(),
            "description": description,
            "inputs": _render_inputs(
                adjusted_values,
                classifications,
                scenario_name=scenario_name,
            ),
            "outputs": _calculate_outputs(adjusted_values),
        }
        for scenario_name, (description, adjusted_values) in scenario_values.items()
    }
    inputs = _render_inputs(values, classifications, scenario_name="base")
    outputs = _calculate_outputs(values)

    low_net = Decimal(str(scenarios["low"]["outputs"]["annual_net_benefit"]["value"]))
    base_net = Decimal(str(outputs["annual_net_benefit"]["value"]))
    high_net = Decimal(str(scenarios["high"]["outputs"]["annual_net_benefit"]["value"]))
    if not low_net <= base_net <= high_net:
        raise RuntimeError("Economic sensitivity scenarios are not monotonic.")

    existing = session.scalar(
        select(EconomicCase)
        .where(
            EconomicCase.engagement_id == engagement_id,
            EconomicCase.source_target_workflow_id == target.id,
            EconomicCase.status == "draft",
        )
        .order_by(EconomicCase.version_number.desc())
        .limit(1)
        .with_for_update()
    )
    if existing is None:
        version = (
            session.scalar(
                select(func.max(EconomicCase.version_number)).where(
                    EconomicCase.engagement_id == engagement_id
                )
            )
            or 0
        ) + 1
        economic_case = EconomicCase(
            engagement_id=engagement_id,
            version_number=version,
            source_target_workflow_id=target.id,
            formula_version=FORMULA_VERSION,
            inputs=inputs,
            outputs=outputs,
            scenarios=scenarios,
            assumptions=_clean_assumptions(assumptions),
            created_by_id=operator.id,
        )
        session.add(economic_case)
        session.flush()
    else:
        economic_case = existing
        economic_case.formula_version = FORMULA_VERSION
        economic_case.inputs = inputs
        economic_case.outputs = outputs
        economic_case.scenarios = scenarios
        economic_case.assumptions = _clean_assumptions(assumptions)

    stale_after_economic_change(session, engagement_id)
    record_audit(
        session,
        engagement_id=engagement_id,
        actor_id=operator.id,
        action="economic_case.calculated",
        target_type="economic_case",
        target_id=economic_case.id,
        detail={
            "formula_version": FORMULA_VERSION,
            "version": economic_case.version_number,
            "scenarios": list(scenarios),
        },
    )
    publish_domain_event(
        session,
        engagement_id=engagement_id,
        event_type="economic_case.calculated",
        aggregate_type="economic_case",
        aggregate_id=economic_case.id,
        payload={"formula_version": FORMULA_VERSION, "scenarios": list(scenarios)},
    )
    return economic_case


def _calculate_outputs(values: dict[str, Decimal]) -> dict[str, dict[str, str | None]]:
    hours_saved = (
        values["annual_volume"]
        * (values["current_minutes_per_item"] - values["target_minutes_per_item"])
        / Decimal(60)
    )
    gross_labor_value = hours_saved * values["loaded_hourly_cost"]
    annual_net_benefit = gross_labor_value - values["annual_operating_cost"]
    payback_months = (
        values["implementation_cost"] / (annual_net_benefit / Decimal(12))
        if annual_net_benefit > 0
        else None
    )
    return {
        "annual_hours_saved": {
            "value": _decimal_string(hours_saved),
            "unit": "hours/year",
            "classification": "calculated",
            "formula": "annual_volume × (current_minutes_per_item − target_minutes_per_item) ÷ 60",
        },
        "annual_gross_labor_value": {
            "value": _money_string(gross_labor_value),
            "unit": "USD/year",
            "classification": "calculated",
            "formula": "annual_hours_saved × loaded_hourly_cost",
        },
        "annual_net_benefit": {
            "value": _money_string(annual_net_benefit),
            "unit": "USD/year",
            "classification": "calculated",
            "formula": "annual_gross_labor_value − annual_operating_cost",
        },
        "payback_months": {
            "value": _decimal_string(payback_months) if payback_months is not None else None,
            "unit": "months",
            "classification": "calculated",
            "formula": "implementation_cost ÷ (annual_net_benefit ÷ 12)",
        },
    }


def _scenario_values(
    values: dict[str, Decimal],
) -> dict[str, tuple[str, dict[str, Decimal]]]:
    current_minutes = values["current_minutes_per_item"]
    base_savings = current_minutes - values["target_minutes_per_item"]

    low = dict(values)
    low["annual_volume"] *= Decimal("0.90")
    low["target_minutes_per_item"] = current_minutes - base_savings * Decimal("0.80")
    low["loaded_hourly_cost"] *= Decimal("0.90")
    low["implementation_cost"] *= Decimal("1.10")
    low["annual_operating_cost"] *= Decimal("1.10")

    high = dict(values)
    high["annual_volume"] *= Decimal("1.10")
    high["target_minutes_per_item"] = max(
        Decimal(0), current_minutes - base_savings * Decimal("1.20")
    )
    high["loaded_hourly_cost"] *= Decimal("1.10")
    high["implementation_cost"] *= Decimal("0.90")
    high["annual_operating_cost"] *= Decimal("0.90")

    return {
        "low": (
            "Conservative volume, time savings, and labor value with 10% higher costs.",
            low,
        ),
        "base": ("Submitted values with no sensitivity adjustment.", dict(values)),
        "high": (
            "Favorable volume, time savings, and labor value with 10% lower costs.",
            high,
        ),
    }


def _render_inputs(
    values: dict[str, Decimal],
    classifications: dict[str, str],
    *,
    scenario_name: str,
) -> dict[str, dict[str, str | dict[str, str]]]:
    transforms = {
        "annual_volume": "90% / submitted / 110%",
        "current_minutes_per_item": "submitted in all scenarios",
        "target_minutes_per_item": "80% / 100% / 120% of submitted time savings",
        "loaded_hourly_cost": "90% / submitted / 110%",
        "implementation_cost": "110% / submitted / 90%",
        "annual_operating_cost": "110% / submitted / 90%",
    }
    return {
        key: {
            "value": _decimal_string(values[key]),
            "unit": unit,
            "classification": classifications[key] if scenario_name == "base" else "simulated",
            "provenance": {
                "source": "submitted_base_input",
                "source_classification": classifications[key],
                "transform": "none" if scenario_name == "base" else transforms[key],
            },
        }
        for key, unit in REQUIRED_INPUTS.items()
    }


def approve_economic_case(
    session: Session,
    *,
    engagement_id: UUID,
    economic_case_id: UUID,
    operator: Operator,
) -> EconomicCase:
    economic_case = session.scalar(
        select(EconomicCase)
        .where(
            EconomicCase.id == economic_case_id,
            EconomicCase.engagement_id == engagement_id,
        )
        .with_for_update()
    )
    if economic_case is None:
        raise EconomicCaseNotFoundError(str(economic_case_id))
    if economic_case.status != "draft":
        raise EconomicStageGateError("Only a current draft economic case can be approved.")
    target = session.get(WorkflowVersion, economic_case.source_target_workflow_id)
    if target is None or target.status != "approved":
        raise EconomicStageGateError("The target workflow dependency is no longer approved.")

    economic_case.status = "approved"
    economic_case.approved_by_id = operator.id
    economic_case.approved_at = datetime.now(UTC)
    engagement = session.get(Engagement, engagement_id)
    if engagement is not None:
        engagement.lifecycle_stage = "economic_case"
    record_audit(
        session,
        engagement_id=engagement_id,
        actor_id=operator.id,
        action="economic_case.approved",
        target_type="economic_case",
        target_id=economic_case.id,
        detail={"version": economic_case.version_number},
    )
    publish_domain_event(
        session,
        engagement_id=engagement_id,
        event_type="economic_case.approved",
        aggregate_type="economic_case",
        aggregate_id=economic_case.id,
        payload={"version": economic_case.version_number},
    )
    session.flush()
    return economic_case


def _clean_assumptions(items: list[str] | None) -> list[str]:
    return [item.strip() for item in (items or []) if item.strip()]


def _decimal_string(value: Decimal) -> str:
    return format(value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP), "f")


def _money_string(value: Decimal) -> str:
    return _decimal_string(value)
