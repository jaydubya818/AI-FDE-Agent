from __future__ import annotations

from collections.abc import Mapping

from ai_fde.modules.factory_engineer.schemas import (
    FactoryOpportunityScore,
    OpportunityFactors,
)

RUBRIC_VERSION = "factory-opportunity-rubric/v1"

# Each component is a transparent weighted mean of 0-5 factor ratings. Inverse
# factors turn a lower risk/complexity rating into a higher readiness/autonomy rating.
RUBRIC: dict[str, dict[str, int]] = {
    "value": {
        "workflow_frequency": 25,
        "human_effort": 25,
        "cycle_time": 20,
        "expected_economic_value": 30,
    },
    "verifiability": {
        "repeatability": 25,
        "standardization": 20,
        "evidence_quality": 25,
        "deterministic_verifiability": 30,
    },
    "readiness": {
        "system_accessibility": 30,
        "evidence_quality": 25,
        "standardization": 20,
        "inverse_implementation_complexity": 25,
    },
    "risk": {
        "blast_radius": 40,
        "data_sensitivity": 35,
        "implementation_complexity": 25,
    },
    "autonomy": {
        "autonomy_potential": 35,
        "repeatability": 20,
        "deterministic_verifiability": 25,
        "inverse_blast_radius": 20,
    },
    "priority": {
        "value": 30,
        "verifiability": 25,
        "readiness": 20,
        "autonomy": 15,
        "inverse_risk": 10,
    },
}


def score_factory_opportunity(
    factors: OpportunityFactors, *, blockers: list[str] | None = None
) -> FactoryOpportunityScore:
    values = factors.model_dump()
    expanded = {
        **values,
        "inverse_implementation_complexity": 5 - values["implementation_complexity"],
        "inverse_blast_radius": 5 - values["blast_radius"],
    }
    value_score = _factor_score(expanded, RUBRIC["value"])
    verifiability_score = _factor_score(expanded, RUBRIC["verifiability"])
    readiness_score = _factor_score(expanded, RUBRIC["readiness"])
    risk_score = _factor_score(expanded, RUBRIC["risk"])
    autonomy_score = _factor_score(expanded, RUBRIC["autonomy"])
    priority_values = {
        "value": value_score,
        "verifiability": verifiability_score,
        "readiness": readiness_score,
        "autonomy": autonomy_score,
        "inverse_risk": 100 - risk_score,
    }
    priority_score = _percentage_score(priority_values, RUBRIC["priority"])
    active_blockers = blockers or []
    if active_blockers:
        recommendation = "HOLD — resolve explicit blockers before selection."
    elif priority_score >= 75 and risk_score <= 60:
        recommendation = "RECOMMEND — strong value, verification, and readiness fit."
    elif priority_score >= 60:
        recommendation = "ASSESS — viable candidate with material tradeoffs to resolve."
    else:
        recommendation = "DEFER — evidence does not yet support near-term selection."

    rationale = [
        f"Value {value_score}/100 from frequency, effort, cycle time, and expected economics.",
        f"Verifiability {verifiability_score}/100 from repeatability, standards, evidence, "
        "and deterministic checks.",
        f"Readiness {readiness_score}/100 after system access and implementation complexity.",
        f"Risk {risk_score}/100 from blast radius, data sensitivity, and implementation "
        "complexity.",
        f"Priority {priority_score}/100 using the published {RUBRIC_VERSION} component weights.",
    ]
    return FactoryOpportunityScore(
        value_score=value_score,
        verifiability_score=verifiability_score,
        readiness_score=readiness_score,
        risk_score=risk_score,
        autonomy_potential=autonomy_score,
        priority_score=priority_score,
        rationale=rationale,
        recommendation=recommendation,
        rubric_version=RUBRIC_VERSION,
        rubric=RUBRIC,
    )


def _factor_score(values: Mapping[str, int], weights: Mapping[str, int]) -> int:
    weighted = sum(values[key] * weight for key, weight in weights.items())
    denominator = 5 * sum(weights.values())
    return (weighted * 100 + denominator // 2) // denominator


def _percentage_score(values: Mapping[str, int], weights: Mapping[str, int]) -> int:
    weighted = sum(values[key] * weight for key, weight in weights.items())
    denominator = sum(weights.values())
    return (weighted + denominator // 2) // denominator
