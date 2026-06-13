"""Document ingestion application services."""

from lingshu_nexus.documents.models import (
    DocumentRecord,
    DocumentStatus,
    DocumentUpload,
    DocumentUploadResult,
    ParsedDocument,
)
from lingshu_nexus.documents.parsers import (
    CompositeDocumentParser,
    MarkdownDocumentParser,
    PyPdfDocumentParser,
)
from lingshu_nexus.documents.repository import InMemoryDocumentRepository
from lingshu_nexus.documents.service import DocumentIngestService
from lingshu_nexus.observability import ObservabilityRecorder
from lingshu_nexus.persistence.object_store import ObjectStore


def create_document_service(
    *,
    object_store: ObjectStore,
    max_upload_bytes: int,
    observability: ObservabilityRecorder | None = None,
) -> DocumentIngestService:
    parser = CompositeDocumentParser(
        markdown_parser=MarkdownDocumentParser(),
        pdf_parser=PyPdfDocumentParser(),
    )
    return DocumentIngestService(
        repository=InMemoryDocumentRepository(),
        object_store=object_store,
        parser=parser,
        max_upload_bytes=max_upload_bytes,
        observability=observability,
    )


__all__ = [
    "CompositeDocumentParser",
    "DocumentIngestService",
    "DocumentRecord",
    "DocumentStatus",
    "DocumentUpload",
    "DocumentUploadResult",
    "InMemoryDocumentRepository",
    "MarkdownDocumentParser",
    "ParsedDocument",
    "PyPdfDocumentParser",
    "create_document_service",
]
