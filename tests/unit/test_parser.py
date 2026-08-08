from __future__ import annotations

import pytest

from ai_fde.modules.evidence.parser import (
    UnsupportedEvidenceTypeError,
    parse_text_evidence,
)


def test_parser_retains_exact_source_offsets() -> None:
    source = b"Title\n\nInvoices over $50,000 require CFO approval.\n\nLast paragraph.\n"

    segments = parse_text_evidence(source, "text/markdown", "policy.md")

    assert [segment.content for segment in segments] == [
        "Title",
        "Invoices over $50,000 require CFO approval.",
        "Last paragraph.",
    ]
    decoded = source.decode()
    for segment in segments:
        assert decoded[segment.start_offset : segment.end_offset] == segment.content
        assert segment.locator == {
            "kind": "text_offset",
            "start": segment.start_offset,
            "end": segment.end_offset,
        }


def test_parser_rejects_untrusted_unsupported_content() -> None:
    with pytest.raises(UnsupportedEvidenceTypeError, match="only UTF-8"):
        parse_text_evidence(b"%PDF", "application/pdf", "policy.pdf")

    with pytest.raises(UnsupportedEvidenceTypeError, match="valid UTF-8"):
        parse_text_evidence(b"\xff\xfe", "text/plain", "invalid.txt")
