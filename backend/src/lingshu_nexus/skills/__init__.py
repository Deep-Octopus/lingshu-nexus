"""Agent Skill Registry services."""

from pathlib import Path

from lingshu_nexus.retrieval import RetrievalService
from lingshu_nexus.skills.models import (
    SkillDefinition,
    SkillExecutionRecord,
    SkillExecutionResult,
    SkillExecutionStatus,
    SkillRouteMode,
    SkillScope,
    SkillStatus,
    SkillValidationReport,
    UserRole,
)
from lingshu_nexus.skills.repository import InMemorySkillRepository, SkillNotFoundError
from lingshu_nexus.skills.service import (
    SkillPermissionError,
    SkillRegistryService,
    SkillRoutingError,
    classify_skill_query_type,
)


def create_skill_registry_service(
    *,
    retrieval_service: RetrievalService,
    skills_root: Path,
) -> SkillRegistryService:
    service = SkillRegistryService(
        repository=InMemorySkillRepository(),
        retrieval_service=retrieval_service,
        skills_root=skills_root,
    )
    service.load_from_filesystem()
    return service


__all__ = [
    "InMemorySkillRepository",
    "SkillDefinition",
    "SkillExecutionRecord",
    "SkillExecutionResult",
    "SkillExecutionStatus",
    "SkillNotFoundError",
    "SkillPermissionError",
    "SkillRegistryService",
    "SkillRouteMode",
    "SkillRoutingError",
    "SkillScope",
    "SkillStatus",
    "SkillValidationReport",
    "UserRole",
    "classify_skill_query_type",
    "create_skill_registry_service",
]
