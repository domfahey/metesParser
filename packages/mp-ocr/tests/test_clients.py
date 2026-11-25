"""Mocked behavioral tests for mp_ocr clients, configuration errors, and caching."""

from __future__ import annotations

import base64
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from mp_ocr import (
    BaseLLMClient,
    CachedLLMClient,
    GeminiClient,
    LLMClientError,
    LLMConfigurationError,
    OpenAIClient,
)


def _install_fake_openai(monkeypatch: pytest.MonkeyPatch):
    module = ModuleType("openai")
    outputs = {"text": "ok"}

    class FakeResponses:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def create(self, **kwargs: object) -> SimpleNamespace:
            self.calls.append(kwargs)
            return SimpleNamespace(output_text=outputs["text"])

    class FakeOpenAI:
        def __init__(self, api_key: str) -> None:
            self.responses = FakeResponses()

    module.OpenAI = FakeOpenAI  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", module)
    return outputs


def _install_fake_gemini(monkeypatch: pytest.MonkeyPatch, generate_content_handler):
    google_module = ModuleType("google")
    genai_module = ModuleType("google.genai")
    errors_module = ModuleType("google.genai.errors")
    types_module = ModuleType("google.genai.types")
    generate_calls: list[str] = []

    class FakeClientError(Exception):
        def __init__(self, status_code: int) -> None:
            super().__init__(f"client {status_code}")
            self.status_code = status_code

    class FakeServerError(Exception):
        def __init__(self, status_code: int) -> None:
            super().__init__(f"server {status_code}")
            self.status_code = status_code

    class FakePart:
        @staticmethod
        def from_text(text: str) -> SimpleNamespace:
            return SimpleNamespace(text=text)

        @staticmethod
        def from_bytes(data: bytes, mime_type: str) -> SimpleNamespace:
            return SimpleNamespace(data=data, mime_type=mime_type)

    class FakeContent:
        def __init__(self, role: str, parts: list[object]) -> None:
            self.role = role
            self.parts = parts

    class FakeClient:
        def __init__(self, api_key: str) -> None:
            self.models = SimpleNamespace(
                generate_content=lambda *, model, contents, config: _handle_generate(
                    model=model,
                    contents=contents,
                    config=config,
                )
            )

    def _handle_generate(*, model, contents, config):
        generate_calls.append(model)
        return generate_content_handler(
            model=model,
            contents=contents,
            config=config,
            client_error=FakeClientError,
            server_error=FakeServerError,
        )

    errors_module.ClientError = FakeClientError  # type: ignore[attr-defined]
    errors_module.ServerError = FakeServerError  # type: ignore[attr-defined]
    types_module.Part = FakePart  # type: ignore[attr-defined]
    types_module.Content = FakeContent  # type: ignore[attr-defined]
    types_module.GenerateContentConfig = lambda **kwargs: kwargs  # type: ignore[attr-defined]

    genai_module.Client = FakeClient  # type: ignore[attr-defined]
    genai_module.errors = errors_module  # type: ignore[attr-defined]
    genai_module.types = types_module  # type: ignore[attr-defined]

    google_module.genai = genai_mod = genai_module  # type: ignore[attr-defined]
    _ = genai_mod
    google_module.__path__ = []  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "google", google_module)
    monkeypatch.setitem(sys.modules, "google.genai", genai_module)
    monkeypatch.setitem(sys.modules, "google.genai.errors", errors_module)
    monkeypatch.setitem(sys.modules, "google.genai.types", types_module)

    return generate_calls, FakeClientError, FakeServerError


def test_base_client_protocol() -> None:
    assert hasattr(BaseLLMClient, "generate_text")
    assert hasattr(BaseLLMClient, "generate_text_with_pdf")


def test_llm_error_hierarchy_exported() -> None:
    assert issubclass(LLMClientError, RuntimeError)
    assert issubclass(LLMConfigurationError, LLMClientError)


def test_openai_client_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(LLMConfigurationError, match="OPENAI_API_KEY"):
        OpenAIClient()


def test_openai_client_generates_text_and_pdf_and_hides_secret(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    outputs = _install_fake_openai(monkeypatch)
    outputs["text"] = '{"calls": []}'
    pdf = tmp_path / "deed.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    client = OpenAIClient(api_key="sk-secret")
    assert "sk-secret" not in repr(client)
    assert client.generate_text("extract", response_mime_type="application/json") == '{"calls": []}'
    assert client.generate_text_with_pdf("read", str(pdf)) == '{"calls": []}'

    pdf_call = client._client.responses.calls[1]
    file_data = pdf_call["input"][0]["content"][0]["file_data"]
    assert base64.b64decode(file_data.split(",", 1)[1]) == b"%PDF-1.4"


def test_gemini_client_retries_retryable_errors_and_collects_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(*, model, contents, config, client_error, server_error):
        if model == "gemini-3-flash-preview":
            raise server_error(503)
        return SimpleNamespace(
            text="",
            candidates=[
                SimpleNamespace(
                    content=SimpleNamespace(parts=[SimpleNamespace(text="fallback text")])
                )
            ],
        )

    calls, _, _ = _install_fake_gemini(monkeypatch, handler)
    client = GeminiClient(api_key="gm-secret")
    assert "gm-secret" not in repr(client)
    assert client.generate_text("hello") == "fallback text"
    assert calls == ["gemini-3-flash-preview", "gemini-2.5-flash"]


def test_gemini_client_propagates_non_retryable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(*, model, contents, config, client_error, server_error):
        raise client_error(400)

    _, client_error, _ = _install_fake_gemini(monkeypatch, handler)
    client = GeminiClient(api_key="gm-secret")
    with pytest.raises(client_error, match="client 400"):
        client.generate_text("hello")


def test_cached_client_hits_and_clears_cache(tmp_path: Path) -> None:
    class FakeClient:
        model = "fake"

        def __init__(self) -> None:
            self.calls = 0

        def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
            self.calls += 1
            return f"resp:{prompt}"

        def generate_text_with_pdf(
            self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
        ) -> str:
            self.calls += 1
            return "pdf-resp"

    fake = FakeClient()
    cached = CachedLLMClient(fake, cache_dir=tmp_path / "cache")
    assert cached.generate_text("p") == "resp:p"
    assert cached.generate_text("p") == "resp:p"
    assert fake.calls == 1
    assert cached.clear_cache() == 1
    assert cached.generate_text("p") == "resp:p"
    assert fake.calls == 2
