"""SourceConnector services for controlled incremental updates."""

from lingshu_nexus.documents import DocumentIngestService
from lingshu_nexus.extraction import (
    CandidateExtractionService,
    InMemoryCandidateRepository,
    LlmProvider,
)
from lingshu_nexus.extraction.prompts import load_literature_extraction_prompt
from lingshu_nexus.persistence.object_store import ObjectStore
from lingshu_nexus.review import ReviewReleaseService
from lingshu_nexus.sources.connectors import (
    FixtureSourceConnector,
    GenericRestSourceConnector,
    SourceConnector,
    SourceConnectorError,
    SourceFetchRequest,
    SourceFetchResult,
)
from lingshu_nexus.sources.models import (
    SourceArtifact,
    SourceArtifactKind,
    SourceArtifactRecord,
    SourceArtifactStatus,
    SourceConnectorConfig,
    SourceConnectorType,
    SourceSchedule,
    SourceSyncResult,
    SourceSyncRun,
)
from lingshu_nexus.sources.repository import (
    InMemorySourceRepository,
    SourceConfigNotFoundError,
    SourceRunNotFoundError,
)
from lingshu_nexus.sources.service import SourceUpdateError, SourceUpdateService


def create_source_update_service(
    *,
    object_store: ObjectStore,
    document_service: DocumentIngestService,
    review_service: ReviewReleaseService,
    provider: LlmProvider,
) -> SourceUpdateService:
    extraction_service = CandidateExtractionService(
        repository=InMemoryCandidateRepository(),
        object_store=object_store,
        provider=provider,
        prompt=load_literature_extraction_prompt(),
    )
    return SourceUpdateService(
        repository=InMemorySourceRepository(),
        object_store=object_store,
        document_service=document_service,
        extraction_service=extraction_service,
        review_service=review_service,
        connectors={
            SourceConnectorType.FIXTURE: FixtureSourceConnector(),
            SourceConnectorType.GENERIC_REST: GenericRestSourceConnector(),
        },
    )


__all__ = [
    "FixtureSourceConnector",
    "GenericRestSourceConnector",
    "InMemorySourceRepository",
    "SourceArtifact",
    "SourceArtifactKind",
    "SourceArtifactRecord",
    "SourceArtifactStatus",
    "SourceConfigNotFoundError",
    "SourceConnector",
    "SourceConnectorConfig",
    "SourceConnectorError",
    "SourceConnectorType",
    "SourceFetchRequest",
    "SourceFetchResult",
    "SourceRunNotFoundError",
    "SourceSchedule",
    "SourceSyncResult",
    "SourceSyncRun",
    "SourceUpdateError",
    "SourceUpdateService",
    "create_source_update_service",
]
