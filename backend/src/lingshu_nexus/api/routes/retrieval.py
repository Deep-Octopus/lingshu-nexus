"""Published graph retrieval API routes."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from lingshu_domain import (
    DEFAULT_DOMAIN_ID,
    EvidenceAssertion,
    EvidenceTerm,
    SourceChunk,
    SourceDocument,
    SourceQualitySignals,
)
from lingshu_nexus.documents import DocumentIngestService
from lingshu_nexus.retrieval import (
    NoActiveReleaseError,
    ReleaseNotIndexedError,
    RetrievalResponse,
    RetrievalService,
)

router = APIRouter(prefix="/api/v1", tags=["retrieval"])


def get_retrieval_service(request: Request) -> RetrievalService:
    return cast(RetrievalService, request.app.state.retrieval_service)


def get_document_service(request: Request) -> DocumentIngestService:
    return cast(DocumentIngestService, request.app.state.document_service)


@router.post("/domains/{domain_id}/graph:sync-active-release")
async def sync_active_release(
    domain_id: str,
    retrieval_service: Annotated[RetrievalService, Depends(get_retrieval_service)],
    document_service: Annotated[DocumentIngestService, Depends(get_document_service)],
) -> dict[str, object]:
    try:
        source_documents, source_chunks = _source_context(
            document_service=document_service,
            domain_id=domain_id,
        )
        release = retrieval_service.sync_active_release(
            domain_id=domain_id,
            source_documents=source_documents,
            source_chunks=source_chunks,
        )
    except NoActiveReleaseError as exc:
        raise HTTPException(status_code=404, detail="No active release for domain") from exc
    return {
        "domain_id": domain_id,
        "release_id": release.id,
        "version": release.version,
        "active": release.active,
    }


@router.get("/domains/{domain_id}/retrieval/search")
async def search_published_evidence(
    domain_id: str,
    retrieval_service: Annotated[RetrievalService, Depends(get_retrieval_service)],
    document_service: Annotated[DocumentIngestService, Depends(get_document_service)],
    query: Annotated[str, Query(min_length=1)],
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> dict[str, object]:
    try:
        source_documents, source_chunks = _source_context(
            document_service=document_service,
            domain_id=domain_id,
        )
        retrieval_service.sync_active_release(
            domain_id=domain_id,
            source_documents=source_documents,
            source_chunks=source_chunks,
        )
        response = retrieval_service.search(domain_id=domain_id, query=query, limit=limit)
    except NoActiveReleaseError as exc:
        raise HTTPException(status_code=404, detail="No active release for domain") from exc
    except ReleaseNotIndexedError as exc:
        raise HTTPException(status_code=409, detail="Active release is not indexed") from exc
    return _retrieval_response_payload(response)


@router.get("/domains/{domain_id}/graph/concepts")
async def find_graph_concepts(
    domain_id: str,
    retrieval_service: Annotated[RetrievalService, Depends(get_retrieval_service)],
    document_service: Annotated[DocumentIngestService, Depends(get_document_service)],
    query: Annotated[str | None, Query()] = None,
) -> dict[str, object]:
    try:
        source_documents, source_chunks = _source_context(
            document_service=document_service,
            domain_id=domain_id,
        )
        retrieval_service.sync_active_release(
            domain_id=domain_id,
            source_documents=source_documents,
            source_chunks=source_chunks,
        )
        concepts = retrieval_service.find_concepts(domain_id=domain_id, query=query)
    except NoActiveReleaseError as exc:
        raise HTTPException(status_code=404, detail="No active release for domain") from exc
    except ReleaseNotIndexedError as exc:
        raise HTTPException(status_code=409, detail="Active release is not indexed") from exc
    return {
        "domain_id": domain_id,
        "concepts": [
            {
                "id": concept.id,
                "label": concept.label,
                "properties": concept.properties,
            }
            for concept in concepts
        ],
    }


@router.get("/domains/{domain_id}/graph/relationships")
async def graph_relationships_for_concept(
    domain_id: str,
    retrieval_service: Annotated[RetrievalService, Depends(get_retrieval_service)],
    document_service: Annotated[DocumentIngestService, Depends(get_document_service)],
    concept_id: Annotated[str | None, Query()] = None,
    text: Annotated[str | None, Query()] = None,
) -> dict[str, object]:
    if concept_id is None and text is None:
        raise HTTPException(status_code=422, detail="concept_id or text is required")
    try:
        source_documents, source_chunks = _source_context(
            document_service=document_service,
            domain_id=domain_id,
        )
        retrieval_service.sync_active_release(
            domain_id=domain_id,
            source_documents=source_documents,
            source_chunks=source_chunks,
        )
        relationships = retrieval_service.relationships_for_concept(
            domain_id=domain_id,
            concept_id=concept_id,
            text=text,
        )
    except NoActiveReleaseError as exc:
        raise HTTPException(status_code=404, detail="No active release for domain") from exc
    except ReleaseNotIndexedError as exc:
        raise HTTPException(status_code=409, detail="Active release is not indexed") from exc
    return {
        "domain_id": domain_id,
        "relationships": [
            {
                "source_id": relationship.source_id,
                "target_id": relationship.target_id,
                "type": relationship.type,
                "properties": relationship.properties,
            }
            for relationship in relationships
        ],
    }


def _source_context(
    *,
    document_service: DocumentIngestService,
    domain_id: str,
) -> tuple[tuple[SourceDocument, ...], tuple[SourceChunk, ...]]:
    documents = document_service.list_documents(domain_id=domain_id)
    return (
        tuple(document.to_source_document() for document in documents),
        tuple(chunk for document in documents for chunk in document.chunks),
    )


def _retrieval_response_payload(response: RetrievalResponse) -> dict[str, object]:
    return {
        "domain_id": response.domain_id,
        "query": response.query,
        "release": {
            "id": response.release.id,
            "version": response.release.version,
            "schema_version": response.release.schema_version,
            "index_version": response.release.index_version,
        },
        "results": [
            {
                "score": result.score,
                "matched_terms": list(result.matched_terms),
                "assertion": _assertion_payload(result.assertion),
                "citations": [
                    {
                        "document_id": citation.document_id,
                        "document_title": citation.document_title,
                        "source_uri": citation.source_uri,
                        "chunk_id": citation.chunk_id,
                        "locator": citation.locator_reference,
                        "parser_version": citation.parser_version,
                        "snippet": citation.snippet,
                    }
                    for citation in result.citations
                ],
            }
            for result in response.results
        ],
        "notice": "仅用于内部科研证据辅助，不作为诊疗建议。",
    }


def _assertion_payload(assertion: EvidenceAssertion) -> dict[str, object]:
    return {
        "id": assertion.id,
        "domain_id": assertion.domain_id,
        "subject": _term_payload(assertion.subject),
        "predicate": assertion.predicate.value,
        "object": _term_payload(assertion.object),
        "source_chunk_ids": list(assertion.source_chunk_ids),
        "review_status": assertion.review_status.value,
        "population": assertion.population,
        "outcome": assertion.outcome,
        "direction": assertion.direction.value,
        "source_quality_signals": _source_quality_payload(assertion.source_quality_signals),
    }


def _term_payload(term: EvidenceTerm) -> dict[str, object]:
    return {
        "type": term.type.value,
        "text": term.text,
        "concept_id": term.concept_id,
        "original_text": term.original_text,
    }


def _source_quality_payload(signals: SourceQualitySignals) -> dict[str, object]:
    return {
        "tier": signals.tier.value,
        "source_type": signals.source_type,
        "journal_quartile": signals.journal_quartile,
        "citation_count": signals.citation_count,
        "is_highly_cited": signals.is_highly_cited,
        "is_hot_paper": signals.is_hot_paper,
    }


@router.get("/retrieval/health")
async def retrieval_health(
    domain_id: Annotated[str, Query()] = DEFAULT_DOMAIN_ID,
) -> dict[str, str]:
    return {
        "domain_id": domain_id,
        "status": "ready",
        "scope": "published-active-release-only",
    }
