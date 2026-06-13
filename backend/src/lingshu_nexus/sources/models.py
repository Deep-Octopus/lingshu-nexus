"""SourceConnector contracts and incremental sync records."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Any

from lingshu_domain.validation import (
    SchemaValidationError,
    require_domain_id,
    require_non_empty,
    require_text,
)
from lingshu_nexus.persistence.models import JobStatus
from lingshu_nexus.persistence.object_store import ObjectRef


def utcnow() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


class SourceArtifactKind(StrEnum):
    JSON = "json"
    FILE = "file"
    DOWNLOAD_REFERENCE = "download_reference"


class SourceConnectorType(StrEnum):
    MANUAL_UPLOAD = "manual_upload"
    FIXTURE = "fixture"
    GENERIC_REST = "generic_rest"


class SourceArtifactStatus(StrEnum):
    RAW_STORED = "raw_stored"
    DOCUMENT_PARSED = "document_parsed"
    DUPLICATE_SKIPPED = "duplicate_skipped"
    PARSE_FAILED = "parse_failed"
    EXTRACTION_FAILED = "extraction_failed"
    REVIEW_BATCH_CREATED = "review_batch_created"


@dataclass(frozen=True)
class SourceSchedule:
    enabled: bool = False
    interval_seconds: int | None = None
    cron: str | None = None
    timezone: str = "UTC"
    next_cursor: str | None = None

    def __post_init__(self) -> None:
        if self.interval_seconds is not None and self.interval_seconds < 1:
            raise SchemaValidationError("SourceSchedule.interval_seconds must be >= 1")
        if self.enabled and self.interval_seconds is None and not self.cron:
            raise SchemaValidationError("Enabled SourceSchedule requires interval_seconds or cron")


@dataclass(frozen=True)
class SourceConnectorConfig:
    id: str
    domain_id: str
    name: str
    connector_type: SourceConnectorType
    config: dict[str, Any] = field(default_factory=dict)
    schedule: SourceSchedule = field(default_factory=SourceSchedule)
    enabled: bool = True
    max_attempts: int = 3
    created_by: str = "system"
    created_at: str = field(default_factory=utcnow)
    updated_at: str = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        require_text(self.id, "SourceConnectorConfig.id")
        require_domain_id(self.domain_id)
        require_text(self.name, "SourceConnectorConfig.name")
        require_text(self.created_by, "SourceConnectorConfig.created_by")
        if self.max_attempts < 1:
            raise SchemaValidationError("SourceConnectorConfig.max_attempts must be >= 1")
        _reject_inline_secret_keys(self.config)


@dataclass(frozen=True)
class SourceArtifact:
    id: str
    domain_id: str
    source_id: str
    kind: SourceArtifactKind
    external_id: str | None = None
    filename: str | None = None
    media_type: str | None = None
    content: bytes | None = None
    json_payload: dict[str, Any] | list[Any] | None = None
    source_uri: str | None = None
    title: str | None = None
    topic_tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_text(self.id, "SourceArtifact.id")
        require_domain_id(self.domain_id)
        require_text(self.source_id, "SourceArtifact.source_id")
        if self.kind is SourceArtifactKind.FILE:
            if self.content is None:
                raise SchemaValidationError("File SourceArtifact requires content")
            require_text(self.filename or "", "SourceArtifact.filename")
        if self.kind is SourceArtifactKind.JSON and self.json_payload is None:
            raise SchemaValidationError("JSON SourceArtifact requires json_payload")
        if self.kind is SourceArtifactKind.DOWNLOAD_REFERENCE:
            require_text(self.source_uri or "", "SourceArtifact.source_uri")

    def raw_bytes(self) -> bytes:
        if self.kind is SourceArtifactKind.FILE:
            assert self.content is not None
            return self.content
        if self.kind is SourceArtifactKind.JSON:
            return json.dumps(
                self.json_payload,
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        return json.dumps(
            {
                "source_uri": self.source_uri,
                "external_id": self.external_id,
                "metadata": self.metadata,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")

    def raw_media_type(self) -> str:
        if self.kind is SourceArtifactKind.FILE:
            return self.media_type or "application/octet-stream"
        return "application/json"

    def content_hash(self) -> str:
        return sha256(self.raw_bytes()).hexdigest()


@dataclass(frozen=True)
class SourceArtifactRecord:
    id: str
    domain_id: str
    source_id: str
    run_id: str
    kind: SourceArtifactKind
    status: SourceArtifactStatus
    idempotency_key: str
    raw_object_ref: ObjectRef | None = None
    external_id: str | None = None
    filename: str | None = None
    source_uri: str | None = None
    document_id: str | None = None
    candidate_run_id: str | None = None
    review_batch_id: str | None = None
    message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        require_text(self.id, "SourceArtifactRecord.id")
        require_domain_id(self.domain_id)
        require_text(self.source_id, "SourceArtifactRecord.source_id")
        require_text(self.run_id, "SourceArtifactRecord.run_id")
        require_text(self.idempotency_key, "SourceArtifactRecord.idempotency_key")


@dataclass(frozen=True)
class SourceSyncRun:
    id: str
    domain_id: str
    source_id: str
    status: JobStatus
    actor_id: str
    idempotency_key: str
    attempt: int = 1
    max_attempts: int = 3
    retried_from_run_id: str | None = None
    window_start: str | None = None
    window_end: str | None = None
    cursor: str | None = None
    raw_response_ref: ObjectRef | None = None
    artifact_ids: tuple[str, ...] = ()
    document_ids: tuple[str, ...] = ()
    candidate_run_ids: tuple[str, ...] = ()
    review_batch_ids: tuple[str, ...] = ()
    duplicate_count: int = 0
    failed_artifact_count: int = 0
    impact_summary: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    created_at: str = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        require_text(self.id, "SourceSyncRun.id")
        require_domain_id(self.domain_id)
        require_text(self.source_id, "SourceSyncRun.source_id")
        require_text(self.actor_id, "SourceSyncRun.actor_id")
        require_text(self.idempotency_key, "SourceSyncRun.idempotency_key")
        if self.attempt < 1:
            raise SchemaValidationError("SourceSyncRun.attempt must be >= 1")
        if self.max_attempts < 1:
            raise SchemaValidationError("SourceSyncRun.max_attempts must be >= 1")
        for field_name, value in (
            ("duplicate_count", self.duplicate_count),
            ("failed_artifact_count", self.failed_artifact_count),
        ):
            if value < 0:
                raise SchemaValidationError(f"SourceSyncRun.{field_name} must be >= 0")


@dataclass(frozen=True)
class SourceSyncResult:
    run: SourceSyncRun
    artifact_records: tuple[SourceArtifactRecord, ...]

    def __post_init__(self) -> None:
        require_non_empty(self.artifact_records, "SourceSyncResult.artifact_records")


def _reject_inline_secret_keys(value: object, path: str = "config") -> None:
    sensitive_parts = ("api_key", "apikey", "token", "password", "secret")
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key).lower()
            if any(part in key_text for part in sensitive_parts):
                raise SchemaValidationError(
                    f"SourceConnectorConfig.{path}.{key} must use a secret reference"
                )
            _reject_inline_secret_keys(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_inline_secret_keys(item, f"{path}[{index}]")
