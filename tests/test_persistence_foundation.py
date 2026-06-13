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
    ConceptType,
    EvidenceAssertion,
    EvidenceTerm,
    GraphRelease,
    PredicateType,
    ReviewStatus,
    SchemaValidationError,
)
from lingshu_nexus.persistence.graph import InMemoryGraphRepository
from lingshu_nexus.persistence.migrations import load_migration_pair
from lingshu_nexus.persistence.models import AuditEvent, ConfigVersion, DataLayer, JobRun, JobStatus
from lingshu_nexus.persistence.object_store import DuplicateObjectError, InMemoryObjectStore


class PersistenceFoundationTestCase(unittest.TestCase):
    def test_foundation_migration_can_apply_drop_and_reapply(self) -> None:
        migration = load_migration_pair("0001_foundation")
        connection = sqlite3.connect(":memory:")
        try:
            connection.executescript(migration.up_sql)
            table_names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            expected_tables = {
                "source_documents",
                "source_chunks",
                "studies",
                "canonical_concepts",
                "evidence_assertions",
                "review_decisions",
                "graph_releases",
                "object_artifacts",
                "graph_sync_records",
                "job_runs",
                "config_versions",
                "audit_events",
            }
            self.assertTrue(expected_tables.issubset(table_names))
            connection.executescript(migration.down_sql)
            remaining = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
            self.assertEqual(remaining, [])
            connection.executescript(migration.up_sql)
        finally:
            connection.close()

    def test_object_store_is_immutable_and_domain_isolated(self) -> None:
        store = InMemoryObjectStore()
        raw_ref = store.put(
            domain_id="acupuncture",
            object_key="doc_001.pdf",
            content=b"raw-pdf-bytes",
            layer=DataLayer.RAW,
            media_type="application/pdf",
            version=1,
        )
        parsed_ref = store.put(
            domain_id="acupuncture",
            object_key="doc_001/chunks.json",
            content=b"parsed-json",
            layer=DataLayer.PARSED,
            media_type="application/json",
            version=1,
        )
        self.assertNotEqual(raw_ref.storage_uri, parsed_ref.storage_uri)
        self.assertEqual(store.get(raw_ref, domain_id="acupuncture"), b"raw-pdf-bytes")
        with self.assertRaises(PermissionError):
            store.get(raw_ref, domain_id="other_domain")
        with self.assertRaises(DuplicateObjectError):
            store.put(
                domain_id="acupuncture",
                object_key="doc_001.pdf",
                content=b"overwrite",
                layer=DataLayer.RAW,
                media_type="application/pdf",
                version=1,
            )

    def test_foundational_records_require_domain_and_audit_fields(self) -> None:
        job = JobRun(
            id="job_001",
            domain_id="acupuncture",
            job_type="migration_check",
            status=JobStatus.SUCCEEDED,
        )
        config = ConfigVersion(
            id="cfg_001",
            domain_id="acupuncture",
            config_type="schema",
            version="acupuncture-tvns-v0.1.0",
            checksum="checksum",
            payload={"domain_id": "acupuncture"},
        )
        audit = AuditEvent(
            id="audit_001",
            domain_id="acupuncture",
            actor_id="system",
            action="config.created",
            target_type="config_version",
            target_id=config.id,
        )
        self.assertEqual(job.domain_id, config.domain_id)
        self.assertEqual(audit.target_id, config.id)

    def test_graph_repository_accepts_only_publishable_release_assertions(self) -> None:
        approved = EvidenceAssertion(
            id="assertion_001",
            domain_id="acupuncture",
            subject=EvidenceTerm(ConceptType.INTERVENTION, "taVNS"),
            predicate=PredicateType.AFFECTS_OUTCOME,
            object=EvidenceTerm(ConceptType.OUTCOME, "sleep quality"),
            source_chunk_ids=("chunk_001",),
            review_status=ReviewStatus.APPROVED,
            extraction_confidence=0.9,
        )
        release = GraphRelease(
            id="release_001",
            domain_id="acupuncture",
            version="v0.1",
            included_assertion_ids=(approved.id,),
            schema_version="acupuncture-tvns-v0.1.0",
            index_version="graph-none-v0.1",
            released_by="reviewer_001",
            active=True,
        )
        repository = InMemoryGraphRepository()
        repository.write_release(release, (approved,))
        self.assertEqual(
            repository.assertion_ids_for_release(domain_id="acupuncture", release_id=release.id),
            (approved.id,),
        )

        pending = EvidenceAssertion(
            id="assertion_pending",
            domain_id="acupuncture",
            subject=EvidenceTerm(ConceptType.INTERVENTION, "taVNS"),
            predicate=PredicateType.AFFECTS_OUTCOME,
            object=EvidenceTerm(ConceptType.OUTCOME, "sleep quality"),
            source_chunk_ids=("chunk_001",),
            review_status=ReviewStatus.PENDING,
        )
        bad_release = GraphRelease(
            id="release_pending",
            domain_id="acupuncture",
            version="v0.2",
            included_assertion_ids=(pending.id,),
            schema_version="acupuncture-tvns-v0.1.0",
            index_version="graph-none-v0.1",
            released_by="reviewer_001",
        )
        with self.assertRaises(SchemaValidationError):
            repository.write_release(bad_release, (pending,))


if __name__ == "__main__":
    unittest.main()
