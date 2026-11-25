"""LLM client abstractions for OpenAI, Gemini, and OpenRouter providers."""

from __future__ import annotations

import base64
import json
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlsplit


class LLMClientError(RuntimeError):
    """Base exception for LLM client failures."""


class LLMConfigurationError(LLMClientError):
    """Raised when the LLM client configuration is invalid."""


def _is_retryable_status(status_code: object) -> bool:
    """Return True for transient HTTP status codes eligible for retry/failover."""
    return (
        isinstance(status_code, int)
        and not isinstance(status_code, bool)
        and (status_code in {408, 409, 429} or 500 <= status_code < 600)
    )


def _has_invalid_header_chars(value: str) -> bool:
    """Return True if *value* has control or non-ASCII chars unsafe for HTTP headers."""
    return not value.isascii() or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value)


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

    Defaults to ``gemini-3.6-flash`` with fallback ``gemini-3.8-flash`` and
    ``thinking_level="LOW"`` (supported across Gemini 3/3.5/3.6/3.8/4 models while
    avoiding unbounded reasoning latency). When ``thinking_budget`` is provided,
    it takes precedence over ``thinking_level``. Set ``thinking_level=None`` to
    use the model's default thinking behavior.
    """

    api_key: str | None = field(default=None, repr=False)
    model: str = "gemini-3.6-flash"
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
                    # google-genai APIError exposes HTTP status on `.code` (not `.status_code`).
                    status_code = getattr(exc, "code", None)
                    if status_code is None:
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


@dataclass(frozen=True)
class OpenRouterClient:
    """OpenRouter-backed LLM client using OpenAI-compatible Chat Completions.

    Routes requests to ``https://openrouter.ai/api/v1`` via the ``openai`` SDK,
    defaulting to ``anthropic/claude-haiku-5.5`` with fallback
    ``anthropic/claude-sonnet-5.5`` and ``reasoning_effort="low"``. For heavily
    degraded or complex scans, set ``model="anthropic/claude-sonnet-5.5"`` (or
    ``OPENROUTER_MODEL=anthropic/claude-sonnet-5.5``) and optionally
    ``pdf_engine="mistral-ocr"``.
    """

    api_key: str | None = field(default=None, repr=False)
    model: str = "anthropic/claude-haiku-5.5"
    fallback_model: str | None = "anthropic/claude-sonnet-5.5"
    base_url: str = "https://openrouter.ai/api/v1"
    pdf_engine: str | None = None
    reasoning_effort: str | None = "low"
    site_url: str | None = None
    app_name: str | None = "MetesParser"
    timeout_s: float | None = 120.0
    max_retries: int = 2
    retry_backoff_s: float = 1.0
    _client: Any = field(init=False, repr=False, compare=False)
    _status_errors: tuple[type[BaseException], ...] = field(init=False, repr=False, compare=False)
    _transport_errors: tuple[type[BaseException], ...] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        raw_key = self.api_key if self.api_key is not None else os.getenv("OPENROUTER_API_KEY")
        key = raw_key.strip() if isinstance(raw_key, str) else ""
        if not key:
            raise LLMConfigurationError(
                "OpenRouter API key not found. Set OPENROUTER_API_KEY environment variable."
            )
        if _has_invalid_header_chars(key):
            raise LLMConfigurationError(
                "OpenRouter API key must contain only printable ASCII characters."
            )
        normalized_model = self.model.strip()
        if not normalized_model:
            raise LLMConfigurationError("model must be a non-empty string.")
        object.__setattr__(self, "model", normalized_model)

        if self.fallback_model is not None:
            normalized_fallback = self.fallback_model.strip()
            if not normalized_fallback:
                raise LLMConfigurationError("fallback_model must be a non-empty string or None.")
            object.__setattr__(self, "fallback_model", normalized_fallback)

        normalized_base_url = self.base_url.strip().rstrip("/")
        if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in normalized_base_url):
            raise LLMConfigurationError("base_url must not contain control characters.")
        parsed_base_url = urlsplit(normalized_base_url)
        scheme = parsed_base_url.scheme.lower()
        hostname = parsed_base_url.hostname
        if scheme not in ("https", "http") or not hostname:
            raise LLMConfigurationError(
                "base_url must be a valid http:// or https:// URL with a hostname."
            )
        if scheme == "http" and hostname.lower() not in {"localhost", "127.0.0.1", "::1"}:
            raise LLMConfigurationError("base_url must use https:// for non-loopback hosts.")
        if (
            parsed_base_url.username is not None
            or parsed_base_url.password is not None
            or parsed_base_url.query
            or parsed_base_url.fragment
            or "?" in normalized_base_url
            or "#" in normalized_base_url
        ):
            raise LLMConfigurationError(
                "base_url must not contain embedded credentials, query strings, or fragments."
            )
        object.__setattr__(self, "base_url", normalized_base_url)

        if self.pdf_engine is not None:
            normalized_engine = self.pdf_engine.strip()
            if not normalized_engine:
                raise LLMConfigurationError("pdf_engine must be a non-empty string or None.")
            object.__setattr__(self, "pdf_engine", normalized_engine)

        if self.reasoning_effort is not None:
            normalized_effort = self.reasoning_effort.strip().lower()
            if not normalized_effort:
                raise LLMConfigurationError("reasoning_effort must be a non-empty string or None.")
            object.__setattr__(self, "reasoning_effort", normalized_effort)

        if self.timeout_s is not None and (
            isinstance(self.timeout_s, bool)
            or not math.isfinite(self.timeout_s)
            or self.timeout_s <= 0
        ):
            raise LLMConfigurationError("timeout_s must be a positive finite number.")
        if (
            isinstance(self.max_retries, bool)
            or not isinstance(self.max_retries, int)
            or self.max_retries < 0
        ):
            raise LLMConfigurationError("max_retries must be a non-negative integer.")
        if (
            isinstance(self.retry_backoff_s, bool)
            or not math.isfinite(self.retry_backoff_s)
            or self.retry_backoff_s < 0
        ):
            raise LLMConfigurationError("retry_backoff_s must be a non-negative finite number.")

        default_headers: dict[str, str] = {}
        if self.site_url is not None:
            normalized_site_url = self.site_url.strip()
            if normalized_site_url:
                if _has_invalid_header_chars(normalized_site_url):
                    raise LLMConfigurationError(
                        "site_url must contain only printable ASCII characters."
                    )
                parsed_site_url = urlsplit(normalized_site_url)
                if (
                    parsed_site_url.scheme.lower() not in ("https", "http")
                    or not parsed_site_url.hostname
                    or parsed_site_url.username is not None
                    or parsed_site_url.password is not None
                ):
                    raise LLMConfigurationError(
                        "site_url must be a valid http:// or https:// URL without credentials."
                    )
                default_headers["HTTP-Referer"] = normalized_site_url
        if self.app_name is not None:
            normalized_app_name = self.app_name.strip()
            if normalized_app_name:
                if _has_invalid_header_chars(normalized_app_name):
                    raise LLMConfigurationError(
                        "app_name must contain only printable ASCII characters."
                    )
                default_headers["X-Title"] = normalized_app_name

        try:
            import openai as openai_mod
        except ImportError as exc:  # pragma: no cover - defensive
            raise LLMConfigurationError(
                "openai package not installed. Install metesparser with OpenAI extras."
            ) from exc

        openai_cls = getattr(openai_mod, "OpenAI", None)
        if not callable(openai_cls):
            raise LLMConfigurationError(
                "openai package not installed. Install metesparser with OpenAI extras."
            )

        # Disable SDK-level retries so OpenRouterClient's round-robin failover
        # and backoff govern retry counts without multiplicative amplification.
        client_kwargs: dict[str, object] = {
            "api_key": key,
            "base_url": self.base_url,
            "max_retries": 0,
        }
        if self.timeout_s is not None:
            client_kwargs["timeout"] = self.timeout_s
        if default_headers:
            client_kwargs["default_headers"] = default_headers

        status_errors = tuple(
            err
            for err in (getattr(openai_mod, "APIStatusError", None),)
            if isinstance(err, type) and issubclass(err, BaseException)
        )
        transport_errors = tuple(
            err
            for err in (
                getattr(openai_mod, "APITimeoutError", None),
                getattr(openai_mod, "APIConnectionError", None),
            )
            if isinstance(err, type) and issubclass(err, BaseException)
        )

        sdk_client = openai_cls(**client_kwargs)
        # Clear OpenAI-specific env credentials so they are never forwarded to OpenRouter.
        for attr in ("organization", "project", "webhook_secret"):
            if hasattr(sdk_client, attr):
                setattr(sdk_client, attr, None)

        object.__setattr__(self, "_client", sdk_client)
        object.__setattr__(self, "_status_errors", status_errors)
        object.__setattr__(self, "_transport_errors", transport_errors)

    def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
        messages: list[dict[str, object]] = [{"role": "user", "content": prompt}]
        return self._create_completion(
            messages, response_mime_type=response_mime_type, include_pdf_plugin=False
        )

    def generate_text_with_pdf(
        self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
    ) -> str:
        filename, pdf_bytes = _read_pdf(pdf_path)
        pdf_base64 = base64.b64encode(pdf_bytes).decode("utf-8")
        messages: list[dict[str, object]] = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "file",
                        "file": {
                            "filename": filename,
                            "file_data": f"data:application/pdf;base64,{pdf_base64}",
                        },
                    },
                    {
                        "type": "text",
                        "text": prompt,
                    },
                ],
            }
        ]
        return self._create_completion(
            messages, response_mime_type=response_mime_type, include_pdf_plugin=True
        )

    def _create_completion(
        self,
        messages: list[dict[str, object]],
        *,
        response_mime_type: str | None = None,
        include_pdf_plugin: bool = False,
    ) -> str:
        request_kwargs: dict[str, object] = {
            "temperature": 0,
            "messages": messages,
        }
        if response_mime_type == "application/json":
            request_kwargs["response_format"] = {"type": "json_object"}

        extra_body: dict[str, object] = {}
        if include_pdf_plugin and self.pdf_engine is not None:
            extra_body["plugins"] = [
                {
                    "id": "file-parser",
                    "pdf": {"engine": self.pdf_engine},
                }
            ]
        if self.reasoning_effort is not None:
            extra_body["reasoning"] = {"effort": self.reasoning_effort}
        if extra_body:
            request_kwargs["extra_body"] = extra_body

        models_to_try: list[str] = [self.model]
        fallback = self.fallback_model
        if fallback and fallback not in models_to_try:
            models_to_try.append(fallback)

        catch_types = self._status_errors + self._transport_errors
        last_error: BaseException | None = None
        total_rounds = self.max_retries + 1

        for round_index in range(total_rounds):
            for model_index, model_name in enumerate(models_to_try):
                has_more_models = model_index < len(models_to_try) - 1
                has_more_rounds = round_index < total_rounds - 1
                try:
                    response = self._client.chat.completions.create(
                        model=model_name,
                        **request_kwargs,
                    )
                except json.JSONDecodeError as exc:
                    err = LLMClientError(f"OpenRouter returned invalid JSON: {exc}")
                    if has_more_models or has_more_rounds:
                        last_error = err
                        continue
                    raise err from exc
                except catch_types as exc:
                    is_retryable = isinstance(exc, self._transport_errors) or (
                        isinstance(exc, self._status_errors)
                        and _is_retryable_status(getattr(exc, "status_code", None))
                    )
                    if is_retryable and (has_more_models or has_more_rounds):
                        last_error = exc
                        continue
                    raise

                payload_error = self._extract_response_error(response, model_name)
                if payload_error is not None:
                    err, is_retryable = payload_error
                    if is_retryable and (has_more_models or has_more_rounds):
                        last_error = err
                        continue
                    raise err

                return self._collect_response_text(response)
            if round_index < total_rounds - 1 and self.retry_backoff_s > 0:
                time.sleep(self.retry_backoff_s * (2**round_index))

        if last_error:
            raise last_error
        return ""

    @staticmethod
    def _extract_response_error(
        response: object, model_name: str
    ) -> tuple[LLMClientError, bool] | None:
        if response is None or isinstance(response, (str, bytes)):
            return (
                LLMClientError(
                    f"OpenRouter returned unexpected response payload for {model_name}: "
                    f"{type(response).__name__}"
                ),
                True,
            )

        response_error = getattr(response, "error", None)
        choices = getattr(response, "choices", None)
        choice_error: object = None
        finish_reason: object = None
        if isinstance(choices, list) and choices:
            first_choice = choices[0]
            choice_error = getattr(first_choice, "error", None)
            finish_reason = getattr(first_choice, "finish_reason", None)

        if response_error is None and choice_error is None and finish_reason != "error":
            return None

        err_obj = response_error if response_error is not None else choice_error
        raw_code: object = None
        raw_message: object = None
        if isinstance(err_obj, dict):
            raw_code = err_obj.get("code")
            raw_message = err_obj.get("message")
        elif err_obj is not None:
            raw_code = getattr(err_obj, "code", None)
            raw_message = getattr(err_obj, "message", None)

        code: int | None = None
        if isinstance(raw_code, int) and not isinstance(raw_code, bool):
            code = raw_code
        elif isinstance(raw_code, str):
            stripped_code = raw_code.strip()
            if stripped_code:
                try:
                    code = int(stripped_code)
                except ValueError:
                    code = None

        if isinstance(raw_message, str) and raw_message.strip():
            message = raw_message.strip()
        elif err_obj is not None:
            message = str(err_obj)
        else:
            message = "upstream completion failed"

        detail_parts: list[str] = []
        if code is not None:
            detail_parts.append(f"code={code}")
        if finish_reason == "error":
            detail_parts.append("finish_reason=error")
        if message:
            detail_parts.append(message)
        detail = "; ".join(detail_parts) or "unknown error"

        err = LLMClientError(f"OpenRouter error for {model_name}: {detail}")
        is_retryable = _is_retryable_status(code) or (code is None and finish_reason == "error")
        return err, is_retryable

    @staticmethod
    def _collect_response_text(response: object) -> str:
        choices = getattr(response, "choices", None)
        if not isinstance(choices, list) or not choices:
            return ""
        message = getattr(choices[0], "message", None)
        if message is None:
            return ""
        content = getattr(message, "content", None)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            segments: list[str] = []
            for part in content:
                part_type = (
                    part.get("type") if isinstance(part, dict) else getattr(part, "type", None)
                )
                if isinstance(part_type, str) and (
                    part_type in ("thinking", "reasoning", "reasoning_text")
                    or part_type.startswith(("thinking", "reasoning"))
                ):
                    continue
                part_text = (
                    part.get("text") if isinstance(part, dict) else getattr(part, "text", None)
                )
                if isinstance(part_text, str):
                    segments.append(part_text)
            return "".join(segments)
        return ""
