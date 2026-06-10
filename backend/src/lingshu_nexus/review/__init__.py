"""Review, normalization, and release services."""

from lingshu_nexus.persistence.object_store import ObjectStore
from lingshu_nexus.review.models import (
    NormalizationStatus,
    ReleasePreview,
    ReleasePreviewExclusion,
    ReleaseRecord,
    ReviewBatch,
    ReviewBatchStatus,
    StandardizationCandidate,
)
from lingshu_nexus.review.normalization import (
    ConceptNormalizer,
    TerminologyNormalizer,
    load_acupuncture_terminology_normalizer,
)
from lingshu_nexus.review.repository import (
    InMemoryReviewRepository,
    ReleaseNotFoundError,
    ReviewBatchNotFoundError,
    ReviewedAssertionNotFoundError,
)
from lingshu_nexus.review.service import (
    ReleaseValidationError,
    ReviewReleaseService,
    ReviewWorkflowError,
)


def create_review_release_service(*, object_store: ObjectStore) -> ReviewReleaseService:
    return ReviewReleaseService(
        repository=InMemoryReviewRepository(),
        object_store=object_store,
        normalizer=load_acupuncture_terminology_normalizer(),
    )


__all__ = [
    "ConceptNormalizer",
    "InMemoryReviewRepository",
    "NormalizationStatus",
    "ReleaseNotFoundError",
    "ReleasePreview",
    "ReleasePreviewExclusion",
    "ReleaseRecord",
    "ReleaseValidationError",
    "ReviewBatch",
    "ReviewBatchNotFoundError",
    "ReviewBatchStatus",
    "ReviewReleaseService",
    "ReviewWorkflowError",
    "ReviewedAssertionNotFoundError",
    "StandardizationCandidate",
    "TerminologyNormalizer",
    "create_review_release_service",
    "load_acupuncture_terminology_normalizer",
]
