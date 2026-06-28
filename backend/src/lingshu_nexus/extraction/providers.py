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
        timeout_seconds: float = 45,
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
            timeout_seconds=settings.mimo_timeout_seconds,
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
                    "api-key": self._api_key,
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=httpx.Timeout(
                    self._timeout_seconds,
                    connect=min(10.0, self._timeout_seconds),
                ),
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ProviderError(
                f"MiMo request timed out after {self._timeout_seconds:g} seconds; "
                "check MIMO_BASE_URL, network access, and provider availability"
            ) from exc
        except httpx.HTTPStatusError as exc:
            detail = _provider_error_detail(exc.response)
            if exc.response.status_code == 401:
                detail = _authentication_error_detail(detail, api_key=self._api_key)
            suffix = f": {detail}" if detail else ""
            raise ProviderError(
                f"MiMo request failed with HTTP {exc.response.status_code}{suffix}"
            ) from exc
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


class DeepSeekProvider:
    """DeepSeek adapter using its OpenAI-compatible chat-completions API."""

    name = "deepseek"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 45,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds

    @classmethod
    def from_settings(cls, settings: Settings) -> DeepSeekProvider:
        extraction_model = (
            settings.deepseek_extraction_model_id or settings.deepseek_model_id
        )
        return cls(
            base_url=settings.deepseek_base_url,
            api_key=settings.deepseek_api_key,
            model=extraction_model,
            timeout_seconds=settings.deepseek_timeout_seconds,
        )

    def complete(self, request: LlmCompletionRequest) -> LlmCompletionResponse:
        self._validate_config()
        started = time.perf_counter()
        url = f"{self._base_url}/chat/completions"
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        try:
            response = httpx.post(
                url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=httpx.Timeout(
                    self._timeout_seconds,
                    connect=min(10.0, self._timeout_seconds),
                ),
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ProviderError(
                f"DeepSeek request timed out after {self._timeout_seconds:g} seconds; "
                "check DEEPSEEK_BASE_URL, network access, and provider availability"
            ) from exc
        except httpx.HTTPStatusError as exc:
            detail = _provider_error_detail(exc.response)
            if exc.response.status_code == 401:
                detail = _deepseek_authentication_error_detail(detail)
            suffix = f": {detail}" if detail else ""
            raise ProviderError(
                f"DeepSeek request failed with HTTP {exc.response.status_code}{suffix}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"DeepSeek request failed: {exc}") from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        try:
            raw_payload = response.json()
        except json.JSONDecodeError as exc:
            raise ProviderError("DeepSeek response was not JSON") from exc
        text = _extract_chat_completion_text(raw_payload, provider_name="DeepSeek")
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
            raise ProviderConfigurationError(
                "DEEPSEEK_BASE_URL is not configured for live extraction"
            )
        if not self._api_key or self._api_key.startswith("replace-with"):
            raise ProviderConfigurationError(
                "DEEPSEEK_API_KEY is not configured for live extraction"
            )
        if not self._model or self._model.startswith("replace-with"):
            raise ProviderConfigurationError(
                "DEEPSEEK_MODEL_ID is not configured for live extraction"
            )


def create_llm_provider(settings: Settings) -> LlmProvider:
    provider = settings.llm_provider.strip().lower()
    if provider == "deepseek":
        return DeepSeekProvider.from_settings(settings)
    if provider == "mimo":
        return MiMoProvider.from_settings(settings)
    raise ProviderConfigurationError(
        f"Unsupported LLM_PROVIDER: {settings.llm_provider}. Expected deepseek or mimo."
    )


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


def _extract_chat_completion_text(
    payload: dict[str, Any],
    *,
    provider_name: str = "MiMo",
) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderError(f"{provider_name} response missing choices")
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise ProviderError(f"{provider_name} response choice is not an object")
    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise ProviderError(f"{provider_name} response choice missing message")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ProviderError(f"{provider_name} response message content is empty")
    return content


def _provider_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError):
        return response.text.strip().replace("\n", " ")[:300]
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str):
            return message.strip()[:300]
    return ""


def _authentication_error_detail(detail: str, *, api_key: str) -> str:
    if api_key.startswith("tp-"):
        guidance = (
            "Token Plan credential is invalid or expired; copy both the API Key and matching "
            "regional Base URL again from https://platform.xiaomimimo.com/#/console/plan-manage"
        )
    else:
        guidance = (
            "API credential is invalid or expired; create or copy it again from the MiMo console"
        )
    return f"{detail}. {guidance}" if detail else guidance


def _deepseek_authentication_error_detail(detail: str) -> str:
    guidance = (
        "DeepSeek API credential is invalid or expired; create or copy a key again from "
        "https://platform.deepseek.com/api_keys"
    )
    return f"{detail}. {guidance}" if detail else guidance


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
