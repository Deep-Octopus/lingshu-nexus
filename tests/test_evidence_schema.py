# ruff: noqa: E402

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "lingshu-domain" / "src"))

from lingshu_domain import (
    ACUPUNCTURE_DOMAIN,
    CanonicalConcept,
    ChunkLocator,
    ConceptType,
    Direction,
    EvidenceAssertion,
    EvidenceTerm,
    GraphRelease,
    ParameterSet,
    PredicateType,
    ReviewStatus,
    SchemaValidationError,
    SourceChunk,
    SourceDocument,
    SourceQualitySignals,
    SourceQualityTier,
    build_domain_config,
)


class EvidenceSchemaTestCase(unittest.TestCase):
    def test_acupuncture_domain_config_contains_tvns_seed_scope(self) -> None:
        self.assertEqual(ACUPUNCTURE_DOMAIN.domain_id, "acupuncture")
        self.assertIn("tVNS", ACUPUNCTURE_DOMAIN.default_topic_tags)
        ACUPUNCTURE_DOMAIN.validate_concept_type(ConceptType.STIMULATION_SITE.value)
        ACUPUNCTURE_DOMAIN.validate_predicate(PredicateType.AFFECTS_OUTCOME.value)

    def test_valid_source_and_publishable_assertion_pass_validation(self) -> None:
        document = SourceDocument(
            id="doc_001",
            domain_id="acupuncture",
            title="taVNS insomnia trial",
            content_hash="hash_001",
            file_version=1,
            topic_tags=("tVNS",),
            source_quality_tier=SourceQualityTier.TOP_DATABASE_HIGH_IMPACT,
        )
        chunk = SourceChunk(
            id="chunk_001",
            domain_id=document.domain_id,
            document_id=document.id,
            locator=ChunkLocator(chunk_index=0, page=5, heading="Results"),
            text="taVNS improved sleep quality in the intervention group.",
            parser_version="parser-v0.1",
        )
        assertion = EvidenceAssertion(
            id="assertion_001",
            domain_id=document.domain_id,
            subject=EvidenceTerm(ConceptType.INTERVENTION, "taVNS"),
            predicate=PredicateType.AFFECTS_OUTCOME,
            object=EvidenceTerm(ConceptType.OUTCOME, "sleep quality score"),
            population="participants with insomnia",
            parameter_set=ParameterSet(
                stimulation_site="cymba conchae",
                frequency_hz=25,
                pulse_width_us=250,
                waveform="rectangular",
                dose="30 min/day for 4 weeks",
                sham_control="earlobe sham stimulation",
            ),
            outcome="sleep quality score",
            direction=Direction.IMPROVED,
            source_chunk_ids=(chunk.id,),
            extraction_confidence=0.88,
            review_status=ReviewStatus.APPROVED,
            source_quality_signals=SourceQualitySignals(
                tier=SourceQualityTier.TOP_DATABASE_HIGH_IMPACT,
                journal_quartile="Q1",
                citation_count=42,
            ),
        )
        assertion.validate_publishable()

    def test_publishable_assertion_requires_domain_and_source_locator(self) -> None:
        with self.assertRaises(SchemaValidationError):
            EvidenceAssertion(
                id="assertion_missing_domain",
                domain_id="",
                subject=EvidenceTerm(ConceptType.INTERVENTION, "taVNS"),
                predicate=PredicateType.AFFECTS_OUTCOME,
                object=EvidenceTerm(ConceptType.OUTCOME, "sleep quality"),
                source_chunk_ids=("chunk_001",),
                review_status=ReviewStatus.APPROVED,
            )

        assertion = EvidenceAssertion(
            id="assertion_no_source",
            domain_id="acupuncture",
            subject=EvidenceTerm(ConceptType.INTERVENTION, "taVNS"),
            predicate=PredicateType.AFFECTS_OUTCOME,
            object=EvidenceTerm(ConceptType.OUTCOME, "sleep quality"),
            source_chunk_ids=(),
            review_status=ReviewStatus.APPROVED,
        )
        with self.assertRaises(SchemaValidationError):
            assertion.validate_publishable()

    def test_non_approved_assertion_cannot_be_published(self) -> None:
        assertion = EvidenceAssertion(
            id="assertion_pending",
            domain_id="acupuncture",
            subject=EvidenceTerm(ConceptType.INTERVENTION, "taVNS"),
            predicate=PredicateType.AFFECTS_OUTCOME,
            object=EvidenceTerm(ConceptType.OUTCOME, "sleep quality"),
            source_chunk_ids=("chunk_001",),
            review_status=ReviewStatus.PENDING,
        )
        with self.assertRaises(SchemaValidationError):
            assertion.validate_publishable()

    def test_second_domain_fixture_needs_no_generic_model_change(self) -> None:
        fixture_domain = build_domain_config(
            domain_id="fixture_domain",
            schema_version="fixture-v0.1",
            display_name="Fixture Domain",
            allowed_concept_types=("intervention", "outcome"),
            allowed_predicates=("affects_outcome",),
        )
        fixture_domain.validate_concept_type("intervention")
        concept = CanonicalConcept(
            id="fixture_concept",
            domain_id=fixture_domain.domain_id,
            type=ConceptType.INTERVENTION,
            preferred_name="fixture intervention",
        )
        self.assertEqual(concept.domain_id, "fixture_domain")

    def test_terminology_seed_contains_tvns_translation_guards(self) -> None:
        terminology_path = ROOT / "config" / "domains" / "acupuncture" / "terminology.v0.1.json"
        terms = json.loads(terminology_path.read_text(encoding="utf-8"))["terms"]
        aliases_by_id = {term["canonical_id"]: set(term["aliases"]) for term in terms}
        self.assertIn("Cymba Conchae", aliases_by_id["site:cymba_conchae"])
        self.assertIn("cavum conchae", aliases_by_id["site:cavum_conchae"])
        self.assertIn("tragus", aliases_by_id["site:tragus"])
        self.assertIn("Postpartum blues", aliases_by_id["condition:blues"])

    def test_graph_release_requires_assertion_ids(self) -> None:
        with self.assertRaises(SchemaValidationError):
            GraphRelease(
                id="release_empty",
                domain_id="acupuncture",
                version="v0.1",
                included_assertion_ids=(),
                schema_version="acupuncture-tvns-v0.1.0",
                index_version="none",
                released_by="reviewer_001",
            )


if __name__ == "__main__":
    unittest.main()
