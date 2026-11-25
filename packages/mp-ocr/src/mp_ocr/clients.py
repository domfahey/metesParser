"""LLM client abstractions for OpenAI and Gemini providers."""

from __future__ import annotations

import base64
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


class LLMClientError(RuntimeError):
    """Base exception for LLM client failures."""


class LLMConfigurationError(LLMClientError):
    """Raised when the LLM client configuration is invalid."""


def _read_pdf(pdf_path: str) -> tuple[str, bytes]:
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found at {pdf_path}")
    return path.name, path.read_bytes()


@runtime_checkable
class BaseLLMClient(Protocol):
    """Protocol all LLM clients must implement."""

    def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
        """Generate text from a prompt."""

    def generate_text_with_pdf(
        self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
    ) -> str:
        """Generate text from a prompt and attached PDF."""


@dataclass(frozen=True)
class OpenAIClient:
    """OpenAI-backed LLM client."""

    api_key: str | None = field(default=None, repr=False)
    model: str = "gpt-5.2"
    _client: Any = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        key = self.api_key or os.getenv("OPENAI_API_KEY")
        if not key:
            raise LLMConfigurationError(
                "OpenAI API key not found. Set OPENAI_API_KEY environment variable."
            )
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - defensive
            raise LLMConfigurationError(
                "openai package not installed. Install metesparser with OpenAI extras."
            ) from exc
        object.__setattr__(self, "_client", OpenAI(api_key=key))

    @staticmethod
    def _response_format_kwargs(response_mime_type: str | None) -> dict[str, object]:
        if response_mime_type == "application/json":
            return {"text": {"format": {"type": "json_object"}}}
        return {}

    def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
        generate_kwargs: dict[str, object] = {
            "model": self.model,
            "temperature": 0,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": prompt,
                        }
                    ],
                }
            ],
        }
        generate_kwargs.update(self._response_format_kwargs(response_mime_type))

        response = self._client.responses.create(**generate_kwargs)
        return response.output_text or ""

    def generate_text_with_pdf(
        self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
    ) -> str:
        filename, pdf_bytes = _read_pdf(pdf_path)
        pdf_base64 = base64.b64encode(pdf_bytes).decode("utf-8")
        generate_kwargs: dict[str, object] = {
            "model": self.model,
            "temperature": 0,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_file",
                            "filename": filename,
                            "file_data": f"data:application/pdf;base64,{pdf_base64}",
                        },
                        {
                            "type": "input_text",
                            "text": prompt,
                        },
                    ],
                }
            ],
        }
        generate_kwargs.update(self._response_format_kwargs(response_mime_type))

        response = self._client.responses.create(**generate_kwargs)
        return response.output_text or ""


@dataclass(frozen=True)
class GeminiClient:
    """Gemini-backed LLM client with optional fallback model, thinking control, and retries.

    Defaults to ``gemini-3-flash-preview`` with fallback ``gemini-3.8-flash`` and
    ``thinking_level="LOW"`` (supported across Gemini 3/3.5/3.6/3.8/4 models while
    avoiding unbounded reasoning latency). When ``thinking_budget`` is provided,
    it takes precedence over ``thinking_level``. Set ``thinking_level=None`` to
    use the model's default thinking behavior.
    """

    api_key: str | None = field(default=None, repr=False)
    model: str = "gemini-3-flash-preview"
    fallback_model: str | None = "gemini-3.8-flash"
    thinking_level: str | None = "LOW"
    thinking_budget: int | None = None
    api_version: str | None = None
    timeout_ms: int | None = 120_000
    max_retries: int = 2
    retry_backoff_s: float = 1.0
    _client: Any = field(init=False, repr=False, compare=False)
    _types: Any = field(init=False, repr=False, compare=False)
    _errors: Any = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        key = self.api_key or os.getenv("GEMINI_API_KEY")
        if not key:
            raise LLMConfigurationError(
                "Gemini API key not found. Set GEMINI_API_KEY environment variable."
            )
        if self.timeout_ms is not None and (
            isinstance(self.timeout_ms, bool) or self.timeout_ms <= 0
        ):
            raise LLMConfigurationError("timeout_ms must be a positive integer.")
        if isinstance(self.max_retries, bool) or self.max_retries < 0:
            raise LLMConfigurationError("max_retries must be a non-negative integer.")
        if (
            isinstance(self.retry_backoff_s, bool)
            or not math.isfinite(self.retry_backoff_s)
            or self.retry_backoff_s < 0
        ):
            raise LLMConfigurationError("retry_backoff_s must be a non-negative finite number.")
        if self.thinking_budget is not None and (
            isinstance(self.thinking_budget, bool) or self.thinking_budget < -1
        ):
            raise LLMConfigurationError("thinking_budget must be >= -1.")
        if self.thinking_level is not None:
            normalized_level = self.thinking_level.strip().upper()
            if not normalized_level:
                raise LLMConfigurationError("thinking_level must be a non-empty string or None.")
            object.__setattr__(self, "thinking_level", normalized_level)
        if self.api_version is not None:
            normalized_version = self.api_version.strip()
            if not normalized_version:
                raise LLMConfigurationError("api_version must be a non-empty string or None.")
            object.__setattr__(self, "api_version", normalized_version)

        try:
            from google import genai
            from google.genai import errors as genai_errors
            from google.genai import types as genai_types
        except ImportError as exc:  # pragma: no cover - defensive
            raise LLMConfigurationError(
                "google-genai package not installed. Install metesparser with the gemini extra: pip install 'metesparser[gemini]'."
            ) from exc

        http_options_kwargs: dict[str, object] = {}
        resolved_api_version = self._resolve_api_version()
        if resolved_api_version is not None:
            http_options_kwargs["api_version"] = resolved_api_version
        if self.timeout_ms is not None:
            http_options_kwargs["timeout"] = self.timeout_ms
        # Keep SDK-level attempts at 1 so GeminiClient's round-robin failover
        # and backoff govern retries without multiplicative amplification.
        retry_options_cls = getattr(genai_types, "HttpRetryOptions", None)
        if callable(retry_options_cls):
            http_options_kwargs["retry_options"] = retry_options_cls(attempts=1)

        http_options_cls = getattr(genai_types, "HttpOptions", None)
        if http_options_kwargs and callable(http_options_cls):
            client = genai.Client(api_key=key, http_options=http_options_cls(**http_options_kwargs))
        else:
            client = genai.Client(api_key=key)

        object.__setattr__(self, "_client", client)
        object.__setattr__(self, "_types", genai_types)
        object.__setattr__(self, "_errors", genai_errors)

    def _resolve_api_version(self) -> str | None:
        if self.api_version is not None:
            return self.api_version
        # google-genai >= 3.0 defaults to v1, where preview models return 404;
        # v1beta serves both preview and GA Gemini models.
        configured_models = [self.model]
        if self.fallback_model:
            configured_models.append(self.fallback_model)
        if any("preview" in model_name.lower() for model_name in configured_models):
            return "v1beta"
        return None

    def _build_thinking_config(self) -> object | None:
        thinking_config_cls = getattr(self._types, "ThinkingConfig", None)
        if not callable(thinking_config_cls):
            return None
        if self.thinking_budget is not None:
            config: object = thinking_config_cls(thinking_budget=self.thinking_budget)
            return config
        if self.thinking_level is not None:
            config = thinking_config_cls(thinking_level=self.thinking_level)
            return config
        return None

    def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
        content = self._types.Content(
            role="user",
            parts=[self._types.Part.from_text(text=prompt)],
        )
        return self._generate([content], response_mime_type=response_mime_type)

    def generate_text_with_pdf(
        self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
    ) -> str:
        _, pdf_bytes = _read_pdf(pdf_path)
        content = self._types.Content(
            role="user",
            parts=[
                self._types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
                self._types.Part.from_text(text=prompt),
            ],
        )
        return self._generate([content], response_mime_type=response_mime_type)

    def _generate(self, contents: list[object], *, response_mime_type: str | None = None) -> str:
        generate_kwargs: dict[str, object] = {"temperature": 0}
        if response_mime_type:
            generate_kwargs["response_mime_type"] = response_mime_type
        thinking_config = self._build_thinking_config()
        if thinking_config is not None:
            generate_kwargs["thinking_config"] = thinking_config

        models_to_try: list[str] = [self.model]
        fallback = self.fallback_model
        if fallback and fallback not in models_to_try:
            models_to_try.append(fallback)

        retryable_codes = {429, 502, 503, 504}
        last_error: Exception | None = None
        total_rounds = self.max_retries + 1

        for round_index in range(total_rounds):
            for model_index, model_name in enumerate(models_to_try):
                config = self._types.GenerateContentConfig(**generate_kwargs)
                try:
                    response = self._client.models.generate_content(
                        model=model_name,
                        contents=contents,
                        config=config,
                    )
                    return self._collect_response_text(response)
                except (self._errors.ClientError, self._errors.ServerError) as exc:
                    status_code = getattr(exc, "status_code", None)
                    has_more_models = model_index < len(models_to_try) - 1
                    has_more_rounds = round_index < total_rounds - 1
                    if status_code in retryable_codes and (has_more_models or has_more_rounds):
                        last_error = exc
                        continue
                    raise
            if round_index < total_rounds - 1 and self.retry_backoff_s > 0:
                time.sleep(self.retry_backoff_s * (2**round_index))

        if last_error:
            raise last_error
        return ""

    def _collect_response_text(self, response: object) -> str:
        # Read non-thought candidate parts first to avoid google-genai's
        # stdout warning when response.text encounters thought_signature parts.
        candidates = getattr(response, "candidates", None)
        if candidates:
            segments: list[str] = []
            saw_parts = False
            for candidate in candidates:
                content = getattr(candidate, "content", None)
                if not content:
                    continue
                parts = getattr(content, "parts", None)
                if not parts:
                    continue
                saw_parts = True
                for part in parts:
                    if getattr(part, "thought", False):
                        continue
                    part_text = getattr(part, "text", None)
                    if isinstance(part_text, str):
                        segments.append(part_text)
            if saw_parts:
                return "".join(segments)

        text = getattr(response, "text", None)
        if isinstance(text, str) and text:
            return text
        return ""
