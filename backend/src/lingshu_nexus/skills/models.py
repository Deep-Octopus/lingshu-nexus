"""Agent Skill Registry domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from lingshu_domain.validation import (
    SchemaValidationError,
    require_domain_id,
    require_non_empty,
    require_text,
)
from lingshu_nexus.retrieval.models import SourceCitation


class SkillStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    DISABLED = "disabled"
    RETIRED = "retired"


class SkillScope(StrEnum):
    READ_ONLY = "read_only"
    BACKGROUND_WRITE = "background_write"


class SkillRouteMode(StrEnum):
    USER_SPECIFIED = "user_specified"
    AUTO = "auto"


class SkillExecutionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class UserRole(StrEnum):
    READ_ONLY = "read_only"
    RESEARCHER = "researcher"
    REVIEWER = "reviewer"
    ADMIN = "admin"


@dataclass(frozen=True)
class SkillValidationReport:
    skill_id: str
    version: str
    valid: bool
    computed_checksum: str
    issues: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_text(self.skill_id, "SkillValidationReport.skill_id")
        require_text(self.version, "SkillValidationReport.version")
        require_text(self.computed_checksum, "SkillValidationReport.computed_checksum")


@dataclass(frozen=True)
class SkillDefinition:
    id: str
    name: str
    description: str
    version: str
    status: SkillStatus
    scope: SkillScope
    minimum_role: UserRole
    server_allowed_tools: tuple[str, ...]
    supported_query_types: tuple[str, ...]
    domain_ids: tuple[str, ...]
    checksum: str
    source_path: str
    test_cases_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_text(self.id, "SkillDefinition.id")
        require_text(self.name, "SkillDefinition.name")
        require_text(self.description, "SkillDefinition.description")
        require_text(self.version, "SkillDefinition.version")
        require_text(self.checksum, "SkillDefinition.checksum")
        require_text(self.source_path, "SkillDefinition.source_path")
        require_non_empty(self.server_allowed_tools, "server_allowed_tools")
        require_non_empty(self.supported_query_types, "supported_query_types")
        require_non_empty(self.domain_ids, "domain_ids")
        for domain_id in self.domain_ids:
            require_domain_id(domain_id)
        if self.id != self.name:
            raise SchemaValidationError("SkillDefinition.id must match SKILL.md name")


@dataclass(frozen=True)
class SkillExecutionRecord:
    id: str
    domain_id: str
    skill_id: str
    skill_version: str
    actor_id: str
    actor_role: UserRole
    route_mode: SkillRouteMode
    query: str
    query_type: str
    status: SkillExecutionStatus
    release_id: str | None = None
    release_version: str | None = None
    citation_keys: tuple[str, ...] = ()
    error: str | None = None
    elapsed_ms: int = 0
    created_at: str = ""

    def __post_init__(self) -> None:
        require_text(self.id, "SkillExecutionRecord.id")
        require_domain_id(self.domain_id)
        require_text(self.skill_id, "SkillExecutionRecord.skill_id")
        require_text(self.skill_version, "SkillExecutionRecord.skill_version")
        require_text(self.actor_id, "SkillExecutionRecord.actor_id")
        require_text(self.query, "SkillExecutionRecord.query")
        require_text(self.query_type, "SkillExecutionRecord.query_type")
        if self.elapsed_ms < 0:
            raise SchemaValidationError("SkillExecutionRecord.elapsed_ms must be >= 0")


@dataclass(frozen=True)
class SkillExecutionResult:
    record: SkillExecutionRecord
    answer: str
    citations: tuple[SourceCitation, ...]

    def __post_init__(self) -> None:
        require_text(self.answer, "SkillExecutionResult.answer")
