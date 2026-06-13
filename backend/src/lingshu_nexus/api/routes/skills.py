"""Agent Skill Registry API routes."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request

from lingshu_domain import DEFAULT_DOMAIN_ID, SourceChunk, SourceDocument
from lingshu_nexus.documents import DocumentIngestService
from lingshu_nexus.retrieval import NoActiveReleaseError, ReleaseNotIndexedError, RetrievalService
from lingshu_nexus.review import ReviewReleaseService
from lingshu_nexus.skills import (
    SkillDefinition,
    SkillExecutionRecord,
    SkillExecutionResult,
    SkillNotFoundError,
    SkillPermissionError,
    SkillRegistryService,
    SkillRoutingError,
    SkillStatus,
    UserRole,
)

router = APIRouter(prefix="/api/v1", tags=["skills"])


def get_skill_service(request: Request) -> SkillRegistryService:
    return cast(SkillRegistryService, request.app.state.skill_registry_service)


def get_retrieval_service(request: Request) -> RetrievalService:
    return cast(RetrievalService, request.app.state.retrieval_service)


def get_document_service(request: Request) -> DocumentIngestService:
    return cast(DocumentIngestService, request.app.state.document_service)


def get_review_service(request: Request) -> ReviewReleaseService:
    return cast(ReviewReleaseService, request.app.state.review_release_service)


@router.get("/skills")
async def list_skills(
    service: Annotated[SkillRegistryService, Depends(get_skill_service)],
    domain_id: Annotated[str, Query()] = DEFAULT_DOMAIN_ID,
) -> dict[str, object]:
    return {
        "domain_id": domain_id,
        "skills": [_skill_payload(skill) for skill in service.list_skills(domain_id=domain_id)],
    }


@router.get("/skills/{skill_id}")
async def get_skill(
    skill_id: str,
    service: Annotated[SkillRegistryService, Depends(get_skill_service)],
    domain_id: Annotated[str, Query()] = DEFAULT_DOMAIN_ID,
) -> dict[str, object]:
    try:
        return _skill_payload(service.get_skill(domain_id=domain_id, skill_id=skill_id))
    except SkillNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Skill not found") from exc


@router.post("/skills/{skill_id}:validate")
async def validate_skill(
    skill_id: str,
    service: Annotated[SkillRegistryService, Depends(get_skill_service)],
    domain_id: Annotated[str, Query()] = DEFAULT_DOMAIN_ID,
) -> dict[str, object]:
    try:
        report = service.validate_skill(domain_id=domain_id, skill_id=skill_id)
    except SkillNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Skill not found") from exc
    return {
        "skill_id": report.skill_id,
        "version": report.version,
        "valid": report.valid,
        "computed_checksum": report.computed_checksum,
        "issues": list(report.issues),
    }


@router.post("/skills/{skill_id}:enable")
async def enable_skill(
    skill_id: str,
    payload: Annotated[dict[str, object], Body()],
    service: Annotated[SkillRegistryService, Depends(get_skill_service)],
    review_service: Annotated[ReviewReleaseService, Depends(get_review_service)],
    domain_id: Annotated[str, Query()] = DEFAULT_DOMAIN_ID,
) -> dict[str, object]:
    return _set_skill_status(
        service=service,
        review_service=review_service,
        domain_id=domain_id,
        skill_id=skill_id,
        status=SkillStatus.ACTIVE,
        actor_id=_payload_text(payload, "actor_id", "admin-ui"),
        actor_role=_role_from_payload(payload),
    )


@router.post("/skills/{skill_id}:disable")
async def disable_skill(
    skill_id: str,
    payload: Annotated[dict[str, object], Body()],
    service: Annotated[SkillRegistryService, Depends(get_skill_service)],
    review_service: Annotated[ReviewReleaseService, Depends(get_review_service)],
    domain_id: Annotated[str, Query()] = DEFAULT_DOMAIN_ID,
) -> dict[str, object]:
    return _set_skill_status(
        service=service,
        review_service=review_service,
        domain_id=domain_id,
        skill_id=skill_id,
        status=SkillStatus.DISABLED,
        actor_id=_payload_text(payload, "actor_id", "admin-ui"),
        actor_role=_role_from_payload(payload),
    )


@router.post("/domains/{domain_id}/skills:execute")
async def execute_skill(
    domain_id: str,
    payload: Annotated[dict[str, object], Body()],
    service: Annotated[SkillRegistryService, Depends(get_skill_service)],
    retrieval_service: Annotated[RetrievalService, Depends(get_retrieval_service)],
    document_service: Annotated[DocumentIngestService, Depends(get_document_service)],
    review_service: Annotated[ReviewReleaseService, Depends(get_review_service)],
) -> dict[str, object]:
    actor_id = _required_payload_text(payload, "actor_id")
    actor_role = _role_from_payload(payload)
    try:
        source_documents, source_chunks = _source_context(
            document_service=document_service,
            domain_id=domain_id,
        )
        retrieval_service.sync_active_release(
            domain_id=domain_id,
            source_documents=source_documents,
            source_chunks=source_chunks,
        )
        result = service.execute(
            domain_id=domain_id,
            query=_required_payload_text(payload, "query"),
            actor_id=actor_id,
            actor_role=actor_role,
            skill_id=_optional_payload_text(payload, "skill_id"),
            limit=_limit_from_payload(payload),
        )
    except NoActiveReleaseError as exc:
        raise HTTPException(status_code=404, detail="No active release for domain") from exc
    except ReleaseNotIndexedError as exc:
        raise HTTPException(status_code=409, detail="Active release is not indexed") from exc
    except SkillNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Skill not found") from exc
    except SkillRoutingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SkillPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    review_service.record_audit_event(
        domain_id=domain_id,
        actor_id=actor_id,
        action="skill.executed",
        target_type="skill",
        target_id=result.record.skill_id,
        metadata={
            "actor_role": actor_role.value,
            "skill_version": result.record.skill_version,
            "execution_id": result.record.id,
            "status": result.record.status.value,
            "release_id": result.record.release_id,
            "release_version": result.record.release_version,
            "citation_keys": list(result.record.citation_keys),
        },
    )
    return _execution_result_payload(result)


@router.get("/domains/{domain_id}/skills/execution-logs")
async def list_skill_execution_logs(
    domain_id: str,
    service: Annotated[SkillRegistryService, Depends(get_skill_service)],
    skill_id: Annotated[str | None, Query()] = None,
) -> dict[str, object]:
    return {
        "domain_id": domain_id,
        "records": [
            _execution_record_payload(record)
            for record in service.list_execution_records(domain_id=domain_id, skill_id=skill_id)
        ],
    }


def _set_skill_status(
    *,
    service: SkillRegistryService,
    review_service: ReviewReleaseService,
    domain_id: str,
    skill_id: str,
    status: SkillStatus,
    actor_id: str,
    actor_role: UserRole,
) -> dict[str, object]:
    try:
        skill = service.set_status(
            domain_id=domain_id,
            skill_id=skill_id,
            status=status,
            actor_role=actor_role,
        )
    except SkillNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Skill not found") from exc
    except SkillPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    review_service.record_audit_event(
        domain_id=domain_id,
        actor_id=actor_id,
        action=f"skill.{status.value}",
        target_type="skill",
        target_id=skill_id,
        metadata={
            "actor_role": actor_role.value,
            "skill_version": skill.version,
            "status": status.value,
        },
    )
    return _skill_payload(skill)


def _source_context(
    *,
    document_service: DocumentIngestService,
    domain_id: str,
) -> tuple[tuple[SourceDocument, ...], tuple[SourceChunk, ...]]:
    documents = document_service.list_documents(domain_id=domain_id)
    return (
        tuple(document.to_source_document() for document in documents),
        tuple(chunk for document in documents for chunk in document.chunks),
    )


def _skill_payload(skill: SkillDefinition) -> dict[str, object]:
    return {
        "id": skill.id,
        "name": skill.name,
        "description": skill.description,
        "version": skill.version,
        "status": skill.status.value,
        "scope": skill.scope.value,
        "minimum_role": skill.minimum_role.value,
        "server_allowed_tools": list(skill.server_allowed_tools),
        "supported_query_types": list(skill.supported_query_types),
        "domain_ids": list(skill.domain_ids),
        "checksum": skill.checksum,
        "source_path": skill.source_path,
        "test_cases_path": skill.test_cases_path,
        "metadata": skill.metadata,
    }


def _execution_result_payload(result: SkillExecutionResult) -> dict[str, object]:
    return {
        "record": _execution_record_payload(result.record),
        "answer": result.answer,
        "citations": [
            {
                "document_id": citation.document_id,
                "document_title": citation.document_title,
                "source_uri": citation.source_uri,
                "chunk_id": citation.chunk_id,
                "locator": citation.locator_reference,
                "parser_version": citation.parser_version,
                "snippet": citation.snippet,
            }
            for citation in result.citations
        ],
        "notice": "仅用于内部科研证据辅助，不作为诊疗建议。",
    }


def _execution_record_payload(record: SkillExecutionRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "domain_id": record.domain_id,
        "skill_id": record.skill_id,
        "skill_version": record.skill_version,
        "actor_id": record.actor_id,
        "actor_role": record.actor_role.value,
        "route_mode": record.route_mode.value,
        "query": record.query,
        "query_type": record.query_type,
        "status": record.status.value,
        "release_id": record.release_id,
        "release_version": record.release_version,
        "citation_keys": list(record.citation_keys),
        "error": record.error,
        "elapsed_ms": record.elapsed_ms,
        "created_at": record.created_at,
    }


def _role_from_payload(payload: dict[str, object]) -> UserRole:
    value = payload.get("actor_role")
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail="actor_role is required")
    try:
        return UserRole(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Unknown actor_role") from exc


def _required_payload_text(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(status_code=422, detail=f"{key} is required")
    return value


def _optional_payload_text(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail=f"{key} must be a string")
    return value or None


def _payload_text(payload: dict[str, object], key: str, default: str) -> str:
    value = payload.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(status_code=422, detail=f"{key} must be a string")
    return value.strip()


def _limit_from_payload(payload: dict[str, object]) -> int:
    value = payload.get("limit", 5)
    if isinstance(value, bool):
        raise HTTPException(status_code=422, detail="limit must be an integer")
    if isinstance(value, int):
        limit = value
    elif isinstance(value, str) and value.isdecimal():
        limit = int(value)
    else:
        raise HTTPException(status_code=422, detail="limit must be an integer")
    if limit < 1 or limit > 20:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 20")
    return limit
