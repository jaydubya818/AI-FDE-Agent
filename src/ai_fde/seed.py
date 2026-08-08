from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from ai_fde.adapters.storage import S3EvidenceStore
from ai_fde.config import get_settings
from ai_fde.db import ensure_local_operator, operator_session
from ai_fde.models import Engagement, Operator
from ai_fde.modules.engagements.service import create_engagement
from ai_fde.modules.evidence.service import create_evidence_asset


def main() -> None:
    settings = get_settings()
    ensure_local_operator(settings)
    store = S3EvidenceStore(settings)
    store.ensure_bucket()
    fixture_root = Path(__file__).resolve().parents[2] / "fixtures" / "acme" / "evidence"

    with operator_session(settings.operator_id) as session:
        operator = session.get(Operator, settings.operator_id)
        if operator is None:
            raise RuntimeError("Configured operator was not initialized.")
        engagement = session.scalar(
            select(Engagement).where(Engagement.slug == "acme-manufacturing")
        )
        if engagement is None:
            engagement = create_engagement(
                session,
                operator=operator,
                name="Acme Manufacturing",
                primary_outcome=(
                    "Reduce invoice-processing cycle time while preserving financial "
                    "approval controls."
                ),
                data_classification="synthetic",
            )
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
