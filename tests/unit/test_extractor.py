from __future__ import annotations

from ai_fde.modules.knowledge.extractor import DeterministicFixtureExtractor


def test_extractor_returns_structured_claims_with_exact_quotes() -> None:
    source = (
        "Process: Invoice approval\n\n"
        "Invoices over $50,000 require CFO approval.\n\n"
        "Accounts Payable uses NetSuite to record invoices."
    )

    result = DeterministicFixtureExtractor().extract(source)
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

    [claim] = DeterministicFixtureExtractor().extract(source).claims

    assert claim.claim_kind == "exception"
    assert claim.predicate == "REQUIRES_APPROVAL"
    assert claim.object_text == "Controller"
    assert claim.normalized_payload["is_exception"] is True
    assert claim.quote == source[: claim.end_offset]


def test_extractor_supports_internal_alpha_workflow_relationships() -> None:
    source = (
        "Identity record creation precedes Account provisioning.\n\n"
        "People Operations hands off to IT Service Desk.\n\n"
        "Customer Support Triage is governed by Service Response Policy.\n\n"
        "Access request approval: Requests for privileged systems require Security approval."
    )

    claims = DeterministicFixtureExtractor().extract(source).claims

    assert {claim.predicate for claim in claims} == {
        "PRECEDES",
        "HANDS_OFF_TO",
        "GOVERNED_BY",
        "REQUIRES_APPROVAL",
    }
    assert next(claim for claim in claims if claim.predicate == "PRECEDES").normalized_payload == {
        "subject": {"type": "process", "name": "Identity record creation"},
        "object": {"type": "process", "name": "Account provisioning"},
    }
    approval = next(claim for claim in claims if claim.predicate == "REQUIRES_APPROVAL")
    assert approval.subject_text == "Access request approval"
    assert approval.object_text == "Security"
    assert approval.normalized_payload["condition"] == "Requests for privileged systems"
    for claim in claims:
        assert source[claim.start_offset : claim.end_offset].strip() == claim.quote
