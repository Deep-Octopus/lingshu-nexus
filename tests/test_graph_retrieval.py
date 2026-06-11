# ruff: noqa: E402

from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "lingshu-domain" / "src"))

from lingshu_domain import (
    ChunkLocator,
    ConceptType,
    Direction,
    EvidenceAssertion,
    EvidenceTerm,
    ParameterSet,
    PredicateType,
    ReviewStatus,
    SourceChunk,
    SourceDocument,
    SourceQualitySignals,
    SourceQualityTier,
)
from lingshu_nexus.extraction import CandidateExtractionRun
from lingshu_nexus.persistence.graph import InMemoryGraphRepository
from lingshu_nexus.persistence.migrations import load_migration_pair
from lingshu_nexus.persistence.models import JobStatus
from lingshu_nexus.persistence.object_store import InMemoryObjectStore
from lingshu_nexus.retrieval import ReleaseNotIndexedError, RetrievalService
from lingshu_nexus.review import (
    InMemoryReviewRepository,
    ReviewReleaseService,
    load_acupuncture_terminology_normalizer,
)


class GraphRetrievalTestCase(unittest.TestCase):
    def test_retrieval_reads_only_active_release_and_returns_chunk_locator(self) -> None:
        retrieval, review_service, source_document, chunks = _services()
        batch = review_service.create_review_batch(
            run=_candidate_run(),
            source_chunks=chunks,
            created_by="worker",
        )
        self.assertIn("assertion_unpublished", batch.assertion_ids)
        review_service.approve_assertion(
            domain_id="acupuncture",
            assertion_id="assertion_sleep",
            reviewer="reviewer_a",
            reason="Locator and parameters verified.",
        )
        release = review_service.create_release(
            domain_id="acupuncture",
            version="v0.1.0",
            assertion_ids=("assertion_sleep",),
            released_by="reviewer_a",
        )
        review_service.activate_release(
            domain_id="acupuncture",
            release_id=release.release.id,
            actor_id="admin",
        )

        retrieval.sync_active_release(
            domain_id="acupuncture",
            source_documents=(source_document,),
            source_chunks=chunks,
        )
        response = retrieval.search(
            domain_id="acupuncture",
            query="Cymba Conchae PSQI sleep",
            limit=5,
        )

        self.assertEqual(response.release.id, release.release.id)
        self.assertEqual(
            tuple(result.assertion.id for result in response.results), ("assertion_sleep",)
        )
        citation = response.results[0].citations[0]
        self.assertEqual(citation.document_id, "doc_tvns")
        self.assertEqual(citation.chunk_id, "chunk_sleep")
        self.assertEqual(citation.locator_reference, "chunk:0|page:2|heading:Results")
        self.assertEqual(citation.document_title, "taVNS insomnia fixture")

        leaked = retrieval.search(
            domain_id="acupuncture",
            query="unpublished dizziness",
            limit=5,
        )
        self.assertEqual(leaked.results, ())

    def test_switching_active_release_changes_retrieval_results(self) -> None:
        retrieval, review_service, source_document, chunks = _services()
        review_service.create_review_batch(
            run=_candidate_run(),
            source_chunks=chunks,
            created_by="worker",
        )
        for assertion_id in ("assertion_sleep", "assertion_safety"):
            review_service.approve_assertion(
                domain_id="acupuncture",
                assertion_id=assertion_id,
                reviewer="reviewer_a",
                reason="Verified.",
            )
        release_1 = review_service.create_release(
            domain_id="acupuncture",
            version="v0.1.0",
            assertion_ids=("assertion_sleep",),
            released_by="reviewer_a",
        )
        release_2 = review_service.create_release(
            domain_id="acupuncture",
            version="v0.2.0",
            assertion_ids=("assertion_safety",),
            released_by="reviewer_a",
        )
        review_service.activate_release(
            domain_id="acupuncture",
            release_id=release_1.release.id,
            actor_id="admin",
        )
        retrieval.sync_active_release(
            domain_id="acupuncture",
            source_documents=(source_document,),
            source_chunks=chunks,
        )
        self.assertEqual(
            tuple(
                result.assertion.id
                for result in retrieval.search(
                    domain_id="acupuncture",
                    query="sleep PSQI",
                ).results
            ),
            ("assertion_sleep",),
        )

        review_service.activate_release(
            domain_id="acupuncture",
            release_id=release_2.release.id,
            actor_id="admin",
        )
        retrieval.sync_active_release(
            domain_id="acupuncture",
            source_documents=(source_document,),
            source_chunks=chunks,
        )
        self.assertEqual(
            retrieval.search(domain_id="acupuncture", query="sleep PSQI").results,
            (),
        )
        self.assertEqual(
            tuple(
                result.assertion.id
                for result in retrieval.search(
                    domain_id="acupuncture",
                    query="adverse event safety",
                ).results
            ),
            ("assertion_safety",),
        )

    def test_graph_navigation_returns_concepts_relationships_and_documents(self) -> None:
        retrieval, review_service, source_document, chunks = _services()
        review_service.create_review_batch(
            run=_candidate_run(),
            source_chunks=chunks,
            created_by="worker",
        )
        review_service.approve_assertion(
            domain_id="acupuncture",
            assertion_id="assertion_sleep",
            reviewer="reviewer_a",
            reason="Verified.",
        )
        release = review_service.create_release(
            domain_id="acupuncture",
            version="v0.1.0",
            assertion_ids=("assertion_sleep",),
            released_by="reviewer_a",
        )
        review_service.activate_release(
            domain_id="acupuncture",
            release_id=release.release.id,
            actor_id="admin",
        )
        retrieval.sync_active_release(
            domain_id="acupuncture",
            source_documents=(source_document,),
            source_chunks=chunks,
        )

        concepts = retrieval.find_concepts(domain_id="acupuncture", query="taVNS")
        self.assertEqual(concepts[0].properties["concept_id"], "intervention:taVNS")
        relationships = retrieval.relationships_for_concept(
            domain_id="acupuncture",
            concept_id="intervention:taVNS",
        )
        self.assertEqual(relationships[0].type, PredicateType.AFFECTS_OUTCOME.value)
        documents = retrieval.source_documents_for_active_release(domain_id="acupuncture")
        self.assertEqual(tuple(document.id for document in documents), ("doc_tvns",))

    def test_retrieval_requires_indexed_active_release(self) -> None:
        retrieval, _review_service, _source_document, _chunks = _services()

        with self.assertRaises(ReleaseNotIndexedError):
            retrieval.search(domain_id="acupuncture", query="sleep")

    def test_graph_retrieval_migration_can_apply_and_drop(self) -> None:
        migrations = [
            load_migration_pair("0001_foundation"),
            load_migration_pair("0002_document_ingestion"),
            load_migration_pair("0003_candidate_extraction"),
            load_migration_pair("0004_review_release"),
            load_migration_pair("0005_graph_retrieval"),
        ]
        connection = sqlite3.connect(":memory:")
        try:
            for migration in migrations:
                connection.executescript(migration.up_sql)
            table_names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            self.assertIn("published_graph_nodes", table_names)
            self.assertIn("published_graph_relationships", table_names)
            self.assertIn("retrieval_index_entries", table_names)
            for migration in reversed(migrations):
                connection.executescript(migration.down_sql)
            remaining = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
            self.assertEqual(remaining, [])
        finally:
            connection.close()


def _services() -> tuple[
    RetrievalService, ReviewReleaseService, SourceDocument, tuple[SourceChunk, ...]
]:
    review_repository = InMemoryReviewRepository()
    review_service = ReviewReleaseService(
        repository=review_repository,
        object_store=InMemoryObjectStore(),
        normalizer=load_acupuncture_terminology_normalizer(),
    )
    retrieval = RetrievalService(
        graph_repository=InMemoryGraphRepository(),
        release_reader=review_service,
    )
    return retrieval, review_service, _source_document(), _source_chunks()


def _source_document() -> SourceDocument:
    return SourceDocument(
        id="doc_tvns",
        domain_id="acupuncture",
        title="taVNS insomnia fixture",
        content_hash="fixture-hash",
        file_version=1,
        source_uri="memory://doc_tvns",
        topic_tags=("tVNS", "taVNS"),
        source_quality_tier=SourceQualityTier.TOP_DATABASE_HIGH_IMPACT,
    )


def _source_chunks() -> tuple[SourceChunk, ...]:
    return (
        SourceChunk(
            id="chunk_sleep",
            domain_id="acupuncture",
            document_id="doc_tvns",
            locator=ChunkLocator(chunk_index=0, page=2, heading="Results"),
            text="tVNS at the Cymba Conchae improved PSQI sleep quality.",
            parser_version="parser-v0.1",
        ),
        SourceChunk(
            id="chunk_safety",
            domain_id="acupuncture",
            document_id="doc_tvns",
            locator=ChunkLocator(chunk_index=1, page=4, heading="Safety"),
            text="The trial monitored minor adverse event safety signals.",
            parser_version="parser-v0.1",
        ),
        SourceChunk(
            id="chunk_unpublished",
            domain_id="acupuncture",
            document_id="doc_tvns",
            locator=ChunkLocator(chunk_index=2, page=5, heading="Unreviewed"),
            text="Unpublished dizziness was mentioned in candidate-only output.",
            parser_version="parser-v0.1",
        ),
    )


def _candidate_run() -> CandidateExtractionRun:
    return CandidateExtractionRun(
        id="extract_fixture",
        domain_id="acupuncture",
        document_id="doc_tvns",
        status=JobStatus.SUCCEEDED,
        provider="fake",
        model="fake-model",
        prompt_version="literature-extraction-v0.1.0",
        schema_version="candidate-extraction-v0.1.0",
        source_chunk_ids=("chunk_sleep", "chunk_safety", "chunk_unpublished"),
        evidence_assertions=(
            EvidenceAssertion(
                id="assertion_sleep",
                domain_id="acupuncture",
                subject=EvidenceTerm(ConceptType.INTERVENTION, "tVNS"),
                predicate=PredicateType.AFFECTS_OUTCOME,
                object=EvidenceTerm(ConceptType.OUTCOME, "sleep quality"),
                source_chunk_ids=("chunk_sleep",),
                review_status=ReviewStatus.PENDING,
                population="adults with insomnia symptoms",
                parameter_set=ParameterSet(
                    stimulation_site="Cymba Conchae",
                    frequency_hz=25,
                    pulse_width_us=250,
                    raw_text="Cymba Conchae",
                ),
                outcome="PSQI",
                direction=Direction.IMPROVED,
                extraction_confidence=0.88,
                source_quality_signals=SourceQualitySignals(
                    tier=SourceQualityTier.TOP_DATABASE_HIGH_IMPACT,
                    journal_quartile="Q1",
                    citation_count=50,
                ),
            ),
            EvidenceAssertion(
                id="assertion_safety",
                domain_id="acupuncture",
                subject=EvidenceTerm(ConceptType.INTERVENTION, "taVNS"),
                predicate=PredicateType.HAS_SAFETY_EVENT,
                object=EvidenceTerm(ConceptType.SAFETY, "minor adverse event"),
                source_chunk_ids=("chunk_safety",),
                review_status=ReviewStatus.PENDING,
                direction=Direction.UNCLEAR,
                extraction_confidence=0.74,
                source_quality_signals=SourceQualitySignals(tier=SourceQualityTier.DATABASE_OTHER),
            ),
            EvidenceAssertion(
                id="assertion_unpublished",
                domain_id="acupuncture",
                subject=EvidenceTerm(ConceptType.INTERVENTION, "taVNS"),
                predicate=PredicateType.HAS_SAFETY_EVENT,
                object=EvidenceTerm(ConceptType.SAFETY, "unpublished dizziness"),
                source_chunk_ids=("chunk_unpublished",),
                review_status=ReviewStatus.PENDING,
                extraction_confidence=0.61,
                source_quality_signals=SourceQualitySignals(tier=SourceQualityTier.DATABASE_OTHER),
            ),
        ),
    )


if __name__ == "__main__":
    unittest.main()
