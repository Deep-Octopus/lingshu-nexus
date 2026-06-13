"""Incremental source sync orchestration."""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from hashlib import sha256
from typing import Any
from uuid import uuid4

from lingshu_domain import Direction, EvidenceAssertion
from lingshu_domain.validation import require_text
from lingshu_nexus.documents import DocumentIngestService, DocumentStatus, DocumentUpload
from lingshu_nexus.extraction import CandidateExtractionService
from lingshu_nexus.observability import ObservabilityRecorder, ObservationStatus
from lingshu_nexus.persistence.models import DataLayer, JobStatus
from lingshu_nexus.persistence.object_store import ObjectRef, ObjectStore
from lingshu_nexus.review import ReviewReleaseService, ReviewWorkflowError
from lingshu_nexus.sources.connectors import (
    SourceConnector,
    SourceConnectorError,
    SourceFetchRequest,
)
from lingshu_nexus.sources.models import (
    SourceArtifact,
    SourceArtifactKind,
    SourceArtifactRecord,
    SourceArtifactStatus,
    SourceConnectorConfig,
    SourceConnectorType,
    SourceSchedule,
    SourceSyncResult,
    SourceSyncRun,
)
from lingshu_nexus.sources.repository import (
    SourceConfigNotFoundError,
    SourceRepository,
    SourceRunNotFoundError,
)


class SourceUpdateError(ValueError):
    """Raised when source sync cannot be executed safely."""


class SourceUpdateService:
    def __init__(
        self,
        *,
        repository: SourceRepository,
        object_store: ObjectStore,
        document_service: DocumentIngestService,
        extraction_service: CandidateExtractionService,
        review_service: ReviewReleaseService,
        connectors: Mapping[SourceConnectorType, SourceConnector],
        observability: ObservabilityRecorder | None = None,
    ) -> None:
        self._repository = repository
        self._object_store = object_store
        self._document_service = document_service
        self._extraction_service = extraction_service
        self._review_service = review_service
        self._connectors = dict(connectors)
        self._observability = observability

    def upsert_source(
        self,
        *,
        domain_id: str,
        source_id: str,
        name: str,
        connector_type: SourceConnectorType,
        config: dict[str, Any] | None = None,
        schedule: SourceSchedule | None = None,
        enabled: bool = True,
        max_attempts: int = 3,
        actor_id: str = "system",
        actor_role: str | None = None,
    ) -> SourceConnectorConfig:
        config_record = SourceConnectorConfig(
            id=source_id,
            domain_id=domain_id,
            name=name,
            connector_type=connector_type,
            config=config or {},
            schedule=schedule or SourceSchedule(),
            enabled=enabled,
            max_attempts=max_attempts,
            created_by=actor_id,
        )
        self._repository.upsert_config(config_record)
        self._review_service.record_audit_event(
            domain_id=domain_id,
            actor_id=actor_id,
            action="source.configured",
            target_type="source_connector",
            target_id=config_record.id,
            metadata={
                "connector_type": connector_type.value,
                "schedule_enabled": config_record.schedule.enabled,
                "actor_role": actor_role,
            },
        )
        return config_record

    def ensure_manual_source(
        self,
        *,
        domain_id: str,
        actor_id: str,
        actor_role: str | None = None,
    ) -> SourceConnectorConfig:
        try:
            return self._repository.get_config(domain_id=domain_id, source_id="manual-upload")
        except SourceConfigNotFoundError:
            return self.upsert_source(
                domain_id=domain_id,
                source_id="manual-upload",
                name="Manual upload",
                connector_type=SourceConnectorType.MANUAL_UPLOAD,
                config={"mode": "files"},
                actor_id=actor_id,
                actor_role=actor_role,
            )

    def list_sources(self, *, domain_id: str) -> tuple[SourceConnectorConfig, ...]:
        return self._repository.list_configs(domain_id=domain_id)

    def get_source(self, *, domain_id: str, source_id: str) -> SourceConnectorConfig:
        return self._repository.get_config(domain_id=domain_id, source_id=source_id)

    def list_runs(self, *, domain_id: str) -> tuple[SourceSyncRun, ...]:
        return self._repository.list_runs(domain_id=domain_id)

    def get_run(self, *, domain_id: str, run_id: str) -> SourceSyncRun:
        return self._repository.get_run(domain_id=domain_id, run_id=run_id)

    def artifact_records_for_run(
        self,
        *,
        domain_id: str,
        run_id: str,
    ) -> tuple[SourceArtifactRecord, ...]:
        return self._repository.list_artifact_records_for_run(domain_id=domain_id, run_id=run_id)

    def sync_source(
        self,
        *,
        domain_id: str,
        source_id: str,
        actor_id: str,
        window_start: str | None = None,
        window_end: str | None = None,
        cursor: str | None = None,
        retry_of_run_id: str | None = None,
    ) -> SourceSyncResult:
        config = self.get_source(domain_id=domain_id, source_id=source_id)
        if not config.enabled:
            raise SourceUpdateError(f"SourceConnector is disabled: {source_id}")
        connector = self._connectors.get(config.connector_type)
        if connector is None:
            raise SourceUpdateError(f"No adapter registered for {config.connector_type.value}")
        attempt = self._next_attempt(domain_id=domain_id, retry_of_run_id=retry_of_run_id)
        try:
            fetched = connector.fetch(
                config=config,
                request=SourceFetchRequest(
                    domain_id=domain_id,
                    window_start=window_start,
                    window_end=window_end,
                    cursor=cursor,
                ),
            )
        except SourceConnectorError as exc:
            return self._record_failed_run(
                config=config,
                actor_id=actor_id,
                attempt=attempt,
                retry_of_run_id=retry_of_run_id,
                window_start=window_start,
                window_end=window_end,
                cursor=cursor,
                error=str(exc),
            )
        raw_response_ref = self._store_raw_response(
            domain_id=domain_id,
            source_id=source_id,
            content=fetched.raw_response,
            media_type=fetched.raw_media_type,
        )
        return self._process_artifacts(
            config=config,
            artifacts=fetched.artifacts,
            actor_id=actor_id,
            attempt=attempt,
            retry_of_run_id=retry_of_run_id,
            window_start=window_start,
            window_end=window_end,
            cursor=cursor,
            raw_response_ref=raw_response_ref,
        )

    def sync_manual_files(
        self,
        *,
        domain_id: str,
        actor_id: str,
        uploads: tuple[DocumentUpload, ...],
        actor_role: str | None = None,
    ) -> SourceSyncResult:
        config = self.ensure_manual_source(
            domain_id=domain_id,
            actor_id=actor_id,
            actor_role=actor_role,
        )
        artifacts = tuple(
            SourceArtifact(
                id=f"manual_{uuid4().hex}",
                domain_id=domain_id,
                source_id=config.id,
                kind=SourceArtifactKind.FILE,
                external_id=upload.filename,
                filename=upload.filename,
                media_type=upload.media_type,
                content=upload.content,
                title=upload.title,
                topic_tags=upload.topic_tags,
                metadata={"ingest_mode": "manual_upload"},
            )
            for upload in uploads
        )
        return self._process_artifacts(
            config=config,
            artifacts=artifacts,
            actor_id=actor_id,
            attempt=1,
        )

    def retry_run(
        self,
        *,
        domain_id: str,
        run_id: str,
        actor_id: str,
    ) -> SourceSyncResult:
        run = self.get_run(domain_id=domain_id, run_id=run_id)
        if run.attempt >= run.max_attempts:
            raise SourceUpdateError(f"SourceSyncRun has reached max_attempts: {run_id}")
        return self.sync_source(
            domain_id=domain_id,
            source_id=run.source_id,
            actor_id=actor_id,
            window_start=run.window_start,
            window_end=run.window_end,
            cursor=run.cursor,
            retry_of_run_id=run.id,
        )

    def _process_artifacts(
        self,
        *,
        config: SourceConnectorConfig,
        artifacts: tuple[SourceArtifact, ...],
        actor_id: str,
        attempt: int,
        retry_of_run_id: str | None = None,
        window_start: str | None = None,
        window_end: str | None = None,
        cursor: str | None = None,
        raw_response_ref: ObjectRef | None = None,
    ) -> SourceSyncResult:
        require_text(actor_id, "actor_id")
        if not artifacts:
            return self._record_failed_run(
                config=config,
                actor_id=actor_id,
                attempt=attempt,
                retry_of_run_id=retry_of_run_id,
                window_start=window_start,
                window_end=window_end,
                cursor=cursor,
                error="SourceConnector returned no artifacts",
            )

        run_id = f"source_run_{uuid4().hex}"
        artifact_records: list[SourceArtifactRecord] = []
        document_ids: list[str] = []
        candidate_run_ids: list[str] = []
        review_batch_ids: list[str] = []
        failed_count = 0
        duplicate_count = 0
        impact_hints: list[dict[str, object]] = []

        for artifact in artifacts:
            idempotency_key = _artifact_idempotency_key(artifact)
            duplicate = self._repository.find_artifact_by_idempotency_key(
                domain_id=config.domain_id,
                idempotency_key=idempotency_key,
            )
            if duplicate is not None:
                duplicate_count += 1
                artifact_records.append(
                    SourceArtifactRecord(
                        id=f"source_artifact_{uuid4().hex}",
                        domain_id=config.domain_id,
                        source_id=config.id,
                        run_id=run_id,
                        kind=artifact.kind,
                        status=SourceArtifactStatus.DUPLICATE_SKIPPED,
                        idempotency_key=idempotency_key,
                        raw_object_ref=duplicate.raw_object_ref,
                        external_id=artifact.external_id,
                        filename=artifact.filename,
                        source_uri=artifact.source_uri,
                        document_id=duplicate.document_id,
                        candidate_run_id=duplicate.candidate_run_id,
                        review_batch_id=duplicate.review_batch_id,
                        message="Duplicate SourceArtifact idempotency key; skipped extraction",
                        metadata={"duplicate_of_artifact_id": duplicate.id},
                    )
                )
                continue

            raw_ref = self._store_artifact_raw(
                artifact=artifact,
                run_id=run_id,
                idempotency_key=idempotency_key,
            )
            upload = _upload_from_artifact(artifact)
            if upload is None:
                artifact_records.append(
                    SourceArtifactRecord(
                        id=f"source_artifact_{uuid4().hex}",
                        domain_id=config.domain_id,
                        source_id=config.id,
                        run_id=run_id,
                        kind=artifact.kind,
                        status=SourceArtifactStatus.RAW_STORED,
                        idempotency_key=idempotency_key,
                        raw_object_ref=raw_ref,
                        external_id=artifact.external_id,
                        filename=artifact.filename,
                        source_uri=artifact.source_uri,
                        message="Raw artifact retained; no document payload mapped yet",
                        metadata=artifact.metadata,
                    )
                )
                continue

            upload_result = self._document_service.batch_upload(
                domain_id=config.domain_id,
                uploads=(upload,),
            )[0]
            if not upload_result.accepted or upload_result.document is None:
                failed_count += 1
                artifact_records.append(
                    SourceArtifactRecord(
                        id=f"source_artifact_{uuid4().hex}",
                        domain_id=config.domain_id,
                        source_id=config.id,
                        run_id=run_id,
                        kind=artifact.kind,
                        status=SourceArtifactStatus.PARSE_FAILED,
                        idempotency_key=idempotency_key,
                        raw_object_ref=raw_ref,
                        external_id=artifact.external_id,
                        filename=artifact.filename,
                        source_uri=artifact.source_uri,
                        message=upload_result.message or "Document upload rejected",
                        metadata=artifact.metadata,
                    )
                )
                continue
            document = upload_result.document
            if upload_result.duplicate:
                duplicate_count += 1
                artifact_records.append(
                    SourceArtifactRecord(
                        id=f"source_artifact_{uuid4().hex}",
                        domain_id=config.domain_id,
                        source_id=config.id,
                        run_id=run_id,
                        kind=artifact.kind,
                        status=SourceArtifactStatus.DUPLICATE_SKIPPED,
                        idempotency_key=idempotency_key,
                        raw_object_ref=raw_ref,
                        external_id=artifact.external_id,
                        filename=artifact.filename,
                        source_uri=artifact.source_uri,
                        document_id=document.id,
                        message="Duplicate document content hash; skipped extraction",
                        metadata=artifact.metadata,
                    )
                )
                continue
            document_ids.append(document.id)
            if document.status is not DocumentStatus.PARSED:
                failed_count += 1
                artifact_records.append(
                    SourceArtifactRecord(
                        id=f"source_artifact_{uuid4().hex}",
                        domain_id=config.domain_id,
                        source_id=config.id,
                        run_id=run_id,
                        kind=artifact.kind,
                        status=SourceArtifactStatus.PARSE_FAILED,
                        idempotency_key=idempotency_key,
                        raw_object_ref=raw_ref,
                        external_id=artifact.external_id,
                        filename=artifact.filename,
                        source_uri=artifact.source_uri,
                        document_id=document.id,
                        message=document.failure_reason or "Document did not parse",
                        metadata=artifact.metadata,
                    )
                )
                continue

            extraction_run = self._extraction_service.extract_document(document)
            candidate_run_ids.append(extraction_run.id)
            if extraction_run.status is not JobStatus.SUCCEEDED:
                failed_count += 1
                artifact_records.append(
                    SourceArtifactRecord(
                        id=f"source_artifact_{uuid4().hex}",
                        domain_id=config.domain_id,
                        source_id=config.id,
                        run_id=run_id,
                        kind=artifact.kind,
                        status=SourceArtifactStatus.EXTRACTION_FAILED,
                        idempotency_key=idempotency_key,
                        raw_object_ref=raw_ref,
                        external_id=artifact.external_id,
                        filename=artifact.filename,
                        source_uri=artifact.source_uri,
                        document_id=document.id,
                        candidate_run_id=extraction_run.id,
                        message=extraction_run.failure_reason or "Candidate extraction failed",
                        metadata=artifact.metadata,
                    )
                )
                continue
            impact_hints.extend(
                _impact_hints(
                    new_assertions=extraction_run.evidence_assertions,
                    active_assertions=self._active_assertions(config.domain_id),
                )
            )
            try:
                review_batch = self._review_service.create_review_batch(
                    run=extraction_run,
                    source_chunks=document.chunks,
                    created_by=actor_id,
                )
            except ReviewWorkflowError as exc:
                failed_count += 1
                artifact_records.append(
                    SourceArtifactRecord(
                        id=f"source_artifact_{uuid4().hex}",
                        domain_id=config.domain_id,
                        source_id=config.id,
                        run_id=run_id,
                        kind=artifact.kind,
                        status=SourceArtifactStatus.EXTRACTION_FAILED,
                        idempotency_key=idempotency_key,
                        raw_object_ref=raw_ref,
                        external_id=artifact.external_id,
                        filename=artifact.filename,
                        source_uri=artifact.source_uri,
                        document_id=document.id,
                        candidate_run_id=extraction_run.id,
                        message=str(exc),
                        metadata=artifact.metadata,
                    )
                )
                continue
            review_batch_ids.append(review_batch.id)
            artifact_records.append(
                SourceArtifactRecord(
                    id=f"source_artifact_{uuid4().hex}",
                    domain_id=config.domain_id,
                    source_id=config.id,
                    run_id=run_id,
                    kind=artifact.kind,
                    status=SourceArtifactStatus.REVIEW_BATCH_CREATED,
                    idempotency_key=idempotency_key,
                    raw_object_ref=raw_ref,
                    external_id=artifact.external_id,
                    filename=artifact.filename,
                    source_uri=artifact.source_uri,
                    document_id=document.id,
                    candidate_run_id=extraction_run.id,
                    review_batch_id=review_batch.id,
                    message="Parsed, extracted, and queued for review",
                    metadata=artifact.metadata,
                )
            )

        status = JobStatus.FAILED if failed_count and not review_batch_ids else JobStatus.SUCCEEDED
        run = SourceSyncRun(
            id=run_id,
            domain_id=config.domain_id,
            source_id=config.id,
            status=status,
            actor_id=actor_id,
            idempotency_key=_run_idempotency_key(config, window_start, window_end, cursor),
            attempt=attempt,
            max_attempts=config.max_attempts,
            retried_from_run_id=retry_of_run_id,
            window_start=window_start,
            window_end=window_end,
            cursor=cursor,
            raw_response_ref=raw_response_ref,
            artifact_ids=tuple(record.id for record in artifact_records),
            document_ids=tuple(document_ids),
            candidate_run_ids=tuple(candidate_run_ids),
            review_batch_ids=tuple(review_batch_ids),
            duplicate_count=duplicate_count,
            failed_artifact_count=failed_count,
            impact_summary={
                "potential_conflict_count": len(impact_hints),
                "hints": impact_hints,
            },
            error=None if status is JobStatus.SUCCEEDED else "One or more artifacts failed",
        )
        self._repository.add_run(run)
        for record in artifact_records:
            self._repository.add_artifact_record(record)
        self._review_service.record_audit_event(
            domain_id=config.domain_id,
            actor_id=actor_id,
            action=(
                "source.sync_completed" if status is JobStatus.SUCCEEDED else "source.sync_failed"
            ),
            target_type="source_connector",
            target_id=config.id,
            metadata={
                "run_id": run.id,
                "status": run.status.value,
                "artifact_count": len(artifact_records),
                "document_count": len(document_ids),
                "review_batch_count": len(review_batch_ids),
                "duplicate_count": duplicate_count,
                "failed_artifact_count": failed_count,
            },
        )
        self._record_source_task_observation(
            run=run,
            status=ObservationStatus.SUCCEEDED
            if status is JobStatus.SUCCEEDED
            else ObservationStatus.FAILED,
            artifact_count=len(artifact_records),
        )
        return SourceSyncResult(run=run, artifact_records=tuple(artifact_records))

    def _record_failed_run(
        self,
        *,
        config: SourceConnectorConfig,
        actor_id: str,
        attempt: int,
        retry_of_run_id: str | None,
        window_start: str | None,
        window_end: str | None,
        cursor: str | None,
        error: str,
    ) -> SourceSyncResult:
        run = SourceSyncRun(
            id=f"source_run_{uuid4().hex}",
            domain_id=config.domain_id,
            source_id=config.id,
            status=JobStatus.FAILED,
            actor_id=actor_id,
            idempotency_key=_run_idempotency_key(config, window_start, window_end, cursor),
            attempt=attempt,
            max_attempts=config.max_attempts,
            retried_from_run_id=retry_of_run_id,
            window_start=window_start,
            window_end=window_end,
            cursor=cursor,
            failed_artifact_count=1,
            error=error,
        )
        artifact_record = SourceArtifactRecord(
            id=f"source_artifact_{uuid4().hex}",
            domain_id=config.domain_id,
            source_id=config.id,
            run_id=run.id,
            kind=SourceArtifactKind.JSON,
            status=SourceArtifactStatus.RAW_STORED,
            idempotency_key=f"failed:{run.id}",
            message=error,
        )
        self._repository.add_run(run)
        self._repository.add_artifact_record(artifact_record)
        self._review_service.record_audit_event(
            domain_id=config.domain_id,
            actor_id=actor_id,
            action="source.sync_failed",
            target_type="source_connector",
            target_id=config.id,
            metadata={"run_id": run.id, "error": error},
        )
        self._record_source_task_observation(
            run=run,
            status=ObservationStatus.FAILED,
            artifact_count=1,
            error=error,
        )
        return SourceSyncResult(run=run, artifact_records=(artifact_record,))

    def _store_raw_response(
        self,
        *,
        domain_id: str,
        source_id: str,
        content: bytes | None,
        media_type: str | None,
    ) -> ObjectRef | None:
        if content is None:
            return None
        return self._object_store.put(
            domain_id=domain_id,
            object_key=f"sources/{source_id}/responses/{uuid4().hex}.raw",
            content=content,
            layer=DataLayer.RAW,
            media_type=media_type or "application/octet-stream",
            version=1,
        )

    def _store_artifact_raw(
        self,
        *,
        artifact: SourceArtifact,
        run_id: str,
        idempotency_key: str,
    ) -> ObjectRef:
        safe_key = sha256(idempotency_key.encode("utf-8")).hexdigest()
        return self._object_store.put(
            domain_id=artifact.domain_id,
            object_key=f"sources/{artifact.source_id}/runs/{run_id}/artifacts/{safe_key}.raw",
            content=artifact.raw_bytes(),
            layer=DataLayer.RAW,
            media_type=artifact.raw_media_type(),
            version=1,
        )

    def _next_attempt(self, *, domain_id: str, retry_of_run_id: str | None) -> int:
        if retry_of_run_id is None:
            return 1
        try:
            run = self._repository.get_run(domain_id=domain_id, run_id=retry_of_run_id)
        except SourceRunNotFoundError as exc:
            raise SourceUpdateError(
                f"Cannot retry unknown SourceSyncRun: {retry_of_run_id}"
            ) from exc
        return run.attempt + 1

    def _active_assertions(self, domain_id: str) -> tuple[EvidenceAssertion, ...]:
        active = self._review_service.active_release(domain_id=domain_id)
        if active is None:
            return ()
        return active.assertions

    def _record_source_task_observation(
        self,
        *,
        run: SourceSyncRun,
        status: ObservationStatus,
        artifact_count: int,
        error: str | None = None,
    ) -> None:
        if self._observability is None:
            return
        self._observability.record(
            event_type="task.source_sync",
            status=status,
            domain_id=run.domain_id,
            actor_id=run.actor_id,
            target_type="source_connector",
            target_id=run.source_id,
            trace_id=run.id,
            metrics={
                "attempt": run.attempt,
                "artifact_count": artifact_count,
                "document_count": len(run.document_ids),
                "review_batch_count": len(run.review_batch_ids),
                "duplicate_count": run.duplicate_count,
                "failed_artifact_count": run.failed_artifact_count,
            },
            metadata={
                "retried_from_run_id": run.retried_from_run_id,
                "potential_conflict_count": run.impact_summary.get("potential_conflict_count", 0),
            },
            error=error or run.error,
        )


def _upload_from_artifact(artifact: SourceArtifact) -> DocumentUpload | None:
    if artifact.kind is SourceArtifactKind.FILE:
        assert artifact.filename is not None
        assert artifact.content is not None
        return DocumentUpload(
            filename=artifact.filename,
            content=artifact.content,
            media_type=artifact.media_type,
            title=artifact.title,
            topic_tags=artifact.topic_tags,
        )
    if artifact.kind is not SourceArtifactKind.JSON:
        return None
    payload = artifact.json_payload
    if not isinstance(payload, dict):
        return None
    document = payload.get("document")
    if not isinstance(document, dict):
        return None
    filename = _required_mapping_text(document, "filename")
    content = _document_content(document)
    return DocumentUpload(
        filename=filename,
        content=content,
        media_type=_optional_mapping_text(document, "media_type"),
        title=_optional_mapping_text(document, "title"),
        topic_tags=tuple(str(tag) for tag in _list_or_empty(document.get("topic_tags"))),
    )


def _document_content(document: dict[str, Any]) -> bytes:
    content_text = document.get("content_text")
    if isinstance(content_text, str):
        return content_text.encode("utf-8")
    content_base64 = document.get("content_base64")
    if isinstance(content_base64, str):
        return base64.b64decode(content_base64)
    raise SourceUpdateError("JSON document fixture requires content_text or content_base64")


def _impact_hints(
    *,
    new_assertions: tuple[EvidenceAssertion, ...],
    active_assertions: tuple[EvidenceAssertion, ...],
) -> list[dict[str, object]]:
    hints: list[dict[str, object]] = []
    for new_assertion in new_assertions:
        for active in active_assertions:
            if not _same_assertion_target(new_assertion, active):
                continue
            if _opposite_direction(new_assertion.direction, active.direction):
                hints.append(
                    {
                        "type": "potential_conflict",
                        "new_assertion_id": new_assertion.id,
                        "active_assertion_id": active.id,
                        "subject": new_assertion.subject.text,
                        "object": new_assertion.object.text,
                        "new_direction": new_assertion.direction.value,
                        "active_direction": active.direction.value,
                    }
                )
    return hints


def _same_assertion_target(left: EvidenceAssertion, right: EvidenceAssertion) -> bool:
    return (
        left.predicate == right.predicate
        and left.subject.text.lower() == right.subject.text.lower()
        and left.object.text.lower() == right.object.text.lower()
    )


def _opposite_direction(left: Direction, right: Direction) -> bool:
    return {left, right} == {Direction.IMPROVED, Direction.WORSENED}


def _artifact_idempotency_key(artifact: SourceArtifact) -> str:
    external = artifact.external_id or artifact.filename or artifact.source_uri or artifact.id
    return ":".join(
        (
            artifact.domain_id,
            artifact.source_id,
            artifact.kind.value,
            external,
            artifact.content_hash(),
        )
    )


def _run_idempotency_key(
    config: SourceConnectorConfig,
    window_start: str | None,
    window_end: str | None,
    cursor: str | None,
) -> str:
    payload = {
        "source_id": config.id,
        "window_start": window_start,
        "window_end": window_end,
        "cursor": cursor,
    }
    return sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _required_mapping_text(mapping: dict[str, Any], field_name: str) -> str:
    value = mapping.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise SourceUpdateError(f"document.{field_name} is required")
    return value.strip()


def _optional_mapping_text(mapping: dict[str, Any], field_name: str) -> str | None:
    value = mapping.get(field_name)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _list_or_empty(value: object) -> list[object]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise SourceUpdateError("topic_tags must be a list")
    return value
