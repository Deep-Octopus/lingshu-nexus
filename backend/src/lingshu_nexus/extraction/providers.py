"""LLM provider port and MiMo adapter."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from lingshu_domain.validation import require_text
from lingshu_nexus.config.settings import Settings
from lingshu_nexus.extraction.models import ProviderUsage


class ProviderError(RuntimeError):
    """Base error for LLM provider failures."""


class ProviderConfigurationError(ProviderError):
    """Raised when a provider lacks required safe runtime configuration."""


@dataclass(frozen=True)
class LlmCompletionRequest:
    system_prompt: str
    user_prompt: str
    prompt_version: str
    schema_version: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_text(self.system_prompt, "LlmCompletionRequest.system_prompt")
        require_text(self.user_prompt, "LlmCompletionRequest.user_prompt")
        require_text(self.prompt_version, "LlmCompletionRequest.prompt_version")
        require_text(self.schema_version, "LlmCompletionRequest.schema_version")


@dataclass(frozen=True)
class LlmCompletionResponse:
    provider: str
    model: str
    text: str
    raw_payload: dict[str, Any] = field(default_factory=dict)
    token_usage: ProviderUsage = field(default_factory=ProviderUsage)
    latency_ms: int | None = None

    def __post_init__(self) -> None:
        require_text(self.provider, "LlmCompletionResponse.provider")
        require_text(self.model, "LlmCompletionResponse.model")
        require_text(self.text, "LlmCompletionResponse.text")
        if self.latency_ms is not None and self.latency_ms < 0:
            raise ProviderError("latency_ms must be >= 0")


class LlmProvider(Protocol):
    name: str

    def complete(self, request: LlmCompletionRequest) -> LlmCompletionResponse:
        """Return a structured extraction completion."""


class MiMoProvider:
    """MiMo HTTP adapter using a configurable chat-completions compatible endpoint."""

    name = "mimo"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        chat_completions_path: str = "/chat/completions",
        timeout_seconds: float = 60,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._chat_completions_path = chat_completions_path
        self._timeout_seconds = timeout_seconds

    @classmethod
    def from_settings(cls, settings: Settings) -> MiMoProvider:
        extraction_model = settings.mimo_extraction_model_id or settings.mimo_model_id
        return cls(
            base_url=settings.mimo_base_url,
            api_key=settings.mimo_api_key,
            model=extraction_model,
        )

    def complete(self, request: LlmCompletionRequest) -> LlmCompletionResponse:
        self._validate_config()
        started = time.perf_counter()
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        url = f"{self._base_url}{self._chat_completions_path}"
        try:
            response = httpx.post(
                url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"MiMo request failed: {exc}") from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        try:
            raw_payload = response.json()
        except json.JSONDecodeError as exc:
            raise ProviderError("MiMo response was not JSON") from exc
        text = _extract_chat_completion_text(raw_payload)
        usage = _usage_from_payload(raw_payload.get("usage", {}))
        return LlmCompletionResponse(
            provider=self.name,
            model=str(raw_payload.get("model") or self._model),
            text=text,
            raw_payload=raw_payload,
            token_usage=usage,
            latency_ms=latency_ms,
        )

    def _validate_config(self) -> None:
        if not self._base_url or "example.invalid" in self._base_url:
            raise ProviderConfigurationError("MIMO_BASE_URL is not configured for live extraction")
        if not self._api_key or self._api_key.startswith("replace-with"):
            raise ProviderConfigurationError("MIMO_API_KEY is not configured for live extraction")
        if not self._model or self._model.startswith("replace-with"):
            raise ProviderConfigurationError("MIMO_MODEL_ID is not configured for live extraction")


class FakeLlmProvider:
    name = "fake"

    def __init__(
        self,
        response_payload: dict[str, Any] | str,
        *,
        model: str = "fake-extraction-model-v0",
        usage: ProviderUsage | None = None,
    ) -> None:
        self._response_payload = response_payload
        self._model = model
        self._usage = usage or ProviderUsage(
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
        )

    def complete(self, request: LlmCompletionRequest) -> LlmCompletionResponse:
        text = (
            self._response_payload
            if isinstance(self._response_payload, str)
            else json.dumps(self._response_payload, ensure_ascii=False)
        )
        return LlmCompletionResponse(
            provider=self.name,
            model=self._model,
            text=text,
            raw_payload={"fixture": True, "prompt_version": request.prompt_version},
            token_usage=self._usage,
            latency_ms=0,
        )


def _extract_chat_completion_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderError("MiMo response missing choices")
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise ProviderError("MiMo response choice is not an object")
    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise ProviderError("MiMo response choice missing message")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ProviderError("MiMo response message content is empty")
    return content


def _usage_from_payload(payload: object) -> ProviderUsage:
    if not isinstance(payload, dict):
        return ProviderUsage()
    return ProviderUsage(
        prompt_tokens=_int_or_none(payload.get("prompt_tokens")),
        completion_tokens=_int_or_none(payload.get("completion_tokens")),
        total_tokens=_int_or_none(payload.get("total_tokens")),
    )


def _int_or_none(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str | bytes | bytearray):
        return int(value)
    raise ProviderError(f"Token usage value is not an integer: {value!r}")
