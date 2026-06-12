"""Chat services and models."""

from lingshu_nexus.chat.models import (
    RESEARCH_NOTICE,
    ChatAnswerResult,
    ChatFeedback,
    ChatMessage,
    ChatRole,
    ChatSession,
    ChatStreamEvent,
    ChatStreamEventType,
    FeedbackRating,
)
from lingshu_nexus.chat.repository import (
    ChatMessageNotFoundError,
    ChatRepository,
    ChatSessionNotFoundError,
    InMemoryChatRepository,
)
from lingshu_nexus.chat.service import ChatService, ChatWorkflowError, chunk_text
from lingshu_nexus.skills import SkillRegistryService


def create_chat_service(*, skill_registry: SkillRegistryService) -> ChatService:
    return ChatService(
        repository=InMemoryChatRepository(),
        skill_registry=skill_registry,
    )


__all__ = [
    "ChatAnswerResult",
    "ChatFeedback",
    "ChatMessage",
    "ChatMessageNotFoundError",
    "ChatRepository",
    "ChatRole",
    "ChatService",
    "ChatSession",
    "ChatSessionNotFoundError",
    "ChatStreamEvent",
    "ChatStreamEventType",
    "ChatWorkflowError",
    "FeedbackRating",
    "InMemoryChatRepository",
    "RESEARCH_NOTICE",
    "chunk_text",
    "create_chat_service",
]
