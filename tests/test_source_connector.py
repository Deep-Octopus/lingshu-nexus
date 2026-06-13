# ruff: noqa: E402

from __future__ import annotations

import json
import sqlite3
import sys
import unittest
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "lingshu-domain" / "src"))

warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated.*",
    category=Warning,
)
from fastapi.testclient import TestClient

from lingshu_domain import Direction, ReviewStatus, SchemaValidationError
from lingshu_nexus.api.main import create_app
from lingshu_nexus.documents import (
    CompositeDocumentParser,
    DocumentIngestService,
    DocumentUpload,
    InMemoryDocumentRepository,
    MarkdownDocumentParser,
    PyPdfDocumentParser,
)
from lingshu_nexus.extraction import (
    CandidateExtractionService,
    InMemoryCandidateRepository,
    LlmCompletionRequest,
    LlmCompletionResponse,
)
from lingshu_nexus.extraction.prompts import load_literature_extraction_prompt
from lingshu_nexus.persistence.migrations import load_migration_pair
from lingshu_nexus.persistence.models import JobStatus
from lingshu_nexus.persistence.object_store import InMemoryObjectStore
from lingshu_nexus.review import (
    InMemoryReviewRepository,
    ReviewReleaseService,
    load_acupuncture_terminology_normalizer,
)
from lingshu_nexus.sources import (
    FixtureSourceConnector,
    InMemorySourceRepository,
    SourceArtifactKind,
    SourceArtifactStatus,
    SourceConnectorType,
    SourceSchedule,
    SourceUpdateService,
)


class SourceConnectorTestCase(unittest.TestCase):
    def test_manual_incremental_sync_creates_candidates_and_skips_duplicate(self) -> None:
        service, review_service = _source_service()

        first = service.sync_manual_files(
            domain_id="acupuncture",
            actor_id="admin-ui",
            uploads=(
                DocumentUpload(
                    filename="tvns-incremental-a.md",
                    media_type="text/markdown",
                    content=(
                        b"# taVNS incremental A\n\n"
                        b"taVNS at Cymba Conchae improved PSQI sleep quality with 25 Hz.\n"
                    ),
                    topic_tags=("tVNS",),
                ),
            ),
        )

        self.assertEqual(first.run.status, JobStatus.SUCCEEDED)
        self.assertEqual(len(first.run.document_ids), 1)
        self.assertEqual(len(first.run.candidate_run_ids), 1)
        self.assertEqual(len(first.run.review_batch_ids), 1)
        self.assertEqual(
            first.artifact_records[0].status,
            SourceArtifactStatus.REVIEW_BATCH_CREATED,
        )
        assertions = review_service.list_assertions(domain_id="acupuncture")
        self.assertEqual(len(assertions), 1)
        self.assertEqual(assertions[0].review_status, ReviewStatus.PENDING)

        approved = review_service.approve_assertion(
            domain_id="acupuncture",
            assertion_id=assertions[0].id,
            reviewer="reviewer-ui",
            reason="Source locator verified.",
        )
        release = review_service.create_release(
            domain_id="acupuncture",
            version="v-source.1",
            assertion_ids=(approved.id,),
            released_by="reviewer-ui",
        )
        review_service.activate_release(
            domain_id="acupuncture",
            release_id=release.release.id,
            actor_id="admin-ui",
        )

        second = service.sync_manual_files(
            domain_id="acupuncture",
            actor_id="admin-ui",
            uploads=(
                DocumentUpload(
                    filename="tvns-incremental-b.md",
                    media_type="text/markdown",
                    content=(
                        b"# taVNS incremental B\n\n"
                        b"taVNS at Cymba Conchae worsened PSQI sleep quality in a safety fixture.\n"
                    ),
                    topic_tags=("tVNS",),
                ),
            ),
        )

        self.assertEqual(second.run.status, JobStatus.SUCCEEDED)
        self.assertEqual(len(second.run.review_batch_ids), 1)
        self.assertEqual(second.run.impact_summary["potential_conflict_count"], 1)
        assertions = review_service.list_assertions(domain_id="acupuncture")
        self.assertEqual(len(assertions), 2)
        second_assertion = [assertion for assertion in assertions if assertion.id != approved.id][0]
        self.assertEqual(second_assertion.direction, Direction.WORSENED)
        review_service.approve_assertion(
            domain_id="acupuncture",
            assertion_id=second_assertion.id,
            reviewer="reviewer-ui",
            reason="Contrasting source preserved for release.",
        )
        second_release = review_service.create_release(
            domain_id="acupuncture",
            version="v-source.2",
            assertion_ids=tuple(assertion.id for assertion in assertions),
            released_by="reviewer-ui",
        )
        activated = review_service.activate_release(
            domain_id="acupuncture",
            release_id=second_release.release.id,
            actor_id="admin-ui",
        )
        self.assertEqual(len(activated.included_assertion_ids), 2)

        duplicate = service.sync_manual_files(
            domain_id="acupuncture",
            actor_id="admin-ui",
            uploads=(
                DocumentUpload(
                    filename="tvns-incremental-b.md",
                    media_type="text/markdown",
                    content=(
                        b"# taVNS incremental B\n\n"
                        b"taVNS at Cymba Conchae worsened PSQI sleep quality in a safety fixture.\n"
                    ),
                ),
            ),
        )

        self.assertEqual(duplicate.run.status, JobStatus.SUCCEEDED)
        self.assertEqual(duplicate.run.duplicate_count, 1)
        self.assertEqual(duplicate.run.review_batch_ids, ())
        self.assertEqual(len(review_service.list_assertions(domain_id="acupuncture")), 2)

    def test_fixture_connector_accepts_json_file_and_download_reference_artifacts(self) -> None:
        service, _review_service = _source_service()
        service.upsert_source(
            domain_id="acupuncture",
            source_id="fixture-source",
            name="Fixture source",
            connector_type=SourceConnectorType.FIXTURE,
            config={
                "artifacts": [
                    {
                        "id": "json-doc",
                        "kind": "json",
                        "external_id": "json-001",
                        "payload": {
                            "document": {
                                "filename": "json-fixture.md",
                                "media_type": "text/markdown",
                                "content_text": (
                                    "# JSON fixture\n\n"
                                    "taVNS at Cymba Conchae improved PSQI sleep quality."
                                ),
                                "topic_tags": ["tVNS"],
                            }
                        },
                    },
                    {
                        "id": "file-doc",
                        "kind": "file",
                        "external_id": "file-001",
                        "filename": "file-fixture.md",
                        "media_type": "text/markdown",
                        "content_text": (
                            "# File fixture\n\ntaVNS at Cymba Conchae improved PSQI sleep quality."
                        ),
                    },
                    {
                        "id": "download-ref",
                        "kind": "download_reference",
                        "external_id": "download-001",
                        "source_uri": "https://example.invalid/paper.pdf",
                    },
                ],
            },
            schedule=SourceSchedule(enabled=True, interval_seconds=3600),
            actor_id="admin-ui",
        )

        result = service.sync_source(
            domain_id="acupuncture",
            source_id="fixture-source",
            actor_id="admin-ui",
            window_start="2026-06-01T00:00:00Z",
            window_end="2026-06-13T00:00:00Z",
        )

        self.assertEqual(result.run.status, JobStatus.SUCCEEDED)
        self.assertEqual(len(result.artifact_records), 3)
        self.assertEqual(len(result.run.document_ids), 2)
        self.assertEqual(len(result.run.review_batch_ids), 2)
        self.assertEqual(
            [record.kind for record in result.artifact_records],
            [
                SourceArtifactKind.JSON,
                SourceArtifactKind.FILE,
                SourceArtifactKind.DOWNLOAD_REFERENCE,
            ],
        )
        self.assertEqual(result.artifact_records[-1].status, SourceArtifactStatus.RAW_STORED)
        self.assertIn("no document payload", result.artifact_records[-1].message or "")

    def test_config_rejects_inline_secret_values(self) -> None:
        service, _review_service = _source_service()

        with self.assertRaises(SchemaValidationError) as context:
            service.upsert_source(
                domain_id="acupuncture",
                source_id="bad-source",
                name="Bad source",
                connector_type=SourceConnectorType.GENERIC_REST,
                config={"base_url": "https://example.invalid", "api_key": "do-not-store"},
                actor_id="admin-ui",
            )

        self.assertIn("secret reference", str(context.exception))

    def test_fastapi_source_routes_run_fixture_connector(self) -> None:
        service, review_service = _source_service()
        app = create_app()
        app.state.source_update_service = service
        app.state.review_release_service = review_service
        client = TestClient(app)

        upsert = client.post(
            "/api/v1/sources",
            params={"domain_id": "acupuncture"},
            json={
                "id": "api-fixture",
                "name": "API fixture",
                "connector_type": "fixture",
                "actor_id": "admin-ui",
                "config": {
                    "artifacts": [
                        {
                            "id": "api-json",
                            "kind": "json",
                            "payload": {
                                "document": {
                                    "filename": "api-source.md",
                                    "media_type": "text/markdown",
                                    "content_text": (
                                        "# API source\n\ntaVNS at Cymba Conchae improved PSQI."
                                    ),
                                }
                            },
                        }
                    ]
                },
            },
        )
        self.assertEqual(upsert.status_code, 200)

        sync = client.post(
            "/api/v1/sources/api-fixture:sync",
            params={"domain_id": "acupuncture"},
            json={"actor_id": "admin-ui"},
        )

        self.assertEqual(sync.status_code, 200)
        sync_payload = sync.json()
        self.assertEqual(sync_payload["run"]["status"], "succeeded")
        self.assertEqual(len(sync_payload["run"]["review_batch_ids"]), 1)
        runs = client.get("/api/v1/source-runs", params={"domain_id": "acupuncture"})
        self.assertEqual(runs.status_code, 200)
        self.assertEqual(len(runs.json()["runs"]), 1)

    def test_fastapi_source_management_requires_admin_and_masks_secret_refs(self) -> None:
        service, review_service = _source_service()
        app = create_app()
        app.state.source_update_service = service
        app.state.review_release_service = review_service
        client = TestClient(app)

        forbidden = client.post(
            "/api/v1/sources",
            params={"domain_id": "acupuncture"},
            json={
                "id": "masked-fixture",
                "name": "Masked fixture",
                "connector_type": "fixture",
                "actor_id": "researcher-ui",
                "actor_role": "researcher",
                "config": {"auth_ref": "env:SOURCE_TOKEN", "artifacts": []},
            },
        )
        self.assertEqual(forbidden.status_code, 403)

        created = client.post(
            "/api/v1/sources",
            params={"domain_id": "acupuncture"},
            json={
                "id": "masked-fixture",
                "name": "Masked fixture",
                "connector_type": "fixture",
                "actor_id": "admin-ui",
                "actor_role": "admin",
                "config": {"auth_ref": "env:SOURCE_TOKEN", "artifacts": []},
            },
        )
        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.json()["config"]["auth_ref"], "***configured***")

        forbidden_sync = client.post(
            "/api/v1/sources/masked-fixture:sync",
            params={"domain_id": "acupuncture"},
            json={"actor_id": "researcher-ui", "actor_role": "researcher"},
        )
        self.assertEqual(forbidden_sync.status_code, 403)

    def test_source_connector_migration_can_apply_and_drop(self) -> None:
        migration_names = (
            "0001_foundation",
            "0002_document_ingestion",
            "0003_candidate_extraction",
            "0004_review_release",
            "0008_source_connector",
        )
        migrations = [load_migration_pair(name) for name in migration_names]
        connection = sqlite3.connect(":memory:")
        try:
            for migration in migrations:
                connection.executescript(migration.up_sql)
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            self.assertIn("source_connector_configs", tables)
            self.assertIn("source_sync_runs", tables)
            self.assertIn("source_artifact_records", tables)
            for migration in reversed(migrations):
                connection.executescript(migration.down_sql)
            remaining = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
            self.assertEqual(remaining, [])
        finally:
            connection.close()


class DynamicFixtureProvider:
    name = "dynamic-fixture"

    def complete(self, request: LlmCompletionRequest) -> LlmCompletionResponse:
        payload = json.loads(request.user_prompt)
        document_id = str(payload["document_id"])
        chunk_id = str(payload["chunks"][0]["id"])
        chunk_text = str(payload["chunks"][0]["text"])
        direction = "worsened" if "worsened" in chunk_text.lower() else "improved"
        return LlmCompletionResponse(
            provider=self.name,
            model="dynamic-fixture-model",
            text=json.dumps(
                _candidate_payload(
                    assertion_id=f"assertion_{document_id}",
                    chunk_id=chunk_id,
                    direction=direction,
                ),
                ensure_ascii=False,
            ),
            raw_payload={"fixture": True},
            latency_ms=0,
        )


def _source_service() -> tuple[SourceUpdateService, ReviewReleaseService]:
    store = InMemoryObjectStore()
    document_service = DocumentIngestService(
        repository=InMemoryDocumentRepository(),
        object_store=store,
        parser=CompositeDocumentParser(
            markdown_parser=MarkdownDocumentParser(),
            pdf_parser=PyPdfDocumentParser(),
        ),
        max_upload_bytes=1024 * 1024,
    )
    review_service = ReviewReleaseService(
        repository=InMemoryReviewRepository(),
        object_store=store,
        normalizer=load_acupuncture_terminology_normalizer(),
    )
    extraction_service = CandidateExtractionService(
        repository=InMemoryCandidateRepository(),
        object_store=store,
        provider=DynamicFixtureProvider(),
        prompt=load_literature_extraction_prompt(),
    )
    return (
        SourceUpdateService(
            repository=InMemorySourceRepository(),
            object_store=store,
            document_service=document_service,
            extraction_service=extraction_service,
            review_service=review_service,
            connectors={SourceConnectorType.FIXTURE: FixtureSourceConnector()},
        ),
        review_service,
    )


def _candidate_payload(*, assertion_id: str, chunk_id: str, direction: str) -> dict[str, object]:
    return {
        "entities": [
            {"type": "intervention", "text": "taVNS", "original_text": "taVNS"},
            {"type": "outcome", "text": "PSQI sleep quality"},
        ],
        "relations": [
            {
                "subject": {"type": "intervention", "text": "taVNS"},
                "predicate": "affects_outcome",
                "object": {"type": "outcome", "text": "PSQI sleep quality"},
                "source_chunk_ids": [chunk_id],
                "confidence": 0.82,
            }
        ],
        "evidence_assertions": [
            {
                "id": assertion_id,
                "subject": {"type": "intervention", "text": "taVNS"},
                "predicate": "affects_outcome",
                "object": {"type": "outcome", "text": "PSQI sleep quality"},
                "source_chunk_ids": [chunk_id],
                "population": "adults in fixture studies",
                "parameter_set": {
                    "stimulation_site": "Cymba Conchae",
                    "frequency_hz": 25,
                    "pulse_width_us": 250,
                    "raw_text": "Cymba Conchae 25 Hz 250 us",
                },
                "outcome": "PSQI",
                "direction": direction,
                "extraction_confidence": 0.9,
            }
        ],
        "study": {"study_type": "fixture"},
    }


if __name__ == "__main__":
    unittest.main()
