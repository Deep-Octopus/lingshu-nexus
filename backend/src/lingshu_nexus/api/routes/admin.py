"""Management panel aggregate API routes."""

from __future__ import annotations

from collections import Counter
from typing import Annotated, cast

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request

from lingshu_domain import DEFAULT_DOMAIN_ID, ReviewStatus
from lingshu_nexus.config.settings import Settings, get_settings
from lingshu_nexus.documents import DocumentIngestService
from lingshu_nexus.observability import ObservabilityRecorder, observation_payload
from lingshu_nexus.persistence.models import AuditEvent, JobRun, JobStatus
from lingshu_nexus.review import ReviewReleaseService
from lingshu_nexus.review.models import ReleaseRecord
from lingshu_nexus.skills import (
    SkillDefinition,
    SkillExecutionStatus,
    SkillNotFoundError,
    SkillPackageValidationError,
    SkillPermissionError,
    SkillRegistryService,
    SkillStatus,
    UserRole,
)
from lingshu_nexus.sources import SourceSyncRun, SourceUpdateService

router = APIRouter(prefix="/api/v1", tags=["admin"])


def get_document_service(request: Request) -> DocumentIngestService:
    return cast(DocumentIngestService, request.app.state.document_service)


def get_review_service(request: Request) -> ReviewReleaseService:
    return cast(ReviewReleaseService, request.app.state.review_release_service)


def get_skill_service(request: Request) -> SkillRegistryService:
    return cast(SkillRegistryService, request.app.state.skill_registry_service)


def get_source_service(request: Request) -> SourceUpdateService:
    return cast(SourceUpdateService, request.app.state.source_update_service)


def get_observability(request: Request) -> ObservabilityRecorder:
    return cast(ObservabilityRecorder, request.app.state.observability)


@router.get("/admin/overview")
async def admin_overview(
    document_service: Annotated[DocumentIngestService, Depends(get_document_service)],
    review_service: Annotated[ReviewReleaseService, Depends(get_review_service)],
    skill_service: Annotated[SkillRegistryService, Depends(get_skill_service)],
    source_service: Annotated[SourceUpdateService, Depends(get_source_service)],
    observability: Annotated[ObservabilityRecorder, Depends(get_observability)],
    domain_id: Annotated[str, Query()] = DEFAULT_DOMAIN_ID,
) -> dict[str, object]:
    documents = document_service.list_documents(domain_id=domain_id)
    assertions = review_service.list_assertions(domain_id=domain_id)
    jobs = document_service.list_job_runs(domain_id=domain_id)
    skill_logs = skill_service.list_execution_records(domain_id=domain_id)
    source_runs = source_service.list_runs(domain_id=domain_id)
    active_release = review_service.active_release(domain_id=domain_id)
    observations = observability.list_events(domain_id=domain_id)
    return {
        "domain_id": domain_id,
        "documents_total": len(documents),
        "document_status_counts": dict(Counter(document.status.value for document in documents)),
        "pending_review_count": sum(
            assertion.review_status in {ReviewStatus.PENDING, ReviewStatus.NEEDS_REVISION}
            for assertion in assertions
        ),
        "review_status_counts": dict(
            Counter(assertion.review_status.value for assertion in assertions)
        ),
        "active_release": _release_summary(active_release),
        "failed_jobs_count": sum(job.status is JobStatus.FAILED for job in jobs),
        "source_sync_summary": {
            "sources_total": len(source_service.list_sources(domain_id=domain_id)),
            "runs_total": len(source_runs),
            "failed": sum(run.status is JobStatus.FAILED for run in source_runs),
            "duplicates_skipped": sum(run.duplicate_count for run in source_runs),
        },
        "skill_execution_summary": {
            "total": len(skill_logs),
            "failed": sum(log.status is SkillExecutionStatus.FAILED for log in skill_logs),
        },
        "model_usage_summary": {
            "records_available": False,
            "total_tokens": None,
            "estimated_cost": None,
            "note": "当前运行期未挂载模型用量仓库；不伪造调用成本。",
        },
        "observability_summary": {
            "events_total": len(observations),
            "failed": sum(event.status.value == "failed" for event in observations),
        },
    }


@router.get("/admin/jobs")
async def admin_jobs(
    document_service: Annotated[DocumentIngestService, Depends(get_document_service)],
    source_service: Annotated[SourceUpdateService, Depends(get_source_service)],
    domain_id: Annotated[str, Query()] = DEFAULT_DOMAIN_ID,
) -> dict[str, object]:
    jobs = document_service.list_job_runs(domain_id=domain_id)
    source_runs = source_service.list_runs(domain_id=domain_id)
    return {
        "domain_id": domain_id,
        "jobs": [_job_payload(job) for job in jobs]
        + [_source_run_as_job_payload(run) for run in source_runs],
        "source_connector": {
            "status": "ready",
            "message": "SourceConnector 已接入；真实外部 adapter 仍需接口样例。",
            "sources_total": len(source_service.list_sources(domain_id=domain_id)),
            "runs_total": len(source_runs),
            "failed_runs": sum(run.status is JobStatus.FAILED for run in source_runs),
        },
    }


@router.get("/admin/audit-events")
async def admin_audit_events(
    review_service: Annotated[ReviewReleaseService, Depends(get_review_service)],
    domain_id: Annotated[str, Query()] = DEFAULT_DOMAIN_ID,
) -> dict[str, object]:
    return {
        "domain_id": domain_id,
        "audit_events": [
            _audit_payload(event) for event in review_service.list_audit_events(domain_id=domain_id)
        ],
    }


@router.post("/admin/skills:upload")
async def admin_upload_skill(
    payload: Annotated[dict[str, object], Body()],
    skill_service: Annotated[SkillRegistryService, Depends(get_skill_service)],
    review_service: Annotated[ReviewReleaseService, Depends(get_review_service)],
) -> dict[str, object]:
    actor_id = _required_payload_text(payload, "actor_id")
    actor_role = _role_from_payload(payload)
    skill_id = _required_payload_text(payload, "skill_id")
    try:
        skill = skill_service.upload_skill_package(
            skill_id=skill_id,
            skill_md=_required_payload_text(payload, "skill_md"),
            registry_yaml=_required_payload_text(payload, "registry_yaml"),
            test_cases_yaml=_required_payload_text(payload, "test_cases_yaml"),
            actor_role=actor_role,
        )
    except SkillPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except SkillPackageValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    for domain_id in skill.domain_ids:
        review_service.record_audit_event(
            domain_id=domain_id,
            actor_id=actor_id,
            action="skill.uploaded",
            target_type="skill",
            target_id=skill.id,
            metadata={
                "skill_version": skill.version,
                "status": skill.status.value,
                "actor_role": actor_role.value,
            },
        )
    return _skill_payload(skill)


@router.post("/admin/skills/{skill_id}:enable")
async def admin_enable_skill(
    skill_id: str,
    payload: Annotated[dict[str, object], Body()],
    skill_service: Annotated[SkillRegistryService, Depends(get_skill_service)],
    review_service: Annotated[ReviewReleaseService, Depends(get_review_service)],
    domain_id: Annotated[str, Query()] = DEFAULT_DOMAIN_ID,
) -> dict[str, object]:
    return _set_admin_skill_status(
        domain_id=domain_id,
        skill_id=skill_id,
        status=SkillStatus.ACTIVE,
        payload=payload,
        skill_service=skill_service,
        review_service=review_service,
    )


@router.post("/admin/skills/{skill_id}:disable")
async def admin_disable_skill(
    skill_id: str,
    payload: Annotated[dict[str, object], Body()],
    skill_service: Annotated[SkillRegistryService, Depends(get_skill_service)],
    review_service: Annotated[ReviewReleaseService, Depends(get_review_service)],
    domain_id: Annotated[str, Query()] = DEFAULT_DOMAIN_ID,
) -> dict[str, object]:
    return _set_admin_skill_status(
        domain_id=domain_id,
        skill_id=skill_id,
        status=SkillStatus.DISABLED,
        payload=payload,
        skill_service=skill_service,
        review_service=review_service,
    )


def _set_admin_skill_status(
    *,
    domain_id: str,
    skill_id: str,
    status: SkillStatus,
    payload: dict[str, object],
    skill_service: SkillRegistryService,
    review_service: ReviewReleaseService,
) -> dict[str, object]:
    actor_id = _required_payload_text(payload, "actor_id")
    actor_role = _role_from_payload(payload)
    try:
        skill = skill_service.set_status(
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
            "skill_version": skill.version,
            "status": status.value,
            "actor_role": actor_role.value,
        },
    )
    return _skill_payload(skill)


def _release_summary(record: ReleaseRecord | None) -> dict[str, object] | None:
    if record is None:
        return None
    return {
        "id": record.release.id,
        "version": record.release.version,
        "assertion_count": len(record.assertions),
        "created_at": record.created_at,
    }


def _job_payload(job: JobRun) -> dict[str, object]:
    return {
        "id": job.id,
        "domain_id": job.domain_id,
        "job_type": job.job_type,
        "status": job.status.value,
        "input_ref": job.input_ref,
        "output_ref": job.output_ref,
        "error": job.error,
    }


def _source_run_as_job_payload(run: SourceSyncRun) -> dict[str, object]:
    return {
        "id": run.id,
        "domain_id": run.domain_id,
        "job_type": "source_sync",
        "status": run.status.value,
        "input_ref": f"source:{run.source_id}:attempt:{run.attempt}",
        "output_ref": ",".join(run.review_batch_ids) if run.review_batch_ids else None,
        "error": run.error,
    }


def _audit_payload(event: AuditEvent) -> dict[str, object]:
    return {
        "id": event.id,
        "domain_id": event.domain_id,
        "actor_id": event.actor_id,
        "action": event.action,
        "target_type": event.target_type,
        "target_id": event.target_id,
        "metadata": event.metadata,
        "created_at": event.created_at,
    }


@router.get("/admin/observability-events")
async def admin_observability_events(
    observability: Annotated[ObservabilityRecorder, Depends(get_observability)],
    domain_id: Annotated[str, Query()] = DEFAULT_DOMAIN_ID,
) -> dict[str, object]:
    return {
        "domain_id": domain_id,
        "events": [
            observation_payload(event) for event in observability.list_events(domain_id=domain_id)
        ],
    }


@router.get("/admin/config-status")
async def admin_config_status(
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    extraction_model = settings.mimo_extraction_model_id or settings.mimo_model_id
    return {
        "app": {
            "environment": settings.app_env,
            "default_domain_id": settings.default_domain_id,
        },
        "mimo": {
            "base_url_configured": bool(settings.mimo_base_url)
            and "example.invalid" not in settings.mimo_base_url,
            "api_key_configured": bool(settings.mimo_api_key)
            and not settings.mimo_api_key.startswith("replace-with"),
            "model_configured": bool(extraction_model)
            and not extraction_model.startswith("replace-with"),
            "model_id": None if extraction_model.startswith("replace-with") else extraction_model,
        },
        "storage": {
            "database_url_configured": bool(settings.database_url),
            "redis_url_configured": bool(settings.redis_url),
            "object_storage_configured": bool(settings.object_storage_local_path),
            "neo4j_uri_configured": bool(settings.neo4j_uri),
        },
        "secret_policy": (
            "Secrets are injected through environment or future secret references; "
            "API responses do not return secret values."
        ),
    }


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


def _required_payload_text(payload: dict[str, object], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(status_code=422, detail=f"{field_name} is required")
    return value.strip()


def _role_from_payload(payload: dict[str, object]) -> UserRole:
    raw_role = payload.get("actor_role", UserRole.READ_ONLY.value)
    try:
        return UserRole(str(raw_role))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="actor_role is invalid") from exc
