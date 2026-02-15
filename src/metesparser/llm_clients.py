"""LLM client abstractions for OpenAI and Gemini providers."""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
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

    api_key: str | None = None
    model: str = "gpt-4.1"
    _client: Any = object()

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
    """Gemini-backed LLM client with optional fallback model."""

    api_key: str | None = None
    model: str = "gemini-2.5-pro"
    fallback_model: str | None = "gemini-2.5-flash"
    _client: Any = object()
    _types: Any = object()
    _errors: Any = object()

    def __post_init__(self) -> None:
        key = self.api_key or os.getenv("GEMINI_API_KEY")
        if not key:
            raise LLMConfigurationError(
                "Gemini API key not found. Set GEMINI_API_KEY environment variable."
            )
        try:
            from google import genai
            from google.genai import errors as genai_errors
            from google.genai import types as genai_types
        except ImportError as exc:  # pragma: no cover - defensive
            raise LLMConfigurationError(
                "google-genai package not installed. Install metesparser with the gemini extra: pip install 'metesparser[gemini]'."
            ) from exc
        object.__setattr__(self, "_client", genai.Client(api_key=key))
        object.__setattr__(self, "_types", genai_types)
        object.__setattr__(self, "_errors", genai_errors)

    def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
        content = self._types.Content(
            role="user",
            parts=[self._types.Part.from_text(text=prompt)],
        )
        return self._generate([content], response_mime_type=response_mime_type)

    def generate_text_with_pdf(
        self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
    ) -> str:
        filename, pdf_bytes = _read_pdf(pdf_path)
        del filename  # Gemini does not currently use filenames for PDF parts
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

        models_to_try: list[str] = [self.model]
        fallback = self.fallback_model
        if fallback and fallback not in models_to_try:
            models_to_try.append(fallback)

        last_error: Exception | None = None

        for index, model_name in enumerate(models_to_try):
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
                retryable_codes = {429, 502, 503, 504}
                if status_code in retryable_codes and index < len(models_to_try) - 1:
                    last_error = exc
                    continue
                raise

        if last_error:
            raise last_error
        return ""

    def _collect_response_text(self, response: object) -> str:
        # google-genai responses expose either .text or candidates/parts.
        text = getattr(response, "text", None)
        if isinstance(text, str) and text:
            return text

        segments: list[str] = []

        candidates = getattr(response, "candidates", None)
        if not candidates:
            return ""
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            if not content:
                continue
            parts = getattr(content, "parts", None)
            if not parts:
                continue
            for part in parts:
                part_text = getattr(part, "text", None)
                if isinstance(part_text, str):
                    segments.append(part_text)
        return "".join(segments)
