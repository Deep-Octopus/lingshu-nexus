"""Terminology-backed concept normalization for review batches."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Protocol

from lingshu_domain import CanonicalConcept, ConceptStatus, ConceptType, EvidenceTerm
from lingshu_domain.validation import require_domain_id, require_text
from lingshu_nexus.review.models import NormalizationStatus, StandardizationCandidate

SENSITIVE_DISEASE_ALIASES = frozenset({"depression", "blues", "postpartum blues"})


@dataclass(frozen=True)
class TerminologyEntry:
    concept: CanonicalConcept
    review_note: str | None = None


class ConceptNormalizer(Protocol):
    def concepts(self, *, domain_id: str) -> tuple[CanonicalConcept, ...]:
        """Return known canonical concepts for the domain."""

    def candidate_for_term(
        self,
        *,
        domain_id: str,
        review_batch_id: str,
        assertion_id: str,
        term_role: str,
        term: EvidenceTerm,
    ) -> StandardizationCandidate:
        """Return a standardization candidate for a source term."""


class TerminologyNormalizer:
    """Alias matcher using the versioned seed terminology file."""

    def __init__(self, *, domain_id: str, entries: tuple[TerminologyEntry, ...]) -> None:
        require_domain_id(domain_id)
        self._domain_id = domain_id
        self._entries = entries
        self._lookup: dict[tuple[ConceptType, str], TerminologyEntry] = {}
        for entry in entries:
            self._lookup[(entry.concept.type, _normalize(entry.concept.preferred_name))] = entry
            for alias in entry.concept.aliases:
                self._lookup[(entry.concept.type, _normalize(alias))] = entry

    def concepts(self, *, domain_id: str) -> tuple[CanonicalConcept, ...]:
        require_domain_id(domain_id)
        if domain_id != self._domain_id:
            return ()
        return tuple(entry.concept for entry in self._entries)

    def candidate_for_term(
        self,
        *,
        domain_id: str,
        review_batch_id: str,
        assertion_id: str,
        term_role: str,
        term: EvidenceTerm,
    ) -> StandardizationCandidate:
        require_domain_id(domain_id)
        require_text(review_batch_id, "review_batch_id")
        require_text(assertion_id, "assertion_id")
        require_text(term_role, "term_role")
        original_text = term.original_text or term.text
        normalized_text = _normalize(original_text)
        entry = self._lookup.get((term.type, normalized_text))
        if entry is None:
            return _candidate(
                domain_id=domain_id,
                review_batch_id=review_batch_id,
                assertion_id=assertion_id,
                term_role=term_role,
                concept_type=term.type,
                original_text=original_text,
                status=NormalizationStatus.UNMAPPED,
                review_note="No seed terminology match; reviewer may create or select a concept.",
            )

        status = NormalizationStatus.SUGGESTED
        if (
            term.type is ConceptType.DISEASE_OR_SYMPTOM
            and normalized_text in SENSITIVE_DISEASE_ALIASES
        ):
            status = NormalizationStatus.NEEDS_REVIEW
        return _candidate(
            domain_id=domain_id,
            review_batch_id=review_batch_id,
            assertion_id=assertion_id,
            term_role=term_role,
            concept_type=term.type,
            original_text=original_text,
            suggested_concept_id=entry.concept.id,
            suggested_preferred_name=entry.concept.preferred_name,
            aliases=entry.concept.aliases,
            status=status,
            review_note=entry.review_note,
        )


def load_acupuncture_terminology_normalizer(
    path: Path | None = None,
) -> TerminologyNormalizer:
    if path is None:
        repo_root = Path(__file__).resolve().parents[4]
        path = repo_root / "config" / "domains" / "acupuncture" / "terminology.v0.1.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    domain_id = str(payload["domain_id"])
    entries: list[TerminologyEntry] = []
    for item in payload.get("terms", []):
        aliases = tuple(str(alias) for alias in item.get("aliases", []))
        concept = CanonicalConcept(
            id=str(item["canonical_id"]),
            domain_id=domain_id,
            type=ConceptType(str(item["type"])),
            preferred_name=str(item["preferred_name"]),
            aliases=aliases,
            status=ConceptStatus.ACTIVE,
        )
        entries.append(
            TerminologyEntry(
                concept=concept,
                review_note=str(item["review_note"]) if item.get("review_note") else None,
            )
        )
    return TerminologyNormalizer(domain_id=domain_id, entries=tuple(entries))


def _candidate(
    *,
    domain_id: str,
    review_batch_id: str,
    assertion_id: str,
    term_role: str,
    concept_type: ConceptType,
    original_text: str,
    suggested_concept_id: str | None = None,
    suggested_preferred_name: str | None = None,
    aliases: tuple[str, ...] = (),
    status: NormalizationStatus,
    review_note: str | None = None,
) -> StandardizationCandidate:
    digest = sha256(
        "|".join(
            (
                domain_id,
                review_batch_id,
                assertion_id,
                term_role,
                concept_type.value,
                original_text,
                suggested_concept_id or "",
            )
        ).encode("utf-8")
    ).hexdigest()[:16]
    return StandardizationCandidate(
        id=f"std_{digest}",
        domain_id=domain_id,
        review_batch_id=review_batch_id,
        assertion_id=assertion_id,
        term_role=term_role,
        concept_type=concept_type,
        original_text=original_text,
        suggested_concept_id=suggested_concept_id,
        suggested_preferred_name=suggested_preferred_name,
        aliases=aliases,
        status=status,
        review_note=review_note,
    )


def _normalize(text: str) -> str:
    return " ".join(text.strip().casefold().split())
