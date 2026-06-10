"""Review, normalization, and release records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from lingshu_domain import ConceptType, EvidenceAssertion, GraphRelease
from lingshu_domain.validation import (
    SchemaValidationError,
    require_domain_id,
    require_non_empty,
    require_text,
)
from lingshu_nexus.persistence.object_store import ObjectRef


def utcnow() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


class ReviewBatchStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class NormalizationStatus(StrEnum):
    SUGGESTED = "suggested"
    NEEDS_REVIEW = "needs_review"
    REVISED = "revised"
    UNMAPPED = "unmapped"


@dataclass(frozen=True)
class StandardizationCandidate:
    id: str
    domain_id: str
    review_batch_id: str
    assertion_id: str
    term_role: str
    concept_type: ConceptType
    original_text: str
    suggested_concept_id: str | None = None
    suggested_preferred_name: str | None = None
    aliases: tuple[str, ...] = ()
    status: NormalizationStatus = NormalizationStatus.UNMAPPED
    review_note: str | None = None
    created_at: str = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        require_text(self.id, "StandardizationCandidate.id")
        require_domain_id(self.domain_id)
        require_text(self.review_batch_id, "StandardizationCandidate.review_batch_id")
        require_text(self.assertion_id, "StandardizationCandidate.assertion_id")
        require_text(self.term_role, "StandardizationCandidate.term_role")
        require_text(self.original_text, "StandardizationCandidate.original_text")


@dataclass(frozen=True)
class ReviewBatch:
    id: str
    domain_id: str
    candidate_run_id: str
    assertion_ids: tuple[str, ...]
    normalization_candidates: tuple[StandardizationCandidate, ...] = ()
    status: ReviewBatchStatus = ReviewBatchStatus.OPEN
    created_by: str = "system"
    created_at: str = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        require_text(self.id, "ReviewBatch.id")
        require_domain_id(self.domain_id)
        require_text(self.candidate_run_id, "ReviewBatch.candidate_run_id")
        require_non_empty(self.assertion_ids, "ReviewBatch.assertion_ids")
        require_text(self.created_by, "ReviewBatch.created_by")


@dataclass(frozen=True)
class ReleasePreviewExclusion:
    assertion_id: str
    reason: str

    def __post_init__(self) -> None:
        require_text(self.assertion_id, "ReleasePreviewExclusion.assertion_id")
        require_text(self.reason, "ReleasePreviewExclusion.reason")


@dataclass(frozen=True)
class ReleasePreview:
    domain_id: str
    requested_assertion_ids: tuple[str, ...]
    included_assertion_ids: tuple[str, ...]
    excluded_assertions: tuple[ReleasePreviewExclusion, ...] = ()
    additions: tuple[str, ...] = ()
    removals: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()
    conflict_assertion_ids: tuple[str, ...] = ()
    active_release_id: str | None = None

    def __post_init__(self) -> None:
        require_domain_id(self.domain_id)
        require_non_empty(self.requested_assertion_ids, "ReleasePreview.requested_assertion_ids")


@dataclass(frozen=True)
class ReleaseRecord:
    release: GraphRelease
    assertions: tuple[EvidenceAssertion, ...]
    artifact_ref: ObjectRef
    created_at: str = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        if self.artifact_ref.domain_id != self.release.domain_id:
            raise SchemaValidationError("Release artifact domain_id must match release domain_id")
        if self.artifact_ref.object_key == "":
            raise SchemaValidationError("Release artifact object_key is required")
