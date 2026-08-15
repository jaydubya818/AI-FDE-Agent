from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from ai_fde.adapters.storage import S3EvidenceStore
from ai_fde.config import get_settings
from ai_fde.db import ensure_local_operator, operator_session
from ai_fde.models import Engagement, Operator
from ai_fde.modules.engagements.service import create_engagement
from ai_fde.modules.evidence.service import create_evidence_asset


@dataclass(frozen=True)
class SyntheticProfile:
    fixture_directory: str
    name: str
    slug: str
    workflow_name: str
    primary_outcome: str


INTERNAL_ALPHA_PROFILES = (
    SyntheticProfile(
        fixture_directory="acme",
        name="Acme Manufacturing",
        slug="acme-manufacturing",
        workflow_name="Accounts Payable",
        primary_outcome=(
            "Reduce invoice-processing cycle time while preserving financial approval controls."
        ),
    ),
    SyntheticProfile(
        fixture_directory="northstar",
        name="Northstar Health",
        slug="northstar-health",
        workflow_name="Employee Access Onboarding",
        primary_outcome=(
            "Shorten new-hire access lead time while preserving privileged-access approval and "
            "the People Operations to IT handoff."
        ),
    ),
    SyntheticProfile(
        fixture_directory="beacon",
        name="Beacon Logistics",
        slug="beacon-logistics",
        workflow_name="Customer Support Triage",
        primary_outcome=(
            "Reduce support-routing time while preserving Zendesk as the system of record and "
            "the Service Response Policy."
        ),
    ),
)


def main() -> None:
    settings = get_settings()
    ensure_local_operator(settings)
    store = S3EvidenceStore(settings)
    store.ensure_bucket()
    fixtures_root = Path(__file__).resolve().parents[2] / "fixtures"

    with operator_session(settings.operator_id) as session:
        operator = session.get(Operator, settings.operator_id)
        if operator is None:
            raise RuntimeError("Configured operator was not initialized.")
        for profile in INTERNAL_ALPHA_PROFILES:
            engagement = session.scalar(select(Engagement).where(Engagement.slug == profile.slug))
            if engagement is None:
                engagement = create_engagement(
                    session,
                    operator=operator,
                    name=profile.name,
                    workflow_name=profile.workflow_name,
                    primary_outcome=profile.primary_outcome,
                    data_classification="synthetic",
                )
            fixture_root = fixtures_root / profile.fixture_directory / "evidence"
            for path in sorted(fixture_root.glob("*.md")):
                create_evidence_asset(
                    session,
                    store,
                    engagement_id=engagement.id,
                    operator=operator,
                    file_name=path.name,
                    content_type="text/markdown",
                    content=path.read_bytes(),
                    source_type="fixture",
                )
            print(f"Seeded {engagement.name}: {engagement.id}")


if __name__ == "__main__":
    main()
