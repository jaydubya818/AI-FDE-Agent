from __future__ import annotations

import io

import pytest
from docx import Document
from PIL import Image

from ai_fde.modules.evidence.parser import (
    EvidenceParseError,
    UnsupportedEvidenceTypeError,
    parse_evidence,
    parse_text_evidence,
)


def test_text_parser_retains_exact_source_offsets() -> None:
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
        assert segment.parser_name == "utf8-paragraph-parser"


def test_csv_parser_produces_addressable_rows() -> None:
    segments = parse_evidence(
        b"Process,Owner,System\nInvoice approval,CFO,NetSuite\n",
        "text/csv",
        "workflow.csv",
    )

    assert [segment.content for segment in segments] == [
        "Process | Owner | System",
        "Invoice approval | CFO | NetSuite",
    ]
    assert segments[1].locator == {"kind": "csv_row", "row": 2}


def test_email_parser_preserves_headers_and_plain_text_body() -> None:
    source = (
        b"From: controller@example.test\r\n"
        b"To: ap@example.test\r\n"
        b"Subject: Approval exception\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Strategic vendors may be approved by the Controller.\r\n"
    )

    segments = parse_evidence(source, "message/rfc822", "approval.eml")

    assert segments[0].locator == {"kind": "email_headers"}
    assert "Subject: Approval exception" in segments[0].content
    assert segments[1].locator == {
        "kind": "email_body",
        "part": 0,
        "media_type": "text/plain",
    }
    assert "Strategic vendors" in segments[1].content


def test_docx_parser_preserves_paragraph_and_table_row_locators() -> None:
    document = Document()
    document.add_paragraph("Invoices over $50,000 require CFO approval.")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "System"
    table.cell(0, 1).text = "NetSuite"
    buffer = io.BytesIO()
    document.save(buffer)

    segments = parse_evidence(
        buffer.getvalue(),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "policy.docx",
    )

    assert segments[0].locator == {"kind": "docx_paragraph", "paragraph": 1}
    assert segments[1].locator == {"kind": "docx_table_row", "table": 1, "row": 1}
    assert segments[1].content == "System | NetSuite"


def test_image_parser_validates_content_and_anchors_the_whole_image() -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (24, 12), color="white").save(buffer, format="PNG")

    [segment] = parse_evidence(buffer.getvalue(), "image/png", "diagram.png")

    assert segment.modality == "image"
    assert segment.locator == {"kind": "whole_image", "width": 24, "height": 12}
    assert "diagram.png" in segment.content


def test_parser_rejects_type_mismatch_malformed_content_and_non_utf8_text() -> None:
    with pytest.raises(UnsupportedEvidenceTypeError, match="does not match"):
        parse_evidence(b"not a pdf", "text/plain", "policy.pdf")

    with pytest.raises(EvidenceParseError, match="PDF evidence is malformed"):
        parse_evidence(b"%PDF malformed", "application/pdf", "policy.pdf")

    with pytest.raises(UnsupportedEvidenceTypeError, match="valid UTF-8"):
        parse_text_evidence(b"\xff\xfe", "text/plain", "invalid.txt")

    with pytest.raises(UnsupportedEvidenceTypeError, match="Supported evidence types"):
        parse_evidence(b"payload", "application/zip", "archive.zip")
