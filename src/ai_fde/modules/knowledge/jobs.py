from __future__ import annotations

import hashlib
import hmac
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ai_fde.adapters.storage import EvidenceObjectVersionNotFoundError, EvidenceStore
from ai_fde.models import (
    CandidateClaim,
    ClaimEvidence,
    Contradiction,
    EvidenceAsset,
    EvidenceSegment,
    ExtractionRun,
    Job,
    Operator,
)
from ai_fde.modules.design_partner.service import (
    CustomerDataProcessingDeniedError,
    require_qualified_evidence_processing,
)
from ai_fde.modules.evidence.parser import ParsedSegment, parse_evidence
from ai_fde.modules.knowledge.extractor import (
    DeterministicFixtureExtractor,
    ExtractionProvider,
    ExtractionResult,
)
from ai_fde.modules.shared import publish_domain_event, record_audit


class JobProcessingError(RuntimeError):
    pass


class JobLeaseLostError(JobProcessingError):
    """The worker no longer owns the exact job attempt it tried to mutate."""


class EvidenceIntegrityError(JobProcessingError):
    """Persisted evidence bytes do not match their immutable provenance metadata."""


class ExtractionBudgetExceededError(JobProcessingError):
    pass


@dataclass(frozen=True)
class ExtractionJobBudget:
    max_segments: int = 100
    max_provider_calls: int = 50
    max_provider_tokens: int = 1_000_000


# UTF-8 bytes conservatively upper-bound text tokens. This additional reserve covers the fixed
# system prompt, schema, message envelope, and provider tokenization variance for each call.
PROVIDER_INPUT_TOKEN_RESERVE = 16_384


def lease_next_job(session: Session, engagement_id: UUID, lease_seconds: int) -> Job | None:
    now = datetime.now(UTC)
    statement = (
        select(Job)
        .where(
            Job.engagement_id == engagement_id,
            Job.available_at <= now,
            Job.attempts < Job.max_attempts,
            or_(
                Job.status == "queued",
                (Job.status == "running") & (Job.leased_until < now),
            ),
        )
        .order_by(Job.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    job = session.scalar(statement)
    if job is None:
        return None
    job.status = "running"
    job.attempts += 1
    job.lease_token = uuid.uuid4()
    job.leased_until = now + timedelta(seconds=lease_seconds)
    job.progress = 5
    return job


def process_job(
    session: Session,
    store: EvidenceStore,
    job: Job,
    *,
    lease_token: UUID,
    extractor: ExtractionProvider | None = None,
    actor: Operator | None = None,
    budget: ExtractionJobBudget | None = None,
    provider_allowed_data_classifications: set[str] | None = None,
    runtime_authority_check: Callable[[datetime], None] | None = None,
) -> None:
    job = _lock_active_lease(session, job.id, lease_token)
    if job.kind != "ingest_evidence":
        raise JobProcessingError(f"Unsupported job kind: {job.kind}")

    evidence_id = UUID(str(job.payload["evidence_asset_id"]))
    asset = session.get(EvidenceAsset, evidence_id)
    if asset is None or asset.engagement_id != job.engagement_id:
        raise JobProcessingError("The evidence asset is not available in this engagement.")

    resolved_extractor = extractor or DeterministicFixtureExtractor()
    resolved_budget = budget or ExtractionJobBudget()
    allowed_classifications = provider_allowed_data_classifications or set()
    qualified_customer_data = _require_customer_data_processing_authority(
        session,
        asset=asset,
        provider_name=resolved_extractor.name,
        provider_allowed_data_classifications=allowed_classifications,
        runtime_authority_check=runtime_authority_check,
    )
    storage_version_id = asset.storage_version_id
    if qualified_customer_data and storage_version_id is None:
        raise EvidenceIntegrityError(
            "Qualified evidence is missing its immutable object version."
        )
    try:
        content = store.get(asset.storage_key, version_id=storage_version_id)
    except EvidenceObjectVersionNotFoundError as exc:
        raise EvidenceIntegrityError(
            "The immutable evidence object version is unavailable."
        ) from exc
    actual_content_hash = hashlib.sha256(content).hexdigest()
    if not hmac.compare_digest(actual_content_hash, asset.content_hash):
        raise EvidenceIntegrityError(
            "The immutable evidence object version failed integrity verification."
        )
    if qualified_customer_data:
        _require_customer_data_processing_authority(
            session,
            asset=asset,
            provider_name=resolved_extractor.name,
            provider_allowed_data_classifications=allowed_classifications,
            runtime_authority_check=runtime_authority_check,
        )
    parsed_segments = parse_evidence(content, asset.content_type, asset.file_name)
    _enforce_extraction_budget(
        parsed_segments,
        content=content,
        extractor=resolved_extractor,
        budget=resolved_budget,
    )

    existing_segment = session.scalar(
        select(EvidenceSegment.id).where(EvidenceSegment.evidence_asset_id == asset.id).limit(1)
    )
    if existing_segment is not None:
        if qualified_customer_data:
            _require_customer_data_processing_authority(
                session,
                asset=asset,
                provider_name=resolved_extractor.name,
                provider_allowed_data_classifications=allowed_classifications,
                runtime_authority_check=runtime_authority_check,
                lock_for_update=True,
            )
        _complete_existing_job(session, job, asset)
        return

    extraction_run = ExtractionRun(
        engagement_id=job.engagement_id,
        evidence_asset_id=asset.id,
        extractor_name=resolved_extractor.name,
        extractor_version=resolved_extractor.version,
        schema_version=resolved_extractor.schema_version,
        provider_name=resolved_extractor.name,
        model_id=resolved_extractor.model_id,
        prompt_version=resolved_extractor.prompt_version,
        input_hash=asset.content_hash,
        input_tokens=0,
        output_tokens=0,
        latency_ms=0,
        result_code="running",
        status="running",
    )
    extracted_segments: list[tuple[ParsedSegment, ExtractionResult]] = []
    for parsed in parsed_segments:
        image_format: Literal["png", "jpeg"] | None = None
        image_bytes = None
        if parsed.modality == "image":
            image_bytes = content
            image_format = "png" if asset.file_name.casefold().endswith(".png") else "jpeg"
        if qualified_customer_data:
            _require_customer_data_processing_authority(
                session,
                asset=asset,
                provider_name=resolved_extractor.name,
                provider_allowed_data_classifications=allowed_classifications,
                runtime_authority_check=runtime_authority_check,
            )
        result = resolved_extractor.extract(
            parsed.content,
            image_bytes=image_bytes,
            image_format=image_format,
            max_output_tokens=resolved_extractor.max_output_tokens,
        )
        if qualified_customer_data:
            _require_customer_data_processing_authority(
                session,
                asset=asset,
                provider_name=resolved_extractor.name,
                provider_allowed_data_classifications=allowed_classifications,
                runtime_authority_check=runtime_authority_check,
            )
        extraction_run.input_tokens += result.input_tokens
        extraction_run.output_tokens += result.output_tokens
        provider_tokens = extraction_run.input_tokens + extraction_run.output_tokens
        if provider_tokens > resolved_budget.max_provider_tokens:
            raise ExtractionBudgetExceededError(
                "Extraction stopped because the provider token budget was exceeded."
            )
        extraction_run.latency_ms += result.latency_ms
        for extracted in result.claims:
            if not (
                0 <= extracted.start_offset < extracted.end_offset <= len(parsed.content)
                and parsed.content[extracted.start_offset : extracted.end_offset] == extracted.quote
            ):
                raise JobProcessingError(
                    "An extracted claim did not resolve to exact stored evidence offsets."
                )
        extracted_segments.append((parsed, result))

    if qualified_customer_data:
        _require_customer_data_processing_authority(
            session,
            asset=asset,
            provider_name=resolved_extractor.name,
            provider_allowed_data_classifications=allowed_classifications,
            runtime_authority_check=runtime_authority_check,
            lock_for_update=True,
        )

    # Do not stage customer-derived database output until the final locked authority
    # check succeeds. The aggregate locks remain held through the caller's commit.
    asset.status = "processing"
    asset.error_message = None
    job.progress = 15
    session.add(extraction_run)
    session.flush()

    created_claims: list[CandidateClaim] = []
    for parsed, result in extracted_segments:
        segment = EvidenceSegment(
            engagement_id=job.engagement_id,
            evidence_asset_id=asset.id,
            ordinal=parsed.ordinal,
            content=parsed.content,
            start_offset=parsed.start_offset,
            end_offset=parsed.end_offset,
            locator=parsed.locator,
            parser_name=parsed.parser_name,
            parser_version=parsed.parser_version,
        )
        session.add(segment)
        session.flush()
        for extracted in result.claims:
            claim = CandidateClaim(
                engagement_id=job.engagement_id,
                extraction_run_id=extraction_run.id,
                claim_kind=extracted.claim_kind,
                subject_text=extracted.subject_text,
                predicate=extracted.predicate,
                object_text=extracted.object_text,
                summary=extracted.summary,
                normalized_payload=extracted.normalized_payload,
                confidence=extracted.confidence,
                materiality=extracted.materiality,
                status="candidate",
            )
            session.add(claim)
            session.flush()
            session.add(
                ClaimEvidence(
                    engagement_id=job.engagement_id,
                    candidate_claim_id=claim.id,
                    evidence_segment_id=segment.id,
                    start_offset=extracted.start_offset,
                    end_offset=extracted.end_offset,
                    quote=extracted.quote,
                )
            )
            created_claims.append(claim)

    session.flush()
    _detect_contradictions(session, job.engagement_id, created_claims)

    extraction_run.status = "complete"
    extraction_run.result_code = "complete"
    extraction_run.completed_at = datetime.now(UTC)
    asset.status = "needs_review" if created_claims else "complete"
    job.status = "completed"
    job.progress = 100
    job.completed_at = datetime.now(UTC)
    job.leased_until = None
    publish_domain_event(
        session,
        engagement_id=job.engagement_id,
        event_type="extraction.completed",
        aggregate_type="evidence_asset",
        aggregate_id=asset.id,
        payload={
            "claim_count": len(created_claims),
            "extractor": resolved_extractor.name,
            "extractor_version": resolved_extractor.version,
        },
    )
    if actor is not None:
        record_audit(
            session,
            engagement_id=job.engagement_id,
            actor_id=actor.id,
            actor_type=actor.identity_kind,
            action="extraction.completed",
            target_type="extraction_run",
            target_id=extraction_run.id,
            detail={
                "provider": extraction_run.provider_name,
                "model_id": extraction_run.model_id,
                "prompt_version": extraction_run.prompt_version,
                "schema_version": extraction_run.schema_version,
                "result_code": extraction_run.result_code,
                "claim_count": len(created_claims),
            },
        )
    if qualified_customer_data:
        # Deployment authority is wall-clock bounded and cannot be serialized by the
        # database row locks. Recheck it after staging derived output so expiry during
        # database work rolls the transaction back before the caller can commit.
        _require_customer_data_processing_authority(
            session,
            asset=asset,
            provider_name=resolved_extractor.name,
            provider_allowed_data_classifications=allowed_classifications,
            runtime_authority_check=runtime_authority_check,
            lock_for_update=True,
        )


def _require_customer_data_processing_authority(
    session: Session,
    *,
    asset: EvidenceAsset,
    provider_name: str,
    provider_allowed_data_classifications: set[str],
    runtime_authority_check: Callable[[datetime], None] | None,
    lock_for_update: bool = False,
) -> bool:
    decision_time = require_qualified_evidence_processing(
        session,
        asset=asset,
        provider_name=provider_name,
        provider_allowed_data_classifications=provider_allowed_data_classifications,
        lock_for_update=lock_for_update,
    )
    if decision_time is None:
        return False
    if runtime_authority_check is None:
        raise CustomerDataProcessingDeniedError(
            "Customer-data processing runtime authorization is unavailable."
        )
    try:
        runtime_authority_check(decision_time)
    except CustomerDataProcessingDeniedError:
        raise
    except ValueError as exc:
        raise CustomerDataProcessingDeniedError(
            "Customer-data processing runtime authorization is no longer valid."
        ) from exc
    return True


def _enforce_extraction_budget(
    parsed_segments: list[ParsedSegment],
    *,
    content: bytes,
    extractor: ExtractionProvider,
    budget: ExtractionJobBudget,
) -> None:
    segment_count = len(parsed_segments)
    if segment_count > budget.max_segments:
        raise ExtractionBudgetExceededError(
            "Evidence produced "
            f"{segment_count} segments; the per-job limit is {budget.max_segments}."
        )
    if segment_count > budget.max_provider_calls:
        raise ExtractionBudgetExceededError(
            "Evidence would exceed the per-job extraction provider-call limit."
        )
    if extractor.max_output_tokens == 0:
        return

    provider_token_ceiling = 0
    for parsed in parsed_segments:
        provider_token_ceiling += (
            len(parsed.content.encode("utf-8"))
            + (len(content) if parsed.modality == "image" else 0)
            + PROVIDER_INPUT_TOKEN_RESERVE
            + extractor.max_output_tokens
        )
    if provider_token_ceiling > budget.max_provider_tokens:
        raise ExtractionBudgetExceededError(
            "Evidence would exceed the conservative per-job provider-token ceiling."
        )


def fail_job(
    session: Session,
    job_id: UUID,
    message: str,
    *,
    lease_token: UUID,
    retryable: bool = True,
    result_code: str = "evidence_processing_failed",
    extractor: ExtractionProvider | None = None,
) -> bool:
    job = session.scalar(
        select(Job)
        .where(
            Job.id == job_id,
            Job.status == "running",
            Job.lease_token == lease_token,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if job is None:
        return False
    job.error_message = message[:4000]
    job.leased_until = None
    if not retryable or job.attempts >= job.max_attempts:
        job.status = "failed"
    else:
        job.status = "queued"
        job.available_at = datetime.now(UTC) + timedelta(seconds=2**job.attempts)
    evidence_id = job.payload.get("evidence_asset_id")
    if evidence_id:
        asset = session.get(EvidenceAsset, UUID(str(evidence_id)))
        if asset is not None:
            asset.status = "failed" if job.status == "failed" else "queued"
            asset.error_message = job.error_message
            if extractor is not None:
                session.add(
                    ExtractionRun(
                        engagement_id=job.engagement_id,
                        evidence_asset_id=asset.id,
                        extractor_name=extractor.name,
                        extractor_version=extractor.version,
                        schema_version=extractor.schema_version,
                        provider_name=extractor.name,
                        model_id=extractor.model_id,
                        prompt_version=extractor.prompt_version,
                        input_hash=asset.content_hash,
                        result_code=result_code[:120],
                        status="failed",
                        error_message=message[:4000],
                        completed_at=datetime.now(UTC),
                    )
                )
    return True


def _lock_active_lease(
    session: Session,
    job_id: UUID,
    lease_token: UUID,
    *,
    now: datetime | None = None,
) -> Job:
    timestamp = now or datetime.now(UTC)
    session.flush()
    job = session.scalar(
        select(Job)
        .where(Job.id == job_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        job is None
        or job.status != "running"
        or job.lease_token != lease_token
        or job.leased_until is None
        or job.leased_until <= timestamp
    ):
        raise JobLeaseLostError("The evidence job lease is missing, expired, or superseded.")
    return job


def _complete_existing_job(session: Session, job: Job, asset: EvidenceAsset) -> None:
    job.status = "completed"
    job.progress = 100
    job.completed_at = datetime.now(UTC)
    job.leased_until = None
    pending = session.scalar(
        select(CandidateClaim.id)
        .join(ExtractionRun, ExtractionRun.id == CandidateClaim.extraction_run_id)
        .where(
            ExtractionRun.evidence_asset_id == asset.id,
            CandidateClaim.status == "candidate",
        )
        .limit(1)
    )
    asset.status = "needs_review" if pending else "complete"


def _detect_contradictions(
    session: Session, engagement_id: UUID, new_claims: list[CandidateClaim]
) -> None:
    for new_claim in new_claims:
        if new_claim.predicate != "REQUIRES_APPROVAL" or not new_claim.object_text:
            continue
        conflicting = list(
            session.scalars(
                select(CandidateClaim).where(
                    CandidateClaim.engagement_id == engagement_id,
                    CandidateClaim.id != new_claim.id,
                    CandidateClaim.subject_text == new_claim.subject_text,
                    CandidateClaim.predicate == new_claim.predicate,
                    CandidateClaim.object_text.is_not(None),
                    CandidateClaim.object_text != new_claim.object_text,
                    CandidateClaim.status.in_(["candidate", "accepted"]),
                )
            )
        )
        for existing in conflicting:
            left, right = sorted((existing.id, new_claim.id), key=str)
            duplicate = session.scalar(
                select(Contradiction.id).where(
                    Contradiction.left_claim_id == left,
                    Contradiction.right_claim_id == right,
                )
            )
            if duplicate is None:
                session.add(
                    Contradiction(
                        engagement_id=engagement_id,
                        left_claim_id=left,
                        right_claim_id=right,
                        summary=(
                            f"Approval evidence names both {existing.object_text} and "
                            f"{new_claim.object_text}. Confirm whether this is a conflict, "
                            "exception, or change over time."
                        ),
                        blocking=True,
                    )
                )
