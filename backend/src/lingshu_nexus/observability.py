"""Minimal structured observability for V1 services."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, cast
from uuid import uuid4

from lingshu_domain.validation import require_text
from lingshu_nexus.persistence.models import utcnow


class ObservationStatus(StrEnum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class StructuredObservation:
    id: str
    event_type: str
    status: ObservationStatus
    domain_id: str | None = None
    actor_id: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    trace_id: str | None = None
    release_id: str | None = None
    config_versions: tuple[str, ...] = ()
    metrics: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    created_at: str = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        require_text(self.id, "StructuredObservation.id")
        require_text(self.event_type, "StructuredObservation.event_type")


class ObservabilityRecorder:
    """Record sanitized JSON events in memory and through the standard logger."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._events: list[StructuredObservation] = []
        self._logger = logger or logging.getLogger("lingshu_nexus.observability")

    def record(
        self,
        *,
        event_type: str,
        status: ObservationStatus,
        domain_id: str | None = None,
        actor_id: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        trace_id: str | None = None,
        release_id: str | None = None,
        config_versions: tuple[str, ...] = (),
        metrics: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> StructuredObservation:
        event = StructuredObservation(
            id=f"obs_{uuid4().hex}",
            event_type=event_type,
            status=status,
            domain_id=domain_id,
            actor_id=actor_id,
            target_type=target_type,
            target_id=target_id,
            trace_id=trace_id,
            release_id=release_id,
            config_versions=config_versions,
            metrics=cast(dict[str, Any], sanitize_for_logging(metrics or {})),
            metadata=cast(dict[str, Any], sanitize_for_logging(metadata or {})),
            error=_short_text(error) if error else None,
        )
        self._events.append(event)
        self._logger.info(
            json.dumps(observation_payload(event), ensure_ascii=False, sort_keys=True)
        )
        return event

    def list_events(self, *, domain_id: str | None = None) -> tuple[StructuredObservation, ...]:
        if domain_id is None:
            return tuple(self._events)
        return tuple(event for event in self._events if event.domain_id == domain_id)


def observation_payload(event: StructuredObservation) -> dict[str, Any]:
    return {
        "id": event.id,
        "event_type": event.event_type,
        "status": event.status.value,
        "domain_id": event.domain_id,
        "actor_id": event.actor_id,
        "target_type": event.target_type,
        "target_id": event.target_id,
        "trace_id": event.trace_id,
        "release_id": event.release_id,
        "config_versions": list(event.config_versions),
        "metrics": event.metrics,
        "metadata": event.metadata,
        "error": event.error,
        "created_at": event.created_at,
    }


def mask_sensitive_config(value: object) -> object:
    return sanitize_for_logging(value)


def sanitize_for_logging(value: object) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, nested in value.items():
            key_text = str(key)
            if _is_sensitive_key(key_text):
                sanitized[key_text] = "***redacted***"
            else:
                sanitized[key_text] = sanitize_for_logging(nested)
        return sanitized
    if isinstance(value, (list, tuple)):
        return [sanitize_for_logging(item) for item in value]
    if isinstance(value, str):
        if _looks_like_secret_reference(value):
            return "***configured***"
        return _short_text(value)
    return value


def _is_sensitive_key(key: str) -> bool:
    lower = key.lower()
    return any(part in lower for part in ("api_key", "apikey", "token", "password", "secret"))


def _looks_like_secret_reference(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered.startswith(("env:", "secret:", "vault:", "aws-sm:", "gcp-sm:"))


def _short_text(value: str, *, limit: int = 500) -> str:
    compact = value.replace("\n", "\\n")
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit]}..."
