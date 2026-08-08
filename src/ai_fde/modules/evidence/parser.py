from __future__ import annotations

import re
from dataclasses import dataclass


class UnsupportedEvidenceTypeError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedSegment:
    ordinal: int
    content: str
    start_offset: int
    end_offset: int
    locator: dict[str, int | str]


SUPPORTED_TEXT_TYPES = {
    "text/plain",
    "text/markdown",
    "application/octet-stream",
}


def parse_text_evidence(content: bytes, content_type: str, file_name: str) -> list[ParsedSegment]:
    suffix = file_name.lower().rsplit(".", maxsplit=1)[-1] if "." in file_name else ""
    if content_type not in SUPPORTED_TEXT_TYPES or suffix not in {"txt", "md"}:
        raise UnsupportedEvidenceTypeError(
            "This vertical slice currently processes only UTF-8 .txt and .md evidence."
        )

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise UnsupportedEvidenceTypeError("Evidence must be valid UTF-8 text.") from exc

    segments: list[ParsedSegment] = []
    for match in re.finditer(r"\S(?:.*?\S)?(?=\n\s*\n|\Z)", text, flags=re.DOTALL):
        segment_text = match.group(0).strip()
        if not segment_text:
            continue
        start = text.find(segment_text, match.start(), match.end())
        end = start + len(segment_text)
        segments.append(
            ParsedSegment(
                ordinal=len(segments),
                content=segment_text,
                start_offset=start,
                end_offset=end,
                locator={"kind": "text_offset", "start": start, "end": end},
            )
        )

    if not segments and text.strip():
        stripped = text.strip()
        start = text.find(stripped)
        segments.append(
            ParsedSegment(
                ordinal=0,
                content=stripped,
                start_offset=start,
                end_offset=start + len(stripped),
                locator={"kind": "text_offset", "start": start, "end": start + len(stripped)},
            )
        )
    return segments
