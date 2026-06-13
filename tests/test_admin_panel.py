# ruff: noqa: E402

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "lingshu-domain" / "src"))

warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated.*",
    category=Warning,
)
from fastapi.testclient import TestClient

from lingshu_domain import (
    ConceptType,
    Direction,
    EvidenceAssertion,
    EvidenceTerm,
    ParameterSet,
    PredicateType,
    ReviewStatus,
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
    DocumentUpload,
    InMemoryDocumentRepository,
    MarkdownDocumentParser,
    PyPdfDocumentParser,
)
from lingshu_nexus.extraction import CandidateExtractionRun
from lingshu_nexus.persistence.graph import InMemoryGraphRepository
from lingshu_nexus.persistence.models import JobStatus
from lingshu_nexus.persistence.object_store import InMemoryObjectStore
from lingshu_nexus.retrieval import RetrievalService
from lingshu_nexus.review import (
    InMemoryReviewRepository,
    ReviewReleaseService,
    load_acupuncture_terminology_normalizer,
)
from lingshu_nexus.skills import InMemorySkillRepository, SkillRegistryService


class AdminPanelTestCase(unittest.TestCase):
    def test_admin_overview_jobs_and_model_usage_boundary(self) -> None:
        client, _assertion_id = _client_with_review_fixture()

        overview = client.get("/api/v1/admin/overview", params={"domain_id": "acupuncture"})
        self.assertEqual(overview.status_code, 200)
        overview_payload = overview.json()
        self.assertEqual(overview_payload["documents_total"], 2)
        self.assertEqual(overview_payload["document_status_counts"]["PARSED"], 1)
        self.assertEqual(overview_payload["document_status_counts"]["PARSE_FAILED"], 1)
        self.assertEqual(overview_payload["pending_review_count"], 1)
        self.assertEqual(overview_payload["failed_jobs_count"], 1)
        self.assertFalse(overview_payload["model_usage_summary"]["records_available"])
        self.assertIn("不伪造调用成本", overview_payload["model_usage_summary"]["note"])

        jobs = client.get("/api/v1/admin/jobs", params={"domain_id": "acupuncture"})
        self.assertEqual(jobs.status_code, 200)
        jobs_payload = jobs.json()
        failed_jobs = [job for job in jobs_payload["jobs"] if job["status"] == "failed"]
        self.assertEqual(len(failed_jobs), 1)
        self.assertIn("PDF parser", failed_jobs[0]["error"])
        self.assertEqual(jobs_payload["source_connector"]["status"], "ready")
        self.assertEqual(jobs_payload["source_connector"]["runs_total"], 0)

    def test_admin_skill_status_changes_require_admin_and_write_audit(self) -> None:
        client, _assertion_id = _client_with_review_fixture()

        forbidden = client.post(
            "/api/v1/admin/skills/evidence-query:disable",
            params={"domain_id": "acupuncture"},
            json={"actor_id": "researcher-ui", "actor_role": "researcher"},
        )
        self.assertEqual(forbidden.status_code, 403)

        disabled = client.post(
            "/api/v1/admin/skills/evidence-query:disable",
            params={"domain_id": "acupuncture"},
            json={"actor_id": "admin-ui", "actor_role": "admin"},
        )
        self.assertEqual(disabled.status_code, 200)
        self.assertEqual(disabled.json()["status"], "disabled")

        enabled = client.post(
            "/api/v1/admin/skills/evidence-query:enable",
            params={"domain_id": "acupuncture"},
            json={"actor_id": "admin-ui", "actor_role": "admin"},
        )
        self.assertEqual(enabled.status_code, 200)
        self.assertEqual(enabled.json()["status"], "active")

        audit = client.get("/api/v1/admin/audit-events", params={"domain_id": "acupuncture"})
        self.assertEqual(audit.status_code, 200)
        actions = [event["action"] for event in audit.json()["audit_events"]]
        self.assertIn("skill.disabled", actions)
        self.assertIn("skill.active", actions)

    def test_admin_skill_upload_validates_package_and_writes_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = _client_with_empty_skill_root(Path(temp_dir))
            upload = client.post(
                "/api/v1/admin/skills:upload",
                json={
                    "actor_id": "admin-ui",
                    "actor_role": "admin",
                    "skill_id": "uploaded-skill",
                    "skill_md": (
                        "---\n"
                        "name: uploaded-skill\n"
                        "description: Uploaded read-only Skill fixture.\n"
                        "---\n\n"
                        "# Uploaded Skill\n\n"
                        "Use only platform read-only retrieval tools.\n"
                    ),
                    "registry_yaml": (
                        "skill_id: uploaded-skill\n"
                        'version: "0.1.0"\n'
                        "status: disabled\n"
                        "scope: read_only\n"
                        "minimum_role: researcher\n"
                        "domain_ids:\n"
                        "  - acupuncture\n"
                        "server_allowed_tools:\n"
                        "  - published_graph_search\n"
                        "supported_query_types:\n"
                        "  - evidence_lookup\n"
                        "checksum: auto\n"
                    ),
                    "test_cases_yaml": "cases:\n  - query: evidence lookup\n",
                },
            )
            self.assertEqual(upload.status_code, 200)
            self.assertEqual(upload.json()["id"], "uploaded-skill")

            skills = client.get("/api/v1/skills", params={"domain_id": "acupuncture"})
            self.assertEqual(skills.status_code, 200)
            self.assertIn(
                "uploaded-skill",
                [skill["id"] for skill in skills.json()["skills"]],
            )

            audit = client.get("/api/v1/admin/audit-events", params={"domain_id": "acupuncture"})
            self.assertEqual(audit.status_code, 200)
            actions = [event["action"] for event in audit.json()["audit_events"]]
            self.assertIn("skill.uploaded", actions)

    def test_review_release_activation_and_chat_citation_path_works_through_api(self) -> None:
        client, assertion_id = _client_with_review_fixture()

        approve = client.post(
            f"/api/v1/review-assertions/{assertion_id}:approve",
            params={"domain_id": "acupuncture"},
            json={"reviewer": "reviewer-ui", "reason": "Source locator verified."},
        )
        self.assertEqual(approve.status_code, 200)
        self.assertEqual(approve.json()["review_status"], "approved")

        preview = client.post(
            "/api/v1/domains/acupuncture/releases:preview",
            json={"assertion_ids": [assertion_id]},
        )
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json()["included_assertion_ids"], [assertion_id])

        release = client.post(
            "/api/v1/domains/acupuncture/releases",
            json={
                "version": "v-admin-fixture.1",
                "assertion_ids": [assertion_id],
                "released_by": "reviewer-ui",
            },
        )
        self.assertEqual(release.status_code, 200)
        release_id = release.json()["id"]

        activated = client.post(
            f"/api/v1/domains/acupuncture/releases/{release_id}:activate",
            json={"actor_id": "admin-ui"},
        )
        self.assertEqual(activated.status_code, 200)
        self.assertTrue(activated.json()["active"])

        session_id = _create_session(client)
        events = _stream_events(
            client,
            session_id=session_id,
            query="Cymba Conchae frequency 25 Hz PSQI parameter",
        )
        self.assertEqual(events[-1]["event"], "done")
        citation_events = [event for event in events if event["event"] == "citation"]
        self.assertEqual(len(citation_events), 1)
        self.assertEqual(citation_events[0]["data"]["document_title"], "taVNS admin fixture")

        audit = client.get("/api/v1/admin/audit-events", params={"domain_id": "acupuncture"})
        actions = [event["action"] for event in audit.json()["audit_events"]]
        self.assertIn("assertion.approve", actions)
        self.assertIn("release.created", actions)
        self.assertIn("release.activated", actions)

    def test_t110_rbac_chat_audit_config_status_and_observability(self) -> None:
        client, assertion_id = _client_with_review_fixture()

        forbidden_review = client.post(
            f"/api/v1/review-assertions/{assertion_id}:approve",
            params={"domain_id": "acupuncture"},
            json={
                "reviewer": "researcher-ui",
                "actor_role": "researcher",
                "reason": "Attempted review without reviewer role.",
            },
        )
        self.assertEqual(forbidden_review.status_code, 403)

        approved = client.post(
            f"/api/v1/review-assertions/{assertion_id}:approve",
            params={"domain_id": "acupuncture"},
            json={
                "reviewer": "reviewer-ui",
                "actor_role": "reviewer",
                "reason": "Source locator verified.",
            },
        )
        self.assertEqual(approved.status_code, 200)

        release = client.post(
            "/api/v1/domains/acupuncture/releases",
            json={
                "version": "v-t110.1",
                "assertion_ids": [assertion_id],
                "released_by": "reviewer-ui",
                "actor_role": "reviewer",
            },
        )
        self.assertEqual(release.status_code, 200)
        release_id = release.json()["id"]

        forbidden_activate = client.post(
            f"/api/v1/domains/acupuncture/releases/{release_id}:activate",
            json={"actor_id": "researcher-ui", "actor_role": "researcher"},
        )
        self.assertEqual(forbidden_activate.status_code, 403)

        activated = client.post(
            f"/api/v1/domains/acupuncture/releases/{release_id}:activate",
            json={"actor_id": "admin-ui", "actor_role": "admin"},
        )
        self.assertEqual(activated.status_code, 200)

        query = "Cymba Conchae frequency 25 Hz PSQI parameter"
        session_id = _create_session(client)
        events = _stream_events(client, session_id=session_id, query=query)
        self.assertEqual(events[-1]["event"], "done")

        audit = client.get("/api/v1/admin/audit-events", params={"domain_id": "acupuncture"})
        audit_events = audit.json()["audit_events"]
        completed = [event for event in audit_events if event["action"] == "chat.answer_completed"]
        self.assertEqual(len(completed), 1)
        metadata = completed[0]["metadata"]
        self.assertEqual(metadata["actor_role"], "researcher")
        self.assertEqual(metadata["release_version"], "v-t110.1")
        self.assertEqual(len(metadata["query_sha256"]), 64)
        self.assertNotIn(query, json.dumps(metadata, ensure_ascii=False))

        observations = client.get(
            "/api/v1/admin/observability-events",
            params={"domain_id": "acupuncture"},
        )
        self.assertEqual(observations.status_code, 200)
        event_types = [event["event_type"] for event in observations.json()["events"]]
        self.assertIn("chat.answer", event_types)

        config_status = client.get("/api/v1/admin/config-status")
        self.assertEqual(config_status.status_code, 200)
        config_body = json.dumps(config_status.json(), ensure_ascii=False)
        self.assertNotIn("change-me-postgres-password", config_body)
        self.assertNotIn("MIMO_API_KEY", config_body)


def _client_with_review_fixture() -> tuple[TestClient, str]:
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
    document_service, document = _document_service_with_jobs()
    assertion_id = "assertion_admin_params"
    review_service.create_review_batch(
        run=_candidate_run(document=document, assertion_id=assertion_id),
        source_chunks=document.chunks,
        created_by="worker",
    )

    app = create_app()
    app.state.document_service = document_service
    app.state.review_release_service = review_service
    app.state.retrieval_service = retrieval
    app.state.skill_registry_service = skill_registry
    app.state.chat_service = create_chat_service(skill_registry=skill_registry)
    return TestClient(app), assertion_id


def _client_with_empty_skill_root(skills_root: Path) -> TestClient:
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
        skills_root=skills_root,
    )
    app = create_app()
    app.state.review_release_service = review_service
    app.state.retrieval_service = retrieval
    app.state.skill_registry_service = skill_registry
    app.state.chat_service = create_chat_service(skill_registry=skill_registry)
    return TestClient(app)


def _document_service_with_jobs() -> tuple[DocumentIngestService, DocumentRecord]:
    service = DocumentIngestService(
        repository=InMemoryDocumentRepository(),
        object_store=InMemoryObjectStore(),
        parser=CompositeDocumentParser(
            markdown_parser=MarkdownDocumentParser(),
            pdf_parser=PyPdfDocumentParser(),
        ),
        max_upload_bytes=1024 * 1024,
    )
    parsed = service.batch_upload(
        domain_id="acupuncture",
        uploads=(
            DocumentUpload(
                filename="admin-fixture.md",
                media_type="text/markdown",
                content=(
                    b"# taVNS admin fixture\n\n"
                    b"taVNS at Cymba Conchae used 25 Hz frequency, 250 us pulse width, "
                    b"and improved PSQI sleep quality.\n"
                ),
            ),
        ),
    )[0]
    failed = service.batch_upload(
        domain_id="acupuncture",
        uploads=(
            DocumentUpload(
                filename="broken.pdf",
                media_type="application/pdf",
                content=b"not a pdf",
            ),
        ),
    )[0]
    assert parsed.document is not None
    assert failed.document is not None
    assert parsed.document.status is DocumentStatus.PARSED
    assert failed.document.status is DocumentStatus.PARSE_FAILED
    return service, parsed.document


def _candidate_run(*, document: DocumentRecord, assertion_id: str) -> CandidateExtractionRun:
    chunk = document.chunks[0]
    return CandidateExtractionRun(
        id="extract_admin_fixture",
        domain_id=document.domain_id,
        document_id=document.id,
        status=JobStatus.SUCCEEDED,
        provider="fake",
        model="fake-model",
        prompt_version="literature-extraction-v0.1.0",
        schema_version="candidate-extraction-v0.1.0",
        source_chunk_ids=(chunk.id,),
        evidence_assertions=(
            EvidenceAssertion(
                id=assertion_id,
                domain_id=document.domain_id,
                subject=EvidenceTerm(ConceptType.INTERVENTION, "taVNS"),
                predicate=PredicateType.AFFECTS_OUTCOME,
                object=EvidenceTerm(ConceptType.OUTCOME, "PSQI sleep quality"),
                source_chunk_ids=(chunk.id,),
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
        ),
    )


def _create_session(client: TestClient) -> str:
    response = client.post(
        "/api/v1/chat/sessions",
        json={
            "domain_id": "acupuncture",
            "actor_id": "researcher-ui",
            "title": "Admin fixture chat",
        },
    )
    if response.status_code != 200:
        raise AssertionError(response.text)
    return str(response.json()["id"])


def _stream_events(
    client: TestClient,
    *,
    session_id: str,
    query: str,
) -> list[dict[str, Any]]:
    with client.stream(
        "POST",
        f"/api/v1/chat/sessions/{session_id}/messages:stream",
        params={"domain_id": "acupuncture"},
        json={
            "query": query,
            "actor_id": "researcher-ui",
            "actor_role": "researcher",
            "skill_id": "evidence-query",
        },
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


if __name__ == "__main__":
    unittest.main()
