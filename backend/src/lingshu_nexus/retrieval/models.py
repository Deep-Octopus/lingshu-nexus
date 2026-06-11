"""Retrieval DTOs for published evidence search."""

from __future__ import annotations

from dataclasses import dataclass

from lingshu_domain import EvidenceAssertion, GraphRelease
from lingshu_domain.validation import SchemaValidationError, require_domain_id, require_text


@dataclass(frozen=True)
class SourceCitation:
    domain_id: str
    document_id: str
    chunk_id: str
    locator_reference: str
    document_title: str | None = None
    source_uri: str | None = None
    snippet: str | None = None
    parser_version: str | None = None

    def __post_init__(self) -> None:
        require_domain_id(self.domain_id)
        require_text(self.document_id, "SourceCitation.document_id")
        require_text(self.chunk_id, "SourceCitation.chunk_id")
        require_text(self.locator_reference, "SourceCitation.locator_reference")


@dataclass(frozen=True)
class RetrievalResult:
    release: GraphRelease
    assertion: EvidenceAssertion
    score: float
    citations: tuple[SourceCitation, ...]
    matched_terms: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.score < 0:
            raise SchemaValidationError("RetrievalResult.score must be >= 0")
        if self.assertion.domain_id != self.release.domain_id:
            raise SchemaValidationError("Retrieval assertion domain_id must match release")
        if self.assertion.id not in self.release.included_assertion_ids:
            raise SchemaValidationError("Retrieval assertion must belong to release")


@dataclass(frozen=True)
class RetrievalResponse:
    domain_id: str
    query: str
    release: GraphRelease
    results: tuple[RetrievalResult, ...]

    def __post_init__(self) -> None:
        require_domain_id(self.domain_id)
        require_text(self.query, "RetrievalResponse.query")
        if self.release.domain_id != self.domain_id:
            raise SchemaValidationError("Retrieval release domain_id must match response domain")
