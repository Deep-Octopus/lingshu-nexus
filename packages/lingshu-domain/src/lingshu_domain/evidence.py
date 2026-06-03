"""Evidence Schema v0.1 domain objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from lingshu_domain.validation import (
    SchemaValidationError,
    require_domain_id,
    require_non_empty,
    require_probability,
    require_text,
)


class ConceptType(StrEnum):
    DISEASE_OR_SYMPTOM = "disease_or_symptom"
    ACUPOINT = "acupoint"
    ACUPOINT_COMBINATION = "acupoint_combination"
    INTERVENTION = "intervention"
    PARAMETER = "parameter"
    OUTCOME = "outcome"
    SAFETY = "safety"
    LITERATURE = "literature"
    STIMULATION_SITE = "stimulation_site"
    MECHANISM = "mechanism"
    POPULATION = "population"


class ConceptStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    NEEDS_REVIEW = "needs_review"


class PredicateType(StrEnum):
    AFFECTS_OUTCOME = "affects_outcome"
    TREATS = "treats"
    HAS_PARAMETER = "has_parameter"
    HAS_OUTCOME = "has_outcome"
    HAS_SAFETY_EVENT = "has_safety_event"
    CONTRAINDICATED_FOR = "contraindicated_for"
    USES_STIMULATION_SITE = "uses_stimulation_site"
    HAS_MECHANISM = "has_mechanism"
    COMPARED_WITH = "compared_with"
    MENTIONED_IN = "mentioned_in"
    RELATED_TO = "related_to"


class Direction(StrEnum):
    IMPROVED = "improved"
    NO_DIFFERENCE = "no_difference"
    WORSENED = "worsened"
    MIXED = "mixed"
    UNCLEAR = "unclear"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_REVISION = "needs_revision"
    CONFLICT = "conflict"


class ReviewDecisionKind(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    MODIFY = "modify"
    MARK_CONFLICT = "mark_conflict"


class SourceQualityTier(StrEnum):
    TOP_DATABASE_HIGH_IMPACT = "top_database_high_impact"
    DATABASE_OTHER = "database_other"
    BACKGROUND_ONLY = "background_only"
    UNKNOWN = "unknown"


class StudyType(StrEnum):
    RCT = "rct"
    SYSTEMATIC_REVIEW = "systematic_review"
    META_ANALYSIS = "meta_analysis"
    OBSERVATIONAL = "observational"
    GUIDELINE_OR_CONSENSUS = "guideline_or_consensus"
    OTHER = "other"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ChunkLocator:
    chunk_index: int
    page: int | None = None
    heading: str | None = None
    paragraph: int | None = None

    def __post_init__(self) -> None:
        if self.chunk_index < 0:
            raise SchemaValidationError("chunk_index must be >= 0")
        if self.page is not None and self.page < 1:
            raise SchemaValidationError("page must be >= 1")

    def as_reference(self) -> str:
        parts = [f"chunk:{self.chunk_index}"]
        if self.page is not None:
            parts.append(f"page:{self.page}")
        if self.heading:
            parts.append(f"heading:{self.heading}")
        if self.paragraph is not None:
            parts.append(f"paragraph:{self.paragraph}")
        return "|".join(parts)


@dataclass(frozen=True)
class EvidenceTerm:
    type: ConceptType
    text: str
    concept_id: str | None = None
    original_text: str | None = None

    def __post_init__(self) -> None:
        require_text(self.text, "term.text")


@dataclass(frozen=True)
class SourceQualitySignals:
    tier: SourceQualityTier = SourceQualityTier.UNKNOWN
    source_type: str | None = None
    journal_quartile: str | None = None
    citation_count: int | None = None
    is_highly_cited: bool = False
    is_hot_paper: bool = False

    def __post_init__(self) -> None:
        if self.citation_count is not None and self.citation_count < 0:
            raise SchemaValidationError("citation_count must be >= 0")


@dataclass(frozen=True)
class ParameterSet:
    stimulation_site: str | None = None
    frequency_hz: float | None = None
    pulse_width_us: float | None = None
    intensity: str | None = None
    duration_minutes: float | None = None
    course: str | None = None
    waveform: str | None = None
    dose: str | None = None
    sham_control: str | None = None
    raw_text: str | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("frequency_hz", self.frequency_hz),
            ("pulse_width_us", self.pulse_width_us),
            ("duration_minutes", self.duration_minutes),
        ):
            if value is not None and value < 0:
                raise SchemaValidationError(f"{field_name} must be >= 0")


@dataclass(frozen=True)
class SourceDocument:
    id: str
    domain_id: str
    title: str
    content_hash: str
    file_version: int
    source_uri: str | None = None
    doi: str | None = None
    pmid: str | None = None
    topic_tags: tuple[str, ...] = ()
    license_note: str | None = None
    source_quality_tier: SourceQualityTier = SourceQualityTier.UNKNOWN

    def __post_init__(self) -> None:
        require_text(self.id, "SourceDocument.id")
        require_domain_id(self.domain_id)
        require_text(self.title, "SourceDocument.title")
        require_text(self.content_hash, "SourceDocument.content_hash")
        if self.file_version < 1:
            raise SchemaValidationError("file_version must be >= 1")


@dataclass(frozen=True)
class SourceChunk:
    id: str
    domain_id: str
    document_id: str
    locator: ChunkLocator
    text: str
    parser_version: str
    embedding_version: str | None = None

    def __post_init__(self) -> None:
        require_text(self.id, "SourceChunk.id")
        require_domain_id(self.domain_id)
        require_text(self.document_id, "SourceChunk.document_id")
        require_text(self.text, "SourceChunk.text")
        require_text(self.parser_version, "SourceChunk.parser_version")


@dataclass(frozen=True)
class Study:
    id: str
    domain_id: str
    source_document_id: str
    study_type: StudyType = StudyType.UNKNOWN
    publication_date: str | None = None
    population_summary: str | None = None
    risk_of_bias_status: str | None = None
    journal_quartile: str | None = None
    citation_count: int | None = None
    region_or_team: str | None = None

    def __post_init__(self) -> None:
        require_text(self.id, "Study.id")
        require_domain_id(self.domain_id)
        require_text(self.source_document_id, "Study.source_document_id")
        if self.citation_count is not None and self.citation_count < 0:
            raise SchemaValidationError("Study.citation_count must be >= 0")


@dataclass(frozen=True)
class CanonicalConcept:
    id: str
    domain_id: str
    type: ConceptType
    preferred_name: str
    aliases: tuple[str, ...] = ()
    external_code: str | None = None
    status: ConceptStatus = ConceptStatus.NEEDS_REVIEW

    def __post_init__(self) -> None:
        require_text(self.id, "CanonicalConcept.id")
        require_domain_id(self.domain_id)
        require_text(self.preferred_name, "CanonicalConcept.preferred_name")


@dataclass(frozen=True)
class EvidenceAssertion:
    id: str
    domain_id: str
    subject: EvidenceTerm
    predicate: PredicateType
    object: EvidenceTerm
    source_chunk_ids: tuple[str, ...]
    review_status: ReviewStatus = ReviewStatus.PENDING
    population: str | None = None
    parameter_set: ParameterSet | None = None
    outcome: str | None = None
    direction: Direction = Direction.UNCLEAR
    extraction_confidence: float = 0
    source_quality_signals: SourceQualitySignals = field(default_factory=SourceQualitySignals)
    study_id: str | None = None
    valid_from: str | None = None
    supersedes: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_text(self.id, "EvidenceAssertion.id")
        require_domain_id(self.domain_id)
        require_probability(self.extraction_confidence, "extraction_confidence")

    def validate_publishable(self) -> None:
        require_domain_id(self.domain_id)
        require_non_empty(self.source_chunk_ids, "source_chunk_ids")
        if self.review_status is not ReviewStatus.APPROVED:
            raise SchemaValidationError("EvidenceAssertion must be approved before release")


@dataclass(frozen=True)
class ReviewDecision:
    id: str
    domain_id: str
    assertion_id: str
    reviewer: str
    decision: ReviewDecisionKind
    reason: str
    timestamp: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        require_text(self.id, "ReviewDecision.id")
        require_domain_id(self.domain_id)
        require_text(self.assertion_id, "ReviewDecision.assertion_id")
        require_text(self.reviewer, "ReviewDecision.reviewer")
        require_text(self.reason, "ReviewDecision.reason")
        require_text(self.timestamp, "ReviewDecision.timestamp")


@dataclass(frozen=True)
class GraphRelease:
    id: str
    domain_id: str
    version: str
    included_assertion_ids: tuple[str, ...]
    schema_version: str
    index_version: str
    released_by: str
    active: bool = False

    def __post_init__(self) -> None:
        require_text(self.id, "GraphRelease.id")
        require_domain_id(self.domain_id)
        require_text(self.version, "GraphRelease.version")
        require_text(self.schema_version, "GraphRelease.schema_version")
        require_text(self.index_version, "GraphRelease.index_version")
        require_text(self.released_by, "GraphRelease.released_by")
        require_non_empty(self.included_assertion_ids, "included_assertion_ids")

