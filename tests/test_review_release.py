# ruff: noqa: E402

from __future__ import annotations

import json
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
    SourceQualitySignals,
    SourceQualityTier,
)
from lingshu_nexus.extraction import CandidateExtractionRun
from lingshu_nexus.persistence.migrations import load_migration_pair
from lingshu_nexus.persistence.models import DataLayer, JobStatus
from lingshu_nexus.persistence.object_store import InMemoryObjectStore
from lingshu_nexus.review import (
    InMemoryReviewRepository,
    NormalizationStatus,
    ReleaseValidationError,
    ReviewReleaseService,
    load_acupuncture_terminology_normalizer,
)


class ReviewReleaseWorkflowTestCase(unittest.TestCase):
    def test_review_batch_standardizes_tvns_terms_without_auto_merging_sensitive_disease(
        self,
    ) -> None:
        service, _repository, _store = _service()
        run, chunks = _candidate_run()

        batch = service.create_review_batch(run=run, source_chunks=chunks, created_by="worker")

        reviewed = service.get_assertion(domain_id="acupuncture", assertion_id="assertion_sleep")
        self.assertEqual(reviewed.subject.text, "taVNS")
        self.assertEqual(reviewed.subject.concept_id, "intervention:taVNS")
        self.assertEqual(reviewed.subject.original_text, "tVNS")
        assert reviewed.parameter_set is not None
        self.assertEqual(reviewed.parameter_set.stimulation_site, "耳甲艇")
        self.assertEqual(reviewed.parameter_set.raw_text, "Cymba Conchae")
        self.assertEqual(reviewed.metadata["lineage"]["parser_versions"], ("parser-v0.1",))

        sensitive = service.get_assertion(domain_id="acupuncture", assertion_id="assertion_blues")
        self.assertIsNone(sensitive.object.concept_id)
        self.assertEqual(sensitive.object.text, "Postpartum blues")
        disease_candidates = [
            candidate
            for candidate in batch.normalization_candidates
            if candidate.assertion_id == "assertion_blues"
            and candidate.original_text == "Postpartum blues"
        ]
        self.assertEqual(disease_candidates[0].status, NormalizationStatus.NEEDS_REVIEW)

    def test_unreviewed_candidate_cannot_enter_release(self) -> None:
        service, _repository, _store = _service()
        run, chunks = _candidate_run()
        service.create_review_batch(run=run, source_chunks=chunks, created_by="worker")

        preview = service.preview_release(
            domain_id="acupuncture",
            assertion_ids=("assertion_sleep",),
        )
        self.assertEqual(preview.included_assertion_ids, ())
        self.assertEqual(preview.excluded_assertions[0].reason, "review_status:pending")
        with self.assertRaises(ReleaseValidationError):
            service.create_release(
                domain_id="acupuncture",
                version="v0.1.0",
                assertion_ids=("assertion_sleep",),
                released_by="reviewer",
            )

    def test_approved_modified_and_rejected_assertions_are_handled_before_release(self) -> None:
        service, _repository, store = _service()
        run, chunks = _candidate_run()
        service.create_review_batch(run=run, source_chunks=chunks, created_by="worker")

        approved = service.approve_assertion(
            domain_id="acupuncture",
            assertion_id="assertion_sleep",
            reviewer="reviewer_a",
            reason="Source locator and parameter fields verified.",
        )
        modified = service.modify_assertion(
            domain_id="acupuncture",
            assertion_id="assertion_blues",
            reviewer="reviewer_a",
            reason="Reviewer confirmed this is a non-diagnostic symptom concept.",
            object_concept_id="condition:blues",
            metadata_updates={"reviewer_normalization": "manual condition:blues mapping"},
        )
        rejected = service.reject_assertion(
            domain_id="acupuncture",
            assertion_id="assertion_rejected",
            reviewer="reviewer_a",
            reason="The assertion overstates a background mention.",
        )

        self.assertEqual(approved.review_status, ReviewStatus.APPROVED)
        self.assertEqual(modified.review_status, ReviewStatus.APPROVED)
        self.assertEqual(modified.object.concept_id, "condition:blues")
        self.assertEqual(rejected.review_status, ReviewStatus.REJECTED)
        self.assertEqual(run.evidence_assertions[0].review_status, ReviewStatus.PENDING)

        preview = service.preview_release(
            domain_id="acupuncture",
            assertion_ids=("assertion_sleep", "assertion_blues", "assertion_rejected"),
        )
        self.assertEqual(preview.included_assertion_ids, ("assertion_sleep", "assertion_blues"))
        self.assertEqual(preview.excluded_assertions[0].assertion_id, "assertion_rejected")
        self.assertEqual(preview.excluded_assertions[0].reason, "review_status:rejected")

        record = service.create_release(
            domain_id="acupuncture",
            version="v0.1.0",
            assertion_ids=preview.included_assertion_ids,
            released_by="reviewer_a",
        )
        self.assertEqual(record.artifact_ref.layer, DataLayer.PUBLISHED)
        artifact = json.loads(store.get(record.artifact_ref, domain_id="acupuncture"))
        self.assertEqual(artifact["release"]["version"], "v0.1.0")
        self.assertEqual(len(artifact["assertions"]), 2)
        self.assertEqual(
            artifact["assertions"][0]["source_quality_signals"]["tier"], "top_database_high_impact"
        )

    def test_release_activation_and_rollback_keep_history_queryable(self) -> None:
        service, _repository, _store = _service()
        run, chunks = _candidate_run()
        service.create_review_batch(run=run, source_chunks=chunks, created_by="worker")
        service.approve_assertion(
            domain_id="acupuncture",
            assertion_id="assertion_sleep",
            reviewer="reviewer_a",
            reason="Verified.",
        )
        service.modify_assertion(
            domain_id="acupuncture",
            assertion_id="assertion_blues",
            reviewer="reviewer_a",
            reason="Manual symptom mapping.",
            object_concept_id="condition:blues",
        )

        release_1 = service.create_release(
            domain_id="acupuncture",
            version="v0.1.0",
            assertion_ids=("assertion_sleep",),
            released_by="reviewer_a",
        )
        release_2 = service.create_release(
            domain_id="acupuncture",
            version="v0.2.0",
            assertion_ids=("assertion_sleep", "assertion_blues"),
            released_by="reviewer_a",
        )
        service.activate_release(
            domain_id="acupuncture",
            release_id=release_1.release.id,
            actor_id="admin",
        )
        service.activate_release(
            domain_id="acupuncture",
            release_id=release_2.release.id,
            actor_id="admin",
        )
        active = service.active_release(domain_id="acupuncture")
        assert active is not None
        self.assertEqual(active.release.id, release_2.release.id)

        service.rollback_to_release(
            domain_id="acupuncture",
            release_id=release_1.release.id,
            actor_id="admin",
            reason="Rollback smoke test.",
        )
        active_after_rollback = service.active_release(domain_id="acupuncture")
        assert active_after_rollback is not None
        self.assertEqual(active_after_rollback.release.id, release_1.release.id)
        self.assertEqual(len(service.list_releases(domain_id="acupuncture")), 2)

    def test_conflict_assertions_can_coexist_in_one_release(self) -> None:
        service, _repository, _store = _service()
        run, chunks = _candidate_run(include_conflict_pair=True)
        service.create_review_batch(run=run, source_chunks=chunks, created_by="worker")

        first = service.mark_conflict(
            domain_id="acupuncture",
            assertion_id="assertion_sleep",
            reviewer="reviewer_a",
            reason="Conflicts with a no-difference finding from the same fixture set.",
            conflict_with_assertion_ids=("assertion_sleep_no_difference",),
        )
        second = service.mark_conflict(
            domain_id="acupuncture",
            assertion_id="assertion_sleep_no_difference",
            reviewer="reviewer_a",
            reason="Conflicts with an improved finding from the same fixture set.",
            conflict_with_assertion_ids=("assertion_sleep",),
        )
        self.assertEqual(first.review_status, ReviewStatus.CONFLICT)
        self.assertEqual(second.review_status, ReviewStatus.CONFLICT)

        preview = service.preview_release(
            domain_id="acupuncture",
            assertion_ids=("assertion_sleep", "assertion_sleep_no_difference"),
        )
        self.assertEqual(
            preview.conflict_assertion_ids,
            ("assertion_sleep", "assertion_sleep_no_difference"),
        )
        record = service.create_release(
            domain_id="acupuncture",
            version="v0.1-conflict",
            assertion_ids=preview.included_assertion_ids,
            released_by="reviewer_a",
        )
        self.assertEqual(
            tuple(assertion.review_status for assertion in record.assertions),
            (ReviewStatus.CONFLICT, ReviewStatus.CONFLICT),
        )

    def test_review_release_migration_can_apply_and_drop(self) -> None:
        migrations = [
            load_migration_pair("0001_foundation"),
            load_migration_pair("0002_document_ingestion"),
            load_migration_pair("0003_candidate_extraction"),
            load_migration_pair("0004_review_release"),
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
            self.assertIn("review_batches", table_names)
            self.assertIn("standardization_candidates", table_names)
            self.assertIn("release_snapshots", table_names)
            for migration in reversed(migrations):
                connection.executescript(migration.down_sql)
            remaining = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
            self.assertEqual(remaining, [])
        finally:
            connection.close()


def _service() -> tuple[ReviewReleaseService, InMemoryReviewRepository, InMemoryObjectStore]:
    repository = InMemoryReviewRepository()
    store = InMemoryObjectStore()
    service = ReviewReleaseService(
        repository=repository,
        object_store=store,
        normalizer=load_acupuncture_terminology_normalizer(),
    )
    return service, repository, store


def _candidate_run(
    *,
    include_conflict_pair: bool = False,
) -> tuple[CandidateExtractionRun, tuple[SourceChunk, ...]]:
    chunks = (
        SourceChunk(
            id="chunk_sleep",
            domain_id="acupuncture",
            document_id="doc_tvns",
            locator=ChunkLocator(chunk_index=0, page=2, heading="Results"),
            text="tVNS at the Cymba Conchae improved PSQI sleep quality.",
            parser_version="parser-v0.1",
        ),
        SourceChunk(
            id="chunk_blues",
            domain_id="acupuncture",
            document_id="doc_tvns",
            locator=ChunkLocator(chunk_index=1, page=3, heading="Population"),
            text="The study discussed Postpartum blues as a symptom-level state.",
            parser_version="parser-v0.1",
        ),
        SourceChunk(
            id="chunk_background",
            domain_id="acupuncture",
            document_id="doc_tvns",
            locator=ChunkLocator(chunk_index=2, page=4, heading="Discussion"),
            text="A background paragraph mentioned safety without trial evidence.",
            parser_version="parser-v0.1",
        ),
    )
    assertions = [
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
                is_highly_cited=True,
            ),
        ),
        EvidenceAssertion(
            id="assertion_blues",
            domain_id="acupuncture",
            subject=EvidenceTerm(ConceptType.INTERVENTION, "taVNS"),
            predicate=PredicateType.RELATED_TO,
            object=EvidenceTerm(ConceptType.DISEASE_OR_SYMPTOM, "Postpartum blues"),
            source_chunk_ids=("chunk_blues",),
            review_status=ReviewStatus.PENDING,
            direction=Direction.UNCLEAR,
            extraction_confidence=0.7,
            source_quality_signals=SourceQualitySignals(tier=SourceQualityTier.DATABASE_OTHER),
        ),
        EvidenceAssertion(
            id="assertion_rejected",
            domain_id="acupuncture",
            subject=EvidenceTerm(ConceptType.INTERVENTION, "taVNS"),
            predicate=PredicateType.HAS_SAFETY_EVENT,
            object=EvidenceTerm(ConceptType.SAFETY, "minor adverse event"),
            source_chunk_ids=("chunk_background",),
            review_status=ReviewStatus.PENDING,
            extraction_confidence=0.45,
            source_quality_signals=SourceQualitySignals(tier=SourceQualityTier.BACKGROUND_ONLY),
        ),
    ]
    if include_conflict_pair:
        assertions.append(
            EvidenceAssertion(
                id="assertion_sleep_no_difference",
                domain_id="acupuncture",
                subject=EvidenceTerm(ConceptType.INTERVENTION, "taVNS"),
                predicate=PredicateType.AFFECTS_OUTCOME,
                object=EvidenceTerm(ConceptType.OUTCOME, "sleep quality"),
                source_chunk_ids=("chunk_sleep",),
                review_status=ReviewStatus.PENDING,
                population="adults with insomnia symptoms",
                parameter_set=ParameterSet(
                    stimulation_site="cymba conchae",
                    frequency_hz=10,
                    pulse_width_us=200,
                    raw_text="cymba conchae",
                ),
                outcome="PSQI",
                direction=Direction.NO_DIFFERENCE,
                extraction_confidence=0.83,
                source_quality_signals=SourceQualitySignals(tier=SourceQualityTier.DATABASE_OTHER),
            )
        )
    run = CandidateExtractionRun(
        id="extract_fixture",
        domain_id="acupuncture",
        document_id="doc_tvns",
        status=JobStatus.SUCCEEDED,
        provider="fake",
        model="fake-model",
        prompt_version="literature-extraction-v0.1.0",
        schema_version="candidate-extraction-v0.1.0",
        source_chunk_ids=tuple(chunk.id for chunk in chunks),
        evidence_assertions=tuple(assertions),
    )
    return run, chunks


if __name__ == "__main__":
    unittest.main()
