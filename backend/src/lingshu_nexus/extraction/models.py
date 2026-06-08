"""Candidate extraction records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from lingshu_domain import EvidenceAssertion, EvidenceTerm, PredicateType
from lingshu_domain.validation import (
    SchemaValidationError,
    require_domain_id,
    require_non_empty,
    require_text,
)
from lingshu_nexus.persistence.models import JobStatus
from lingshu_nexus.persistence.object_store import ObjectRef


def utcnow() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


class ExtractionSchemaVersion(StrEnum):
    CANDIDATE_V0_1 = "candidate-extraction-v0.1.0"


@dataclass(frozen=True)
class ExtractionPrompt:
    id: str
    domain_id: str
    version: str
    checksum: str
    text: str

    def __post_init__(self) -> None:
        require_text(self.id, "ExtractionPrompt.id")
        require_domain_id(self.domain_id)
        require_text(self.version, "ExtractionPrompt.version")
        require_text(self.checksum, "ExtractionPrompt.checksum")
        require_text(self.text, "ExtractionPrompt.text")


@dataclass(frozen=True)
class ProviderUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    estimated_cost: float | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("prompt_tokens", self.prompt_tokens),
            ("completion_tokens", self.completion_tokens),
            ("total_tokens", self.total_tokens),
        ):
            if value is not None and value < 0:
                raise SchemaValidationError(f"{field_name} must be >= 0")
        if self.estimated_cost is not None and self.estimated_cost < 0:
            raise SchemaValidationError("estimated_cost must be >= 0")


@dataclass(frozen=True)
class CandidateRelation:
    id: str
    domain_id: str
    subject: EvidenceTerm
    predicate: PredicateType
    object: EvidenceTerm
    source_chunk_ids: tuple[str, ...]
    confidence: float = 0

    def __post_init__(self) -> None:
        require_text(self.id, "CandidateRelation.id")
        require_domain_id(self.domain_id)
        require_non_empty(self.source_chunk_ids, "CandidateRelation.source_chunk_ids")
        if self.confidence < 0 or self.confidence > 1:
            raise SchemaValidationError("CandidateRelation.confidence must be between 0 and 1")


@dataclass(frozen=True)
class CandidateExtractionRun:
    id: str
    domain_id: str
    document_id: str
    status: JobStatus
    provider: str
    model: str
    prompt_version: str
    schema_version: str
    source_chunk_ids: tuple[str, ...]
    evidence_assertions: tuple[EvidenceAssertion, ...] = ()
    relations: tuple[CandidateRelation, ...] = ()
    entities: tuple[EvidenceTerm, ...] = ()
    study_metadata: dict[str, Any] = field(default_factory=dict)
    token_usage: ProviderUsage = field(default_factory=ProviderUsage)
    latency_ms: int | None = None
    raw_response_hash: str | None = None
    output_ref: ObjectRef | None = None
    failure_reason: str | None = None
    created_at: str = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        require_text(self.id, "CandidateExtractionRun.id")
        require_domain_id(self.domain_id)
        require_text(self.document_id, "CandidateExtractionRun.document_id")
        require_text(self.provider, "CandidateExtractionRun.provider")
        require_text(self.model, "CandidateExtractionRun.model")
        require_text(self.prompt_version, "CandidateExtractionRun.prompt_version")
        require_text(self.schema_version, "CandidateExtractionRun.schema_version")
        require_non_empty(self.source_chunk_ids, "CandidateExtractionRun.source_chunk_ids")
        if self.latency_ms is not None and self.latency_ms < 0:
            raise SchemaValidationError("latency_ms must be >= 0")
