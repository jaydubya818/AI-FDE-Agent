"""Characterization tests for the pure economics arithmetic.

Extends docs/NIGHTLY-BACKLOG.md's 2026-09-01 coverage-gap entry:
`_calculate_outputs` and `_scenario_values` in
`ai_fde.modules.economics.service` take no Session and touch no
database, but the only existing test that exercises them
(`tests/acceptance/test_workflow_economics_specification.py`) is
`@pytest.mark.integration` and therefore skips without a Docker
daemon. These two functions do not need separating to be tested in
isolation -- they already are pure -- so this pins their behaviour
directly, no Docker required.
"""

from __future__ import annotations

from decimal import Decimal

from ai_fde.modules.economics.service import _calculate_outputs, _scenario_values

BASE_VALUES: dict[str, Decimal] = {
    "annual_volume": Decimal("1000"),
    "current_minutes_per_item": Decimal("30"),
    "target_minutes_per_item": Decimal("10"),
    "loaded_hourly_cost": Decimal("60"),
    "implementation_cost": Decimal("12000"),
    "annual_operating_cost": Decimal("5000"),
}


def test_calculate_outputs_matches_the_documented_formula() -> None:
    outputs = _calculate_outputs(dict(BASE_VALUES))
    # hours_saved = 1000 * (30 - 10) / 60 = 333.333...
    assert outputs["annual_hours_saved"]["value"] == "333.33"
    # gross_labor_value = 333.333... * 60 = 20000.00
    assert outputs["annual_gross_labor_value"]["value"] == "20000.00"
    # annual_net_benefit = 20000.00 - 5000 = 15000.00
    assert outputs["annual_net_benefit"]["value"] == "15000.00"
    # payback_months = 12000 / (15000 / 12) = 9.60
    assert outputs["payback_months"]["value"] == "9.60"


def test_payback_months_is_none_when_net_benefit_is_not_positive() -> None:
    values = dict(BASE_VALUES)
    values["annual_operating_cost"] = Decimal("25000")  # exceeds gross labor value
    outputs = _calculate_outputs(values)
    net_benefit_value = outputs["annual_net_benefit"]["value"]
    assert net_benefit_value is not None
    assert Decimal(net_benefit_value) < 0
    assert outputs["payback_months"]["value"] is None


def test_payback_months_is_none_at_exactly_zero_net_benefit() -> None:
    values = dict(BASE_VALUES)
    values["annual_operating_cost"] = Decimal("20000")  # exactly equals gross labor value
    outputs = _calculate_outputs(values)
    assert outputs["annual_net_benefit"]["value"] == "0.00"
    # _calculate_outputs guards on `annual_net_benefit > 0`, so an exact
    # break-even (0) also reports payback_months as None, not 0 or infinite.
    assert outputs["payback_months"]["value"] is None


def test_scenarios_are_monotonic_low_base_high_on_net_benefit() -> None:
    scenarios = _scenario_values(dict(BASE_VALUES))
    assert set(scenarios) == {"low", "base", "high"}

    def net_benefit(name: str) -> Decimal:
        _, adjusted = scenarios[name]
        value = _calculate_outputs(adjusted)["annual_net_benefit"]["value"]
        assert value is not None
        return Decimal(value)

    low_net, base_net, high_net = net_benefit("low"), net_benefit("base"), net_benefit("high")
    assert low_net <= base_net <= high_net
    # calculate_economic_case() asserts exactly this ordering at runtime and
    # raises RuntimeError if it is ever violated -- this pins the assumption
    # that guard depends on, using the real scenario generator.


def test_high_scenario_time_savings_never_goes_negative() -> None:
    # base_savings = 10 - 1 = 9; high widens savings by 120% of that (10.8),
    # which exceeds current_minutes_per_item (10) and would go negative
    # without the max(Decimal(0), ...) floor in _scenario_values.
    values = dict(BASE_VALUES)
    values["current_minutes_per_item"] = Decimal("10")
    values["target_minutes_per_item"] = Decimal("1")  # base_savings = 9
    _, high = _scenario_values(values)["high"]
    assert high["target_minutes_per_item"] == Decimal("0")
