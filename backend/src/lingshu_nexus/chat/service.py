"""Chat session and Skill-backed answer service."""

from __future__ import annotations

from uuid import uuid4

from lingshu_domain.validation import require_domain_id, require_text
from lingshu_nexus.chat.models import (
    RESEARCH_NOTICE,
    ChatAnswerResult,
    ChatFeedback,
    ChatMessage,
    ChatRole,
    ChatSession,
    FeedbackRating,
)
from lingshu_nexus.chat.repository import ChatRepository
from lingshu_nexus.retrieval.models import SourceCitation
from lingshu_nexus.skills import SkillExecutionResult, SkillRegistryService, UserRole


class ChatWorkflowError(ValueError):
    """Raised when chat workflow input is invalid."""


class ChatService:
    def __init__(
        self,
        *,
        repository: ChatRepository,
        skill_registry: SkillRegistryService,
    ) -> None:
        self._repository = repository
        self._skill_registry = skill_registry

    def create_session(
        self,
        *,
        domain_id: str,
        created_by: str,
        title: str | None = None,
    ) -> ChatSession:
        require_domain_id(domain_id)
        require_text(created_by, "created_by")
        session = ChatSession(
            id=f"chat_{uuid4().hex}",
            domain_id=domain_id,
            title=title or "Evidence chat",
            created_by=created_by,
        )
        self._repository.add_session(session)
        return session

    def list_sessions(self, *, domain_id: str) -> tuple[ChatSession, ...]:
        return self._repository.list_sessions(domain_id=domain_id)

    def get_session(self, *, domain_id: str, session_id: str) -> ChatSession:
        return self._repository.get_session(domain_id=domain_id, session_id=session_id)

    def messages_for_session(self, *, domain_id: str, session_id: str) -> tuple[ChatMessage, ...]:
        return self._repository.messages_for_session(domain_id=domain_id, session_id=session_id)

    def answer(
        self,
        *,
        domain_id: str,
        session_id: str,
        query: str,
        actor_id: str,
        actor_role: UserRole,
        skill_id: str | None = None,
        limit: int = 5,
    ) -> ChatAnswerResult:
        session = self.get_session(domain_id=domain_id, session_id=session_id)
        require_text(query, "query")
        user_message = ChatMessage(
            id=f"msg_{uuid4().hex}",
            session_id=session.id,
            domain_id=domain_id,
            role=ChatRole.USER,
            content=query,
            actor_id=actor_id,
        )
        self._repository.add_message(user_message)
        skill_result = self._skill_registry.execute(
            domain_id=domain_id,
            query=query,
            actor_id=actor_id,
            actor_role=actor_role,
            skill_id=skill_id,
            limit=limit,
        )
        assistant_message = _assistant_message_from_result(
            session=session,
            actor_id="system",
            result=skill_result,
        )
        self._repository.add_message(assistant_message)
        citations = tuple(_citation_payload(citation) for citation in skill_result.citations)
        limitations = _limitations(citations)
        return ChatAnswerResult(
            user_message=user_message,
            assistant_message=assistant_message,
            answer=skill_result.answer,
            citations=citations,
            skill={
                "id": skill_result.record.skill_id,
                "version": skill_result.record.skill_version,
            },
            release={
                "id": skill_result.record.release_id,
                "version": skill_result.record.release_version,
            },
            limitations=limitations,
            notice=RESEARCH_NOTICE,
        )

    def submit_feedback(
        self,
        *,
        domain_id: str,
        session_id: str,
        message_id: str,
        actor_id: str,
        rating: FeedbackRating,
        note: str | None = None,
    ) -> ChatFeedback:
        session = self.get_session(domain_id=domain_id, session_id=session_id)
        message = self._repository.get_message(domain_id=domain_id, message_id=message_id)
        if message.session_id != session.id:
            raise ChatWorkflowError("message does not belong to session")
        if message.role is not ChatRole.ASSISTANT:
            raise ChatWorkflowError("feedback can only target assistant messages")
        feedback = ChatFeedback(
            id=f"feedback_{uuid4().hex}",
            session_id=session_id,
            message_id=message_id,
            domain_id=domain_id,
            actor_id=actor_id,
            rating=rating,
            note=note,
        )
        self._repository.add_feedback(feedback)
        return feedback


def _assistant_message_from_result(
    *,
    session: ChatSession,
    actor_id: str,
    result: SkillExecutionResult,
) -> ChatMessage:
    return ChatMessage(
        id=f"msg_{uuid4().hex}",
        session_id=session.id,
        domain_id=session.domain_id,
        role=ChatRole.ASSISTANT,
        content=result.answer,
        actor_id=actor_id,
        skill_id=result.record.skill_id,
        skill_version=result.record.skill_version,
        release_id=result.record.release_id,
        release_version=result.record.release_version,
        citation_keys=result.record.citation_keys,
        metadata={"skill_execution_id": result.record.id},
    )


def _citation_payload(citation: SourceCitation) -> dict[str, str | None]:
    return {
        "document_id": citation.document_id,
        "document_title": citation.document_title,
        "source_uri": citation.source_uri,
        "chunk_id": citation.chunk_id,
        "locator": citation.locator_reference,
        "parser_version": citation.parser_version,
        "snippet": citation.snippet,
    }


def _limitations(citations: tuple[dict[str, str | None], ...]) -> tuple[str, ...]:
    base = ["当前检索范围仅覆盖已审核并发布的 active release。"]
    if not citations:
        base.append("未检索到可引用证据，不能据此形成医学结论。")
    return tuple(base)


def chunk_text(text: str, *, chunk_size: int = 80) -> tuple[str, ...]:
    if chunk_size < 1:
        raise ValueError("chunk_size must be >= 1")
    chunks: list[str] = []
    for line in text.splitlines(keepends=True):
        if not line:
            continue
        start = 0
        while start < len(line):
            chunks.append(line[start : start + chunk_size])
            start += chunk_size
    return tuple(chunks or (text,))
