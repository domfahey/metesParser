from __future__ import annotations

import base64
import sys
from types import ModuleType, SimpleNamespace

import pytest

from metesparser.llm_clients import (
    GeminiClient,
    LLMConfigurationError,
    OpenAIClient,
    _read_pdf,
)


def _install_fake_openai(monkeypatch):
    module = ModuleType("openai")
    outputs = {"text": "ok"}

    class FakeResponses:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(output_text=outputs["text"])

    class FakeOpenAI:
        def __init__(self, api_key: str):
            self.responses = FakeResponses()

    module.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", module)
    return module, outputs


def _install_fake_gemini(monkeypatch, generate_content_handler):
    google_module = ModuleType("google")
    genai_module = ModuleType("google.genai")
    errors_module = ModuleType("google.genai.errors")
    types_module = ModuleType("google.genai.types")
    generate_calls: list[str] = []

    class FakeClientError(Exception):
        def __init__(self, status_code: int):
            super().__init__(f"client {status_code}")
            self.status_code = status_code

    class FakeServerError(Exception):
        def __init__(self, status_code: int):
            super().__init__(f"server {status_code}")
            self.status_code = status_code

    class FakePart:
        @staticmethod
        def from_text(text: str):
            return SimpleNamespace(text=text)

        @staticmethod
        def from_bytes(data: bytes, mime_type: str):
            return SimpleNamespace(data=data, mime_type=mime_type)

    class FakeContent:
        def __init__(self, role: str, parts):
            self.role = role
            self.parts = parts

    class FakeClient:
        def __init__(self, api_key: str):
            self.models = SimpleNamespace(
                generate_content=lambda *, model, contents, config: _handle_generate(
                    model=model,
                    contents=contents,
                    config=config,
                    generate_calls=generate_calls,
                    client_error=FakeClientError,
                    server_error=FakeServerError,
                )
            )

    def _handle_generate(*, model, contents, config, generate_calls, client_error, server_error):
        generate_calls.append(model)
        return generate_content_handler(
            model=model,
            contents=contents,
            config=config,
            client_error=client_error,
            server_error=server_error,
        )

    errors_module.ClientError = FakeClientError
    errors_module.ServerError = FakeServerError
    types_module.Part = FakePart
    types_module.Content = FakeContent
    types_module.GenerateContentConfig = lambda **kwargs: kwargs

    genai_module.Client = FakeClient
    genai_module.errors = errors_module
    genai_module.types = types_module

    google_module.genai = genai_module
    google_module.__path__ = []
    monkeypatch.setitem(sys.modules, "google", google_module)
    monkeypatch.setitem(sys.modules, "google.genai", genai_module)
    monkeypatch.setitem(sys.modules, "google.genai.errors", errors_module)
    monkeypatch.setitem(sys.modules, "google.genai.types", types_module)

    return generate_calls, FakeClientError, FakeServerError


def test_read_pdf_reads_bytes(tmp_path):
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"binary")

    name, content = _read_pdf(str(pdf))
    assert name == "sample.pdf"
    assert content == b"binary"


def test_read_pdf_raises_when_missing():
    with pytest.raises(FileNotFoundError, match="PDF not found at missing.pdf"):
        _read_pdf("missing.pdf")


def test_openai_client_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(LLMConfigurationError, match="OPENAI_API_KEY"):
        OpenAIClient()


def test_openai_client_raises_when_sdk_missing(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "key")
    monkeypatch.setitem(sys.modules, "openai", ModuleType("openai"))
    with pytest.raises(LLMConfigurationError, match="openai package not installed"):
        OpenAIClient()


def test_openai_client_generates_text_and_handles_pdf(monkeypatch, tmp_path):
    _, outputs = _install_fake_openai(monkeypatch)
    outputs["text"] = "response-text"
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"binary")

    client = OpenAIClient()
    assert client.generate_text("hello") == "response-text"
    assert client.generate_text_with_pdf("analyze", str(pdf_path)) == "response-text"


def test_openai_generate_text_with_pdf_includes_encoded_pdf(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    fake_openai_module, _ = _install_fake_openai(monkeypatch)
    pdf = tmp_path / "input.pdf"
    pdf.write_bytes(b"%PDF")

    client = OpenAIClient()
    assert (
        client.generate_text_with_pdf("prompt", str(pdf), response_mime_type="text/plain") == "ok"
    )

    call = client._client.responses.calls[0]
    content = call["input"][0]["content"]
    file_data = content[0]["file_data"]
    assert file_data.startswith("data:application/pdf;base64,")
    assert base64.b64decode(file_data.split(",", 1)[1]) == b"%PDF"


def test_gemini_client_requires_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    _install_fake_gemini(
        monkeypatch,
        lambda **kwargs: SimpleNamespace(text="irrelevant"),
    )

    with pytest.raises(LLMConfigurationError, match="GEMINI_API_KEY"):
        GeminiClient()


def test_gemini_client_retries_retryable_errors_and_collects_candidate_text(monkeypatch):
    def handler(*, model, contents, config, client_error, server_error):
        if model == "gemini-2.5-pro":
            raise server_error(503)
        return SimpleNamespace(
            text="",
            candidates=[
                SimpleNamespace(
                    content=SimpleNamespace(parts=[SimpleNamespace(text="via candidates")])
                )
            ],
        )

    _, _, _ = _install_fake_gemini(monkeypatch, handler)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    client = GeminiClient(model="gemini-2.5-pro", fallback_model="gemini-2.5-flash")
    assert client.generate_text("hello") == "via candidates"


def test_gemini_client_re_raises_non_retryable_client_error(monkeypatch):
    def handler(*, model, contents, config, client_error, server_error):
        raise client_error(400)

    _, client_error, _ = _install_fake_gemini(monkeypatch, handler)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    client = GeminiClient(model="gemini-2.5-pro", fallback_model=None)

    with pytest.raises(client_error, match="client 400"):
        client.generate_text("hello")


def test_gemini_client_default_fallback_and_retries(monkeypatch):
    def handler(*, model, contents, config, client_error, server_error):
        if model == "gemini-3.6-flash":
            raise server_error(503)
        return SimpleNamespace(
            candidates=[
                SimpleNamespace(
                    content=SimpleNamespace(
                        parts=[
                            SimpleNamespace(thought=True, text="skip me"),
                            SimpleNamespace(thought_signature=b"sig", text=None),
                            SimpleNamespace(text="from 3.8 fallback"),
                        ]
                    )
                )
            ]
        )

    calls, _, _ = _install_fake_gemini(monkeypatch, handler)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    client = GeminiClient()
    assert client.model == "gemini-3.6-flash"
    assert client.fallback_model == "gemini-3.8-flash"
    assert client.thinking_level == "LOW"
    assert client.generate_text("hello") == "from 3.8 fallback"
    assert calls == ["gemini-3.6-flash", "gemini-3.8-flash"]


def test_gemini_client_thought_only_candidates_do_not_touch_response_text(monkeypatch):
    class ThoughtOnlyResponse:
        def __init__(self) -> None:
            self.candidates = [
                SimpleNamespace(
                    content=SimpleNamespace(
                        parts=[SimpleNamespace(thought=True, text="private reasoning")]
                    )
                )
            ]

        @property
        def text(self) -> str:
            raise AssertionError("response.text should not be accessed")

    _install_fake_gemini(monkeypatch, lambda **kwargs: ThoughtOnlyResponse())
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    client = GeminiClient()
    assert client.generate_text("hello") == ""


def test_gemini_client_retry_exhaustion_with_backoff_and_real_sdk_types(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr("metesparser.llm_clients.time.sleep", sleeps.append)

    def handler(*, model, contents, config, client_error, server_error):
        raise server_error(503)

    calls, _, server_error = _install_fake_gemini(monkeypatch, handler)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    client = GeminiClient(max_retries=1, retry_backoff_s=0.25)
    with pytest.raises(server_error, match="server 503"):
        client.generate_text("hello")
    assert calls == [
        "gemini-3.6-flash",
        "gemini-3.8-flash",
        "gemini-3.6-flash",
        "gemini-3.8-flash",
    ]
    assert sleeps == [0.25]

    zero_retry_client = GeminiClient(max_retries=0)
    calls.clear()
    sleeps.clear()
    with pytest.raises(server_error, match="server 503"):
        zero_retry_client.generate_text("hello")
    assert calls == ["gemini-3.6-flash", "gemini-3.8-flash"]
    assert sleeps == []


def test_gemini_client_real_google_genai_sdk_config_construction():
    from google.genai import types as genai_types

    client = GeminiClient(api_key="test-key-unused-offline")
    assert client.model == "gemini-3.6-flash"
    assert client._resolve_api_version() is None
    http_opts = client._client._api_client._http_options
    assert http_opts.api_version == "v1"
    assert http_opts.timeout == 120_000
    assert http_opts.retry_options is not None
    assert http_opts.retry_options.attempts == 1
    thinking = client._build_thinking_config()
    assert isinstance(thinking, genai_types.ThinkingConfig)
    config = genai_types.GenerateContentConfig(temperature=0, thinking_config=thinking)
    assert config.thinking_config is not None

    preview_client = GeminiClient(
        api_key="test-key-unused-offline",
        model="gemini-3-flash-preview",
        fallback_model=None,
        thinking_budget=0,
    )
    assert preview_client._resolve_api_version() == "v1beta"
    assert preview_client._client._api_client._http_options.api_version == "v1beta"
    budget_thinking = preview_client._build_thinking_config()
    assert isinstance(budget_thinking, genai_types.ThinkingConfig)
    assert budget_thinking.thinking_budget == 0
    assert budget_thinking.thinking_level is None


def test_gemini_client_validates_config_parameters(monkeypatch):
    _install_fake_gemini(monkeypatch, lambda **kwargs: SimpleNamespace(text="ok"))
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    for bad_kwargs in (
        {"timeout_ms": 0},
        {"timeout_ms": -5},
        {"timeout_ms": True},
        {"max_retries": -1},
        {"max_retries": False},
        {"retry_backoff_s": -1.0},
        {"retry_backoff_s": float("inf")},
        {"thinking_budget": -2},
        {"thinking_level": "  "},
        {"api_version": " "},
    ):
        with pytest.raises(LLMConfigurationError):
            GeminiClient(**bad_kwargs)


def test_gemini_client_package_and_monolith_parity(monkeypatch, tmp_path):
    from mp_ocr.cache import CachedLLMClient as PackageCachedLLMClient
    from mp_ocr.clients import GeminiClient as PackageGeminiClient

    from metesparser.llm_cache import CachedLLMClient as MonolithCachedLLMClient

    _install_fake_gemini(monkeypatch, lambda **kwargs: SimpleNamespace(text="ok"))
    pkg_low = PackageGeminiClient(api_key="k", thinking_level="low")
    mono_low = GeminiClient(api_key="k", thinking_level="LOW")
    assert pkg_low.fallback_model == mono_low.fallback_model == "gemini-3.8-flash"
    assert pkg_low.thinking_level == mono_low.thinking_level == "LOW"
    assert PackageCachedLLMClient(pkg_low, tmp_path / "c")._cache_key(
        "prompt", None
    ) == MonolithCachedLLMClient(mono_low, tmp_path / "c")._cache_key("prompt", None)

    pkg_high = PackageGeminiClient(api_key="k", thinking_level="HIGH")
    assert PackageCachedLLMClient(pkg_low, tmp_path / "c")._cache_key(
        "prompt", None
    ) != PackageCachedLLMClient(pkg_high, tmp_path / "c")._cache_key("prompt", None)
