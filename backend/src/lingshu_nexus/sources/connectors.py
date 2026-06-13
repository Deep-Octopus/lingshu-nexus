"""SourceConnector port and generic adapters."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4

import httpx

from lingshu_domain.validation import require_domain_id
from lingshu_nexus.sources.models import (
    SourceArtifact,
    SourceArtifactKind,
    SourceConnectorConfig,
)


class SourceConnectorError(RuntimeError):
    """Raised when a SourceConnector cannot fetch artifacts."""


@dataclass(frozen=True)
class SourceFetchRequest:
    domain_id: str
    window_start: str | None = None
    window_end: str | None = None
    cursor: str | None = None

    def __post_init__(self) -> None:
        require_domain_id(self.domain_id)


@dataclass(frozen=True)
class SourceFetchResult:
    artifacts: tuple[SourceArtifact, ...]
    raw_response: bytes | None = None
    raw_media_type: str | None = None


class SourceConnector(Protocol):
    def fetch(
        self,
        *,
        config: SourceConnectorConfig,
        request: SourceFetchRequest,
    ) -> SourceFetchResult:
        """Fetch new raw artifacts without writing published knowledge."""


class FixtureSourceConnector:
    """Deterministic connector for contract tests and offline fixtures."""

    def fetch(
        self,
        *,
        config: SourceConnectorConfig,
        request: SourceFetchRequest,
    ) -> SourceFetchResult:
        raw_artifacts = config.config.get("artifacts", [])
        if not isinstance(raw_artifacts, list):
            raise SourceConnectorError("fixture config.artifacts must be a list")
        artifacts = tuple(
            artifact_from_mapping(
                item,
                domain_id=request.domain_id,
                source_id=config.id,
                fallback_index=index,
            )
            for index, item in enumerate(raw_artifacts)
        )
        raw_response = json.dumps(
            {"artifacts": raw_artifacts},
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
        return SourceFetchResult(
            artifacts=artifacts,
            raw_response=raw_response,
            raw_media_type="application/json",
        )


class GenericRestSourceConnector:
    """Configurable REST adapter that preserves raw responses before mapping."""

    def __init__(self, *, timeout_seconds: float = 30) -> None:
        self._timeout_seconds = timeout_seconds

    def fetch(
        self,
        *,
        config: SourceConnectorConfig,
        request: SourceFetchRequest,
    ) -> SourceFetchResult:
        base_url = _required_config_text(config.config, "base_url").rstrip("/")
        path = str(config.config.get("path", ""))
        method = str(config.config.get("method", "GET")).upper()
        response_mode = str(config.config.get("response_mode", "json"))
        if method not in {"GET", "POST"}:
            raise SourceConnectorError("generic_rest method must be GET or POST")
        url = f"{base_url}{path}"
        params = _dict_or_empty(config.config.get("params"))
        if request.window_start:
            params.setdefault("window_start", request.window_start)
        if request.window_end:
            params.setdefault("window_end", request.window_end)
        if request.cursor:
            params.setdefault("cursor", request.cursor)
        body = _dict_or_empty(config.config.get("body"))
        try:
            with httpx.Client(timeout=self._timeout_seconds) as client:
                response = client.request(method, url, params=params, json=body or None)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SourceConnectorError(f"generic_rest request failed: {exc}") from exc

        content_type = response.headers.get("content-type", "application/octet-stream")
        if response_mode == "file":
            artifact = SourceArtifact(
                id=f"artifact_{uuid4().hex}",
                domain_id=request.domain_id,
                source_id=config.id,
                kind=SourceArtifactKind.FILE,
                filename=str(config.config.get("filename") or "downloaded-artifact.bin"),
                media_type=content_type.split(";", maxsplit=1)[0],
                content=response.content,
                source_uri=str(response.url),
                metadata={"adapter": "generic_rest", "status_code": response.status_code},
            )
            return SourceFetchResult(
                artifacts=(artifact,),
                raw_response=response.content,
                raw_media_type=content_type,
            )
        if response_mode == "download_reference":
            payload = response.json()
            source_uri = _required_payload_text(payload, "source_uri")
            artifact = SourceArtifact(
                id=f"artifact_{uuid4().hex}",
                domain_id=request.domain_id,
                source_id=config.id,
                kind=SourceArtifactKind.DOWNLOAD_REFERENCE,
                external_id=_optional_payload_text(payload, "external_id"),
                source_uri=source_uri,
                metadata={"adapter": "generic_rest", "status_code": response.status_code},
            )
            return SourceFetchResult(
                artifacts=(artifact,),
                raw_response=response.content,
                raw_media_type=content_type,
            )
        if response_mode != "json":
            raise SourceConnectorError(
                "generic_rest response_mode must be json, file, or download_reference"
            )
        payload = response.json()
        raw_items = _json_artifact_items(payload)
        artifacts = tuple(
            artifact_from_mapping(
                item,
                domain_id=request.domain_id,
                source_id=config.id,
                fallback_index=index,
            )
            for index, item in enumerate(raw_items)
        )
        return SourceFetchResult(
            artifacts=artifacts,
            raw_response=response.content,
            raw_media_type=content_type,
        )


def artifact_from_mapping(
    item: object,
    *,
    domain_id: str,
    source_id: str,
    fallback_index: int,
) -> SourceArtifact:
    if not isinstance(item, dict):
        raise SourceConnectorError("source artifact mapping must be an object")
    kind = SourceArtifactKind(str(item.get("kind", SourceArtifactKind.JSON.value)))
    artifact_id = str(item.get("id") or f"artifact_{fallback_index:04d}_{uuid4().hex}")
    external_id = _optional_payload_text(item, "external_id")
    source_uri = _optional_payload_text(item, "source_uri")
    title = _optional_payload_text(item, "title")
    topic_tags = tuple(str(tag) for tag in _list_or_empty(item.get("topic_tags")))
    metadata = _dict_or_empty(item.get("metadata"))
    if kind is SourceArtifactKind.FILE:
        content_text = item.get("content_text")
        if not isinstance(content_text, str):
            raise SourceConnectorError(
                "file artifact requires content_text in fixture/generic JSON"
            )
        return SourceArtifact(
            id=artifact_id,
            domain_id=domain_id,
            source_id=source_id,
            kind=kind,
            external_id=external_id,
            filename=_required_payload_text(item, "filename"),
            media_type=_optional_payload_text(item, "media_type"),
            content=content_text.encode("utf-8"),
            source_uri=source_uri,
            title=title,
            topic_tags=topic_tags,
            metadata=metadata,
        )
    if kind is SourceArtifactKind.DOWNLOAD_REFERENCE:
        return SourceArtifact(
            id=artifact_id,
            domain_id=domain_id,
            source_id=source_id,
            kind=kind,
            external_id=external_id,
            source_uri=source_uri,
            title=title,
            topic_tags=topic_tags,
            metadata=metadata,
        )
    payload = item.get("json_payload", item.get("payload", item))
    if not isinstance(payload, dict | list):
        raise SourceConnectorError("json artifact payload must be an object or array")
    return SourceArtifact(
        id=artifact_id,
        domain_id=domain_id,
        source_id=source_id,
        kind=kind,
        external_id=external_id,
        media_type="application/json",
        json_payload=payload,
        source_uri=source_uri,
        title=title,
        topic_tags=topic_tags,
        metadata=metadata,
    )


def _json_artifact_items(payload: object) -> list[object]:
    if isinstance(payload, dict):
        artifacts = payload.get("artifacts")
        if isinstance(artifacts, list):
            return artifacts
        return [payload]
    if isinstance(payload, list):
        return payload
    raise SourceConnectorError("generic_rest JSON response must be object or array")


def _required_config_text(config: dict[str, Any], field_name: str) -> str:
    value = config.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise SourceConnectorError(f"generic_rest config.{field_name} is required")
    return value.strip()


def _required_payload_text(payload: object, field_name: str) -> str:
    if not isinstance(payload, dict):
        raise SourceConnectorError("payload must be an object")
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise SourceConnectorError(f"payload.{field_name} is required")
    return value.strip()


def _optional_payload_text(payload: object, field_name: str) -> str | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get(field_name)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _dict_or_empty(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise SourceConnectorError("expected an object")
    return dict(value)


def _list_or_empty(value: object) -> list[object]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise SourceConnectorError("expected a list")
    return value
