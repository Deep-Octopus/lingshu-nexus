#!/usr/bin/env python3
"""Run the repeatable T-120 V1 acceptance regression set."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_TESTS = (
    "tests/test_v1_acceptance.py",
    "tests/test_document_ingestion.py",
    "tests/test_candidate_extraction.py",
    "tests/test_review_release.py",
    "tests/test_graph_retrieval.py",
    "tests/test_skill_registry.py",
    "tests/test_chat_stream.py",
    "tests/test_admin_panel.py",
    "tests/test_source_connector.py",
)


def _run(command: list[str]) -> None:
    print(f"+ {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--backend-only",
        action="store_true",
        help="Skip the frontend production build when Node.js is unavailable.",
    )
    args = parser.parse_args(argv)

    _run([sys.executable, "-m", "pytest", *BACKEND_TESTS])
    if not args.backend_only:
        if shutil.which("npm") is None:
            raise SystemExit("npm is required for the full V1 acceptance run")
        _run(["npm", "--prefix", "frontend", "run", "build"])
    print("V1 fixture acceptance checks passed.")
    print("Real-corpus and live-provider acceptance remain external-input gates.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
