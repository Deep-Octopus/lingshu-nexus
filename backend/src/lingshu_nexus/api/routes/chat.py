"""Chat sessions and SSE answer API routes."""

from __future__ import annotations

import json
from collections.abc import Iterator
from hashlib import sha256
from typing import Annotated, cast

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from lingshu_domain import DEFAULT_DOMAIN_ID, SourceChunk, SourceDocument
from lingshu_nexus.chat import (
    RESEARCH_NOTICE,
    ChatAnswerResult,
    ChatFeedback,
    ChatMessage,
    ChatMessageNotFoundError,
    ChatService,
    ChatSession,
    ChatSessionNotFoundError,
    ChatStreamEvent,
    ChatStreamEventType,
    ChatWorkflowError,
    FeedbackRating,
    chunk_text,
)
from lingshu_nexus.documents import DocumentIngestService
from lingshu_nexus.observability import ObservabilityRecorder, ObservationStatus
from lingshu_nexus.retrieval import NoActiveReleaseError, ReleaseNotIndexedError, RetrievalService
from lingshu_nexus.review import ReviewReleaseService
from lingshu_nexus.skills import (
    SkillNotFoundError,
    SkillPermissionError,
    SkillRoutingError,
    UserRole,
)

router = APIRouter(prefix="/api/v1", tags=["chat"])


def get_chat_service(request: Request) -> ChatService:
    return cast(ChatService, request.app.state.chat_service)


def get_retrieval_service(request: Request) -> RetrievalService:
    return cast(RetrievalService, request.app.state.retrieval_service)


def get_document_service(request: Request) -> DocumentIngestService:
    return cast(DocumentIngestService, request.app.state.document_service)


def get_review_service(request: Request) -> ReviewReleaseService:
    return cast(ReviewReleaseService, request.app.state.review_release_service)


def get_observability(request: Request) -> ObservabilityRecorder:
    return cast(ObservabilityRecorder, request.app.state.observability)


@router.post("/chat/sessions")
async def create_chat_session(
    payload: Annotated[dict[str, object], Body()],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> dict[str, object]:
    session = service.create_session(
        domain_id=_payload_text(payload, "domain_id", DEFAULT_DOMAIN_ID),
        created_by=_required_payload_text(payload, "actor_id"),
        title=_optional_payload_text(payload, "title"),
    )
    return _session_payload(session)


@router.get("/chat/sessions")
async def list_chat_sessions(
    service: Annotated[ChatService, Depends(get_chat_service)],
    domain_id: Annotated[str, Query()] = DEFAULT_DOMAIN_ID,
) -> dict[str, object]:
    return {
        "domain_id": domain_id,
        "sessions": [
            _session_payload(session) for session in service.list_sessions(domain_id=domain_id)
        ],
    }


@router.get("/chat/sessions/{session_id}/messages")
async def list_chat_messages(
    session_id: str,
    service: Annotated[ChatService, Depends(get_chat_service)],
    domain_id: Annotated[str, Query()] = DEFAULT_DOMAIN_ID,
) -> dict[str, object]:
    try:
        messages = service.messages_for_session(domain_id=domain_id, session_id=session_id)
    except ChatSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Chat session not found") from exc
    return {
        "domain_id": domain_id,
        "session_id": session_id,
        "messages": [_message_payload(message) for message in messages],
    }


@router.post("/chat/sessions/{session_id}/messages:stream")
async def stream_chat_message(
    session_id: str,
    payload: Annotated[dict[str, object], Body()],
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
    retrieval_service: Annotated[RetrievalService, Depends(get_retrieval_service)],
    document_service: Annotated[DocumentIngestService, Depends(get_document_service)],
    review_service: Annotated[ReviewReleaseService, Depends(get_review_service)],
    observability: Annotated[ObservabilityRecorder, Depends(get_observability)],
    domain_id: Annotated[str, Query()] = DEFAULT_DOMAIN_ID,
) -> StreamingResponse:
    query = _required_payload_text(payload, "query")
    actor_id = _required_payload_text(payload, "actor_id")
    actor_role = _role_from_payload(payload)
    skill_id = _optional_payload_text(payload, "skill_id")
    limit = _limit_from_payload(payload)

    def event_stream() -> Iterator[str]:
        yield _sse(
            ChatStreamEvent(
                type=ChatStreamEventType.RETRIEVAL,
                payload={
                    "stage": "started",
                    "message": "Checking active release and published evidence index.",
                    "notice": RESEARCH_NOTICE,
                },
            )
        )
        try:
            source_documents, source_chunks = _source_context(
                document_service=document_service,
                domain_id=domain_id,
            )
            release = retrieval_service.sync_active_release(
                domain_id=domain_id,
                source_documents=source_documents,
                source_chunks=source_chunks,
            )
            yield _sse(
                ChatStreamEvent(
                    type=ChatStreamEventType.RETRIEVAL,
                    payload={
                        "stage": "active_release_indexed",
                        "release_id": release.id,
                        "release_version": release.version,
                    },
                )
            )
            result = chat_service.answer(
                domain_id=domain_id,
                session_id=session_id,
                query=query,
                actor_id=actor_id,
                actor_role=actor_role,
                skill_id=skill_id,
                limit=limit,
            )
        except NoActiveReleaseError:
            _record_chat_failure(
                review_service=review_service,
                observability=observability,
                domain_id=domain_id,
                session_id=session_id,
                actor_id=actor_id,
                actor_role=actor_role,
                query=query,
                code="no_active_release",
                message="当前领域没有 active release，无法回答。",
            )
            yield _error_event("no_active_release", "当前领域没有 active release，无法回答。")
            return
        except ReleaseNotIndexedError:
            _record_chat_failure(
                review_service=review_service,
                observability=observability,
                domain_id=domain_id,
                session_id=session_id,
                actor_id=actor_id,
                actor_role=actor_role,
                query=query,
                code="release_not_indexed",
                message="active release 尚未建立检索索引。",
            )
            yield _error_event("release_not_indexed", "active release 尚未建立检索索引。")
            return
        except ChatSessionNotFoundError:
            _record_chat_failure(
                review_service=review_service,
                observability=observability,
                domain_id=domain_id,
                session_id=session_id,
                actor_id=actor_id,
                actor_role=actor_role,
                query=query,
                code="session_not_found",
                message="Chat session not found.",
            )
            yield _error_event("session_not_found", "Chat session not found.")
            return
        except SkillNotFoundError:
            _record_chat_failure(
                review_service=review_service,
                observability=observability,
                domain_id=domain_id,
                session_id=session_id,
                actor_id=actor_id,
                actor_role=actor_role,
                query=query,
                code="skill_not_found",
                message="指定 Skill 不存在或不属于当前领域。",
            )
            yield _error_event("skill_not_found", "指定 Skill 不存在或不属于当前领域。")
            return
        except SkillRoutingError as exc:
            _record_chat_failure(
                review_service=review_service,
                observability=observability,
                domain_id=domain_id,
                session_id=session_id,
                actor_id=actor_id,
                actor_role=actor_role,
                query=query,
                code="skill_routing_failed",
                message=str(exc),
            )
            yield _error_event("skill_routing_failed", str(exc))
            return
        except SkillPermissionError as exc:
            _record_chat_failure(
                review_service=review_service,
                observability=observability,
                domain_id=domain_id,
                session_id=session_id,
                actor_id=actor_id,
                actor_role=actor_role,
                query=query,
                code="skill_forbidden",
                message=str(exc),
            )
            yield _error_event("skill_forbidden", str(exc))
            return

        _record_chat_success(
            review_service=review_service,
            observability=observability,
            domain_id=domain_id,
            session_id=session_id,
            actor_id=actor_id,
            actor_role=actor_role,
            query=query,
            result=result,
        )
        for delta in chunk_text(result.answer):
            yield _sse(ChatStreamEvent(type=ChatStreamEventType.TEXT, payload={"delta": delta}))
        for citation in result.citations:
            yield _sse(ChatStreamEvent(type=ChatStreamEventType.CITATION, payload=citation))
        yield _sse(
            ChatStreamEvent(
                type=ChatStreamEventType.DONE,
                payload=_done_payload(result),
            )
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/chat/sessions/{session_id}/messages/{message_id}:feedback")
async def submit_chat_feedback(
    session_id: str,
    message_id: str,
    payload: Annotated[dict[str, object], Body()],
    service: Annotated[ChatService, Depends(get_chat_service)],
    review_service: Annotated[ReviewReleaseService, Depends(get_review_service)],
    domain_id: Annotated[str, Query()] = DEFAULT_DOMAIN_ID,
) -> dict[str, object]:
    actor_id = _required_payload_text(payload, "actor_id")
    try:
        feedback = service.submit_feedback(
            domain_id=domain_id,
            session_id=session_id,
            message_id=message_id,
            actor_id=actor_id,
            rating=_rating_from_payload(payload),
            note=_optional_payload_text(payload, "note"),
        )
    except (ChatSessionNotFoundError, ChatMessageNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Chat message not found") from exc
    except ChatWorkflowError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    review_service.record_audit_event(
        domain_id=domain_id,
        actor_id=actor_id,
        action="chat.feedback_submitted",
        target_type="chat_message",
        target_id=message_id,
        metadata={
            "session_id": session_id,
            "rating": feedback.rating.value,
            "note_present": feedback.note is not None,
        },
    )
    return _feedback_payload(feedback)


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


def _sse(event: ChatStreamEvent) -> str:
    return (
        f"event: {event.type.value}\n"
        f"data: {json.dumps(event.payload, ensure_ascii=False, sort_keys=True)}\n\n"
    )


def _error_event(code: str, message: str) -> str:
    return _sse(
        ChatStreamEvent(
            type=ChatStreamEventType.ERROR,
            payload={
                "code": code,
                "message": message,
                "notice": RESEARCH_NOTICE,
            },
        )
    )


def _done_payload(result: ChatAnswerResult) -> dict[str, object]:
    return {
        "conversation_id": result.assistant_message.session_id,
        "message_id": result.assistant_message.id,
        "skill": result.skill,
        "graph_release": result.release,
        "citations": result.citations,
        "limitations": list(result.limitations),
        "trace_id": result.assistant_message.metadata.get("skill_execution_id"),
        "notice": result.notice,
    }


def _record_chat_success(
    *,
    review_service: ReviewReleaseService,
    observability: ObservabilityRecorder,
    domain_id: str,
    session_id: str,
    actor_id: str,
    actor_role: UserRole,
    query: str,
    result: ChatAnswerResult,
) -> None:
    release = result.release
    skill = result.skill
    citation_keys = result.assistant_message.citation_keys
    skill_execution_id = result.assistant_message.metadata.get("skill_execution_id")
    review_service.record_audit_event(
        domain_id=domain_id,
        actor_id=actor_id,
        action="chat.answer_completed",
        target_type="chat_session",
        target_id=session_id,
        metadata={
            "actor_role": actor_role.value,
            "user_message_id": result.user_message.id,
            "assistant_message_id": result.assistant_message.id,
            "skill_execution_id": skill_execution_id,
            "skill_id": skill.get("id"),
            "skill_version": skill.get("version"),
            "release_id": release.get("id"),
            "release_version": release.get("version"),
            "citation_keys": list(citation_keys),
            "query_sha256": _query_hash(query),
            "query_length": len(query),
        },
    )
    observability.record(
        event_type="chat.answer",
        status=ObservationStatus.SUCCEEDED,
        domain_id=domain_id,
        actor_id=actor_id,
        target_type="chat_session",
        target_id=session_id,
        trace_id=str(skill_execution_id) if skill_execution_id else None,
        release_id=str(release.get("id")) if release.get("id") else None,
        metrics={
            "query_length": len(query),
            "answer_length": len(result.answer),
            "citation_count": len(result.citations),
        },
        metadata={
            "actor_role": actor_role.value,
            "skill_id": skill.get("id"),
            "skill_version": skill.get("version"),
            "release_version": release.get("version"),
        },
    )


def _record_chat_failure(
    *,
    review_service: ReviewReleaseService,
    observability: ObservabilityRecorder,
    domain_id: str,
    session_id: str,
    actor_id: str,
    actor_role: UserRole,
    query: str,
    code: str,
    message: str,
) -> None:
    metadata = {
        "actor_role": actor_role.value,
        "error_code": code,
        "query_sha256": _query_hash(query),
        "query_length": len(query),
    }
    review_service.record_audit_event(
        domain_id=domain_id,
        actor_id=actor_id,
        action="chat.answer_failed",
        target_type="chat_session",
        target_id=session_id,
        metadata=metadata,
    )
    observability.record(
        event_type="chat.answer",
        status=ObservationStatus.FAILED,
        domain_id=domain_id,
        actor_id=actor_id,
        target_type="chat_session",
        target_id=session_id,
        metrics={"query_length": len(query)},
        metadata=metadata,
        error=message,
    )


def _query_hash(query: str) -> str:
    return sha256(query.encode("utf-8")).hexdigest()


def _session_payload(session: ChatSession) -> dict[str, object]:
    return {
        "id": session.id,
        "domain_id": session.domain_id,
        "title": session.title,
        "created_by": session.created_by,
        "created_at": session.created_at,
    }


def _message_payload(message: ChatMessage) -> dict[str, object]:
    return {
        "id": message.id,
        "session_id": message.session_id,
        "domain_id": message.domain_id,
        "role": message.role.value,
        "content": message.content,
        "actor_id": message.actor_id,
        "skill_id": message.skill_id,
        "skill_version": message.skill_version,
        "release_id": message.release_id,
        "release_version": message.release_version,
        "citation_keys": list(message.citation_keys),
        "metadata": message.metadata,
        "created_at": message.created_at,
    }


def _feedback_payload(feedback: ChatFeedback) -> dict[str, object]:
    return {
        "id": feedback.id,
        "session_id": feedback.session_id,
        "message_id": feedback.message_id,
        "domain_id": feedback.domain_id,
        "actor_id": feedback.actor_id,
        "rating": feedback.rating.value,
        "note": feedback.note,
        "created_at": feedback.created_at,
    }


def _role_from_payload(payload: dict[str, object]) -> UserRole:
    value = payload.get("actor_role")
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail="actor_role is required")
    try:
        return UserRole(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Unknown actor_role") from exc


def _rating_from_payload(payload: dict[str, object]) -> FeedbackRating:
    value = payload.get("rating")
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail="rating is required")
    try:
        return FeedbackRating(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Unknown rating") from exc


def _required_payload_text(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(status_code=422, detail=f"{key} is required")
    return value


def _payload_text(payload: dict[str, object], key: str, default: str) -> str:
    value = payload.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(status_code=422, detail=f"{key} must be a string")
    return value


def _optional_payload_text(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail=f"{key} must be a string")
    return value or None


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
