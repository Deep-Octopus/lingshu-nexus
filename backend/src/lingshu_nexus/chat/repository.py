"""Chat repository port and in-memory adapter."""

from __future__ import annotations

from typing import Protocol

from lingshu_domain.validation import require_domain_id, require_text
from lingshu_nexus.chat.models import ChatFeedback, ChatMessage, ChatSession


class ChatSessionNotFoundError(KeyError):
    """Raised when a chat session is unknown."""


class ChatMessageNotFoundError(KeyError):
    """Raised when a chat message is unknown."""


class ChatRepository(Protocol):
    def add_session(self, session: ChatSession) -> None:
        """Persist a new chat session."""

    def get_session(self, *, domain_id: str, session_id: str) -> ChatSession:
        """Return one chat session."""

    def list_sessions(self, *, domain_id: str) -> tuple[ChatSession, ...]:
        """Return chat sessions for one domain."""

    def add_message(self, message: ChatMessage) -> None:
        """Append one chat message."""

    def get_message(self, *, domain_id: str, message_id: str) -> ChatMessage:
        """Return one chat message."""

    def messages_for_session(self, *, domain_id: str, session_id: str) -> tuple[ChatMessage, ...]:
        """Return messages in one session."""

    def add_feedback(self, feedback: ChatFeedback) -> None:
        """Persist feedback for one assistant message."""

    def feedback_for_message(self, *, domain_id: str, message_id: str) -> tuple[ChatFeedback, ...]:
        """Return feedback for one message."""


class InMemoryChatRepository:
    def __init__(self) -> None:
        self._sessions: dict[tuple[str, str], ChatSession] = {}
        self._messages: dict[tuple[str, str], ChatMessage] = {}
        self._messages_by_session: dict[tuple[str, str], list[str]] = {}
        self._feedback: list[ChatFeedback] = []

    def add_session(self, session: ChatSession) -> None:
        identity = (session.domain_id, session.id)
        if identity in self._sessions:
            raise ValueError(f"Chat session already exists: {identity}")
        self._sessions[identity] = session
        self._messages_by_session[identity] = []

    def get_session(self, *, domain_id: str, session_id: str) -> ChatSession:
        require_domain_id(domain_id)
        require_text(session_id, "session_id")
        try:
            return self._sessions[(domain_id, session_id)]
        except KeyError as exc:
            raise ChatSessionNotFoundError(session_id) from exc

    def list_sessions(self, *, domain_id: str) -> tuple[ChatSession, ...]:
        require_domain_id(domain_id)
        return tuple(
            sorted(
                (
                    session
                    for (session_domain_id, _), session in self._sessions.items()
                    if session_domain_id == domain_id
                ),
                key=lambda session: session.created_at,
            )
        )

    def add_message(self, message: ChatMessage) -> None:
        self.get_session(domain_id=message.domain_id, session_id=message.session_id)
        identity = (message.domain_id, message.id)
        if identity in self._messages:
            raise ValueError(f"Chat message already exists: {identity}")
        self._messages[identity] = message
        self._messages_by_session[(message.domain_id, message.session_id)].append(message.id)

    def get_message(self, *, domain_id: str, message_id: str) -> ChatMessage:
        require_domain_id(domain_id)
        require_text(message_id, "message_id")
        try:
            return self._messages[(domain_id, message_id)]
        except KeyError as exc:
            raise ChatMessageNotFoundError(message_id) from exc

    def messages_for_session(self, *, domain_id: str, session_id: str) -> tuple[ChatMessage, ...]:
        self.get_session(domain_id=domain_id, session_id=session_id)
        message_ids = self._messages_by_session.get((domain_id, session_id), [])
        return tuple(self._messages[(domain_id, message_id)] for message_id in message_ids)

    def add_feedback(self, feedback: ChatFeedback) -> None:
        message = self.get_message(domain_id=feedback.domain_id, message_id=feedback.message_id)
        if message.session_id != feedback.session_id:
            raise ChatMessageNotFoundError(feedback.message_id)
        self._feedback.append(feedback)

    def feedback_for_message(self, *, domain_id: str, message_id: str) -> tuple[ChatFeedback, ...]:
        require_domain_id(domain_id)
        require_text(message_id, "message_id")
        return tuple(
            feedback
            for feedback in self._feedback
            if feedback.domain_id == domain_id and feedback.message_id == message_id
        )
