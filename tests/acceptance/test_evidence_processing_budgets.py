from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pytest

from ai_fde.adapters.storage import InMemoryEvidenceStore
from ai_fde.db import operator_session
from ai_fde.models import Operator
from ai_fde.modules.engagements.service import create_engagement
from ai_fde.modules.evidence.service import create_evidence_asset
from ai_fde.modules.knowledge.extractor import ExtractionResult
from ai_fde.modules.knowledge.jobs import (
    ExtractionBudgetExceededError,
    ExtractionJobBudget,
    lease_next_job,
    process_job,
)
from ai_fde.worker import public_job_failure
from tests.conftest import OperatorFixture


@dataclass
class CountingExtractor:
    name: str = "counting-test-extractor"
    version: str = "1"
    schema_version: str = "claim-v1"
    prompt_version: str = "test-prompt"
    model_id: str | None = "test-model"
    max_output_tokens: int = 512
    calls: int = 0

    def extract(
        self,
        text: str,
        *,
        image_bytes: bytes | None = None,
        image_format: Literal["png", "jpeg"] | None = None,
        max_output_tokens: int | None = None,
    ) -> ExtractionResult:
        del text, image_bytes, image_format, max_output_tokens
        self.calls += 1
        return ExtractionResult(
            claims=[],
            provider_name=self.name,
            model_id=self.model_id,
            prompt_version=self.prompt_version,
            schema_version=self.schema_version,
            input_tokens=10,
            output_tokens=5,
        )


@pytest.mark.integration
@pytest.mark.parametrize(
    ("budget", "message"),
    [
        (ExtractionJobBudget(max_segments=1), "segment"),
        (ExtractionJobBudget(max_segments=10, max_provider_calls=1), "provider-call"),
        (
            ExtractionJobBudget(
                max_segments=10,
                max_provider_calls=10,
                max_provider_tokens=100,
            ),
            "provider-token",
        ),
    ],
)
def test_extraction_budgets_stop_before_provider_calls(
    test_operator: OperatorFixture,
    budget: ExtractionJobBudget,
    message: str,
) -> None:
    store = InMemoryEvidenceStore()
    extractor = CountingExtractor()
    with operator_session(test_operator.id) as session:
        operator = session.get_one(Operator, test_operator.id)
        engagement = create_engagement(
            session,
            operator=operator,
            name=f"{message.title()} Budget Manufacturing",
            primary_outcome="Bound provider work before customer evidence is processed.",
        )
        create_evidence_asset(
            session,
            store,
            engagement_id=engagement.id,
            operator=operator,
            file_name="budget.md",
            content_type="text/markdown",
            content=b"First segment.\n\nSecond segment.",
        )
        engagement_id = engagement.id

    with (
        pytest.raises(ExtractionBudgetExceededError, match=message),
        operator_session(test_operator.id) as session,
    ):
        job = lease_next_job(session, engagement_id, lease_seconds=30)
        assert job is not None
        process_job(session, store, job, extractor=extractor, budget=budget)

    assert extractor.calls == 0


def test_extraction_budget_failures_are_terminal_and_safe() -> None:
    failure = public_job_failure(ExtractionBudgetExceededError("raw content omitted"))

    assert failure.code == "extraction_budget_exceeded"
    assert failure.retryable is False
    assert "raw content" not in failure.message
