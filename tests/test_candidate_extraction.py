from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "lingshu-domain" / "src"))

from lingshu_domain import ReviewStatus
from lingshu_nexus.config.settings import Settings
from lingshu_nexus.documents import (
    CompositeDocumentParser,
    DocumentRecord,
    DocumentIngestService,
    DocumentUpload,
    InMemoryDocumentRepository,
    MarkdownDocumentParser,
    PyPdfDocumentParser,
)
from lingshu_nexus.extraction import (
    CandidateExtractionService,
    FakeLlmProvider,
    InMemoryCandidateRepository,
    MiMoProvider,
    ProviderConfigurationError,
)
from lingshu_nexus.extraction.prompts import load_literature_extraction_prompt
from lingshu_nexus.extraction.providers import LlmCompletionRequest
from lingshu_nexus.persistence.migrations import load_migration_pair
from lingshu_nexus.persistence.models import DataLayer, JobStatus
from lingshu_nexus.persistence.object_store import InMemoryObjectStore


class CandidateExtractionTestCase(unittest.TestCase):
    def test_fake_provider_generates_schema_valid_candidate_assertion(self) -> None:
        document, store = _parsed_document()
        repository = InMemoryCandidateRepository()
        service = CandidateExtractionService(
            repository=repository,
            object_store=store,
            provider=FakeLlmProvider(_valid_payload(document.chunks[0].id)),
            prompt=load_literature_extraction_prompt(),
        )

        run = service.extract_document(document)

        self.assertEqual(run.status, JobStatus.SUCCEEDED)
        self.assertEqual(run.provider, "fake")
        self.assertEqual(run.prompt_version, "literature-extraction-v0.1.0")
        self.assertEqual(run.schema_version, "candidate-extraction-v0.1.0")
        self.assertEqual(len(run.evidence_assertions), 1)
        assertion = run.evidence_assertions[0]
        self.assertEqual(assertion.review_status, ReviewStatus.PENDING)
        self.assertEqual(assertion.source_chunk_ids, (document.chunks[0].id,))
        assert assertion.parameter_set is not None
        self.assertEqual(assertion.parameter_set.stimulation_site, "Cymba Conchae")
        assert run.output_ref is not None
        artifact_record = store.record_for(run.output_ref, domain_id="acupuncture")
        self.assertEqual(artifact_record.layer, DataLayer.CANDIDATE)
        artifact = json.loads(store.get(run.output_ref, domain_id="acupuncture"))
        self.assertEqual(artifact["provider"], "fake")
        self.assertNotIn("api_key", json.dumps(artifact).lower())
        stored_runs = repository.list_runs_for_document(
            domain_id="acupuncture",
            document_id=document.id,
        )
        self.assertEqual(stored_runs, (run,))

    def test_output_without_source_locator_is_rejected_and_recorded(self) -> None:
        document, store = _parsed_document()
        service = CandidateExtractionService(
            repository=InMemoryCandidateRepository(),
            object_store=store,
            provider=FakeLlmProvider(_valid_payload("missing_chunk")),
            prompt=load_literature_extraction_prompt(),
        )

        run = service.extract_document(document)

        self.assertEqual(run.status, JobStatus.FAILED)
        self.assertIn("unknown chunks", run.failure_reason or "")
        self.assertEqual(run.evidence_assertions, ())
        self.assertIsNone(run.output_ref)

    def test_invalid_json_is_rejected_without_candidate_artifact(self) -> None:
        document, store = _parsed_document()
        service = CandidateExtractionService(
            repository=InMemoryCandidateRepository(),
            object_store=store,
            provider=FakeLlmProvider("{not json"),
            prompt=load_literature_extraction_prompt(),
        )

        run = service.extract_document(document)

        self.assertEqual(run.status, JobStatus.FAILED)
        self.assertIn("not valid JSON", run.failure_reason or "")
        self.assertIsNone(run.output_ref)

    def test_mimo_provider_requires_live_configuration_before_http_call(self) -> None:
        provider = MiMoProvider.from_settings(Settings())

        with self.assertRaises(ProviderConfigurationError):
            provider.complete(
                request=_completion_request(),
            )

    def test_candidate_extraction_migration_can_apply_and_drop(self) -> None:
        foundation = load_migration_pair("0001_foundation")
        ingestion = load_migration_pair("0002_document_ingestion")
        extraction = load_migration_pair("0003_candidate_extraction")
        connection = sqlite3.connect(":memory:")
        try:
            connection.executescript(foundation.up_sql)
            connection.executescript(ingestion.up_sql)
            connection.executescript(extraction.up_sql)
            table_names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            self.assertIn("candidate_extraction_runs", table_names)
            self.assertIn("candidate_evidence_assertions", table_names)
            connection.executescript(extraction.down_sql)
            connection.executescript(ingestion.down_sql)
            connection.executescript(foundation.down_sql)
            remaining = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
            self.assertEqual(remaining, [])
        finally:
            connection.close()


def _parsed_document() -> tuple[DocumentRecord, InMemoryObjectStore]:
    store = InMemoryObjectStore()
    service = DocumentIngestService(
        repository=InMemoryDocumentRepository(),
        object_store=store,
        parser=CompositeDocumentParser(
            markdown_parser=MarkdownDocumentParser(),
            pdf_parser=PyPdfDocumentParser(),
        ),
        max_upload_bytes=1024 * 1024,
    )
    result = service.batch_upload(
        domain_id="acupuncture",
        uploads=(
            DocumentUpload(
                filename="tvns-extraction.md",
                media_type="text/markdown",
                content=(
                    b"# taVNS trial\n\n"
                    b"taVNS at the Cymba Conchae improved PSQI sleep quality. "
                    b"Stimulation used 25 Hz, 250 us pulse width, and sham control.\n"
                ),
                topic_tags=("tVNS",),
            ),
        ),
    )[0]
    assert result.document is not None
    return result.document, store


def _valid_payload(chunk_id: str) -> dict[str, object]:
    return {
        "entities": [
            {"type": "intervention", "text": "taVNS", "original_text": "taVNS"},
            {
                "type": "stimulation_site",
                "text": "Cymba Conchae",
                "original_text": "Cymba Conchae",
            },
        ],
        "relations": [
            {
                "subject": {"type": "intervention", "text": "taVNS"},
                "predicate": "uses_stimulation_site",
                "object": {"type": "stimulation_site", "text": "Cymba Conchae"},
                "source_chunk_ids": [chunk_id],
                "confidence": 0.82,
            }
        ],
        "evidence_assertions": [
            {
                "subject": {"type": "intervention", "text": "taVNS"},
                "predicate": "affects_outcome",
                "object": {"type": "outcome", "text": "sleep quality"},
                "source_chunk_ids": [chunk_id],
                "population": "adults with sleep symptoms",
                "parameter_set": {
                    "stimulation_site": "Cymba Conchae",
                    "frequency_hz": 25,
                    "pulse_width_us": 250,
                    "duration_minutes": 30,
                    "course": "daily sessions",
                    "sham_control": "sham auricular stimulation",
                    "raw_text": "25 Hz, 250 us, Cymba Conchae",
                },
                "outcome": "PSQI",
                "direction": "improved",
                "extraction_confidence": 0.87,
                "metadata": {
                    "study_type": "rct",
                    "sample_size": 60,
                    "primary_outcome": "PSQI",
                },
            }
        ],
        "study": {"study_type": "rct", "sample_size": 60, "region_or_team": "fixture"},
    }


def _completion_request() -> LlmCompletionRequest:
    return LlmCompletionRequest(
        system_prompt="Return JSON.",
        user_prompt="{}",
        prompt_version="literature-extraction-v0.1.0",
        schema_version="candidate-extraction-v0.1.0",
    )


if __name__ == "__main__":
    unittest.main()
