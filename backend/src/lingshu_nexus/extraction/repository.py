"""Candidate extraction repository port and in-memory adapter."""

from __future__ import annotations

from typing import Protocol

from lingshu_domain.validation import require_domain_id, require_text
from lingshu_nexus.extraction.models import CandidateExtractionRun


class CandidateRunNotFoundError(KeyError):
    """Raised when an extraction run is not found."""


class CandidateRepository(Protocol):
    def add_run(self, run: CandidateExtractionRun) -> None:
        """Persist an extraction run."""

    def get_run(self, *, domain_id: str, run_id: str) -> CandidateExtractionRun:
        """Return one run."""

    def list_runs_for_document(
        self,
        *,
        domain_id: str,
        document_id: str,
    ) -> tuple[CandidateExtractionRun, ...]:
        """Return extraction attempts for one document."""


class InMemoryCandidateRepository:
    def __init__(self) -> None:
        self._runs: dict[tuple[str, str], CandidateExtractionRun] = {}

    def add_run(self, run: CandidateExtractionRun) -> None:
        identity = (run.domain_id, run.id)
        if identity in self._runs:
            raise ValueError(f"Candidate extraction run already exists: {identity}")
        self._runs[identity] = run

    def get_run(self, *, domain_id: str, run_id: str) -> CandidateExtractionRun:
        require_domain_id(domain_id)
        require_text(run_id, "run_id")
        try:
            return self._runs[(domain_id, run_id)]
        except KeyError as exc:
            raise CandidateRunNotFoundError(run_id) from exc

    def list_runs_for_document(
        self,
        *,
        domain_id: str,
        document_id: str,
    ) -> tuple[CandidateExtractionRun, ...]:
        require_domain_id(domain_id)
        require_text(document_id, "document_id")
        runs = [
            run
            for (run_domain_id, _), run in self._runs.items()
            if run_domain_id == domain_id and run.document_id == document_id
        ]
        return tuple(sorted(runs, key=lambda run: run.created_at))
