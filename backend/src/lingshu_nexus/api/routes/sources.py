"""SourceConnector and incremental sync API routes."""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, Request, UploadFile

from lingshu_domain import DEFAULT_DOMAIN_ID
from lingshu_domain.validation import SchemaValidationError
from lingshu_nexus.documents import DocumentUpload
from lingshu_nexus.sources import (
    SourceArtifactRecord,
    SourceConfigNotFoundError,
    SourceConnectorConfig,
    SourceConnectorType,
    SourceRunNotFoundError,
    SourceSchedule,
    SourceSyncResult,
    SourceSyncRun,
    SourceUpdateError,
    SourceUpdateService,
)

router = APIRouter(prefix="/api/v1", tags=["sources"])


def get_source_service(request: Request) -> SourceUpdateService:
    return cast(SourceUpdateService, request.app.state.source_update_service)


@router.get("/sources")
async def list_sources(
    service: Annotated[SourceUpdateService, Depends(get_source_service)],
    domain_id: Annotated[str, Query()] = DEFAULT_DOMAIN_ID,
) -> dict[str, object]:
    return {
        "domain_id": domain_id,
        "sources": [
            _source_payload(source) for source in service.list_sources(domain_id=domain_id)
        ],
    }


@router.post("/sources")
async def upsert_source(
    payload: Annotated[dict[str, Any], Body()],
    service: Annotated[SourceUpdateService, Depends(get_source_service)],
    domain_id: Annotated[str, Query()] = DEFAULT_DOMAIN_ID,
) -> dict[str, object]:
    try:
        source = service.upsert_source(
            domain_id=domain_id,
            source_id=_required_text(payload, "id"),
            name=_required_text(payload, "name"),
            connector_type=SourceConnectorType(_required_text(payload, "connector_type")),
            config=_optional_dict(payload, "config") or {},
            schedule=_schedule_from_payload(_optional_dict(payload, "schedule") or {}),
            enabled=bool(payload.get("enabled", True)),
            max_attempts=int(payload.get("max_attempts", 3)),
            actor_id=_required_text(payload, "actor_id"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SchemaValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _source_payload(source)


@router.post("/sources/{source_id}:sync")
async def sync_source(
    source_id: str,
    payload: Annotated[dict[str, Any], Body()],
    service: Annotated[SourceUpdateService, Depends(get_source_service)],
    domain_id: Annotated[str, Query()] = DEFAULT_DOMAIN_ID,
) -> dict[str, object]:
    try:
        result = service.sync_source(
            domain_id=domain_id,
            source_id=source_id,
            actor_id=_required_text(payload, "actor_id"),
            window_start=_optional_text(payload, "window_start"),
            window_end=_optional_text(payload, "window_end"),
            cursor=_optional_text(payload, "cursor"),
        )
    except SourceConfigNotFoundError as exc:
        raise HTTPException(status_code=404, detail="SourceConnector not found") from exc
    except SourceUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _sync_result_payload(result)


@router.post("/source-runs/{run_id}:retry")
async def retry_source_run(
    run_id: str,
    payload: Annotated[dict[str, Any], Body()],
    service: Annotated[SourceUpdateService, Depends(get_source_service)],
    domain_id: Annotated[str, Query()] = DEFAULT_DOMAIN_ID,
) -> dict[str, object]:
    try:
        result = service.retry_run(
            domain_id=domain_id,
            run_id=run_id,
            actor_id=_required_text(payload, "actor_id"),
        )
    except SourceRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="SourceSyncRun not found") from exc
    except SourceUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _sync_result_payload(result)


@router.get("/source-runs")
async def list_source_runs(
    service: Annotated[SourceUpdateService, Depends(get_source_service)],
    domain_id: Annotated[str, Query()] = DEFAULT_DOMAIN_ID,
) -> dict[str, object]:
    runs = service.list_runs(domain_id=domain_id)
    return {
        "domain_id": domain_id,
        "runs": [_run_payload(run) for run in runs],
    }


@router.get("/source-runs/{run_id}")
async def get_source_run(
    run_id: str,
    service: Annotated[SourceUpdateService, Depends(get_source_service)],
    domain_id: Annotated[str, Query()] = DEFAULT_DOMAIN_ID,
) -> dict[str, object]:
    try:
        run = service.get_run(domain_id=domain_id, run_id=run_id)
    except SourceRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="SourceSyncRun not found") from exc
    return {
        **_run_payload(run),
        "artifacts": [
            _artifact_payload(record)
            for record in service.artifact_records_for_run(domain_id=domain_id, run_id=run_id)
        ],
    }


@router.post("/domains/{domain_id}/sources:manual-sync")
async def manual_source_sync(
    domain_id: str,
    files: Annotated[list[UploadFile], File(description="PDF or Markdown files")],
    service: Annotated[SourceUpdateService, Depends(get_source_service)],
    actor_id: Annotated[str, Form()] = "admin-ui",
) -> dict[str, object]:
    uploads: list[DocumentUpload] = []
    for file in files:
        uploads.append(
            DocumentUpload(
                filename=file.filename or "upload",
                content=await file.read(),
                media_type=file.content_type,
            )
        )
    try:
        result = service.sync_manual_files(
            domain_id=domain_id,
            actor_id=actor_id,
            uploads=tuple(uploads),
        )
    except SourceUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _sync_result_payload(result)


def _sync_result_payload(result: SourceSyncResult) -> dict[str, object]:
    return {
        "run": _run_payload(result.run),
        "artifacts": [_artifact_payload(record) for record in result.artifact_records],
    }


def _source_payload(source: SourceConnectorConfig) -> dict[str, object]:
    return {
        "id": source.id,
        "domain_id": source.domain_id,
        "name": source.name,
        "connector_type": source.connector_type.value,
        "enabled": source.enabled,
        "max_attempts": source.max_attempts,
        "schedule": {
            "enabled": source.schedule.enabled,
            "interval_seconds": source.schedule.interval_seconds,
            "cron": source.schedule.cron,
            "timezone": source.schedule.timezone,
            "next_cursor": source.schedule.next_cursor,
        },
        "config": source.config,
        "created_by": source.created_by,
        "created_at": source.created_at,
        "updated_at": source.updated_at,
    }


def _run_payload(run: SourceSyncRun) -> dict[str, object]:
    return {
        "id": run.id,
        "domain_id": run.domain_id,
        "source_id": run.source_id,
        "status": run.status.value,
        "actor_id": run.actor_id,
        "attempt": run.attempt,
        "max_attempts": run.max_attempts,
        "retried_from_run_id": run.retried_from_run_id,
        "window_start": run.window_start,
        "window_end": run.window_end,
        "cursor": run.cursor,
        "raw_response_uri": run.raw_response_ref.storage_uri if run.raw_response_ref else None,
        "artifact_ids": list(run.artifact_ids),
        "document_ids": list(run.document_ids),
        "candidate_run_ids": list(run.candidate_run_ids),
        "review_batch_ids": list(run.review_batch_ids),
        "duplicate_count": run.duplicate_count,
        "failed_artifact_count": run.failed_artifact_count,
        "impact_summary": run.impact_summary,
        "error": run.error,
        "created_at": run.created_at,
    }


def _artifact_payload(record: SourceArtifactRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "domain_id": record.domain_id,
        "source_id": record.source_id,
        "run_id": record.run_id,
        "kind": record.kind.value,
        "status": record.status.value,
        "idempotency_key": record.idempotency_key,
        "raw_uri": record.raw_object_ref.storage_uri if record.raw_object_ref else None,
        "external_id": record.external_id,
        "filename": record.filename,
        "source_uri": record.source_uri,
        "document_id": record.document_id,
        "candidate_run_id": record.candidate_run_id,
        "review_batch_id": record.review_batch_id,
        "message": record.message,
        "metadata": record.metadata,
        "created_at": record.created_at,
    }


def _schedule_from_payload(payload: dict[str, Any]) -> SourceSchedule:
    return SourceSchedule(
        enabled=bool(payload.get("enabled", False)),
        interval_seconds=_optional_int(payload, "interval_seconds"),
        cron=_optional_text(payload, "cron"),
        timezone=str(payload.get("timezone", "UTC")),
        next_cursor=_optional_text(payload, "next_cursor"),
    )


def _required_text(payload: dict[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(status_code=422, detail=f"{field_name} is required")
    return value.strip()


def _optional_text(payload: dict[str, Any], field_name: str) -> str | None:
    value = payload.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail=f"{field_name} must be a string")
    text = value.strip()
    return text or None


def _optional_dict(payload: dict[str, Any], field_name: str) -> dict[str, Any] | None:
    value = payload.get(field_name)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise HTTPException(status_code=422, detail=f"{field_name} must be an object")
    return value


def _optional_int(payload: dict[str, Any], field_name: str) -> int | None:
    value = payload.get(field_name)
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value)
    raise HTTPException(status_code=422, detail=f"{field_name} must be an integer")
