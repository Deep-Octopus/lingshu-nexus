"""Document ingestion records and DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from lingshu_domain import SourceChunk, SourceDocument, SourceQualityTier
from lingshu_domain.validation import SchemaValidationError, require_domain_id, require_text
from lingshu_nexus.persistence.object_store import ObjectRef


def _utcnow() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


class DocumentStatus(StrEnum):
    UPLOADED = "UPLOADED"
    DEDUP_CHECKED = "DEDUP_CHECKED"
    PARSED = "PARSED"
    PARSE_FAILED = "PARSE_FAILED"


@dataclass(frozen=True)
class DocumentUpload:
    filename: str
    content: bytes
    media_type: str | None = None
    title: str | None = None
    topic_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_text(self.filename, "DocumentUpload.filename")


@dataclass(frozen=True)
class ParsedDocument:
    title: str
    chunks: tuple[SourceChunk, ...]
    parser_version: str

    def __post_init__(self) -> None:
        require_text(self.title, "ParsedDocument.title")
        require_text(self.parser_version, "ParsedDocument.parser_version")
        if not self.chunks:
            raise SchemaValidationError("ParsedDocument.chunks must not be empty")


@dataclass(frozen=True)
class DocumentRecord:
    id: str
    domain_id: str
    title: str
    filename: str
    media_type: str
    content_hash: str
    byte_size: int
    status: DocumentStatus
    file_version: int
    raw_object_ref: ObjectRef | None = None
    parsed_object_ref: ObjectRef | None = None
    parser_version: str | None = None
    failure_reason: str | None = None
    chunks: tuple[SourceChunk, ...] = ()
    topic_tags: tuple[str, ...] = ()
    source_uri: str | None = None
    parse_attempts: int = 0
    status_history: tuple[DocumentStatus, ...] = (DocumentStatus.UPLOADED,)
    source_quality_tier: SourceQualityTier = SourceQualityTier.UNKNOWN
    created_at: str = field(default_factory=_utcnow)
    updated_at: str = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        require_text(self.id, "DocumentRecord.id")
        require_domain_id(self.domain_id)
        require_text(self.title, "DocumentRecord.title")
        require_text(self.filename, "DocumentRecord.filename")
        require_text(self.media_type, "DocumentRecord.media_type")
        require_text(self.content_hash, "DocumentRecord.content_hash")
        if self.byte_size < 0:
            raise SchemaValidationError("DocumentRecord.byte_size must be >= 0")
        if self.file_version < 1:
            raise SchemaValidationError("DocumentRecord.file_version must be >= 1")
        if self.parse_attempts < 0:
            raise SchemaValidationError("DocumentRecord.parse_attempts must be >= 0")

    def to_source_document(self) -> SourceDocument:
        return SourceDocument(
            id=self.id,
            domain_id=self.domain_id,
            title=self.title,
            content_hash=self.content_hash,
            file_version=self.file_version,
            source_uri=self.source_uri,
            topic_tags=self.topic_tags,
            source_quality_tier=self.source_quality_tier,
        )


@dataclass(frozen=True)
class DocumentUploadResult:
    filename: str
    accepted: bool
    duplicate: bool
    document: DocumentRecord | None = None
    message: str | None = None

    @property
    def document_id(self) -> str | None:
        if self.document is None:
            return None
        return self.document.id
