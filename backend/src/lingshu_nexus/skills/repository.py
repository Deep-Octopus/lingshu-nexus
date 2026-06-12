"""Skill Registry repository port and in-memory adapter."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from lingshu_domain.validation import require_domain_id, require_text
from lingshu_nexus.skills.models import SkillDefinition, SkillExecutionRecord, SkillStatus


class SkillNotFoundError(KeyError):
    """Raised when a Skill is unknown in the requested domain."""


class SkillRepository(Protocol):
    def upsert_skill(self, skill: SkillDefinition) -> None:
        """Create or update one Skill definition."""

    def get_skill(self, *, domain_id: str, skill_id: str) -> SkillDefinition:
        """Return one Skill visible in a domain."""

    def list_skills(self, *, domain_id: str) -> tuple[SkillDefinition, ...]:
        """Return Skills visible in a domain."""

    def set_status(
        self,
        *,
        domain_id: str,
        skill_id: str,
        status: SkillStatus,
    ) -> SkillDefinition:
        """Update Skill status."""

    def add_execution_record(self, record: SkillExecutionRecord) -> None:
        """Append one immutable execution record."""

    def list_execution_records(
        self,
        *,
        domain_id: str,
        skill_id: str | None = None,
    ) -> tuple[SkillExecutionRecord, ...]:
        """Return Skill execution records."""


class InMemorySkillRepository:
    def __init__(self) -> None:
        self._skills: dict[str, SkillDefinition] = {}
        self._records: list[SkillExecutionRecord] = []

    def upsert_skill(self, skill: SkillDefinition) -> None:
        self._skills[skill.id] = skill

    def get_skill(self, *, domain_id: str, skill_id: str) -> SkillDefinition:
        require_domain_id(domain_id)
        require_text(skill_id, "skill_id")
        skill = self._skills.get(skill_id)
        if skill is None or domain_id not in skill.domain_ids:
            raise SkillNotFoundError(skill_id)
        return skill

    def list_skills(self, *, domain_id: str) -> tuple[SkillDefinition, ...]:
        require_domain_id(domain_id)
        return tuple(
            sorted(
                (skill for skill in self._skills.values() if domain_id in skill.domain_ids),
                key=lambda skill: (skill.id, skill.version),
            )
        )

    def set_status(
        self,
        *,
        domain_id: str,
        skill_id: str,
        status: SkillStatus,
    ) -> SkillDefinition:
        skill = self.get_skill(domain_id=domain_id, skill_id=skill_id)
        updated = replace(skill, status=status)
        self._skills[skill_id] = updated
        return updated

    def add_execution_record(self, record: SkillExecutionRecord) -> None:
        self._records.append(record)

    def list_execution_records(
        self,
        *,
        domain_id: str,
        skill_id: str | None = None,
    ) -> tuple[SkillExecutionRecord, ...]:
        require_domain_id(domain_id)
        return tuple(
            record
            for record in self._records
            if record.domain_id == domain_id and (skill_id is None or record.skill_id == skill_id)
        )
