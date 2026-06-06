"""Document upload, deduplication and parsing use cases."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from hashlib import sha256
from uuid import uuid4

from lingshu_domain import SourceChunk
from lingshu_domain.validation import require_domain_id, require_text
from lingshu_nexus.documents.models import (
    DocumentRecord,
    DocumentStatus,
    DocumentUpload,
    DocumentUploadResult,
)
from lingshu_nexus.documents.parsers import (
    DocumentParseError,
    DocumentParseRequest,
    DocumentParser,
    UnsupportedDocumentTypeError,
    canonical_media_type,
)
from lingshu_nexus.documents.repository import DocumentRepository
from lingshu_nexus.persistence.models import DataLayer, JobRun, JobStatus
from lingshu_nexus.persistence.object_store import ObjectStore


class DocumentIngestService:
    def __init__(
        self,
        *,
        repository: DocumentRepository,
        object_store: ObjectStore,
        parser: DocumentParser,
        max_upload_bytes: int,
    ) -> None:
        if max_upload_bytes < 1:
            raise ValueError("max_upload_bytes must be >= 1")
        self._repository = repository
        self._object_store = object_store
        self._parser = parser
        self._max_upload_bytes = max_upload_bytes

    def batch_upload(
        self,
        *,
        domain_id: str,
        uploads: tuple[DocumentUpload, ...],
    ) -> tuple[DocumentUploadResult, ...]:
        require_domain_id(domain_id)
        return tuple(self._upload_one(domain_id=domain_id, upload=upload) for upload in uploads)

    def list_documents(self, *, domain_id: str) -> tuple[DocumentRecord, ...]:
        return self._repository.list(domain_id=domain_id)

    def get_document(self, *, domain_id: str, document_id: str) -> DocumentRecord:
        return self._repository.get(domain_id=domain_id, document_id=document_id)

    def reprocess(self, *, domain_id: str, document_id: str) -> DocumentRecord:
        record = self.get_document(domain_id=domain_id, document_id=document_id)
        if record.raw_object_ref is None:
            raise DocumentParseError("Document has no stored raw object to reprocess")
        content = self._object_store.get(record.raw_object_ref, domain_id=domain_id)
        return self._parse_and_store(record=record, content=content)

    def _upload_one(self, *, domain_id: str, upload: DocumentUpload) -> DocumentUploadResult:
        if len(upload.content) > self._max_upload_bytes:
            return DocumentUploadResult(
                filename=upload.filename,
                accepted=False,
                duplicate=False,
                message=(
                    f"File exceeds max upload size of {self._max_upload_bytes} bytes: "
                    f"{len(upload.content)}"
                ),
            )

        content_hash = sha256(upload.content).hexdigest()
        existing = self._repository.find_by_hash(domain_id=domain_id, content_hash=content_hash)
        if existing is not None:
            return DocumentUploadResult(
                filename=upload.filename,
                accepted=True,
                duplicate=True,
                document=existing,
                message="Duplicate content hash; existing document returned",
            )

        document_id = f"doc_{uuid4().hex}"
        media_type = canonical_media_type(upload.filename, upload.media_type) or (
            upload.media_type or "application/octet-stream"
        )
        raw_object_ref = self._object_store.put(
            domain_id=domain_id,
            object_key=f"documents/{document_id}/raw/{_safe_filename(upload.filename)}",
            content=upload.content,
            layer=DataLayer.RAW,
            media_type=media_type,
            version=1,
        )
        record = DocumentRecord(
            id=document_id,
            domain_id=domain_id,
            title=upload.title or _title_from_filename(upload.filename),
            filename=upload.filename,
            media_type=media_type,
            content_hash=content_hash,
            byte_size=len(upload.content),
            status=DocumentStatus.DEDUP_CHECKED,
            file_version=1,
            raw_object_ref=raw_object_ref,
            topic_tags=upload.topic_tags,
            source_uri=raw_object_ref.storage_uri,
            status_history=(DocumentStatus.UPLOADED, DocumentStatus.DEDUP_CHECKED),
        )
        self._repository.add(record)
        parsed_record = self._parse_and_store(record=record, content=upload.content)
        return DocumentUploadResult(
            filename=upload.filename,
            accepted=True,
            duplicate=False,
            document=parsed_record,
        )

    def _parse_and_store(self, *, record: DocumentRecord, content: bytes) -> DocumentRecord:
        attempt = record.parse_attempts + 1
        job_id = f"job_{uuid4().hex}"
        running_job = JobRun(
            id=job_id,
            domain_id=record.domain_id,
            job_type="parse_document",
            status=JobStatus.RUNNING,
            input_ref=f"document:{record.id}:attempt:{attempt}",
        )
        try:
            parsed = self._parser.parse(
                DocumentParseRequest(
                    domain_id=record.domain_id,
                    document_id=record.id,
                    filename=record.filename,
                    content=content,
                    media_type=record.media_type,
                    title_hint=_manual_title_hint(record),
                )
            )
            parsed_json = json.dumps(
                {
                    "document_id": record.id,
                    "parser_version": parsed.parser_version,
                    "chunks": [_chunk_to_json(chunk) for chunk in parsed.chunks],
                },
                ensure_ascii=False,
            ).encode("utf-8")
            parsed_ref = self._object_store.put(
                domain_id=record.domain_id,
                object_key=f"documents/{record.id}/parsed/chunks.json",
                content=parsed_json,
                layer=DataLayer.PARSED,
                media_type="application/json",
                version=attempt,
            )
            updated = replace(
                record,
                title=parsed.title,
                status=DocumentStatus.PARSED,
                parsed_object_ref=parsed_ref,
                parser_version=parsed.parser_version,
                failure_reason=None,
                chunks=parsed.chunks,
                parse_attempts=attempt,
                status_history=(*record.status_history, DocumentStatus.PARSED),
            )
            self._repository.update(updated)
            self._repository.add_job_run(
                replace(running_job, status=JobStatus.SUCCEEDED, output_ref=parsed_ref.storage_uri)
            )
            return updated
        except (DocumentParseError, UnsupportedDocumentTypeError) as exc:
            updated = replace(
                record,
                status=DocumentStatus.PARSE_FAILED,
                failure_reason=str(exc),
                chunks=(),
                parse_attempts=attempt,
                status_history=(*record.status_history, DocumentStatus.PARSE_FAILED),
            )
            self._repository.update(updated)
            self._repository.add_job_run(
                replace(running_job, status=JobStatus.FAILED, error=str(exc))
            )
            return updated


def _chunk_to_json(chunk: SourceChunk) -> dict[str, object]:
    return {
        "id": chunk.id,
        "domain_id": chunk.domain_id,
        "document_id": chunk.document_id,
        "locator": {
            "chunk_index": chunk.locator.chunk_index,
            "page": chunk.locator.page,
            "heading": chunk.locator.heading,
            "paragraph": chunk.locator.paragraph,
            "reference": chunk.locator.as_reference(),
        },
        "text": chunk.text,
        "parser_version": chunk.parser_version,
        "embedding_version": chunk.embedding_version,
    }


def _safe_filename(filename: str) -> str:
    require_text(filename, "filename")
    name = filename.rsplit("/", maxsplit=1)[-1]
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name) or "upload.bin"


def _title_from_filename(filename: str) -> str:
    safe_name = _safe_filename(filename)
    return safe_name.rsplit(".", maxsplit=1)[0] or "untitled"


def _manual_title_hint(record: DocumentRecord) -> str | None:
    filename_title = _title_from_filename(record.filename)
    if record.title == filename_title:
        return None
    return record.title
