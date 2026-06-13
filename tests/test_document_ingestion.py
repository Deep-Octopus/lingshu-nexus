# ruff: noqa: E402

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "lingshu-domain" / "src"))

warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated.*",
    category=Warning,
)
from fastapi.testclient import TestClient

from lingshu_domain import SchemaValidationError
from lingshu_nexus.api.main import create_app
from lingshu_nexus.documents import (
    CompositeDocumentParser,
    DocumentIngestService,
    DocumentStatus,
    DocumentUpload,
    InMemoryDocumentRepository,
    MarkdownDocumentParser,
    PyPdfDocumentParser,
)
from lingshu_nexus.persistence.migrations import load_migration_pair
from lingshu_nexus.persistence.models import DataLayer, JobStatus
from lingshu_nexus.persistence.object_store import (
    DuplicateObjectError,
    InMemoryObjectStore,
    LocalFilesystemObjectStore,
)


class DocumentIngestionTestCase(unittest.TestCase):
    def test_markdown_upload_generates_heading_and_paragraph_locators(self) -> None:
        service, _, store = _service()
        result = service.batch_upload(
            domain_id="acupuncture",
            uploads=(
                DocumentUpload(
                    filename="tvns-note.md",
                    media_type="text/markdown",
                    content=(
                        b"# taVNS sleep study\n\n"
                        b"First paragraph about cymba conchae stimulation.\n\n"
                        b"## Outcomes\n\n"
                        b"Sleep quality improved in the fixture text.\n"
                    ),
                    topic_tags=("tVNS",),
                ),
            ),
        )[0]

        self.assertTrue(result.accepted)
        self.assertFalse(result.duplicate)
        self.assertIsNotNone(result.document)
        document = result.document
        assert document is not None
        self.assertEqual(document.status, DocumentStatus.PARSED)
        self.assertEqual(document.title, "taVNS sleep study")
        self.assertEqual(len(document.chunks), 2)
        self.assertEqual(document.chunks[0].locator.heading, "taVNS sleep study")
        self.assertEqual(document.chunks[0].locator.paragraph, 1)
        self.assertEqual(document.chunks[1].locator.heading, "Outcomes")
        self.assertEqual(document.chunks[1].locator.paragraph, 2)
        self.assertIn(DocumentStatus.DEDUP_CHECKED, document.status_history)
        self.assertIsNotNone(document.raw_object_ref)
        self.assertIsNotNone(document.parsed_object_ref)
        assert document.raw_object_ref is not None
        assert document.parsed_object_ref is not None
        self.assertEqual(
            store.record_for(document.raw_object_ref, domain_id="acupuncture").layer,
            DataLayer.RAW,
        )
        self.assertEqual(
            store.record_for(document.parsed_object_ref, domain_id="acupuncture").layer,
            DataLayer.PARSED,
        )

    def test_pdf_upload_generates_page_locator(self) -> None:
        service, _, _ = _service()
        result = service.batch_upload(
            domain_id="acupuncture",
            uploads=(
                DocumentUpload(
                    filename="fixture.pdf",
                    media_type="application/pdf",
                    content=_minimal_pdf_bytes(
                        ("PDF fixture title", "Paragraph one text for page one.")
                    ),
                ),
            ),
        )[0]

        self.assertTrue(result.accepted)
        document = result.document
        assert document is not None
        self.assertEqual(document.status, DocumentStatus.PARSED)
        self.assertEqual(len(document.chunks), 1)
        self.assertEqual(document.chunks[0].locator.page, 1)
        self.assertEqual(document.chunks[0].locator.paragraph, 1)
        self.assertIn("PDF fixture title", document.chunks[0].text)

    def test_duplicate_upload_returns_existing_document_without_new_record(self) -> None:
        service, repository, _ = _service()
        upload = DocumentUpload(
            filename="duplicate.md",
            media_type="text/markdown",
            content=b"# Duplicate\n\nSame content.\n",
        )
        first = service.batch_upload(domain_id="acupuncture", uploads=(upload,))[0]
        second = service.batch_upload(domain_id="acupuncture", uploads=(upload,))[0]

        self.assertFalse(first.duplicate)
        self.assertTrue(second.duplicate)
        self.assertEqual(first.document_id, second.document_id)
        self.assertEqual(len(repository.list(domain_id="acupuncture")), 1)

    def test_unsupported_file_enters_failed_status_without_blocking_batch(self) -> None:
        service, repository, _ = _service()
        parsed, failed = service.batch_upload(
            domain_id="acupuncture",
            uploads=(
                DocumentUpload(
                    filename="ok.md",
                    media_type="text/markdown",
                    content=b"# OK\n\nParsed content.\n",
                ),
                DocumentUpload(
                    filename="notes.txt",
                    media_type="text/plain",
                    content=b"Unsupported plain text fixture.",
                ),
            ),
        )

        assert parsed.document is not None
        assert failed.document is not None
        self.assertEqual(parsed.document.status, DocumentStatus.PARSED)
        self.assertEqual(failed.document.status, DocumentStatus.PARSE_FAILED)
        self.assertIn("Unsupported document type", failed.document.failure_reason or "")
        self.assertEqual(len(repository.list(domain_id="acupuncture")), 2)

    def test_parse_failure_can_be_reprocessed_and_records_attempts(self) -> None:
        service, repository, _ = _service()
        result = service.batch_upload(
            domain_id="acupuncture",
            uploads=(
                DocumentUpload(
                    filename="broken.pdf",
                    media_type="application/pdf",
                    content=b"not a pdf",
                ),
            ),
        )[0]
        assert result.document is not None
        self.assertEqual(result.document.status, DocumentStatus.PARSE_FAILED)

        reprocessed = service.reprocess(
            domain_id="acupuncture",
            document_id=result.document.id,
        )

        self.assertEqual(reprocessed.status, DocumentStatus.PARSE_FAILED)
        self.assertEqual(reprocessed.parse_attempts, 2)
        job_runs = repository.job_runs_for(
            domain_id="acupuncture",
            document_id=result.document.id,
        )
        self.assertEqual(len(job_runs), 2)
        self.assertTrue(all(job.status is JobStatus.FAILED for job in job_runs))

    def test_size_limit_rejects_without_formal_document_record(self) -> None:
        service, repository, _ = _service(max_upload_bytes=4)
        result = service.batch_upload(
            domain_id="acupuncture",
            uploads=(
                DocumentUpload(
                    filename="too-large.md",
                    media_type="text/markdown",
                    content=b"12345",
                ),
            ),
        )[0]

        self.assertFalse(result.accepted)
        self.assertIsNone(result.document)
        self.assertEqual(repository.list(domain_id="acupuncture"), ())

    def test_local_filesystem_object_store_is_immutable_and_readable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = LocalFilesystemObjectStore(temp_dir)
            ref = store.put(
                domain_id="acupuncture",
                object_key="documents/doc_001/raw/file.md",
                content=b"raw",
                layer=DataLayer.RAW,
                media_type="text/markdown",
                version=1,
            )

            self.assertEqual(store.get(ref, domain_id="acupuncture"), b"raw")
            self.assertEqual(store.record_for(ref, domain_id="acupuncture").byte_size, 3)
            with self.assertRaises(DuplicateObjectError):
                store.put(
                    domain_id="acupuncture",
                    object_key="documents/doc_001/raw/file.md",
                    content=b"overwrite",
                    layer=DataLayer.RAW,
                    media_type="text/markdown",
                    version=1,
                )
            with self.assertRaises(SchemaValidationError):
                store.put(
                    domain_id="../bad",
                    object_key="documents/doc_001/raw/file.md",
                    content=b"raw",
                    layer=DataLayer.RAW,
                    media_type="text/markdown",
                    version=1,
                )

    def test_document_ingestion_migration_can_apply_and_drop(self) -> None:
        foundation = load_migration_pair("0001_foundation")
        ingestion = load_migration_pair("0002_document_ingestion")
        connection = sqlite3.connect(":memory:")
        try:
            connection.executescript(foundation.up_sql)
            connection.executescript(ingestion.up_sql)
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            self.assertIn("document_ingest_records", tables)
            connection.executescript(ingestion.down_sql)
            connection.executescript(foundation.down_sql)
            remaining = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
            self.assertEqual(remaining, [])
        finally:
            connection.close()

    def test_fastapi_batch_upload_list_and_detail_routes(self) -> None:
        service, _, _ = _service()
        app = create_app()
        app.state.document_service = service
        client = TestClient(app)

        upload_response = client.post(
            "/api/v1/domains/acupuncture/documents:batch-upload",
            files={
                "files": (
                    "api-fixture.md",
                    b"# API fixture\n\nA routed upload can be parsed.",
                    "text/markdown",
                )
            },
        )

        self.assertEqual(upload_response.status_code, 200)
        upload_payload = upload_response.json()
        document_id = upload_payload["results"][0]["document_id"]
        self.assertEqual(upload_payload["results"][0]["status"], "PARSED")

        list_response = client.get("/api/v1/documents", params={"domain_id": "acupuncture"})
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.json()["documents"][0]["id"], document_id)

        detail_response = client.get(
            f"/api/v1/documents/{document_id}",
            params={"domain_id": "acupuncture"},
        )
        self.assertEqual(detail_response.status_code, 200)
        detail_payload = detail_response.json()
        self.assertEqual(detail_payload["chunks"][0]["locator"]["heading"], "API fixture")

    def test_fastapi_batch_upload_route_alias_without_colon(self) -> None:
        service, _, _ = _service()
        app = create_app()
        app.state.document_service = service
        client = TestClient(app)

        upload_response = client.post(
            "/api/v1/domains/acupuncture/documents/batch-upload",
            files={
                "files": (
                    "api-alias-fixture.md",
                    b"# API alias fixture\n\nA routed upload can avoid colon action paths.",
                    "text/markdown",
                )
            },
        )

        self.assertEqual(upload_response.status_code, 200)
        upload_payload = upload_response.json()
        self.assertEqual(upload_payload["results"][0]["status"], "PARSED")

    def test_fastapi_batch_upload_rejects_read_only_role(self) -> None:
        service, _, _ = _service()
        app = create_app()
        app.state.document_service = service
        client = TestClient(app)

        upload_response = client.post(
            "/api/v1/domains/acupuncture/documents:batch-upload",
            files={
                "files": (
                    "read-only-fixture.md",
                    b"# Read only\n\nUpload should be forbidden.",
                    "text/markdown",
                )
            },
            data={"actor_id": "readonly-ui", "actor_role": "read_only"},
        )

        self.assertEqual(upload_response.status_code, 403)


def _service(
    max_upload_bytes: int = 1024 * 1024,
) -> tuple[DocumentIngestService, InMemoryDocumentRepository, InMemoryObjectStore]:
    repository = InMemoryDocumentRepository()
    store = InMemoryObjectStore()
    parser = CompositeDocumentParser(
        markdown_parser=MarkdownDocumentParser(),
        pdf_parser=PyPdfDocumentParser(),
    )
    return (
        DocumentIngestService(
            repository=repository,
            object_store=store,
            parser=parser,
            max_upload_bytes=max_upload_bytes,
        ),
        repository,
        store,
    )


def _minimal_pdf_bytes(lines: tuple[str, ...]) -> bytes:
    text_commands = ["BT", "/F1 12 Tf", "72 720 Td"]
    for index, line in enumerate(lines):
        if index > 0:
            text_commands.append("0 -20 Td")
        text_commands.append(f"({_pdf_escape(line)}) Tj")
    text_commands.append("ET")
    stream = " ".join(text_commands).encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length "
        + str(len(stream)).encode("ascii")
        + b" >>\nstream\n"
        + stream
        + b"\nendstream",
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for object_number, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{object_number} 0 obj\n".encode("ascii"))
        pdf.extend(body)
        pdf.extend(b"\nendobj\n")
    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(pdf)


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


if __name__ == "__main__":
    unittest.main()
