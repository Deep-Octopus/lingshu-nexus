# ruff: noqa: E402

from __future__ import annotations

import copy
import json
import sys
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

from lingshu_domain import ConceptType, EvidenceTerm
from lingshu_nexus.api.main import create_app
from lingshu_nexus.chat import create_chat_service
from lingshu_nexus.documents import (
    CompositeDocumentParser,
    DocumentIngestService,
    InMemoryDocumentRepository,
    MarkdownDocumentParser,
    PyPdfDocumentParser,
)
from lingshu_nexus.extraction import LlmCompletionRequest, LlmCompletionResponse
from lingshu_nexus.observability import ObservabilityRecorder
from lingshu_nexus.persistence.graph import InMemoryGraphRepository
from lingshu_nexus.persistence.object_store import InMemoryObjectStore
from lingshu_nexus.retrieval import RetrievalService
from lingshu_nexus.review import (
    InMemoryReviewRepository,
    ReviewReleaseService,
    load_acupuncture_terminology_normalizer,
)
from lingshu_nexus.skills import create_skill_registry_service
from lingshu_nexus.sources import create_source_update_service

EVALS = ROOT / "evals"
FIXTURE_DOCUMENT = EVALS / "fixtures" / "tvns_sleep_safety.fixture.md"
EXTRACTION_EXPECTATION = EVALS / "expected" / "candidate_extraction.v0.1.json"
QUESTION_SEEDS = EVALS / "questions" / "tvns_eval_seeds.v0.1.json"
BOUNDARY_CASES = EVALS / "boundary" / "refusal_cases.v0.1.json"
TERMINOLOGY_CASES = EVALS / "terminology" / "tvns_normalization.v0.1.json"

REQUIRED_QUESTION_CATEGORIES = {
    "sleep_intervention_parameters",
    "frequency_effects",
    "contraindications_safety",
    "study_protocol_parameters_outcomes",
    "sleep_mechanism",
    "cross_indication_mechanism",
    "rct_design",
    "non_behavioral_measures",
    "regional_research_focus",
    "timeline_literature",
    "recent_three_year_trends",
    "no_unified_standard",
}


class V1AcceptanceTestCase(unittest.TestCase):
    def test_eval_assets_cover_t120_seeds_and_are_fixture_labeled(self) -> None:
        extraction = _load_json(EXTRACTION_EXPECTATION)
        questions = _load_json(QUESTION_SEEDS)
        boundaries = _load_json(BOUNDARY_CASES)
        terminology = _load_json(TERMINOLOGY_CASES)

        self.assertTrue(extraction["fixture_only"])
        self.assertTrue(questions["fixture_only"])
        self.assertTrue(boundaries["fixture_only"])
        self.assertTrue(terminology["fixture_only"])
        self.assertIn("synthetic fixture", FIXTURE_DOCUMENT.read_text(encoding="utf-8"))

        question_items = _object_list(questions, "questions")
        categories = {str(item["category"]) for item in question_items}
        self.assertEqual(categories, REQUIRED_QUESTION_CATEGORIES)
        self.assertNotIn("expected_answer", json.dumps(question_items, ensure_ascii=False))
        self.assertGreaterEqual(len(_object_list(boundaries, "cases")), 15)

        seed_only = [item for item in question_items if item["fixture_status"] == "seed_only"]
        self.assertTrue(seed_only)
        self.assertTrue(
            all("expected_citations" not in item for item in seed_only),
            "Seed-only questions must not invent expected citations before real evidence exists.",
        )

    def test_terminology_cases_preserve_site_mappings_and_sensitive_distinctions(self) -> None:
        normalizer = load_acupuncture_terminology_normalizer()
        payload = _load_json(TERMINOLOGY_CASES)
        results: dict[str, str] = {}

        for index, item in enumerate(_object_list(payload, "cases")):
            input_text = str(item["input"])
            candidate = normalizer.candidate_for_term(
                domain_id="acupuncture",
                review_batch_id="eval_batch",
                assertion_id=f"eval_assertion_{index}",
                term_role="object",
                term=EvidenceTerm(
                    type=ConceptType(str(item["concept_type"])),
                    text=input_text,
                    original_text=input_text,
                ),
            )
            self.assertEqual(candidate.suggested_concept_id, item["expected_concept_id"])
            self.assertEqual(candidate.suggested_preferred_name, item["expected_preferred_name"])
            self.assertEqual(candidate.status.value, item["expected_status"])
            results[input_text] = candidate.suggested_concept_id or ""

        self.assertNotEqual(results["Cymba Conchae"], results["cavum conchae"])
        self.assertNotEqual(results["depression"], results["blues"])
        self.assertEqual(results["blues"], results["Postpartum blues"])

    def test_fixture_flow_uploads_extracts_reviews_publishes_streams_and_rolls_back(self) -> None:
        client = _acceptance_client()
        sync = client.post(
            "/api/v1/domains/acupuncture/sources:manual-sync",
            files=[
                (
                    "files",
                    (
                        FIXTURE_DOCUMENT.name,
                        FIXTURE_DOCUMENT.read_bytes(),
                        "text/markdown",
                    ),
                )
            ],
            data={"actor_id": "researcher-eval", "actor_role": "researcher"},
        )
        self.assertEqual(sync.status_code, 200, sync.text)
        run = sync.json()["run"]
        self.assertEqual(run["status"], "succeeded")
        self.assertEqual(len(run["document_ids"]), 1)
        self.assertEqual(len(run["candidate_run_ids"]), 1)
        self.assertEqual(len(run["review_batch_ids"]), 1)

        documents = client.get("/api/v1/documents", params={"domain_id": "acupuncture"})
        self.assertEqual(documents.status_code, 200)
        self.assertEqual(len(documents.json()["documents"]), 1)
        document_id = documents.json()["documents"][0]["id"]
        detail = client.get(f"/api/v1/documents/{document_id}", params={"domain_id": "acupuncture"})
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(len(detail.json()["chunks"]), 2)

        assertions_response = client.get(
            "/api/v1/review-assertions", params={"domain_id": "acupuncture"}
        )
        self.assertEqual(assertions_response.status_code, 200)
        assertions = {item["id"]: item for item in assertions_response.json()["assertions"]}
        primary_id = "eval_assertion_sleep_parameters"
        candidate_only_id = "eval_assertion_candidate_only"
        self.assertEqual(set(assertions), {primary_id, candidate_only_id})
        self.assertEqual(assertions[primary_id]["review_status"], "pending")
        self.assertEqual(assertions[candidate_only_id]["review_status"], "pending")

        forbidden_review = client.post(
            f"/api/v1/review-assertions/{primary_id}:approve",
            params={"domain_id": "acupuncture"},
            json={
                "reviewer": "researcher-eval",
                "actor_role": "researcher",
                "reason": "Fixture authorization negative case.",
            },
        )
        self.assertEqual(forbidden_review.status_code, 403)

        approved = client.post(
            f"/api/v1/review-assertions/{primary_id}:approve",
            params={"domain_id": "acupuncture"},
            json={
                "reviewer": "reviewer-eval",
                "actor_role": "reviewer",
                "reason": "Synthetic locator and expected structure verified.",
            },
        )
        self.assertEqual(approved.status_code, 200, approved.text)

        preview = client.post(
            "/api/v1/domains/acupuncture/releases:preview",
            json={"assertion_ids": [primary_id, candidate_only_id]},
        )
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json()["included_assertion_ids"], [primary_id])
        self.assertEqual(
            [item["assertion_id"] for item in preview.json()["excluded_assertions"]],
            [candidate_only_id],
        )

        blocked_release = client.post(
            "/api/v1/domains/acupuncture/releases",
            json={
                "version": "v-eval.blocked",
                "assertion_ids": [primary_id, candidate_only_id],
                "released_by": "reviewer-eval",
                "actor_role": "reviewer",
            },
        )
        self.assertEqual(blocked_release.status_code, 409)

        release_v1 = _create_release(client, version="v-eval.1", assertion_id=primary_id)
        forbidden_activate = client.post(
            f"/api/v1/domains/acupuncture/releases/{release_v1}:activate",
            json={"actor_id": "researcher-eval", "actor_role": "researcher"},
        )
        self.assertEqual(forbidden_activate.status_code, 403)
        activated = _activate_release(client, release_v1)
        self.assertEqual(activated["version"], "v-eval.1")

        questions = {
            item["id"]: item for item in _object_list(_load_json(QUESTION_SEEDS), "questions")
        }
        evidence_events = _stream_events(
            client,
            query=str(questions["tvns-sleep-parameters"]["question"]),
            skill_id="evidence-query",
        )
        self.assertEqual(evidence_events[-1]["event"], "done")
        self.assertEqual(evidence_events[-1]["data"]["graph_release"]["version"], "v-eval.1")
        citations = [event for event in evidence_events if event["event"] == "citation"]
        self.assertEqual(len(citations), 1)
        self.assertIn("Published fixture evidence", citations[0]["data"]["locator"])
        self.assertIn("仅用于内部科研证据辅助", evidence_events[-1]["data"]["notice"])

        landscape_events = _stream_events(
            client,
            query=str(questions["tvns-timeline"]["question"]),
            skill_id="literature-landscape",
        )
        self.assertEqual(landscape_events[-1]["event"], "done")
        self.assertEqual(landscape_events[-1]["data"]["skill"]["id"], "literature-landscape")
        self.assertIn("citation", [event["event"] for event in landscape_events])

        skill_logs = client.get("/api/v1/domains/acupuncture/skills/execution-logs")
        self.assertEqual(skill_logs.status_code, 200)
        executed_skill_ids = {record["skill_id"] for record in skill_logs.json()["records"]}
        self.assertTrue({"evidence-query", "literature-landscape"}.issubset(executed_skill_ids))

        candidate_only_events = _stream_events(
            client,
            query="dizziness",
            skill_id="evidence-query",
        )
        candidate_only_body = json.dumps(candidate_only_events, ensure_ascii=False)
        self.assertNotIn("candidate-only dizziness", candidate_only_body)
        self.assertNotIn("Candidate-only fixture evidence", candidate_only_body)
        self.assertNotIn("citation", [event["event"] for event in candidate_only_events])
        self.assertIn("未在已发布证据中检索到", candidate_only_body)

        release_v2 = _create_release(client, version="v-eval.2", assertion_id=primary_id)
        self.assertEqual(_activate_release(client, release_v2)["version"], "v-eval.2")
        rollback = client.post(
            f"/api/v1/domains/acupuncture/releases/{release_v1}:rollback",
            json={
                "actor_id": "admin-eval",
                "actor_role": "admin",
                "reason": "T-120 deterministic rollback verification.",
            },
        )
        self.assertEqual(rollback.status_code, 200, rollback.text)
        self.assertEqual(rollback.json()["version"], "v-eval.1")

        post_rollback_events = _stream_events(
            client,
            query=str(questions["tvns-sleep-parameters"]["question"]),
            skill_id="evidence-query",
        )
        self.assertEqual(post_rollback_events[-1]["data"]["graph_release"]["version"], "v-eval.1")

        audit = client.get("/api/v1/admin/audit-events", params={"domain_id": "acupuncture"})
        self.assertEqual(audit.status_code, 200)
        actions = {event["action"] for event in audit.json()["audit_events"]}
        self.assertTrue(
            {
                "source.sync_completed",
                "assertion.approve",
                "release.created",
                "release.activated",
                "release.rollback",
                "chat.answer_completed",
            }.issubset(actions)
        )


class EvaluationFixtureProvider:
    name = "t120-eval-fixture"

    def __init__(self, expectation_path: Path) -> None:
        template = _load_json(expectation_path)
        if template.get("fixture_only") is not True:
            raise ValueError("Evaluation provider only accepts fixture_only expectations")
        self._template = template

    def complete(self, request: LlmCompletionRequest) -> LlmCompletionResponse:
        prompt = json.loads(request.user_prompt)
        if not isinstance(prompt, dict) or not isinstance(prompt.get("chunks"), list):
            raise ValueError("Evaluation prompt must contain parsed chunks")
        chunk_ids = [str(chunk["id"]) for chunk in prompt["chunks"] if isinstance(chunk, dict)]
        payload = copy.deepcopy(self._template)
        payload.pop("fixture_only", None)
        for collection_name in ("relations", "evidence_assertions"):
            collection = payload.get(collection_name)
            if not isinstance(collection, list):
                raise ValueError(f"{collection_name} must be a list")
            for item in collection:
                if not isinstance(item, dict):
                    raise ValueError(f"{collection_name} entries must be objects")
                indexes = item.pop("source_chunk_indexes", None)
                if not isinstance(indexes, list) or not indexes:
                    raise ValueError("source_chunk_indexes must be a non-empty list")
                item["source_chunk_ids"] = [chunk_ids[int(index)] for index in indexes]
        return LlmCompletionResponse(
            provider=self.name,
            model="fixture-only-v0.1",
            text=json.dumps(payload, ensure_ascii=False),
            raw_payload={"fixture_only": True},
            latency_ms=0,
        )


def _acceptance_client() -> TestClient:
    store = InMemoryObjectStore()
    observability = ObservabilityRecorder()
    document_service = DocumentIngestService(
        repository=InMemoryDocumentRepository(),
        object_store=store,
        parser=CompositeDocumentParser(
            markdown_parser=MarkdownDocumentParser(),
            pdf_parser=PyPdfDocumentParser(),
        ),
        max_upload_bytes=1024 * 1024,
        observability=observability,
    )
    review_service = ReviewReleaseService(
        repository=InMemoryReviewRepository(),
        object_store=store,
        normalizer=load_acupuncture_terminology_normalizer(),
    )
    source_service = create_source_update_service(
        object_store=store,
        document_service=document_service,
        review_service=review_service,
        provider=EvaluationFixtureProvider(EXTRACTION_EXPECTATION),
        observability=observability,
    )
    retrieval_service = RetrievalService(
        graph_repository=InMemoryGraphRepository(),
        release_reader=review_service,
    )
    skill_registry = create_skill_registry_service(
        retrieval_service=retrieval_service,
        skills_root=ROOT / "skills",
    )
    app = create_app()
    app.state.observability = observability
    app.state.document_service = document_service
    app.state.review_release_service = review_service
    app.state.source_update_service = source_service
    app.state.retrieval_service = retrieval_service
    app.state.skill_registry_service = skill_registry
    app.state.chat_service = create_chat_service(skill_registry=skill_registry)
    return TestClient(app)


def _create_release(client: TestClient, *, version: str, assertion_id: str) -> str:
    response = client.post(
        "/api/v1/domains/acupuncture/releases",
        json={
            "version": version,
            "assertion_ids": [assertion_id],
            "released_by": "reviewer-eval",
            "actor_role": "reviewer",
        },
    )
    if response.status_code != 200:
        raise AssertionError(response.text)
    return str(response.json()["id"])


def _activate_release(client: TestClient, release_id: str) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/domains/acupuncture/releases/{release_id}:activate",
        json={"actor_id": "admin-eval", "actor_role": "admin"},
    )
    if response.status_code != 200:
        raise AssertionError(response.text)
    payload = response.json()
    if not isinstance(payload, dict):
        raise AssertionError("Release activation response must be an object")
    return payload


def _stream_events(
    client: TestClient,
    *,
    query: str,
    skill_id: str,
) -> list[dict[str, Any]]:
    session = client.post(
        "/api/v1/chat/sessions",
        json={
            "domain_id": "acupuncture",
            "actor_id": "researcher-eval",
            "title": "T-120 fixture acceptance",
        },
    )
    if session.status_code != 200:
        raise AssertionError(session.text)
    session_id = str(session.json()["id"])
    with client.stream(
        "POST",
        f"/api/v1/chat/sessions/{session_id}/messages:stream",
        json={
            "query": query,
            "actor_id": "researcher-eval",
            "actor_role": "researcher",
            "skill_id": skill_id,
        },
    ) as response:
        if response.status_code != 200:
            raise AssertionError(response.text)
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
            elif line.startswith("data: "):
                data = line[len("data: ") :]
        events.append({"event": event_name, "data": json.loads(data)})
    return events


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AssertionError(f"Expected JSON object: {path}")
    return payload


def _object_list(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise AssertionError(f"{key} must be a list of objects")
    return value


if __name__ == "__main__":
    unittest.main()
