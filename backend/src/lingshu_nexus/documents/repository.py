"""Document repository port and in-memory adapter."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from lingshu_domain.validation import require_domain_id, require_text
from lingshu_nexus.documents.models import DocumentRecord
from lingshu_nexus.persistence.models import JobRun


class DocumentNotFoundError(KeyError):
    """Raised when a document id is unknown in the requested domain."""


class DocumentRepository(Protocol):
    def add(self, record: DocumentRecord) -> None:
        """Persist a new document record."""

    def update(self, record: DocumentRecord) -> None:
        """Replace an existing document record."""

    def get(self, *, domain_id: str, document_id: str) -> DocumentRecord:
        """Return one document by domain and id."""

    def list(self, *, domain_id: str) -> tuple[DocumentRecord, ...]:
        """Return all documents for one domain."""

    def find_by_hash(self, *, domain_id: str, content_hash: str) -> DocumentRecord | None:
        """Find the existing formal document for the same bytes in one domain."""

    def add_job_run(self, job_run: JobRun) -> None:
        """Append a job run record."""

    def job_runs_for(self, *, domain_id: str, document_id: str) -> tuple[JobRun, ...]:
        """Return parse/reprocess attempts for one document."""

    def list_job_runs(self, *, domain_id: str) -> tuple[JobRun, ...]:
        """Return all document parse/reprocess job runs for one domain."""


class InMemoryDocumentRepository:
    def __init__(self) -> None:
        self._documents: dict[tuple[str, str], DocumentRecord] = {}
        self._hash_index: dict[tuple[str, str], str] = {}
        self._job_runs: list[JobRun] = []

    def add(self, record: DocumentRecord) -> None:
        identity = (record.domain_id, record.id)
        if identity in self._documents:
            raise ValueError(f"Document already exists: {identity}")
        self._documents[identity] = record
        self._hash_index[(record.domain_id, record.content_hash)] = record.id

    def update(self, record: DocumentRecord) -> None:
        identity = (record.domain_id, record.id)
        if identity not in self._documents:
            raise DocumentNotFoundError(record.id)
        self._documents[identity] = replace(record)
        self._hash_index[(record.domain_id, record.content_hash)] = record.id

    def get(self, *, domain_id: str, document_id: str) -> DocumentRecord:
        require_domain_id(domain_id)
        require_text(document_id, "document_id")
        try:
            return self._documents[(domain_id, document_id)]
        except KeyError as exc:
            raise DocumentNotFoundError(document_id) from exc

    def list(self, *, domain_id: str) -> tuple[DocumentRecord, ...]:
        require_domain_id(domain_id)
        records = [
            record
            for (record_domain_id, _), record in self._documents.items()
            if record_domain_id == domain_id
        ]
        return tuple(sorted(records, key=lambda record: record.created_at))

    def find_by_hash(self, *, domain_id: str, content_hash: str) -> DocumentRecord | None:
        require_domain_id(domain_id)
        require_text(content_hash, "content_hash")
        document_id = self._hash_index.get((domain_id, content_hash))
        if document_id is None:
            return None
        return self._documents[(domain_id, document_id)]

    def add_job_run(self, job_run: JobRun) -> None:
        self._job_runs.append(job_run)

    def job_runs_for(self, *, domain_id: str, document_id: str) -> tuple[JobRun, ...]:
        require_domain_id(domain_id)
        require_text(document_id, "document_id")
        input_prefix = f"document:{document_id}:"
        return tuple(
            job_run
            for job_run in self._job_runs
            if job_run.domain_id == domain_id and (job_run.input_ref or "").startswith(input_prefix)
        )

    def list_job_runs(self, *, domain_id: str) -> tuple[JobRun, ...]:
        require_domain_id(domain_id)
        return tuple(job_run for job_run in self._job_runs if job_run.domain_id == domain_id)
