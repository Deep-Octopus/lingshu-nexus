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
from lingshu_nexus.retrieval import RetrievalService
from lingshu_nexus.review import (
    InMemoryReviewRepository,
    ReviewReleaseService,
    load_acupuncture_terminology_normalizer,
)
from lingshu_nexus.skills import (
    InMemorySkillRepository,
    SkillDefinition,
    SkillPermissionError,
    SkillRegistryService,
    SkillRouteMode,
    SkillScope,
    SkillStatus,
    UserRole,
    classify_skill_query_type,
)


class SkillRegistryTestCase(unittest.TestCase):
    def test_builtin_skills_validate_and_list_versions(self) -> None:
        service, _repository, _retrieval, _review_service = _skill_service()

        skills = service.list_skills(domain_id="acupuncture")

        self.assertEqual(
            tuple(skill.id for skill in skills), ("evidence-query", "literature-landscape")
        )
        self.assertEqual(tuple(skill.version for skill in skills), ("0.1.0", "0.1.0"))
        for skill in skills:
            report = service.validate_skill(domain_id="acupuncture", skill_id=skill.id)
            self.assertTrue(report.valid, report.issues)
            self.assertEqual(report.issues, ())
            self.assertTrue(skill.test_cases_path)
            self.assertEqual(skill.scope, SkillScope.READ_ONLY)

    def test_user_specified_skill_executes_against_active_release_and_logs_citations(self) -> None:
        service, _repository, retrieval, review_service = _skill_service()
        _publish_fixture_release(retrieval, review_service)

        result = service.execute(
            domain_id="acupuncture",
            query="Cymba Conchae frequency 25 Hz PSQI parameter",
            actor_id="researcher_1",
            actor_role=UserRole.RESEARCHER,
            skill_id="evidence-query",
        )

        self.assertEqual(result.record.skill_id, "evidence-query")
        self.assertEqual(result.record.route_mode, SkillRouteMode.USER_SPECIFIED)
        self.assertEqual(result.record.release_version, "v0.1.0")
        self.assertEqual(result.record.query_type, "frequency_effect")
        self.assertIn("仅用于内部科研证据辅助", result.answer)
        self.assertIn("frequency=25Hz", result.answer)
        self.assertIn("doc_tvns", tuple(citation.document_id for citation in result.citations))
        logs = service.list_execution_records(domain_id="acupuncture", skill_id="evidence-query")
        self.assertEqual(len(logs), 1)
        self.assertIn("doc_tvns:chunk_params:chunk:0|page:2|heading:Results", logs[0].citation_keys)

    def test_disabled_and_unauthorized_skills_cannot_execute(self) -> None:
        service, _repository, retrieval, review_service = _skill_service()
        _publish_fixture_release(retrieval, review_service)

        with self.assertRaises(SkillPermissionError):
            service.execute(
                domain_id="acupuncture",
                query="safety adverse event",
                actor_id="readonly_1",
                actor_role=UserRole.READ_ONLY,
                skill_id="evidence-query",
            )

        service.set_status(
            domain_id="acupuncture",
            skill_id="evidence-query",
            status=SkillStatus.DISABLED,
            actor_role=UserRole.ADMIN,
        )
        with self.assertRaises(SkillPermissionError):
            service.execute(
                domain_id="acupuncture",
                query="safety adverse event",
                actor_id="researcher_1",
                actor_role=UserRole.RESEARCHER,
                skill_id="evidence-query",
            )

    def test_auto_route_ignores_disabled_and_background_write_skills(self) -> None:
        service, repository, retrieval, review_service = _skill_service()
        _publish_fixture_release(retrieval, review_service)
        repository.upsert_skill(_background_write_skill())
        service.set_status(
            domain_id="acupuncture",
            skill_id="evidence-query",
            status=SkillStatus.DISABLED,
            actor_role=UserRole.ADMIN,
        )

        result = service.execute(
            domain_id="acupuncture",
            query="mechanism vagal afferent modulation for taVNS",
            actor_id="researcher_1",
            actor_role=UserRole.RESEARCHER,
        )

        self.assertEqual(result.record.skill_id, "literature-landscape")
        self.assertEqual(result.record.route_mode, SkillRouteMode.AUTO)
        self.assertIn("命题分布", result.answer)
        self.assertNotEqual(result.record.skill_id, "graph-review-assistant")

    def test_query_classifier_covers_tvns_v1_question_types(self) -> None:
        cases = {
            "刺激参数和 sham control 怎么汇总": "parameter_summary",
            "taVNS 安全性和禁忌证": "safety_contraindication",
            "25 Hz frequency effect": "frequency_effect",
            "mechanism vagal afferent pathway": "mechanism_summary",
            "RCT randomized trial design": "rct_design_summary",
            "按时间列出文献 timeline": "timeline_literature",
        }
        for query, expected in cases.items():
            with self.subTest(query=query):
                self.assertEqual(classify_skill_query_type(query), expected)

    def test_skill_registry_migration_can_apply_and_drop(self) -> None:
        migrations = [
            load_migration_pair("0001_foundation"),
            load_migration_pair("0002_document_ingestion"),
            load_migration_pair("0003_candidate_extraction"),
            load_migration_pair("0004_review_release"),
            load_migration_pair("0005_graph_retrieval"),
            load_migration_pair("0006_skill_registry"),
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
            self.assertIn("skill_registry_entries", table_names)
            self.assertIn("skill_execution_logs", table_names)
            for migration in reversed(migrations):
                connection.executescript(migration.down_sql)
            remaining = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
            self.assertEqual(remaining, [])
        finally:
            connection.close()


def _skill_service() -> tuple[
    SkillRegistryService,
    InMemorySkillRepository,
    RetrievalService,
    ReviewReleaseService,
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
    repository = InMemorySkillRepository()
    service = SkillRegistryService(
        repository=repository,
        retrieval_service=retrieval,
        skills_root=ROOT / "skills",
    )
    service.load_from_filesystem()
    return service, repository, retrieval, review_service


def _publish_fixture_release(
    retrieval: RetrievalService,
    review_service: ReviewReleaseService,
) -> None:
    review_service.create_review_batch(
        run=_candidate_run(),
        source_chunks=_source_chunks(),
        created_by="worker",
    )
    for assertion_id in ("assertion_params", "assertion_safety", "assertion_mechanism"):
        review_service.approve_assertion(
            domain_id="acupuncture",
            assertion_id=assertion_id,
            reviewer="reviewer_1",
            reason="Fixture source locator verified.",
        )
    release = review_service.create_release(
        domain_id="acupuncture",
        version="v0.1.0",
        assertion_ids=("assertion_params", "assertion_safety", "assertion_mechanism"),
        released_by="reviewer_1",
    )
    review_service.activate_release(
        domain_id="acupuncture",
        release_id=release.release.id,
        actor_id="admin_1",
    )
    retrieval.sync_active_release(
        domain_id="acupuncture",
        source_documents=(_source_document(),),
        source_chunks=_source_chunks(),
    )


def _source_document() -> SourceDocument:
    return SourceDocument(
        id="doc_tvns",
        domain_id="acupuncture",
        title="taVNS research fixture",
        content_hash="fixture-hash",
        file_version=1,
        source_uri="memory://doc_tvns",
        topic_tags=("tVNS", "taVNS"),
        source_quality_tier=SourceQualityTier.TOP_DATABASE_HIGH_IMPACT,
    )


def _source_chunks() -> tuple[SourceChunk, ...]:
    return (
        SourceChunk(
            id="chunk_params",
            domain_id="acupuncture",
            document_id="doc_tvns",
            locator=ChunkLocator(chunk_index=0, page=2, heading="Results"),
            text=(
                "taVNS at Cymba Conchae used 25 Hz frequency, 250 us pulse width, "
                "and improved PSQI sleep quality."
            ),
            parser_version="parser-v0.1",
        ),
        SourceChunk(
            id="chunk_safety",
            domain_id="acupuncture",
            document_id="doc_tvns",
            locator=ChunkLocator(chunk_index=1, page=4, heading="Safety"),
            text="The RCT monitored safety, adverse event signals, and exclusion criteria.",
            parser_version="parser-v0.1",
        ),
        SourceChunk(
            id="chunk_mechanism",
            domain_id="acupuncture",
            document_id="doc_tvns",
            locator=ChunkLocator(chunk_index=2, page=5, heading="Mechanism"),
            text="The mechanism hypothesis involved vagal afferent modulation.",
            parser_version="parser-v0.1",
        ),
    )


def _candidate_run() -> CandidateExtractionRun:
    return CandidateExtractionRun(
        id="extract_tvns_skill_fixture",
        domain_id="acupuncture",
        document_id="doc_tvns",
        status=JobStatus.SUCCEEDED,
        provider="fake",
        model="fake-model",
        prompt_version="literature-extraction-v0.1.0",
        schema_version="candidate-extraction-v0.1.0",
        source_chunk_ids=("chunk_params", "chunk_safety", "chunk_mechanism"),
        evidence_assertions=(
            EvidenceAssertion(
                id="assertion_params",
                domain_id="acupuncture",
                subject=EvidenceTerm(ConceptType.INTERVENTION, "taVNS"),
                predicate=PredicateType.AFFECTS_OUTCOME,
                object=EvidenceTerm(ConceptType.OUTCOME, "PSQI sleep quality"),
                source_chunk_ids=("chunk_params",),
                review_status=ReviewStatus.PENDING,
                population="adults with insomnia symptoms",
                parameter_set=ParameterSet(
                    stimulation_site="Cymba Conchae",
                    frequency_hz=25,
                    pulse_width_us=250,
                    raw_text="Cymba Conchae 25 Hz 250 us",
                ),
                outcome="PSQI",
                direction=Direction.IMPROVED,
                extraction_confidence=0.9,
                source_quality_signals=SourceQualitySignals(
                    tier=SourceQualityTier.TOP_DATABASE_HIGH_IMPACT,
                    journal_quartile="Q1",
                    citation_count=80,
                ),
            ),
            EvidenceAssertion(
                id="assertion_safety",
                domain_id="acupuncture",
                subject=EvidenceTerm(ConceptType.INTERVENTION, "taVNS"),
                predicate=PredicateType.HAS_SAFETY_EVENT,
                object=EvidenceTerm(ConceptType.SAFETY, "minor adverse event monitoring"),
                source_chunk_ids=("chunk_safety",),
                review_status=ReviewStatus.PENDING,
                direction=Direction.UNCLEAR,
                extraction_confidence=0.8,
                source_quality_signals=SourceQualitySignals(tier=SourceQualityTier.DATABASE_OTHER),
            ),
            EvidenceAssertion(
                id="assertion_mechanism",
                domain_id="acupuncture",
                subject=EvidenceTerm(ConceptType.INTERVENTION, "taVNS"),
                predicate=PredicateType.HAS_MECHANISM,
                object=EvidenceTerm(ConceptType.MECHANISM, "vagal afferent modulation"),
                source_chunk_ids=("chunk_mechanism",),
                review_status=ReviewStatus.PENDING,
                direction=Direction.UNCLEAR,
                extraction_confidence=0.72,
                source_quality_signals=SourceQualitySignals(tier=SourceQualityTier.DATABASE_OTHER),
                metadata={"study_design": "sham-controlled RCT"},
            ),
        ),
    )


def _background_write_skill() -> SkillDefinition:
    return SkillDefinition(
        id="graph-review-assistant",
        name="graph-review-assistant",
        description="Background graph review helper that must not be auto-routed from chat.",
        version="0.1.0",
        status=SkillStatus.ACTIVE,
        scope=SkillScope.BACKGROUND_WRITE,
        minimum_role=UserRole.ADMIN,
        server_allowed_tools=("graph_write",),
        supported_query_types=("mechanism_summary", "evidence_lookup"),
        domain_ids=("acupuncture",),
        checksum="fixture",
        source_path="memory://graph-review-assistant",
    )


if __name__ == "__main__":
    unittest.main()
