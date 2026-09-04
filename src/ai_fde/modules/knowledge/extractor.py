from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal, Protocol


@dataclass(frozen=True)
class ExtractedClaim:
    claim_kind: str
    subject_text: str
    predicate: str
    object_text: str | None
    summary: str
    normalized_payload: dict[str, Any]
    confidence: Decimal
    materiality: str
    start_offset: int
    end_offset: int
    quote: str


@dataclass(frozen=True)
class ExtractionResult:
    claims: list[ExtractedClaim]
    provider_name: str
    model_id: str | None
    prompt_version: str
    schema_version: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    result_code: str = "complete"


class ExtractionProviderError(RuntimeError):
    def __init__(self, message: str, *, result_code: str, retryable: bool) -> None:
        super().__init__(message)
        self.result_code = result_code
        self.retryable = retryable


class ExtractionProvider(Protocol):
    name: str
    version: str
    schema_version: str
    prompt_version: str
    model_id: str | None
    max_output_tokens: int

    def extract(
        self,
        text: str,
        *,
        image_bytes: bytes | None = None,
        image_format: Literal["png", "jpeg"] | None = None,
        max_output_tokens: int | None = None,
    ) -> ExtractionResult: ...


class DeterministicFixtureExtractor:
    """Transparent pattern extractor for committed synthetic fixture profiles only."""

    name = "deterministic-fixture-patterns"
    version = "2.0.0"
    schema_version = "claim-v1"
    prompt_version = "fixture-rules-v2"
    model_id: str | None = None
    max_output_tokens = 0

    _owns = re.compile(
        r"(?P<person>[A-Z][A-Za-z'-]+(?:[ \t]+[A-Z][A-Za-z'-]+)+)[ \t]+owns[ \t]+"
        r"(?P<process>[A-Z][A-Za-z &-]+?)(?:\.|$)"
    )
    _uses = re.compile(
        r"(?P<subject>[A-Z][A-Za-z &-]+?)\s+uses\s+"
        r"(?P<system>[A-Z][A-Za-z0-9._-]+)(?:\s+to\b|\.|$)"
    )
    _approval_rule = re.compile(
        r"Invoices\s+(?P<condition>.+?)\s+require\s+(?P<approver>.+?)\s+approval(?:\.|$)",
        flags=re.IGNORECASE,
    )
    _approval_exception = re.compile(
        r"(?:However,\s*)?(?P<condition>Strategic vendors.+?)\s+"
        r"(?:may|are)\s+(?:be\s+)?approved by (?:the )?"
        r"(?P<approver>[A-Z][A-Za-z ]+?)(?=\s+when|\.|$)",
        flags=re.IGNORECASE,
    )
    _named_approval_rule = re.compile(
        r"(?P<subject>[A-Z][A-Za-z &-]+ approval):\s*"
        r"(?P<condition>.+?)\s+require(?:s)?\s+"
        r"(?P<approver>[A-Z][A-Za-z &-]+?)\s+approval(?:\.|$)"
    )
    _precedes = re.compile(
        r"(?P<subject>[A-Z][A-Za-z0-9 &'/-]+?)\s+precedes\s+"
        r"(?P<object>[A-Z][A-Za-z0-9 &'/-]+?)(?:\.|$)"
    )
    _hands_off = re.compile(
        r"(?P<subject>[A-Z][A-Za-z0-9 &'/-]+?)\s+hands off to\s+"
        r"(?P<object>[A-Z][A-Za-z0-9 &'/-]+?)(?:\.|$)"
    )
    _governed_by = re.compile(
        r"(?P<subject>[A-Z][A-Za-z0-9 &'/-]+?)\s+is governed by\s+"
        r"(?P<object>[A-Z][A-Za-z0-9 &'/-]+?)(?:\.|$)"
    )
    _explicit_entity = re.compile(
        r"(?P<type>Person|System|Process|Department|Role):\s*(?P<name>[^\n.]+)",
        flags=re.IGNORECASE,
    )

    def extract(
        self,
        text: str,
        *,
        image_bytes: bytes | None = None,
        image_format: Literal["png", "jpeg"] | None = None,
        max_output_tokens: int | None = None,
    ) -> ExtractionResult:
        del image_bytes, image_format, max_output_tokens
        claims: list[ExtractedClaim] = []
        claims.extend(self._extract_ownership(text))
        claims.extend(self._extract_system_usage(text))
        claims.extend(self._extract_approval_rules(text))
        claims.extend(self._extract_named_approval_rules(text))
        claims.extend(self._extract_approval_exceptions(text))
        claims.extend(self._extract_sequences(text))
        claims.extend(self._extract_handoffs(text))
        claims.extend(self._extract_governance(text))
        claims.extend(self._extract_explicit_entities(text))
        return ExtractionResult(
            claims=self._deduplicate(claims),
            provider_name=self.name,
            model_id=self.model_id,
            prompt_version=self.prompt_version,
            schema_version=self.schema_version,
        )

    def _extract_ownership(self, text: str) -> list[ExtractedClaim]:
        output: list[ExtractedClaim] = []
        for match in self._owns.finditer(text):
            person = self._clean(match.group("person"))
            process = self._clean(match.group("process"))
            output.append(
                self._claim(
                    match,
                    claim_kind="relationship",
                    subject_text=person,
                    predicate="OWNS",
                    object_text=process,
                    summary=f"{person} owns {process}.",
                    payload={
                        "subject": {"type": "person", "name": person},
                        "object": {"type": "process", "name": process},
                    },
                    confidence="0.9900",
                )
            )
        return output

    def _extract_system_usage(self, text: str) -> list[ExtractedClaim]:
        output: list[ExtractedClaim] = []
        for match in self._uses.finditer(text):
            subject = self._clean(match.group("subject"))
            system = self._clean(match.group("system"))
            output.append(
                self._claim(
                    match,
                    claim_kind="relationship",
                    subject_text=subject,
                    predicate="USES",
                    object_text=system,
                    summary=f"{subject} uses {system}.",
                    payload={
                        "subject": {"type": "process", "name": subject},
                        "object": {"type": "system", "name": system},
                    },
                    confidence="0.9800",
                )
            )
        return output

    def _extract_approval_rules(self, text: str) -> list[ExtractedClaim]:
        output: list[ExtractedClaim] = []
        for match in self._approval_rule.finditer(text):
            condition = self._clean(match.group("condition"))
            approver = self._clean(match.group("approver"))
            output.append(
                self._claim(
                    match,
                    claim_kind="rule",
                    subject_text="Invoice approval",
                    predicate="REQUIRES_APPROVAL",
                    object_text=approver,
                    summary=f"Invoices {condition} require {approver} approval.",
                    payload={
                        "subject": {"type": "process", "name": "Invoice approval"},
                        "object": {"type": "role", "name": approver},
                        "condition": condition,
                        "is_exception": False,
                    },
                    confidence="0.9900",
                )
            )
        return output

    def _extract_approval_exceptions(self, text: str) -> list[ExtractedClaim]:
        output: list[ExtractedClaim] = []
        for match in self._approval_exception.finditer(text):
            condition = self._clean(match.group("condition"))
            approver = self._clean(match.group("approver"))
            output.append(
                self._claim(
                    match,
                    claim_kind="exception",
                    subject_text="Invoice approval",
                    predicate="REQUIRES_APPROVAL",
                    object_text=approver,
                    summary=f"Exception: {condition} may be approved by {approver}.",
                    payload={
                        "subject": {"type": "process", "name": "Invoice approval"},
                        "object": {"type": "role", "name": approver},
                        "condition": condition,
                        "is_exception": True,
                    },
                    confidence="0.9600",
                )
            )
        return output

    def _extract_named_approval_rules(self, text: str) -> list[ExtractedClaim]:
        output: list[ExtractedClaim] = []
        for match in self._named_approval_rule.finditer(text):
            subject = self._clean(match.group("subject"))
            condition = self._clean(match.group("condition"))
            approver = self._clean(match.group("approver"))
            output.append(
                self._claim(
                    match,
                    claim_kind="rule",
                    subject_text=subject,
                    predicate="REQUIRES_APPROVAL",
                    object_text=approver,
                    summary=f"{condition} require {approver} approval.",
                    payload={
                        "subject": {"type": "process", "name": subject},
                        "object": {"type": "role", "name": approver},
                        "condition": condition,
                        "is_exception": False,
                    },
                    confidence="0.9900",
                )
            )
        return output

    def _extract_sequences(self, text: str) -> list[ExtractedClaim]:
        return self._extract_binary_relationships(
            text,
            pattern=self._precedes,
            predicate="PRECEDES",
            subject_type="process",
            object_type="process",
            summary_template="{subject} precedes {object}.",
            confidence="0.9800",
        )

    def _extract_handoffs(self, text: str) -> list[ExtractedClaim]:
        return self._extract_binary_relationships(
            text,
            pattern=self._hands_off,
            predicate="HANDS_OFF_TO",
            subject_type="role",
            object_type="role",
            summary_template="{subject} hands off to {object}.",
            confidence="0.9800",
        )

    def _extract_governance(self, text: str) -> list[ExtractedClaim]:
        return self._extract_binary_relationships(
            text,
            pattern=self._governed_by,
            predicate="GOVERNED_BY",
            subject_type="process",
            object_type="policy",
            summary_template="{subject} is governed by {object}.",
            confidence="0.9900",
        )

    def _extract_binary_relationships(
        self,
        text: str,
        *,
        pattern: re.Pattern[str],
        predicate: str,
        subject_type: str,
        object_type: str,
        summary_template: str,
        confidence: str,
    ) -> list[ExtractedClaim]:
        output: list[ExtractedClaim] = []
        for match in pattern.finditer(text):
            subject = self._clean(match.group("subject"))
            object_text = self._clean(match.group("object"))
            output.append(
                self._claim(
                    match,
                    claim_kind="relationship",
                    subject_text=subject,
                    predicate=predicate,
                    object_text=object_text,
                    summary=summary_template.format(subject=subject, object=object_text),
                    payload={
                        "subject": {"type": subject_type, "name": subject},
                        "object": {"type": object_type, "name": object_text},
                    },
                    confidence=confidence,
                )
            )
        return output

    def _extract_explicit_entities(self, text: str) -> list[ExtractedClaim]:
        output: list[ExtractedClaim] = []
        for match in self._explicit_entity.finditer(text):
            entity_type = match.group("type").lower()
            name = self._clean(match.group("name"))
            output.append(
                self._claim(
                    match,
                    claim_kind="entity",
                    subject_text=name,
                    predicate="IDENTIFIED_AS",
                    object_text=entity_type,
                    summary=f"{name} is identified as a {entity_type}.",
                    payload={"subject": {"type": entity_type, "name": name}},
                    confidence="0.9900",
                    materiality="low",
                )
            )
        return output

    @staticmethod
    def _claim(
        match: re.Match[str],
        *,
        claim_kind: str,
        subject_text: str,
        predicate: str,
        object_text: str | None,
        summary: str,
        payload: dict[str, Any],
        confidence: str,
        materiality: str = "material",
    ) -> ExtractedClaim:
        return ExtractedClaim(
            claim_kind=claim_kind,
            subject_text=subject_text,
            predicate=predicate,
            object_text=object_text,
            summary=summary,
            normalized_payload=payload,
            confidence=Decimal(confidence),
            materiality=materiality,
            start_offset=match.start(),
            end_offset=match.end(),
            quote=match.group(0).strip(),
        )

    @staticmethod
    def _clean(value: str) -> str:
        return value.strip().rstrip(".").strip()

    @staticmethod
    def _deduplicate(claims: list[ExtractedClaim]) -> list[ExtractedClaim]:
        seen: set[tuple[str, str, str, str | None, int, int]] = set()
        unique: list[ExtractedClaim] = []
        for claim in claims:
            key = (
                claim.claim_kind,
                claim.subject_text.casefold(),
                claim.predicate,
                claim.object_text.casefold() if claim.object_text else None,
                claim.start_offset,
                claim.end_offset,
            )
            if key not in seen:
                seen.add(key)
                unique.append(claim)
        return unique
