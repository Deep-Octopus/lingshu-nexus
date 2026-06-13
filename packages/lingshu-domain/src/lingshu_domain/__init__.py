"""Shared domain primitives for LingShu Nexus."""

from dataclasses import dataclass

from lingshu_domain.config import (
    ACUPUNCTURE_DOMAIN,
    DomainConfig,
    build_domain_config,
)
from lingshu_domain.evidence import (
    CanonicalConcept,
    ChunkLocator,
    ConceptStatus,
    ConceptType,
    Direction,
    EvidenceAssertion,
    EvidenceTerm,
    GraphRelease,
    ParameterSet,
    PredicateType,
    ReviewDecision,
    ReviewDecisionKind,
    ReviewStatus,
    SourceChunk,
    SourceDocument,
    SourceQualitySignals,
    SourceQualityTier,
    Study,
    StudyType,
)
from lingshu_domain.validation import SchemaValidationError

DEFAULT_DOMAIN_ID = "acupuncture"


@dataclass(frozen=True)
class DomainContext:
    domain_id: str = DEFAULT_DOMAIN_ID
    scenario_id: str | None = None

    def require_domain(self) -> str:
        if not self.domain_id:
            raise ValueError("domain_id is required")
        return self.domain_id


__all__ = [
    "ACUPUNCTURE_DOMAIN",
    "DEFAULT_DOMAIN_ID",
    "CanonicalConcept",
    "ChunkLocator",
    "ConceptStatus",
    "ConceptType",
    "Direction",
    "DomainConfig",
    "DomainContext",
    "EvidenceAssertion",
    "EvidenceTerm",
    "GraphRelease",
    "ParameterSet",
    "PredicateType",
    "ReviewDecision",
    "ReviewDecisionKind",
    "ReviewStatus",
    "SchemaValidationError",
    "SourceChunk",
    "SourceDocument",
    "SourceQualityTier",
    "SourceQualitySignals",
    "Study",
    "StudyType",
    "build_domain_config",
]
