"""Database-facing records for the persistence foundation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from lingshu_domain.validation import SchemaValidationError, require_domain_id, require_text


def utcnow() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


class DataLayer(StrEnum):
    RAW = "raw"
    PARSED = "parsed"
    CANDIDATE = "candidate"
    PUBLISHED = "published"
    DERIVED = "derived"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


@dataclass(frozen=True)
class StoredObjectRecord:
    id: str
    domain_id: str
    layer: DataLayer
    object_key: str
    content_hash: str
    media_type: str
    byte_size: int
    version: int
    storage_uri: str

    def __post_init__(self) -> None:
        require_text(self.id, "StoredObjectRecord.id")
        require_domain_id(self.domain_id)
        require_text(self.object_key, "StoredObjectRecord.object_key")
        require_text(self.content_hash, "StoredObjectRecord.content_hash")
        require_text(self.media_type, "StoredObjectRecord.media_type")
        require_text(self.storage_uri, "StoredObjectRecord.storage_uri")
        if self.byte_size < 0:
            raise SchemaValidationError("StoredObjectRecord.byte_size must be >= 0")
        if self.version < 1:
            raise SchemaValidationError("StoredObjectRecord.version must be >= 1")


@dataclass(frozen=True)
class JobRun:
    id: str
    domain_id: str
    job_type: str
    status: JobStatus
    input_ref: str | None = None
    output_ref: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        require_text(self.id, "JobRun.id")
        require_domain_id(self.domain_id)
        require_text(self.job_type, "JobRun.job_type")


@dataclass(frozen=True)
class ConfigVersion:
    id: str
    domain_id: str
    config_type: str
    version: str
    checksum: str
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_text(self.id, "ConfigVersion.id")
        require_domain_id(self.domain_id)
        require_text(self.config_type, "ConfigVersion.config_type")
        require_text(self.version, "ConfigVersion.version")
        require_text(self.checksum, "ConfigVersion.checksum")


@dataclass(frozen=True)
class AuditEvent:
    id: str
    domain_id: str
    actor_id: str
    action: str
    target_type: str
    target_id: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        require_text(self.id, "AuditEvent.id")
        require_domain_id(self.domain_id)
        require_text(self.actor_id, "AuditEvent.actor_id")
        require_text(self.action, "AuditEvent.action")
        require_text(self.target_type, "AuditEvent.target_type")
        require_text(self.target_id, "AuditEvent.target_id")


@dataclass(frozen=True)
class GraphSyncRecord:
    id: str
    domain_id: str
    release_id: str
    graph_backend: str
    status: JobStatus
    synced_assertion_count: int = 0
    error: str | None = None

    def __post_init__(self) -> None:
        require_text(self.id, "GraphSyncRecord.id")
        require_domain_id(self.domain_id)
        require_text(self.release_id, "GraphSyncRecord.release_id")
        require_text(self.graph_backend, "GraphSyncRecord.graph_backend")
        if self.synced_assertion_count < 0:
            raise SchemaValidationError("GraphSyncRecord.synced_assertion_count must be >= 0")
