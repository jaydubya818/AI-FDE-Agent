from __future__ import annotations

import pytest

from ai_fde.modules.evidence.service import (
    EvidenceValidationError,
    normalize_evidence_file_name,
)


@pytest.mark.parametrize(
    "file_name",
    [
        "",
        "   ",
        ".",
        "..",
        ".hidden.md",
        "../../evil.md",
        "..\\..\\evil.md",
        "mixed/path\\evil.md",
        "control\x00character.md",
        "control\x1fcharacter.md",
        "control\x7fcharacter.md",
        "control\N{RIGHT-TO-LEFT OVERRIDE}character.md",
        "control%01character.md",
        "CON.txt",
    ],
)
def test_evidence_file_name_rejects_unsafe_cross_platform_basenames(
    file_name: str,
) -> None:
    with pytest.raises(EvidenceValidationError, match="one safe file basename"):
        normalize_evidence_file_name(file_name)


def test_evidence_file_name_is_trimmed_and_unicode_normalized() -> None:
    decomposed = "  Re\N{COMBINING ACUTE ACCENT}sume\N{COMBINING ACUTE ACCENT}.md  "
    composed = (
        "R\N{LATIN SMALL LETTER E WITH ACUTE}sum"
        "\N{LATIN SMALL LETTER E WITH ACUTE}.md"
    )

    assert normalize_evidence_file_name(decomposed) == composed
