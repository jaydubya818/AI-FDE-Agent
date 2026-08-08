from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ai_fde.adapters.storage import EvidenceStore
from ai_fde.models import (
    CandidateClaim,
    ClaimEvidence,
    Contradiction,
    EvidenceAsset,
    EvidenceSegment,
    ExtractionRun,
    Job,
)
from ai_fde.modules.evidence.parser import parse_text_evidence
from ai_fde.modules.knowledge.extractor import DeterministicAcmeExtractor
from ai_fde.modules.shared import publish_domain_event


class JobProcessingError(RuntimeError):
    pass


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
    extractor: DeterministicAcmeExtractor | None = None,
) -> None:
    if job.kind != "ingest_evidence":
        raise JobProcessingError(f"Unsupported job kind: {job.kind}")

    evidence_id = UUID(str(job.payload["evidence_asset_id"]))
    asset = session.get(EvidenceAsset, evidence_id)
    if asset is None or asset.engagement_id != job.engagement_id:
        raise JobProcessingError("The evidence asset is not available in this engagement.")

    resolved_extractor = extractor or DeterministicAcmeExtractor()
    asset.status = "processing"
    asset.error_message = None
    job.progress = 15
    content = store.get(asset.storage_key)
    parsed_segments = parse_text_evidence(content, asset.content_type, asset.file_name)

    existing_segment = session.scalar(
        select(EvidenceSegment.id).where(EvidenceSegment.evidence_asset_id == asset.id).limit(1)
    )
    if existing_segment is not None:
        _complete_existing_job(session, job, asset)
        return

    extraction_run = ExtractionRun(
        engagement_id=job.engagement_id,
        evidence_asset_id=asset.id,
        extractor_name=resolved_extractor.name,
        extractor_version=resolved_extractor.version,
        schema_version=resolved_extractor.schema_version,
        status="running",
    )
    session.add(extraction_run)
    session.flush()

    created_claims: list[CandidateClaim] = []
    for parsed in parsed_segments:
        segment = EvidenceSegment(
            engagement_id=job.engagement_id,
            evidence_asset_id=asset.id,
            ordinal=parsed.ordinal,
            content=parsed.content,
            start_offset=parsed.start_offset,
            end_offset=parsed.end_offset,
            locator=parsed.locator,
            parser_name="utf8-paragraph-parser",
            parser_version="1.0.0",
        )
        session.add(segment)
        session.flush()

        for extracted in resolved_extractor.extract(parsed.content):
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


def fail_job(session: Session, job_id: UUID, message: str) -> None:
    job = session.get(Job, job_id)
    if job is None:
        return
    job.error_message = message[:4000]
    job.leased_until = None
    if job.attempts >= job.max_attempts:
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
