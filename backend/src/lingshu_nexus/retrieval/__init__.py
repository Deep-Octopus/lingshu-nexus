"""Published graph retrieval services."""

from lingshu_nexus.persistence.graph import InMemoryGraphRepository
from lingshu_nexus.retrieval.models import RetrievalResponse, RetrievalResult, SourceCitation
from lingshu_nexus.retrieval.service import (
    NoActiveReleaseError,
    ReleaseNotIndexedError,
    ReleaseReader,
    RetrievalService,
)


def create_retrieval_service(*, release_reader: ReleaseReader) -> RetrievalService:
    return RetrievalService(
        graph_repository=InMemoryGraphRepository(),
        release_reader=release_reader,
    )


__all__ = [
    "InMemoryGraphRepository",
    "NoActiveReleaseError",
    "ReleaseNotIndexedError",
    "ReleaseReader",
    "RetrievalResponse",
    "RetrievalResult",
    "RetrievalService",
    "SourceCitation",
    "create_retrieval_service",
]
