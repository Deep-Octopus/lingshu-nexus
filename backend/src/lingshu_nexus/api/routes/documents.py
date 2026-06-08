"""Document ingestion and literature status API routes."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile

from lingshu_domain import DEFAULT_DOMAIN_ID, SourceChunk
from lingshu_nexus.documents import DocumentIngestService, DocumentRecord, DocumentUpload
from lingshu_nexus.documents.parsers import DocumentParseError
from lingshu_nexus.documents.repository import DocumentNotFoundError

router = APIRouter(prefix="/api/v1", tags=["documents"])


def get_document_service(request: Request) -> DocumentIngestService:
    return cast(DocumentIngestService, request.app.state.document_service)


@router.post("/domains/{domain_id}/documents:batch-upload")
async def batch_upload_documents(
    domain_id: str,
    files: Annotated[list[UploadFile], File(description="PDF or Markdown files")],
    service: Annotated[DocumentIngestService, Depends(get_document_service)],
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
    results = service.batch_upload(domain_id=domain_id, uploads=tuple(uploads))
    return {
        "domain_id": domain_id,
        "results": [
            {
                "filename": result.filename,
                "accepted": result.accepted,
                "duplicate": result.duplicate,
                "document_id": result.document_id,
                "status": result.document.status.value if result.document else None,
                "message": result.message,
            }
            for result in results
        ],
    }


@router.get("/documents")
async def list_documents(
    service: Annotated[DocumentIngestService, Depends(get_document_service)],
    domain_id: Annotated[str, Query()] = DEFAULT_DOMAIN_ID,
) -> dict[str, object]:
    records = service.list_documents(domain_id=domain_id)
    return {"domain_id": domain_id, "documents": [_document_summary(record) for record in records]}


@router.get("/documents/{document_id}")
async def get_document(
    document_id: str,
    service: Annotated[DocumentIngestService, Depends(get_document_service)],
    domain_id: Annotated[str, Query()] = DEFAULT_DOMAIN_ID,
) -> dict[str, object]:
    try:
        record = service.get_document(domain_id=domain_id, document_id=document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Document not found") from exc
    return _document_detail(record)


@router.post("/documents/{document_id}:reprocess")
async def reprocess_document(
    document_id: str,
    service: Annotated[DocumentIngestService, Depends(get_document_service)],
    domain_id: Annotated[str, Query()] = DEFAULT_DOMAIN_ID,
) -> dict[str, object]:
    try:
        record = service.reprocess(domain_id=domain_id, document_id=document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Document not found") from exc
    except DocumentParseError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _document_detail(record)


def _document_summary(record: DocumentRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "domain_id": record.domain_id,
        "title": record.title,
        "filename": record.filename,
        "media_type": record.media_type,
        "content_hash": record.content_hash,
        "byte_size": record.byte_size,
        "status": record.status.value,
        "parser_version": record.parser_version,
        "failure_reason": record.failure_reason,
        "chunk_count": len(record.chunks),
        "parse_attempts": record.parse_attempts,
        "updated_at": record.updated_at,
    }


def _document_detail(record: DocumentRecord) -> dict[str, object]:
    return {
        **_document_summary(record),
        "source_uri": record.source_uri,
        "parsed_uri": record.parsed_object_ref.storage_uri if record.parsed_object_ref else None,
        "status_history": [status.value for status in record.status_history],
        "chunks": [_chunk_payload(chunk) for chunk in record.chunks],
    }


def _chunk_payload(chunk: SourceChunk) -> dict[str, object]:
    return {
        "id": chunk.id,
        "locator": {
            "chunk_index": chunk.locator.chunk_index,
            "page": chunk.locator.page,
            "heading": chunk.locator.heading,
            "paragraph": chunk.locator.paragraph,
            "reference": chunk.locator.as_reference(),
        },
        "text": chunk.text,
        "parser_version": chunk.parser_version,
    }
