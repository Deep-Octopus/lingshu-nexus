"""Chat session, message, feedback, and stream event models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from lingshu_domain.validation import SchemaValidationError, require_domain_id, require_text
from lingshu_nexus.review.models import utcnow

RESEARCH_NOTICE = "仅用于内部科研证据辅助，不作为诊疗建议。"


class ChatRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class ChatStreamEventType(StrEnum):
    RETRIEVAL = "retrieval"
    TEXT = "text"
    CITATION = "citation"
    DONE = "done"
    ERROR = "error"


class FeedbackRating(StrEnum):
    HELPFUL = "helpful"
    NOT_HELPFUL = "not_helpful"
    CORRECTION = "correction"


@dataclass(frozen=True)
class ChatSession:
    id: str
    domain_id: str
    title: str
    created_by: str
    created_at: str = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        require_text(self.id, "ChatSession.id")
        require_domain_id(self.domain_id)
        require_text(self.title, "ChatSession.title")
        require_text(self.created_by, "ChatSession.created_by")


@dataclass(frozen=True)
class ChatMessage:
    id: str
    session_id: str
    domain_id: str
    role: ChatRole
    content: str
    actor_id: str
    skill_id: str | None = None
    skill_version: str | None = None
    release_id: str | None = None
    release_version: str | None = None
    citation_keys: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        require_text(self.id, "ChatMessage.id")
        require_text(self.session_id, "ChatMessage.session_id")
        require_domain_id(self.domain_id)
        require_text(self.content, "ChatMessage.content")
        require_text(self.actor_id, "ChatMessage.actor_id")


@dataclass(frozen=True)
class ChatFeedback:
    id: str
    session_id: str
    message_id: str
    domain_id: str
    actor_id: str
    rating: FeedbackRating
    note: str | None = None
    created_at: str = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        require_text(self.id, "ChatFeedback.id")
        require_text(self.session_id, "ChatFeedback.session_id")
        require_text(self.message_id, "ChatFeedback.message_id")
        require_domain_id(self.domain_id)
        require_text(self.actor_id, "ChatFeedback.actor_id")


@dataclass(frozen=True)
class ChatStreamEvent:
    type: ChatStreamEventType
    payload: dict[str, Any]

    def __post_init__(self) -> None:
        if not self.payload:
            raise SchemaValidationError("ChatStreamEvent.payload must not be empty")


@dataclass(frozen=True)
class ChatAnswerResult:
    user_message: ChatMessage
    assistant_message: ChatMessage
    answer: str
    citations: tuple[dict[str, Any], ...]
    skill: dict[str, str]
    release: dict[str, str | None]
    limitations: tuple[str, ...]
    notice: str = RESEARCH_NOTICE

    def __post_init__(self) -> None:
        require_text(self.answer, "ChatAnswerResult.answer")
