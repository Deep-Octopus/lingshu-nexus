# ruff: noqa: E402

from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

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
from lingshu_nexus.api.main import create_app
from lingshu_nexus.chat import create_chat_service
from lingshu_nexus.documents import (
    CompositeDocumentParser,
    DocumentIngestService,
    DocumentRecord,
    DocumentStatus,
    InMemoryDocumentRepository,
    MarkdownDocumentParser,
    PyPdfDocumentParser,
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
from lingshu_nexus.skills import InMemorySkillRepository, SkillRegistryService


class ChatStreamTestCase(unittest.TestCase):
    def test_sse_stream_returns_text_citations_done_and_records_feedback(self) -> None:
        client = _client_with_fixture(active_release=True)
        session_id = _create_session(client)

        events = _stream_events(
            client,
            session_id=session_id,
            query="Cymba Conchae frequency 25 Hz PSQI parameter",
            skill_id="evidence-query",
        )

        self.assertIn("retrieval", [event["event"] for event in events])
        self.assertIn("text", [event["event"] for event in events])
        self.assertIn("citation", [event["event"] for event in events])
        self.assertEqual(events[-1]["event"], "done")
        done = events[-1]["data"]
        self.assertEqual(done["skill"]["id"], "evidence-query")
        self.assertEqual(done["graph_release"]["version"], "v0.1.0")
        self.assertIn("仅用于内部科研证据辅助", done["notice"])
        citation_events = [event for event in events if event["event"] == "citation"]
        self.assertEqual(citation_events[0]["data"]["document_id"], "doc_tvns")
        self.assertEqual(citation_events[0]["data"]["chunk_id"], "chunk_params")

        messages = client.get(f"/api/v1/chat/sessions/{session_id}/messages").json()["messages"]
        self.assertEqual([message["role"] for message in messages], ["user", "assistant"])
        assistant_id = messages[1]["id"]
        feedback = client.post(
            f"/api/v1/chat/sessions/{session_id}/messages/{assistant_id}:feedback",
            json={
                "actor_id": "researcher_1",
                "rating": "helpful",
            },
        )
        self.assertEqual(feedback.status_code, 200)
        self.assertEqual(feedback.json()["rating"], "helpful")

    def test_stream_returns_clear_error_without_active_release(self) -> None:
        client = _client_with_fixture(active_release=False)
        session_id = _create_session(client)

        events = _stream_events(
            client,
            session_id=session_id,
            query="sleep quality evidence",
        )

        self.assertEqual([event["event"] for event in events], ["retrieval", "error"])
        self.assertEqual(events[-1]["data"]["code"], "no_active_release")
        self.assertIn("没有 active release", events[-1]["data"]["message"])

    def test_stream_does_not_leak_candidate_only_assertions(self) -> None:
        client = _client_with_fixture(active_release=True)
        session_id = _create_session(client)

        events = _stream_events(
            client,
            session_id=session_id,
            query="dizziness",
            skill_id="evidence-query",
        )
        body = json.dumps(events, ensure_ascii=False)

        self.assertNotIn("unpublished dizziness", body)
        self.assertNotIn("candidate-only", body)
        self.assertNotIn("citation", [event["event"] for event in events])
        text = "".join(
            event["data"].get("delta", "") for event in events if event["event"] == "text"
        )
        self.assertIn("未在已发布证据中检索到", text)

    def test_chat_migration_can_apply_and_drop(self) -> None:
        migrations = [
            load_migration_pair("0001_foundation"),
            load_migration_pair("0002_document_ingestion"),
            load_migration_pair("0003_candidate_extraction"),
            load_migration_pair("0004_review_release"),
            load_migration_pair("0005_graph_retrieval"),
            load_migration_pair("0006_skill_registry"),
            load_migration_pair("0007_chat_sessions"),
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
            self.assertIn("chat_sessions", table_names)
            self.assertIn("chat_messages", table_names)
            self.assertIn("chat_feedback", table_names)
            for migration in reversed(migrations):
                connection.executescript(migration.down_sql)
            remaining = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
            self.assertEqual(remaining, [])
        finally:
            connection.close()


def _client_with_fixture(*, active_release: bool) -> TestClient:
    review_service = ReviewReleaseService(
        repository=InMemoryReviewRepository(),
        object_store=InMemoryObjectStore(),
        normalizer=load_acupuncture_terminology_normalizer(),
    )
    retrieval = RetrievalService(
        graph_repository=InMemoryGraphRepository(),
        release_reader=review_service,
    )
    skill_registry = SkillRegistryService(
        repository=InMemorySkillRepository(),
        retrieval_service=retrieval,
        skills_root=ROOT / "skills",
    )
    skill_registry.load_from_filesystem()
    chat_service = create_chat_service(skill_registry=skill_registry)
    document_service = _document_service()
    if active_release:
        _publish_release(review_service=review_service, retrieval=retrieval)

    app = create_app()
    app.state.document_service = document_service
    app.state.review_release_service = review_service
    app.state.retrieval_service = retrieval
    app.state.skill_registry_service = skill_registry
    app.state.chat_service = chat_service
    return TestClient(app)


def _document_service() -> DocumentIngestService:
    repository = InMemoryDocumentRepository()
    repository.add(
        DocumentRecord(
            id="doc_tvns",
            domain_id="acupuncture",
            title="taVNS research fixture",
            filename="tvns.md",
            media_type="text/markdown",
            content_hash="fixture-hash",
            byte_size=100,
            status=DocumentStatus.PARSED,
            file_version=1,
            parser_version="parser-v0.1",
            chunks=_source_chunks(),
            source_uri="memory://doc_tvns",
            topic_tags=("tVNS", "taVNS"),
            source_quality_tier=SourceQualityTier.TOP_DATABASE_HIGH_IMPACT,
        )
    )
    return DocumentIngestService(
        repository=repository,
        object_store=InMemoryObjectStore(),
        parser=CompositeDocumentParser(
            markdown_parser=MarkdownDocumentParser(),
            pdf_parser=PyPdfDocumentParser(),
        ),
        max_upload_bytes=1024 * 1024,
    )


def _create_session(client: TestClient) -> str:
    response = client.post(
        "/api/v1/chat/sessions",
        json={
            "domain_id": "acupuncture",
            "actor_id": "researcher_1",
            "title": "Fixture chat",
        },
    )
    self_check = response.status_code
    if self_check != 200:
        raise AssertionError(response.text)
    return str(response.json()["id"])


def _stream_events(
    client: TestClient,
    *,
    session_id: str,
    query: str,
    skill_id: str | None = None,
) -> list[dict[str, Any]]:
    payload: dict[str, object] = {
        "query": query,
        "actor_id": "researcher_1",
        "actor_role": "researcher",
    }
    if skill_id is not None:
        payload["skill_id"] = skill_id
    with client.stream(
        "POST",
        f"/api/v1/chat/sessions/{session_id}/messages:stream",
        json=payload,
    ) as response:
        body = response.read().decode("utf-8")
    return _parse_sse(body)


def _parse_sse(body: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for block in body.strip().split("\n\n"):
        if not block:
            continue
        event_name = ""
        data = "{}"
        for line in block.splitlines():
            if line.startswith("event: "):
                event_name = line[len("event: ") :]
            if line.startswith("data: "):
                data = line[len("data: ") :]
        events.append({"event": event_name, "data": json.loads(data)})
    return events


def _publish_release(
    *,
    review_service: ReviewReleaseService,
    retrieval: RetrievalService,
) -> None:
    review_service.create_review_batch(
        run=_candidate_run(),
        source_chunks=_source_chunks(),
        created_by="worker",
    )
    review_service.approve_assertion(
        domain_id="acupuncture",
        assertion_id="assertion_params",
        reviewer="reviewer_1",
        reason="Fixture source locator verified.",
    )
    release = review_service.create_release(
        domain_id="acupuncture",
        version="v0.1.0",
        assertion_ids=("assertion_params",),
        released_by="reviewer_1",
    )
    review_service.activate_release(
        domain_id="acupuncture",
        release_id=release.release.id,
        actor_id="admin_1",
    )
    retrieval.sync_active_release(
        domain_id="acupuncture",
        source_documents=(
            _document_service().list_documents(domain_id="acupuncture")[0].to_source_document(),
        ),
        source_chunks=_source_chunks(),
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
            id="chunk_unpublished",
            domain_id="acupuncture",
            document_id="doc_tvns",
            locator=ChunkLocator(chunk_index=1, page=5, heading="Candidate"),
            text="Candidate-only text mentioned unpublished dizziness.",
            parser_version="parser-v0.1",
        ),
    )


def _candidate_run() -> CandidateExtractionRun:
    return CandidateExtractionRun(
        id="extract_chat_fixture",
        domain_id="acupuncture",
        document_id="doc_tvns",
        status=JobStatus.SUCCEEDED,
        provider="fake",
        model="fake-model",
        prompt_version="literature-extraction-v0.1.0",
        schema_version="candidate-extraction-v0.1.0",
        source_chunk_ids=("chunk_params", "chunk_unpublished"),
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
                id="assertion_unpublished",
                domain_id="acupuncture",
                subject=EvidenceTerm(ConceptType.INTERVENTION, "taVNS"),
                predicate=PredicateType.HAS_SAFETY_EVENT,
                object=EvidenceTerm(ConceptType.OUTCOME, "unpublished dizziness"),
                source_chunk_ids=("chunk_unpublished",),
                review_status=ReviewStatus.PENDING,
                direction=Direction.UNCLEAR,
                extraction_confidence=0.8,
                source_quality_signals=SourceQualitySignals(tier=SourceQualityTier.DATABASE_OTHER),
            ),
        ),
    )


if __name__ == "__main__":
    unittest.main()
