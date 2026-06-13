# ruff: noqa: E402

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "lingshu-domain" / "src"))

from lingshu_domain import DEFAULT_DOMAIN_ID, DomainContext
from lingshu_nexus.config.settings import Settings


class ScaffoldTestCase(unittest.TestCase):
    def test_required_scaffold_paths_exist(self) -> None:
        required_paths = [
            "backend/src/lingshu_nexus/api/main.py",
            "backend/src/lingshu_nexus/worker/main.py",
            "packages/lingshu-domain/src/lingshu_domain/__init__.py",
            "frontend/package.json",
            "frontend/src/App.vue",
            "config/README.md",
            "docs/adr",
            ".env.example",
            "docker-compose.yml",
            "pyproject.toml",
            "Makefile",
        ]
        for relative_path in required_paths:
            with self.subTest(path=relative_path):
                self.assertTrue((ROOT / relative_path).exists())

    def test_default_domain_context_is_acupuncture(self) -> None:
        context = DomainContext()
        self.assertEqual(DEFAULT_DOMAIN_ID, "acupuncture")
        self.assertEqual(context.require_domain(), "acupuncture")

    def test_settings_defaults_match_scaffold(self) -> None:
        settings = Settings()
        self.assertEqual(settings.default_domain_id, "acupuncture")
        self.assertIn("postgresql://", settings.database_url)
        self.assertEqual(settings.object_storage_bucket, "lingshu-documents")
        self.assertEqual(settings.neo4j_uri, "bolt://localhost:7687")

    def test_env_example_uses_placeholders_for_sensitive_values(self) -> None:
        env_text = (ROOT / ".env.example").read_text(encoding="utf-8")
        forbidden_fragments = ["sk-", "xai-", "ghp_", "AIza", "Bearer "]
        for fragment in forbidden_fragments:
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, env_text)


if __name__ == "__main__":
    unittest.main()
