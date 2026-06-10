"""Review workflow and release API routes."""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request

from lingshu_domain import DEFAULT_DOMAIN_ID, EvidenceAssertion, EvidenceTerm, SourceQualitySignals
from lingshu_nexus.review import (
    ReleaseNotFoundError,
    ReleaseValidationError,
    ReviewBatch,
    ReviewBatchNotFoundError,
    ReviewedAssertionNotFoundError,
    ReviewReleaseService,
    ReviewWorkflowError,
)
from lingshu_nexus.review.models import (
    ReleasePreview,
    ReleaseRecord,
    StandardizationCandidate,
)

router = APIRouter(prefix="/api/v1", tags=["review"])


def get_review_service(request: Request) -> ReviewReleaseService:
    return cast(ReviewReleaseService, request.app.state.review_release_service)


@router.get("/review-batches")
async def list_review_batches(
    service: Annotated[ReviewReleaseService, Depends(get_review_service)],
    domain_id: Annotated[str, Query()] = DEFAULT_DOMAIN_ID,
) -> dict[str, object]:
    return {
        "domain_id": domain_id,
        "review_batches": [
            _review_batch_payload(batch)
            for batch in service.list_review_batches(domain_id=domain_id)
        ],
    }


@router.get("/review-batches/{batch_id}")
async def get_review_batch(
    batch_id: str,
    service: Annotated[ReviewReleaseService, Depends(get_review_service)],
    domain_id: Annotated[str, Query()] = DEFAULT_DOMAIN_ID,
) -> dict[str, object]:
    try:
        batch = service.get_review_batch(domain_id=domain_id, batch_id=batch_id)
    except ReviewBatchNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Review batch not found") from exc
    return _review_batch_payload(batch)


@router.get("/review-assertions")
async def list_review_assertions(
    service: Annotated[ReviewReleaseService, Depends(get_review_service)],
    domain_id: Annotated[str, Query()] = DEFAULT_DOMAIN_ID,
) -> dict[str, object]:
    return {
        "domain_id": domain_id,
        "assertions": [
            _assertion_payload(assertion)
            for assertion in service.list_assertions(domain_id=domain_id)
        ],
    }


@router.post("/review-assertions/{assertion_id}:approve")
async def approve_assertion(
    assertion_id: str,
    payload: Annotated[dict[str, Any], Body()],
    service: Annotated[ReviewReleaseService, Depends(get_review_service)],
    domain_id: Annotated[str, Query()] = DEFAULT_DOMAIN_ID,
) -> dict[str, object]:
    try:
        assertion = service.approve_assertion(
            domain_id=domain_id,
            assertion_id=assertion_id,
            reviewer=_required_text(payload, "reviewer"),
            reason=_required_text(payload, "reason"),
        )
    except ReviewedAssertionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Assertion not found") from exc
    except ReviewWorkflowError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _assertion_payload(assertion)


@router.post("/review-assertions/{assertion_id}:reject")
async def reject_assertion(
    assertion_id: str,
    payload: Annotated[dict[str, Any], Body()],
    service: Annotated[ReviewReleaseService, Depends(get_review_service)],
    domain_id: Annotated[str, Query()] = DEFAULT_DOMAIN_ID,
) -> dict[str, object]:
    try:
        assertion = service.reject_assertion(
            domain_id=domain_id,
            assertion_id=assertion_id,
            reviewer=_required_text(payload, "reviewer"),
            reason=_required_text(payload, "reason"),
        )
    except ReviewedAssertionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Assertion not found") from exc
    return _assertion_payload(assertion)


@router.post("/review-assertions/{assertion_id}:modify")
async def modify_assertion(
    assertion_id: str,
    payload: Annotated[dict[str, Any], Body()],
    service: Annotated[ReviewReleaseService, Depends(get_review_service)],
    domain_id: Annotated[str, Query()] = DEFAULT_DOMAIN_ID,
) -> dict[str, object]:
    try:
        assertion = service.modify_assertion(
            domain_id=domain_id,
            assertion_id=assertion_id,
            reviewer=_required_text(payload, "reviewer"),
            reason=_required_text(payload, "reason"),
            subject_text=_optional_text(payload, "subject_text"),
            subject_concept_id=_optional_text(payload, "subject_concept_id"),
            object_text=_optional_text(payload, "object_text"),
            object_concept_id=_optional_text(payload, "object_concept_id"),
            population=_optional_text(payload, "population"),
            outcome=_optional_text(payload, "outcome"),
            metadata_updates=_optional_dict(payload, "metadata_updates"),
            approve=bool(payload.get("approve", True)),
        )
    except ReviewedAssertionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Assertion not found") from exc
    return _assertion_payload(assertion)


@router.post("/review-assertions/{assertion_id}:mark-conflict")
async def mark_conflict(
    assertion_id: str,
    payload: Annotated[dict[str, Any], Body()],
    service: Annotated[ReviewReleaseService, Depends(get_review_service)],
    domain_id: Annotated[str, Query()] = DEFAULT_DOMAIN_ID,
) -> dict[str, object]:
    try:
        assertion = service.mark_conflict(
            domain_id=domain_id,
            assertion_id=assertion_id,
            reviewer=_required_text(payload, "reviewer"),
            reason=_required_text(payload, "reason"),
            conflict_with_assertion_ids=_string_tuple(payload.get("conflict_with_assertion_ids")),
        )
    except ReviewedAssertionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Assertion not found") from exc
    except ReviewWorkflowError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _assertion_payload(assertion)


@router.post("/domains/{domain_id}/releases:preview")
async def preview_release(
    domain_id: str,
    payload: Annotated[dict[str, Any], Body()],
    service: Annotated[ReviewReleaseService, Depends(get_review_service)],
) -> dict[str, object]:
    preview = service.preview_release(
        domain_id=domain_id,
        assertion_ids=_string_tuple(payload.get("assertion_ids")),
    )
    return _release_preview_payload(preview)


@router.get("/domains/{domain_id}/releases")
async def list_releases(
    domain_id: str,
    service: Annotated[ReviewReleaseService, Depends(get_review_service)],
) -> dict[str, object]:
    active = service.active_release(domain_id=domain_id)
    return {
        "domain_id": domain_id,
        "active_release_id": active.release.id if active else None,
        "releases": [
            _release_record_payload(record) for record in service.list_releases(domain_id=domain_id)
        ],
    }


@router.post("/domains/{domain_id}/releases")
async def create_release(
    domain_id: str,
    payload: Annotated[dict[str, Any], Body()],
    service: Annotated[ReviewReleaseService, Depends(get_review_service)],
) -> dict[str, object]:
    try:
        record = service.create_release(
            domain_id=domain_id,
            version=_required_text(payload, "version"),
            assertion_ids=_string_tuple(payload.get("assertion_ids")),
            released_by=_required_text(payload, "released_by"),
        )
    except (ReviewedAssertionNotFoundError, ReleaseNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Release input not found") from exc
    except ReleaseValidationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _release_record_payload(record)


@router.post("/domains/{domain_id}/releases/{release_id}:activate")
async def activate_release(
    domain_id: str,
    release_id: str,
    payload: Annotated[dict[str, Any], Body()],
    service: Annotated[ReviewReleaseService, Depends(get_review_service)],
) -> dict[str, object]:
    try:
        release = service.activate_release(
            domain_id=domain_id,
            release_id=release_id,
            actor_id=_required_text(payload, "actor_id"),
        )
    except ReleaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Release not found") from exc
    return {
        "id": release.id,
        "domain_id": release.domain_id,
        "version": release.version,
        "active": release.active,
    }


@router.post("/domains/{domain_id}/releases/{release_id}:rollback")
async def rollback_release(
    domain_id: str,
    release_id: str,
    payload: Annotated[dict[str, Any], Body()],
    service: Annotated[ReviewReleaseService, Depends(get_review_service)],
) -> dict[str, object]:
    try:
        release = service.rollback_to_release(
            domain_id=domain_id,
            release_id=release_id,
            actor_id=_required_text(payload, "actor_id"),
            reason=_required_text(payload, "reason"),
        )
    except ReleaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Release not found") from exc
    return {
        "id": release.id,
        "domain_id": release.domain_id,
        "version": release.version,
        "active": release.active,
    }


def _review_batch_payload(batch: ReviewBatch) -> dict[str, object]:
    return {
        "id": batch.id,
        "domain_id": batch.domain_id,
        "candidate_run_id": batch.candidate_run_id,
        "assertion_ids": list(batch.assertion_ids),
        "status": batch.status.value,
        "created_by": batch.created_by,
        "created_at": batch.created_at,
        "normalization_candidates": [
            _normalization_candidate_payload(candidate)
            for candidate in batch.normalization_candidates
        ],
    }


def _normalization_candidate_payload(candidate: StandardizationCandidate) -> dict[str, object]:
    return {
        "id": candidate.id,
        "assertion_id": candidate.assertion_id,
        "term_role": candidate.term_role,
        "concept_type": candidate.concept_type.value,
        "original_text": candidate.original_text,
        "suggested_concept_id": candidate.suggested_concept_id,
        "suggested_preferred_name": candidate.suggested_preferred_name,
        "aliases": list(candidate.aliases),
        "status": candidate.status.value,
        "review_note": candidate.review_note,
    }


def _assertion_payload(assertion: EvidenceAssertion) -> dict[str, object]:
    return {
        "id": assertion.id,
        "domain_id": assertion.domain_id,
        "subject": _term_payload(assertion.subject),
        "predicate": assertion.predicate.value,
        "object": _term_payload(assertion.object),
        "source_chunk_ids": list(assertion.source_chunk_ids),
        "review_status": assertion.review_status.value,
        "population": assertion.population,
        "outcome": assertion.outcome,
        "direction": assertion.direction.value,
        "extraction_confidence": assertion.extraction_confidence,
        "source_quality_signals": _source_quality_payload(assertion.source_quality_signals),
        "parameter_set": None
        if assertion.parameter_set is None
        else {
            "stimulation_site": assertion.parameter_set.stimulation_site,
            "frequency_hz": assertion.parameter_set.frequency_hz,
            "pulse_width_us": assertion.parameter_set.pulse_width_us,
            "intensity": assertion.parameter_set.intensity,
            "duration_minutes": assertion.parameter_set.duration_minutes,
            "course": assertion.parameter_set.course,
            "waveform": assertion.parameter_set.waveform,
            "dose": assertion.parameter_set.dose,
            "sham_control": assertion.parameter_set.sham_control,
            "raw_text": assertion.parameter_set.raw_text,
        },
        "metadata": assertion.metadata,
    }


def _term_payload(term: EvidenceTerm) -> dict[str, object]:
    return {
        "type": term.type.value,
        "text": term.text,
        "concept_id": term.concept_id,
        "original_text": term.original_text,
    }


def _source_quality_payload(signals: SourceQualitySignals) -> dict[str, object]:
    return {
        "tier": signals.tier.value,
        "source_type": signals.source_type,
        "journal_quartile": signals.journal_quartile,
        "citation_count": signals.citation_count,
        "is_highly_cited": signals.is_highly_cited,
        "is_hot_paper": signals.is_hot_paper,
    }


def _release_preview_payload(preview: ReleasePreview) -> dict[str, object]:
    return {
        "domain_id": preview.domain_id,
        "requested_assertion_ids": list(preview.requested_assertion_ids),
        "included_assertion_ids": list(preview.included_assertion_ids),
        "excluded_assertions": [
            {"assertion_id": exclusion.assertion_id, "reason": exclusion.reason}
            for exclusion in preview.excluded_assertions
        ],
        "additions": list(preview.additions),
        "removals": list(preview.removals),
        "unchanged": list(preview.unchanged),
        "conflict_assertion_ids": list(preview.conflict_assertion_ids),
        "active_release_id": preview.active_release_id,
    }


def _release_record_payload(record: ReleaseRecord) -> dict[str, object]:
    return {
        "id": record.release.id,
        "domain_id": record.release.domain_id,
        "version": record.release.version,
        "included_assertion_ids": list(record.release.included_assertion_ids),
        "schema_version": record.release.schema_version,
        "index_version": record.release.index_version,
        "released_by": record.release.released_by,
        "active": record.release.active,
        "assertion_count": len(record.assertions),
        "artifact_uri": record.artifact_ref.storage_uri,
        "created_at": record.created_at,
    }


def _required_text(payload: dict[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(status_code=422, detail=f"{field_name} is required")
    return value


def _optional_text(payload: dict[str, Any], field_name: str) -> str | None:
    value = payload.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail=f"{field_name} must be a string")
    return value


def _optional_dict(payload: dict[str, Any], field_name: str) -> dict[str, Any] | None:
    value = payload.get(field_name)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise HTTPException(status_code=422, detail=f"{field_name} must be an object")
    return value


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise HTTPException(status_code=422, detail="assertion_ids must be a non-empty list")
    result = tuple(str(item) for item in value if str(item))
    if not result:
        raise HTTPException(status_code=422, detail="assertion_ids must be a non-empty list")
    return result
