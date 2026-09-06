from __future__ import annotations

from dataclasses import dataclass

from ai_fde.modules.factory_engineer.schemas import OpportunityFactors


@dataclass(frozen=True)
class SyntheticOpportunityTemplate:
    fixture_profile: str
    opportunity_key: str
    name: str
    description: str
    factors: OpportunityFactors


SYNTHETIC_OPPORTUNITY_TEMPLATES = (
    SyntheticOpportunityTemplate(
        fixture_profile="acme",
        opportunity_key="dependency-modernization",
        name="Dependency modernization",
        description=(
            "Modernize the dependencies around the synthetic invoice-processing integration "
            "with bounded code scope and deterministic compatibility checks."
        ),
        factors=OpportunityFactors(
            workflow_frequency=4,
            human_effort=3,
            cycle_time=3,
            repeatability=5,
            standardization=5,
            evidence_quality=4,
            deterministic_verifiability=5,
            blast_radius=3,
            system_accessibility=4,
            data_sensitivity=2,
            implementation_complexity=3,
            expected_economic_value=4,
            autonomy_potential=4,
        ),
    ),
    SyntheticOpportunityTemplate(
        fixture_profile="beacon",
        opportunity_key="test-remediation",
        name="Test remediation",
        description=(
            "Repair deterministic routing regressions for the synthetic support-triage "
            "workflow while preserving Zendesk as the system of record."
        ),
        factors=OpportunityFactors(
            workflow_frequency=5,
            human_effort=4,
            cycle_time=4,
            repeatability=5,
            standardization=4,
            evidence_quality=4,
            deterministic_verifiability=5,
            blast_radius=2,
            system_accessibility=5,
            data_sensitivity=2,
            implementation_complexity=2,
            expected_economic_value=4,
            autonomy_potential=5,
        ),
    ),
    SyntheticOpportunityTemplate(
        fixture_profile="northstar",
        opportunity_key="security-remediation",
        name="Security remediation",
        description=(
            "Remediate bounded identity-policy findings for the synthetic employee-access "
            "workflow with independent validation and human approval."
        ),
        factors=OpportunityFactors(
            workflow_frequency=4,
            human_effort=4,
            cycle_time=4,
            repeatability=4,
            standardization=5,
            evidence_quality=5,
            deterministic_verifiability=4,
            blast_radius=5,
            system_accessibility=3,
            data_sensitivity=5,
            implementation_complexity=4,
            expected_economic_value=5,
            autonomy_potential=2,
        ),
    ),
)
