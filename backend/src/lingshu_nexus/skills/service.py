"""Agent Skill Registry and read-only Skill execution service."""

from __future__ import annotations

import re
import shutil
from collections import Counter
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from lingshu_domain import EvidenceAssertion, SourceDocument
from lingshu_domain.validation import require_domain_id, require_text
from lingshu_nexus.retrieval import RetrievalService
from lingshu_nexus.retrieval.models import RetrievalResponse, SourceCitation
from lingshu_nexus.review.models import utcnow
from lingshu_nexus.skills.metadata import (
    compute_skill_checksum,
    load_skill_definition,
    validate_skill_package,
)
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
from lingshu_nexus.skills.repository import SkillRepository

READ_ONLY_SERVER_TOOLS = frozenset(
    {
        "published_graph_search",
        "source_chunk_fetch",
        "source_document_list",
        "graph_relationship_lookup",
    }
)

ROLE_RANK = {
    UserRole.READ_ONLY: 0,
    UserRole.RESEARCHER: 1,
    UserRole.REVIEWER: 2,
    UserRole.ADMIN: 3,
}
SAFE_SKILL_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")


class SkillPermissionError(PermissionError):
    """Raised when a user cannot execute or manage a Skill."""


class SkillRoutingError(LookupError):
    """Raised when automatic routing cannot select a safe Skill."""


class SkillPackageValidationError(ValueError):
    """Raised when an uploaded Skill package cannot be validated."""


class SkillRegistryService:
    """Load, validate, route, and execute read-only Agent Skills."""

    def __init__(
        self,
        *,
        repository: SkillRepository,
        retrieval_service: RetrievalService,
        skills_root: Path,
    ) -> None:
        self._repository = repository
        self._retrieval_service = retrieval_service
        self._skills_root = skills_root

    def load_from_filesystem(self) -> tuple[SkillDefinition, ...]:
        if not self._skills_root.exists():
            return ()
        loaded: list[SkillDefinition] = []
        for skill_dir in sorted(path for path in self._skills_root.iterdir() if path.is_dir()):
            if not (skill_dir / "SKILL.md").exists():
                continue
            skill = load_skill_definition(skill_dir)
            self._repository.upsert_skill(skill)
            loaded.append(skill)
        return tuple(loaded)

    def list_skills(self, *, domain_id: str) -> tuple[SkillDefinition, ...]:
        return self._repository.list_skills(domain_id=domain_id)

    def get_skill(self, *, domain_id: str, skill_id: str) -> SkillDefinition:
        return self._repository.get_skill(domain_id=domain_id, skill_id=skill_id)

    def validate_skill(self, *, domain_id: str, skill_id: str) -> SkillValidationReport:
        skill = self.get_skill(domain_id=domain_id, skill_id=skill_id)
        loaded, issues = validate_skill_package(Path(skill.source_path))
        computed_checksum = compute_skill_checksum(Path(skill.source_path))
        version = loaded.version if loaded is not None else skill.version
        return SkillValidationReport(
            skill_id=skill_id,
            version=version,
            valid=not issues and loaded is not None,
            computed_checksum=computed_checksum,
            issues=issues,
        )

    def upload_skill_package(
        self,
        *,
        skill_id: str,
        skill_md: str,
        registry_yaml: str,
        test_cases_yaml: str,
        actor_role: UserRole,
    ) -> SkillDefinition:
        if ROLE_RANK[actor_role] < ROLE_RANK[UserRole.ADMIN]:
            raise SkillPermissionError("Only admins can upload Skills")
        safe_skill_id = _safe_skill_id(skill_id)
        root = self._skills_root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        incoming_dir = root / ".uploads" / f"{safe_skill_id}-{uuid4().hex}"
        try:
            incoming_dir.mkdir(parents=True, exist_ok=False)
            (incoming_dir / "tests").mkdir(parents=True, exist_ok=False)
            (incoming_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")
            (incoming_dir / "registry.yaml").write_text(registry_yaml, encoding="utf-8")
            (incoming_dir / "tests" / "cases.yaml").write_text(
                test_cases_yaml,
                encoding="utf-8",
            )
            loaded, issues = validate_skill_package(incoming_dir)
            if loaded is None or issues:
                raise SkillPackageValidationError("; ".join(issues) or "Skill package is invalid")
            if loaded.id != safe_skill_id:
                raise SkillPackageValidationError(
                    "skill_id must match SKILL.md name and registry.yaml skill_id"
                )
            destination = root / safe_skill_id
            if destination.exists():
                shutil.rmtree(destination)
            shutil.move(str(incoming_dir), str(destination))
            skill = load_skill_definition(destination)
            self._repository.upsert_skill(skill)
            return skill
        finally:
            if incoming_dir.exists():
                shutil.rmtree(incoming_dir)

    def set_status(
        self,
        *,
        domain_id: str,
        skill_id: str,
        status: SkillStatus,
        actor_role: UserRole,
    ) -> SkillDefinition:
        if ROLE_RANK[actor_role] < ROLE_RANK[UserRole.ADMIN]:
            raise SkillPermissionError("Only admins can enable or disable Skills")
        skill = self._repository.set_status(
            domain_id=domain_id,
            skill_id=skill_id,
            status=status,
        )
        return skill

    def execute(
        self,
        *,
        domain_id: str,
        query: str,
        actor_id: str,
        actor_role: UserRole,
        skill_id: str | None = None,
        limit: int = 5,
    ) -> SkillExecutionResult:
        require_domain_id(domain_id)
        require_text(query, "query")
        require_text(actor_id, "actor_id")
        if limit < 1:
            raise ValueError("limit must be >= 1")

        query_type = classify_skill_query_type(query)
        route_mode = SkillRouteMode.USER_SPECIFIED if skill_id else SkillRouteMode.AUTO
        skill = self._select_skill(
            domain_id=domain_id,
            query_type=query_type,
            actor_role=actor_role,
            skill_id=skill_id,
        )
        self._authorize_read_only_execution(
            domain_id=domain_id,
            skill=skill,
            actor_role=actor_role,
            route_mode=route_mode,
        )

        started_at = perf_counter()
        response: RetrievalResponse | None = None
        try:
            response = self._retrieval_service.search(
                domain_id=domain_id,
                query=query,
                limit=limit,
            )
            documents = (
                self._retrieval_service.source_documents_for_active_release(domain_id=domain_id)
                if "source_document_list" in skill.server_allowed_tools
                else ()
            )
            citations = _collect_citations(response)
            answer = _render_answer(
                skill=skill,
                query=query,
                query_type=query_type,
                response=response,
                documents=documents,
            )
            record = self._record_execution(
                domain_id=domain_id,
                skill=skill,
                actor_id=actor_id,
                actor_role=actor_role,
                route_mode=route_mode,
                query=query,
                query_type=query_type,
                status=SkillExecutionStatus.SUCCEEDED,
                response=response,
                citation_keys=_citation_keys(citations),
                elapsed_ms=_elapsed_ms(started_at),
            )
            return SkillExecutionResult(record=record, answer=answer, citations=citations)
        except Exception as exc:
            self._record_execution(
                domain_id=domain_id,
                skill=skill,
                actor_id=actor_id,
                actor_role=actor_role,
                route_mode=route_mode,
                query=query,
                query_type=query_type,
                status=SkillExecutionStatus.FAILED,
                response=response,
                citation_keys=(),
                error=str(exc),
                elapsed_ms=_elapsed_ms(started_at),
            )
            raise

    def list_execution_records(
        self,
        *,
        domain_id: str,
        skill_id: str | None = None,
    ) -> tuple[SkillExecutionRecord, ...]:
        return self._repository.list_execution_records(domain_id=domain_id, skill_id=skill_id)

    def _select_skill(
        self,
        *,
        domain_id: str,
        query_type: str,
        actor_role: UserRole,
        skill_id: str | None,
    ) -> SkillDefinition:
        if skill_id is not None:
            return self.get_skill(domain_id=domain_id, skill_id=skill_id)
        candidates = [
            skill
            for skill in self.list_skills(domain_id=domain_id)
            if skill.status is SkillStatus.ACTIVE
            and skill.scope is SkillScope.READ_ONLY
            and query_type in skill.supported_query_types
            and ROLE_RANK[actor_role] >= ROLE_RANK[skill.minimum_role]
            and set(skill.server_allowed_tools).issubset(READ_ONLY_SERVER_TOOLS)
        ]
        if not candidates:
            raise SkillRoutingError("No enabled read-only Skill is available for this query")
        return sorted(candidates, key=lambda skill: (_skill_route_priority(skill.id), skill.id))[0]

    def _authorize_read_only_execution(
        self,
        *,
        domain_id: str,
        skill: SkillDefinition,
        actor_role: UserRole,
        route_mode: SkillRouteMode,
    ) -> None:
        if domain_id not in skill.domain_ids:
            raise SkillPermissionError("Skill is not enabled for this domain")
        if skill.status is not SkillStatus.ACTIVE:
            raise SkillPermissionError("Skill is not active")
        if ROLE_RANK[actor_role] < ROLE_RANK[skill.minimum_role]:
            raise SkillPermissionError("User role cannot execute this Skill")
        if skill.scope is not SkillScope.READ_ONLY:
            raise SkillPermissionError("Chat Skill execution only permits read-only Skills")
        if route_mode is SkillRouteMode.AUTO and not set(skill.server_allowed_tools).issubset(
            READ_ONLY_SERVER_TOOLS
        ):
            raise SkillPermissionError("Automatic routing only permits read-only server tools")
        if not set(skill.server_allowed_tools).issubset(READ_ONLY_SERVER_TOOLS):
            raise SkillPermissionError("Skill has server tools outside the read-only allowlist")

    def _record_execution(
        self,
        *,
        domain_id: str,
        skill: SkillDefinition,
        actor_id: str,
        actor_role: UserRole,
        route_mode: SkillRouteMode,
        query: str,
        query_type: str,
        status: SkillExecutionStatus,
        response: RetrievalResponse | None,
        citation_keys: tuple[str, ...],
        elapsed_ms: int,
        error: str | None = None,
    ) -> SkillExecutionRecord:
        record = SkillExecutionRecord(
            id=f"skill_exec_{uuid4().hex}",
            domain_id=domain_id,
            skill_id=skill.id,
            skill_version=skill.version,
            actor_id=actor_id,
            actor_role=actor_role,
            route_mode=route_mode,
            query=query,
            query_type=query_type,
            status=status,
            release_id=response.release.id if response else None,
            release_version=response.release.version if response else None,
            citation_keys=citation_keys,
            error=error,
            elapsed_ms=elapsed_ms,
            created_at=utcnow(),
        )
        self._repository.add_execution_record(record)
        return record


def classify_skill_query_type(query: str) -> str:
    text = query.casefold()
    if _has_any(text, ("禁忌", "不良", "安全", "排除标准", "adverse", "safety", "contraindicat")):
        return "safety_contraindication"
    if _has_any(text, ("频率", "frequency", "hz")):
        return "frequency_effect"
    if _has_any(
        text,
        (
            "参数",
            "剂量",
            "刺激部位",
            "脉宽",
            "强度",
            "时长",
            "疗程",
            "sham",
            "control",
            "parameter",
            "dose",
        ),
    ):
        return "parameter_summary"
    if _has_any(text, ("机制", "mechanism", "迷走", "vagus", "afferent", "通路")):
        return "mechanism_summary"
    if _has_any(text, ("rct", "randomized", "trial", "试验设计", "随机", "纳排")):
        return "rct_design_summary"
    if _has_any(text, ("按时间", "时间线", "timeline", "年份", "publication", "文献列表")):
        return "timeline_literature"
    if _has_any(text, ("空白", "gap", "landscape", "分布", "主题")):
        return "research_gap"
    return "evidence_lookup"


def _safe_skill_id(skill_id: str) -> str:
    value = require_text(skill_id, "skill_id")
    if not SAFE_SKILL_ID_PATTERN.fullmatch(value):
        raise SkillPackageValidationError(
            "skill_id must use 2-64 lowercase letters, digits, hyphens, or underscores"
        )
    return value


def _render_answer(
    *,
    skill: SkillDefinition,
    query: str,
    query_type: str,
    response: RetrievalResponse,
    documents: tuple[SourceDocument, ...],
) -> str:
    if skill.id == "literature-landscape":
        return _render_literature_landscape(
            query=query,
            query_type=query_type,
            response=response,
            documents=documents,
        )
    return _render_evidence_query(query=query, query_type=query_type, response=response)


def _render_evidence_query(
    *,
    query: str,
    query_type: str,
    response: RetrievalResponse,
) -> str:
    lines = [
        "仅用于内部科研证据辅助，不作为诊疗建议。",
        f"Skill 查询类型：{query_type}；active release：{response.release.version}。",
    ]
    if not response.results:
        lines.append(f"未在已发布证据中检索到与“{query}”匹配的引用。")
        return "\n".join(lines)
    for index, result in enumerate(response.results, start=1):
        assertion = result.assertion
        lines.append(f"{index}. {_assertion_sentence(assertion)}")
        parameter_text = _parameter_sentence(assertion)
        if parameter_text:
            lines.append(f"   参数：{parameter_text}")
        citation = result.citations[0]
        lines.append(
            f"   引用：{citation.document_id}/{citation.chunk_id} ({citation.locator_reference})"
        )
    return "\n".join(lines)


def _render_literature_landscape(
    *,
    query: str,
    query_type: str,
    response: RetrievalResponse,
    documents: tuple[SourceDocument, ...],
) -> str:
    lines = [
        "仅用于内部科研证据辅助，不作为诊疗建议。",
        f"Skill 查询类型：{query_type}；active release：{response.release.version}。",
    ]
    if not response.results:
        lines.append(f"当前已发布证据未覆盖“{query}”。")
    else:
        predicate_counts = Counter(result.assertion.predicate.value for result in response.results)
        quality_counts = Counter(
            result.assertion.source_quality_signals.tier.value for result in response.results
        )
        lines.append(
            "命题分布："
            + ", ".join(f"{name}={count}" for name, count in sorted(predicate_counts.items()))
        )
        lines.append(
            "来源质量信号："
            + ", ".join(f"{name}={count}" for name, count in sorted(quality_counts.items()))
        )
        for index, result in enumerate(response.results, start=1):
            lines.append(f"{index}. {_assertion_sentence(result.assertion)}")
    if documents:
        lines.append("发布版本引用文献：")
        for document in sorted(documents, key=lambda item: item.title):
            lines.append(
                f"- {document.title} ({document.id}; quality={document.source_quality_tier.value})"
            )
        if query_type == "timeline_literature":
            lines.append("当前 SourceDocument 尚未记录 publication_date，无法伪造按年份排序。")
    return "\n".join(lines)


def _assertion_sentence(assertion: EvidenceAssertion) -> str:
    parts = [
        assertion.subject.text,
        assertion.predicate.value,
        assertion.object.text,
        f"direction={assertion.direction.value}",
    ]
    if assertion.population:
        parts.append(f"population={assertion.population}")
    if assertion.outcome:
        parts.append(f"outcome={assertion.outcome}")
    return "; ".join(parts)


def _parameter_sentence(assertion: EvidenceAssertion) -> str:
    parameter_set = assertion.parameter_set
    if parameter_set is None:
        return ""
    parts: list[str] = []
    if parameter_set.stimulation_site:
        parts.append(f"site={parameter_set.stimulation_site}")
    if parameter_set.frequency_hz is not None:
        parts.append(f"frequency={parameter_set.frequency_hz:g}Hz")
    if parameter_set.pulse_width_us is not None:
        parts.append(f"pulse_width={parameter_set.pulse_width_us:g}us")
    if parameter_set.intensity:
        parts.append(f"intensity={parameter_set.intensity}")
    if parameter_set.duration_minutes is not None:
        parts.append(f"duration={parameter_set.duration_minutes:g}min")
    if parameter_set.course:
        parts.append(f"course={parameter_set.course}")
    if parameter_set.waveform:
        parts.append(f"waveform={parameter_set.waveform}")
    if parameter_set.dose:
        parts.append(f"dose={parameter_set.dose}")
    if parameter_set.sham_control:
        parts.append(f"sham_control={parameter_set.sham_control}")
    return ", ".join(parts)


def _collect_citations(response: RetrievalResponse) -> tuple[SourceCitation, ...]:
    citations: list[SourceCitation] = []
    seen: set[str] = set()
    for result in response.results:
        for citation in result.citations:
            key = _citation_key(citation)
            if key not in seen:
                seen.add(key)
                citations.append(citation)
    return tuple(citations)


def _citation_keys(citations: tuple[SourceCitation, ...]) -> tuple[str, ...]:
    return tuple(_citation_key(citation) for citation in citations)


def _citation_key(citation: SourceCitation) -> str:
    return f"{citation.document_id}:{citation.chunk_id}:{citation.locator_reference}"


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((perf_counter() - started_at) * 1000))


def _skill_route_priority(skill_id: str) -> int:
    priority = {"evidence-query": 0, "literature-landscape": 1}
    return priority.get(skill_id, 100)


def _has_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def clone_skill_with_status(skill: SkillDefinition, status: SkillStatus) -> SkillDefinition:
    return replace(skill, status=status)
