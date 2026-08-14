from __future__ import annotations

from ai_fde.modules.knowledge.extractor import DeterministicAcmeExtractor


def test_extractor_returns_structured_claims_with_exact_quotes() -> None:
    source = (
        "Process: Invoice approval\n\n"
        "Invoices over $50,000 require CFO approval.\n\n"
        "Accounts Payable uses NetSuite to record invoices."
    )

    result = DeterministicAcmeExtractor().extract(source)
    claims = result.claims

    assert {claim.predicate for claim in claims} == {
        "IDENTIFIED_AS",
        "REQUIRES_APPROVAL",
        "USES",
    }
    for claim in claims:
        assert source[claim.start_offset : claim.end_offset].strip() == claim.quote
        assert claim.normalized_payload["subject"]["type"]
        assert claim.confidence > 0


def test_extractor_preserves_exception_semantics() -> None:
    source = (
        "However, Strategic vendors with an approved annual contract may be approved "
        "by the Controller when the CFO is unavailable."
    )

    [claim] = DeterministicAcmeExtractor().extract(source).claims

    assert claim.claim_kind == "exception"
    assert claim.predicate == "REQUIRES_APPROVAL"
    assert claim.object_text == "Controller"
    assert claim.normalized_payload["is_exception"] is True
    assert claim.quote == source[: claim.end_offset]
