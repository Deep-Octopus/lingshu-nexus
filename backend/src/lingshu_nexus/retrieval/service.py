"""Published evidence retrieval service."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import fields, is_dataclass
from typing import Any, Protocol

from lingshu_domain import (
    EvidenceAssertion,
    GraphRelease,
    ReviewStatus,
    SourceChunk,
    SourceDocument,
)
from lingshu_domain.validation import require_domain_id, require_text
from lingshu_nexus.persistence.graph import (
    GraphNode,
    GraphRelationship,
    GraphRepository,
    GraphSourceReference,
)
from lingshu_nexus.retrieval.models import RetrievalResponse, RetrievalResult, SourceCitation
from lingshu_nexus.review.models import ReleaseRecord


class ReleaseReader(Protocol):
    def active_release(self, *, domain_id: str) -> ReleaseRecord | None:
        """Return the active release record for one domain."""


class NoActiveReleaseError(LookupError):
    """Raised when a domain has no active published release."""


class ReleaseNotIndexedError(LookupError):
    """Raised when graph retrieval has not been synced for the active release."""


class RetrievalService:
    """Read-only retrieval over active published graph releases."""

    def __init__(
        self,
        *,
        graph_repository: GraphRepository,
        release_reader: ReleaseReader,
    ) -> None:
        self._graph_repository = graph_repository
        self._release_reader = release_reader

    def sync_active_release(
        self,
        *,
        domain_id: str,
        source_documents: tuple[SourceDocument, ...] = (),
        source_chunks: tuple[SourceChunk, ...] = (),
    ) -> GraphRelease:
        require_domain_id(domain_id)
        record = self._release_reader.active_release(domain_id=domain_id)
        if record is None:
            raise NoActiveReleaseError(domain_id)
        self._graph_repository.write_release(
            record.release,
            record.assertions,
            source_documents=source_documents,
            source_chunks=source_chunks,
        )
        self._graph_repository.set_active_release(domain_id=domain_id, release_id=record.release.id)
        return record.release

    def search(
        self,
        *,
        domain_id: str,
        query: str,
        limit: int = 5,
    ) -> RetrievalResponse:
        require_domain_id(domain_id)
        require_text(query, "query")
        if limit < 1:
            raise ValueError("limit must be >= 1")
        release_id = self._graph_repository.active_release_id(domain_id=domain_id)
        if release_id is None:
            raise ReleaseNotIndexedError(domain_id)
        release = self._graph_repository.get_release(domain_id=domain_id, release_id=release_id)
        assertions = self._graph_repository.list_assertions_for_release(
            domain_id=domain_id,
            release_id=release_id,
        )
        tokens = _query_tokens(query)
        results: list[RetrievalResult] = []
        for assertion in assertions:
            if assertion.review_status not in {ReviewStatus.APPROVED, ReviewStatus.CONFLICT}:
                continue
            if assertion.id not in release.included_assertion_ids:
                continue
            references = self._graph_repository.source_references_for_assertion(
                domain_id=domain_id,
                release_id=release_id,
                assertion_id=assertion.id,
            )
            citations = _citations_from_references(references)
            if not citations:
                continue
            corpus = _assertion_search_text(assertion, references)
            matched_terms = tuple(token for token in tokens if token in corpus.casefold())
            if not matched_terms:
                continue
            score = _score_assertion(assertion=assertion, matched_terms=matched_terms)
            results.append(
                RetrievalResult(
                    release=release,
                    assertion=assertion,
                    score=score,
                    citations=citations,
                    matched_terms=matched_terms,
                )
            )
        ranked = tuple(
            sorted(
                results,
                key=lambda result: (
                    -result.score,
                    result.assertion.source_quality_signals.tier.value,
                    result.assertion.id,
                ),
            )[:limit]
        )
        return RetrievalResponse(domain_id=domain_id, query=query, release=release, results=ranked)

    def find_concepts(
        self,
        *,
        domain_id: str,
        query: str | None = None,
    ) -> tuple[GraphNode, ...]:
        release_id = self._active_release_id(domain_id=domain_id)
        return self._graph_repository.find_concepts(
            domain_id=domain_id,
            release_id=release_id,
            query=query,
        )

    def relationships_for_concept(
        self,
        *,
        domain_id: str,
        concept_id: str | None = None,
        text: str | None = None,
    ) -> tuple[GraphRelationship, ...]:
        release_id = self._active_release_id(domain_id=domain_id)
        return self._graph_repository.relationships_for_concept(
            domain_id=domain_id,
            release_id=release_id,
            concept_id=concept_id,
            text=text,
        )

    def source_documents_for_active_release(
        self,
        *,
        domain_id: str,
    ) -> tuple[SourceDocument, ...]:
        release_id = self._active_release_id(domain_id=domain_id)
        return self._graph_repository.source_documents_for_release(
            domain_id=domain_id,
            release_id=release_id,
        )

    def _active_release_id(self, *, domain_id: str) -> str:
        release_id = self._graph_repository.active_release_id(domain_id=domain_id)
        if release_id is None:
            raise ReleaseNotIndexedError(domain_id)
        return release_id


def _query_tokens(query: str) -> tuple[str, ...]:
    tokens = re.findall(r"[\w.]+|[\u4e00-\u9fff]+", query.casefold())
    return tuple(dict.fromkeys(token for token in tokens if token.strip()))


def _citations_from_references(
    references: tuple[GraphSourceReference, ...],
) -> tuple[SourceCitation, ...]:
    citations: list[SourceCitation] = []
    for reference in references:
        if not reference.document_id or reference.locator_reference is None:
            continue
        citations.append(
            SourceCitation(
                domain_id=reference.domain_id,
                document_id=reference.document_id,
                chunk_id=reference.chunk_id,
                locator_reference=reference.locator_reference,
                document_title=reference.document_title,
                source_uri=reference.source_uri,
                snippet=_snippet(reference.chunk_text),
                parser_version=reference.parser_version,
            )
        )
    return tuple(citations)


def _score_assertion(
    *,
    assertion: EvidenceAssertion,
    matched_terms: tuple[str, ...],
) -> float:
    review_bonus = 0.2 if assertion.review_status is ReviewStatus.CONFLICT else 0.4
    confidence_bonus = assertion.extraction_confidence / 10
    return float(len(matched_terms)) + review_bonus + confidence_bonus


def _assertion_search_text(
    assertion: EvidenceAssertion,
    references: tuple[GraphSourceReference, ...],
) -> str:
    values: list[str] = [
        assertion.id,
        assertion.subject.text,
        assertion.subject.original_text or "",
        assertion.subject.concept_id or "",
        assertion.predicate.value,
        assertion.object.text,
        assertion.object.original_text or "",
        assertion.object.concept_id or "",
        assertion.population or "",
        assertion.outcome or "",
        assertion.direction.value,
        assertion.study_id or "",
    ]
    if assertion.parameter_set is not None:
        values.extend(_dataclass_values(assertion.parameter_set))
    values.extend(_dataclass_values(assertion.source_quality_signals))
    values.extend(_metadata_values(assertion.metadata))
    values.extend(reference.chunk_text or "" for reference in references)
    values.extend(reference.document_title or "" for reference in references)
    return " ".join(value for value in values if value)


def _dataclass_values(value: object) -> list[str]:
    if not is_dataclass(value):
        return []
    result: list[str] = []
    for field in fields(value):
        field_value = getattr(value, field.name)
        if field_value is None:
            continue
        result.append(str(getattr(field_value, "value", field_value)))
    return result


def _metadata_values(metadata: dict[str, Any]) -> list[str]:
    result: list[str] = []
    stack: list[Any] = list(metadata.values())
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            stack.extend(value.values())
        elif isinstance(value, Iterable) and not isinstance(value, str | bytes):
            stack.extend(value)
        elif value is not None:
            result.append(str(value))
    return result


def _snippet(text: str | None, *, max_length: int = 220) -> str | None:
    if text is None:
        return None
    compact = " ".join(text.split())
    if len(compact) <= max_length:
        return compact
    return f"{compact[: max_length - 3]}..."
