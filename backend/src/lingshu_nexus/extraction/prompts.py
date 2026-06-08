"""Versioned extraction prompt loader."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from lingshu_nexus.extraction.models import ExtractionPrompt

PROMPT_VERSION = "literature-extraction-v0.1.0"


def load_literature_extraction_prompt(domain_id: str = "acupuncture") -> ExtractionPrompt:
    prompt_path = _repo_root() / "config" / "prompts" / domain_id / "literature_extraction.v0.1.md"
    text = prompt_path.read_text(encoding="utf-8")
    return ExtractionPrompt(
        id=f"{domain_id}-literature-extraction",
        domain_id=domain_id,
        version=PROMPT_VERSION,
        checksum=sha256(text.encode("utf-8")).hexdigest(),
        text=text,
    )


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]
