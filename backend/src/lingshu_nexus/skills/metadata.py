"""Filesystem metadata loader for Agent Skill packages."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

from lingshu_domain.validation import SchemaValidationError, require_text
from lingshu_nexus.skills.models import SkillDefinition, SkillScope, SkillStatus, UserRole

AUTO_CHECKSUM_VALUES = {"auto", "generated_on_publish", ""}


def load_skill_definition(skill_dir: Path) -> SkillDefinition:
    skill_md = skill_dir / "SKILL.md"
    registry_yaml = skill_dir / "registry.yaml"
    if not skill_md.exists():
        raise SchemaValidationError(f"SKILL.md is missing: {skill_dir}")
    if not registry_yaml.exists():
        raise SchemaValidationError(f"registry.yaml is missing: {skill_dir}")

    frontmatter = parse_skill_frontmatter(skill_md.read_text(encoding="utf-8"))
    registry = parse_simple_yaml(registry_yaml.read_text(encoding="utf-8"))
    name = _required_string(frontmatter, "name")
    description = _required_string(frontmatter, "description")
    skill_id = _required_string(registry, "skill_id")
    if skill_id != name:
        raise SchemaValidationError("registry.yaml skill_id must match SKILL.md name")
    computed_checksum = compute_skill_checksum(skill_dir)
    expected_checksum = str(registry.get("checksum", "auto"))
    if expected_checksum not in AUTO_CHECKSUM_VALUES and expected_checksum != computed_checksum:
        raise SchemaValidationError(f"Skill checksum mismatch for {skill_id}")

    test_cases_path = skill_dir / "tests" / "cases.yaml"
    return SkillDefinition(
        id=skill_id,
        name=name,
        description=description,
        version=_required_string(registry, "version"),
        status=SkillStatus(_required_string(registry, "status")),
        scope=SkillScope(_required_string(registry, "scope")),
        minimum_role=UserRole(_required_string(registry, "minimum_role")),
        server_allowed_tools=_string_tuple(registry, "server_allowed_tools"),
        supported_query_types=_string_tuple(registry, "supported_query_types"),
        domain_ids=_string_tuple(registry, "domain_ids"),
        checksum=computed_checksum,
        source_path=str(skill_dir),
        test_cases_path=str(test_cases_path) if test_cases_path.exists() else None,
        metadata={
            "registry_checksum_policy": expected_checksum,
            "has_test_cases": test_cases_path.exists(),
        },
    )


def validate_skill_package(skill_dir: Path) -> tuple[SkillDefinition | None, tuple[str, ...]]:
    issues: list[str] = []
    try:
        skill = load_skill_definition(skill_dir)
    except (SchemaValidationError, ValueError) as exc:
        return None, (str(exc),)
    skill_md = skill_dir / "SKILL.md"
    if skill_md.stat().st_size == 0:
        issues.append("SKILL.md must not be empty")
    if skill.test_cases_path is None:
        issues.append("tests/cases.yaml is required for an enableable V1 Skill")
    elif Path(skill.test_cases_path).stat().st_size == 0:
        issues.append("tests/cases.yaml must not be empty")
    return skill, tuple(issues)


def parse_skill_frontmatter(markdown: str) -> dict[str, Any]:
    lines = markdown.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SchemaValidationError("SKILL.md must start with YAML frontmatter")
    end_index: int | None = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = index
            break
    if end_index is None:
        raise SchemaValidationError("SKILL.md frontmatter must be closed with ---")
    return parse_simple_yaml("\n".join(lines[1:end_index]))


def compute_skill_checksum(skill_dir: Path) -> str:
    digest = sha256()
    for filename in ("SKILL.md", "registry.yaml"):
        path = skill_dir / filename
        digest.update(filename.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def parse_simple_yaml(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    current_list_key: str | None = None
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("- "):
            if current_list_key is None:
                raise SchemaValidationError(f"Unexpected list item at line {line_number}")
            current_value = result[current_list_key]
            if not isinstance(current_value, list):
                raise SchemaValidationError(f"YAML key is not a list: {current_list_key}")
            current_value.append(_parse_scalar(line[2:].strip()))
            continue
        if ":" not in line:
            raise SchemaValidationError(f"Unsupported YAML line {line_number}: {line}")
        key, value = line.split(":", maxsplit=1)
        key = key.strip()
        require_text(key, f"YAML key at line {line_number}")
        value = value.strip()
        if value == "":
            result[key] = []
            current_list_key = key
        else:
            result[key] = _parse_scalar(value)
            current_list_key = None
    return result


def _parse_scalar(value: str) -> object:
    if " #" in value:
        value = value.split(" #", maxsplit=1)[0].strip()
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    return value


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise SchemaValidationError(f"{key} is required")
    return require_text(value, key)


def _string_tuple(payload: dict[str, Any], key: str) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise SchemaValidationError(f"{key} must be a YAML list")
    values = tuple(require_text(str(item), key) for item in value)
    if not values:
        raise SchemaValidationError(f"{key} must not be empty")
    return values
