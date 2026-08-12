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

    def extract(
        self,
        text: str,
        *,
        image_bytes: bytes | None = None,
        image_format: Literal["png", "jpeg"] | None = None,
    ) -> ExtractionResult: ...


class DeterministicAcmeExtractor:
    """Narrow, transparent extractor for the first fixture-backed vertical slice."""

    name = "deterministic-acme-patterns"
    version = "1.0.0"
    schema_version = "claim-v1"
    prompt_version = "fixture-rules-v1"
    model_id: str | None = None

    _owns = re.compile(
        r"(?P<person>[A-Z][A-Za-z'-]+(?:\s+[A-Z][A-Za-z'-]+)+)\s+owns\s+"
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
    ) -> ExtractionResult:
        del image_bytes, image_format
        claims: list[ExtractedClaim] = []
        claims.extend(self._extract_ownership(text))
        claims.extend(self._extract_system_usage(text))
        claims.extend(self._extract_approval_rules(text))
        claims.extend(self._extract_approval_exceptions(text))
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
