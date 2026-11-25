"""Mocked behavioral tests for mp_ocr clients, configuration errors, and caching."""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import httpx
import pytest
from mp_ocr import (
    BaseLLMClient,
    CachedLLMClient,
    GeminiClient,
    LLMClientError,
    LLMConfigurationError,
    OpenAIClient,
    OpenRouterClient,
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
        if model == "gemini-3.6-flash":
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
    assert calls == ["gemini-3.6-flash", "gemini-3.8-flash"]


def test_gemini_client_propagates_non_retryable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(*, model, contents, config, client_error, server_error):
        raise client_error(400)

    _, client_error, _ = _install_fake_gemini(monkeypatch, handler)
    client = GeminiClient(api_key="gm-secret")
    with pytest.raises(client_error, match="client 400"):
        client.generate_text("hello")


def test_gemini_client_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(LLMConfigurationError, match="GEMINI_API_KEY"):
        GeminiClient()


def test_gemini_client_generates_text_with_pdf_and_missing_pdf_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: list[object] = []

    def handler(*, model, contents, config, client_error, server_error):
        captured.append(contents)
        return SimpleNamespace(text="extracted deed text", candidates=[])

    calls, _, _ = _install_fake_gemini(monkeypatch, handler)
    pdf = tmp_path / "deed.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

    client = GeminiClient(api_key="gm-secret")
    assert client.generate_text_with_pdf("read pdf", str(pdf)) == "extracted deed text"
    assert calls == ["gemini-3.6-flash"]
    parts = captured[0][0].parts  # type: ignore[index,attr-defined]
    assert parts[0].data == b"%PDF-1.4\n%%EOF\n"
    assert parts[0].mime_type == "application/pdf"
    assert parts[1].text == "read pdf"

    with pytest.raises(FileNotFoundError, match="PDF not found"):
        client.generate_text_with_pdf("read pdf", str(tmp_path / "missing.pdf"))


def test_gemini_client_fallback_exhaustion_raises_after_trying_all_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(*, model, contents, config, client_error, server_error):
        raise server_error(503)

    sleeps: list[float] = []
    monkeypatch.setattr("mp_ocr.clients.time.sleep", sleeps.append)

    calls, _, server_error = _install_fake_gemini(monkeypatch, handler)
    client = GeminiClient(api_key="gm-secret")
    with pytest.raises(server_error, match="server 503"):
        client.generate_text("hello")
    assert calls == [
        "gemini-3.6-flash",
        "gemini-3.8-flash",
        "gemini-3.6-flash",
        "gemini-3.8-flash",
        "gemini-3.6-flash",
        "gemini-3.8-flash",
    ]
    assert sleeps == [1.0, 2.0]


def test_gemini_client_http_options_thinking_config_and_thought_filtering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_client_kwargs: list[dict[str, object]] = []
    captured_configs: list[dict[str, object]] = []

    google_module = ModuleType("google")
    genai_module = ModuleType("google.genai")
    errors_module = ModuleType("google.genai.errors")
    types_module = ModuleType("google.genai.types")

    class FakeClientError(Exception):
        def __init__(self, status_code: int) -> None:
            super().__init__(f"client {status_code}")
            self.status_code = status_code

    class FakeServerError(Exception):
        def __init__(self, status_code: int) -> None:
            super().__init__(f"server {status_code}")
            self.status_code = status_code

    class GuardedResponse:
        def __init__(self, parts: list[object]) -> None:
            self.candidates = [SimpleNamespace(content=SimpleNamespace(parts=parts))]

        @property
        def text(self) -> str:
            raise AssertionError("response.text must not be accessed when candidate parts exist")

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            captured_client_kwargs.append(kwargs)
            self.models = SimpleNamespace(
                generate_content=lambda *, model, contents, config: (
                    captured_configs.append(config),
                    GuardedResponse(
                        [
                            SimpleNamespace(thought=True, text="internal chain of thought"),
                            SimpleNamespace(thought_signature=b"sig", text=None),
                            SimpleNamespace(thought=False, text="clean deed text"),
                        ]
                    ),
                )[1]
            )

    errors_module.ClientError = FakeClientError  # type: ignore[attr-defined]
    errors_module.ServerError = FakeServerError  # type: ignore[attr-defined]
    types_module.Part = SimpleNamespace(from_text=lambda *, text: SimpleNamespace(text=text))  # type: ignore[attr-defined]
    types_module.Content = lambda *, role, parts: SimpleNamespace(role=role, parts=parts)  # type: ignore[attr-defined]
    types_module.HttpOptions = lambda **kwargs: {"http_options": kwargs}  # type: ignore[attr-defined]
    types_module.HttpRetryOptions = lambda **kwargs: {"retry_options": kwargs}  # type: ignore[attr-defined]
    types_module.ThinkingConfig = lambda **kwargs: {"thinking_config": kwargs}  # type: ignore[attr-defined]
    types_module.GenerateContentConfig = lambda **kwargs: kwargs  # type: ignore[attr-defined]
    genai_module.Client = FakeClient  # type: ignore[attr-defined]
    genai_module.errors = errors_module  # type: ignore[attr-defined]
    genai_module.types = types_module  # type: ignore[attr-defined]
    google_module.genai = genai_module  # type: ignore[attr-defined]
    google_module.__path__ = []  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "google", google_module)
    monkeypatch.setitem(sys.modules, "google.genai", genai_module)
    monkeypatch.setitem(sys.modules, "google.genai.errors", errors_module)
    monkeypatch.setitem(sys.modules, "google.genai.types", types_module)

    # Default: GA primary + fallback -> omits api_version (uses v1), 120s timeout, single SDK attempt, thinking_level=LOW
    default_client = GeminiClient(api_key="gm-secret")
    assert default_client.generate_text("hello") == "clean deed text"
    assert captured_client_kwargs[-1]["http_options"] == {
        "http_options": {
            "timeout": 120_000,
            "retry_options": {"retry_options": {"attempts": 1}},
        }
    }
    assert captured_configs[-1]["thinking_config"] == {"thinking_config": {"thinking_level": "LOW"}}

    # Preview model -> auto-selects v1beta; thinking_budget overrides default thinking_level
    preview_client = GeminiClient(
        api_key="gm-secret",
        model="gemini-3-flash-preview",
        fallback_model="gemini-3.8-flash",
        thinking_budget=0,
        timeout_ms=45_000,
    )
    assert preview_client.generate_text("hello") == "clean deed text"
    assert captured_client_kwargs[-1]["http_options"] == {
        "http_options": {
            "api_version": "v1beta",
            "timeout": 45_000,
            "retry_options": {"retry_options": {"attempts": 1}},
        }
    }
    assert captured_configs[-1]["thinking_config"] == {"thinking_config": {"thinking_budget": 0}}

    # thinking_level=None omits thinking_config; lowercase level is normalized
    unbounded_client = GeminiClient(
        api_key="gm-secret",
        model="gemini-3.8-flash",
        fallback_model=None,
        thinking_level=None,
        api_version="v1",
        timeout_ms=None,
    )
    assert unbounded_client.generate_text("hello") == "clean deed text"
    assert captured_client_kwargs[-1]["http_options"] == {
        "http_options": {
            "api_version": "v1",
            "retry_options": {"retry_options": {"attempts": 1}},
        }
    }
    assert "thinking_config" not in captured_configs[-1]

    minimal_client = GeminiClient(api_key="gm-secret", thinking_level=" minimal ")
    assert minimal_client.thinking_level == "MINIMAL"
    assert minimal_client.generate_text("hello") == "clean deed text"
    assert captured_configs[-1]["thinking_config"] == {
        "thinking_config": {"thinking_level": "MINIMAL"}
    }


def test_gemini_client_single_model_retries_with_backoff_and_validates_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = {"count": 0}

    def handler(*, model, contents, config, client_error, server_error):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise server_error(503)
        return SimpleNamespace(text="recovered", candidates=[])

    sleeps: list[float] = []
    monkeypatch.setattr("mp_ocr.clients.time.sleep", sleeps.append)
    calls, _, _ = _install_fake_gemini(monkeypatch, handler)

    client = GeminiClient(
        api_key="gm-secret",
        fallback_model=None,
        max_retries=2,
        retry_backoff_s=0.5,
    )
    assert client.generate_text("hello") == "recovered"
    assert calls == ["gemini-3.6-flash"] * 3
    assert sleeps == [0.5, 1.0]

    for bad_kwargs in (
        {"timeout_ms": 0},
        {"timeout_ms": True},
        {"max_retries": -1},
        {"retry_backoff_s": -0.1},
        {"retry_backoff_s": float("nan")},
        {"thinking_budget": -2},
        {"thinking_level": "   "},
        {"api_version": ""},
    ):
        with pytest.raises(LLMConfigurationError):
            GeminiClient(api_key="gm-secret", **bad_kwargs)  # type: ignore[arg-type]


def test_cached_client_separates_gemini_thinking_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_fake_gemini(monkeypatch, lambda **kwargs: SimpleNamespace(text="ok", candidates=[]))
    low_a = CachedLLMClient(
        GeminiClient(api_key="k", thinking_level="low"), cache_dir=tmp_path / "cache"
    )
    low_b = CachedLLMClient(
        GeminiClient(api_key="k", thinking_level="LOW"), cache_dir=tmp_path / "cache"
    )
    high = CachedLLMClient(
        GeminiClient(api_key="k", thinking_level="HIGH"), cache_dir=tmp_path / "cache"
    )
    budget = CachedLLMClient(
        GeminiClient(api_key="k", thinking_budget=0), cache_dir=tmp_path / "cache"
    )

    assert low_a._cache_key("p", None) == low_b._cache_key("p", None)
    assert low_a._cache_key("p", None) != high._cache_key("p", None)
    assert low_a._cache_key("p", None) != budget._cache_key("p", None)


def test_gemini_client_handles_real_sdk_error_code_attribute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from google.genai import errors as genai_errors

    seen_models: list[str] = []

    def fake_generate(*, model: str, contents: object, config: object) -> object:
        seen_models.append(model)
        if model == "gemini-3.6-flash":
            raise genai_errors.ClientError(
                429, {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}}
            )
        return SimpleNamespace(text="served by fallback", candidates=[])

    client = GeminiClient(api_key="test-key-unused-offline", max_retries=0)
    monkeypatch.setattr(client._client.models, "generate_content", fake_generate)
    assert client.generate_text("hello") == "served by fallback"
    assert seen_models == ["gemini-3.6-flash", "gemini-3.8-flash"]


def test_openai_client_generate_text_with_pdf_missing_file_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_fake_openai(monkeypatch)
    client = OpenAIClient(api_key="sk-secret")
    with pytest.raises(FileNotFoundError, match="PDF not found"):
        client.generate_text_with_pdf("read", str(tmp_path / "does_not_exist.pdf"))


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


def _install_fake_openrouter_openai(monkeypatch: pytest.MonkeyPatch, handler):
    module = ModuleType("openai")
    client_inits: list[dict[str, object]] = []
    create_calls: list[dict[str, object]] = []

    class FakeAPIStatusError(Exception):
        def __init__(self, status_code: int) -> None:
            super().__init__(f"status {status_code}")
            self.status_code = status_code

    class FakeAPITimeoutError(Exception):
        pass

    class FakeAPIConnectionError(Exception):
        pass

    class FakeCompletions:
        def create(self, **kwargs: object) -> object:
            create_calls.append(kwargs)
            return handler(
                kwargs=kwargs,
                status_error=FakeAPIStatusError,
                timeout_error=FakeAPITimeoutError,
                connection_error=FakeAPIConnectionError,
            )

    class FakeOpenAI:
        def __init__(self, **kwargs: object) -> None:
            client_inits.append(kwargs)
            self.chat = SimpleNamespace(completions=FakeCompletions())

    module.OpenAI = FakeOpenAI  # type: ignore[attr-defined]
    module.APIStatusError = FakeAPIStatusError  # type: ignore[attr-defined]
    module.APITimeoutError = FakeAPITimeoutError  # type: ignore[attr-defined]
    module.APIConnectionError = FakeAPIConnectionError  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", module)
    return client_inits, create_calls, FakeAPIStatusError, FakeAPITimeoutError


def test_openrouter_client_requires_api_key_and_validates_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(LLMConfigurationError, match="OPENROUTER_API_KEY"):
        OpenRouterClient()

    _install_fake_openrouter_openai(
        monkeypatch,
        lambda **kwargs: SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
        ),
    )
    for bad_kwargs in (
        {"model": "   "},
        {"fallback_model": ""},
        {"base_url": "ftp://openrouter.ai/api/v1"},
        {"pdf_engine": "  "},
        {"reasoning_effort": " "},
        {"timeout_s": 0},
        {"timeout_s": True},
        {"timeout_s": float("nan")},
        {"max_retries": -1},
        {"retry_backoff_s": -0.5},
    ):
        with pytest.raises(LLMConfigurationError):
            OpenRouterClient(api_key="or-secret", **bad_kwargs)  # type: ignore[arg-type]


def test_openrouter_client_text_pdf_plugins_headers_and_redaction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def handler(*, kwargs, status_error, timeout_error, connection_error):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=[
                            {"type": "reasoning", "text": "private thought"},
                            {"type": "text", "text": "extracted "},
                            {"type": "text", "text": "deed text"},
                        ]
                    )
                )
            ]
        )

    client_inits, create_calls, _, _ = _install_fake_openrouter_openai(monkeypatch, handler)
    pdf = tmp_path / "deed.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

    client = OpenRouterClient(
        api_key="or-secret-value",
        model="google/gemini-3.8-flash",
        pdf_engine="mistral-ocr",
        reasoning_effort=" LOW ",
        site_url="https://example.com",
    )
    assert "or-secret-value" not in repr(client)
    assert "_client=" not in repr(client)
    assert client.reasoning_effort == "low"
    with pytest.raises(TypeError):
        OpenRouterClient(api_key="or-secret-value", _client=object())  # type: ignore[call-arg]

    assert client_inits[0]["base_url"] == "https://openrouter.ai/api/v1"
    assert client_inits[0]["max_retries"] == 0
    assert client_inits[0]["timeout"] == 120.0
    assert client_inits[0]["default_headers"] == {
        "HTTP-Referer": "https://example.com",
        "X-Title": "MetesParser",
    }

    # Text call includes reasoning extra_body + json response_format, but NOT file-parser plugin
    assert client.generate_text("parse", response_mime_type="application/json") == (
        "extracted deed text"
    )
    text_call = create_calls[0]
    assert text_call["model"] == "google/gemini-3.8-flash"
    assert text_call["response_format"] == {"type": "json_object"}
    assert text_call["extra_body"] == {"reasoning": {"effort": "low"}}

    # PDF call attaches inline base64 file block AND file-parser plugin
    assert client.generate_text_with_pdf("read pdf", str(pdf)) == "extracted deed text"
    pdf_call = create_calls[1]
    content = pdf_call["messages"][0]["content"]  # type: ignore[index]
    assert content[0]["type"] == "file"
    assert content[0]["file"]["filename"] == "deed.pdf"
    file_data = content[0]["file"]["file_data"]
    assert file_data.startswith("data:application/pdf;base64,")
    assert base64.b64decode(file_data.split(",", 1)[1]) == b"%PDF-1.4\n%%EOF\n"
    assert content[1] == {"type": "text", "text": "read pdf"}
    assert pdf_call["extra_body"] == {
        "plugins": [{"id": "file-parser", "pdf": {"engine": "mistral-ocr"}}],
        "reasoning": {"effort": "low"},
    }

    with pytest.raises(FileNotFoundError, match="PDF not found"):
        client.generate_text_with_pdf("read pdf", str(tmp_path / "missing.pdf"))


def test_openrouter_client_retries_failover_and_propagates_non_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = {"n": 0}

    def handler(*, kwargs, status_error, timeout_error, connection_error):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise status_error(429)
        if attempts["n"] == 2:
            raise timeout_error("timed out")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])

    sleeps: list[float] = []
    monkeypatch.setattr("mp_ocr.clients.time.sleep", sleeps.append)
    _, create_calls, status_error, _ = _install_fake_openrouter_openai(monkeypatch, handler)

    client = OpenRouterClient(
        api_key="or-secret",
        model="google/gemini-3.6-flash",
        fallback_model="google/gemini-3.8-flash",
        max_retries=1,
        retry_backoff_s=0.5,
    )
    assert client.generate_text("hello") == "ok"
    assert [c["model"] for c in create_calls] == [
        "google/gemini-3.6-flash",
        "google/gemini-3.8-flash",
        "google/gemini-3.6-flash",
    ]
    assert sleeps == [0.5]

    # Non-retryable 400 raises immediately with no sleep or fallback
    def bad_request(*, kwargs, status_error, timeout_error, connection_error):
        raise status_error(400)

    _, err_calls, bad_status_error, _ = _install_fake_openrouter_openai(monkeypatch, bad_request)
    sleeps.clear()
    client_400 = OpenRouterClient(
        api_key="or-secret",
        model="google/gemini-3.6-flash",
        fallback_model="google/gemini-3.8-flash",
    )
    with pytest.raises(bad_status_error, match="status 400"):
        client_400.generate_text("hello")
    assert [c["model"] for c in err_calls] == ["google/gemini-3.6-flash"]
    assert sleeps == []


def test_cached_client_separates_openrouter_pdf_engine_and_reasoning_effort(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_fake_openrouter_openai(
        monkeypatch,
        lambda **kwargs: SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
        ),
    )
    c_default = CachedLLMClient(OpenRouterClient(api_key="k"), cache_dir=tmp_path / "cache")
    c_mistral = CachedLLMClient(
        OpenRouterClient(api_key="k", pdf_engine="mistral-ocr"), cache_dir=tmp_path / "cache"
    )
    c_none = CachedLLMClient(
        OpenRouterClient(api_key="k", reasoning_effort=None), cache_dir=tmp_path / "cache"
    )
    c_low_upper = CachedLLMClient(
        OpenRouterClient(api_key="k", reasoning_effort="LOW"), cache_dir=tmp_path / "cache"
    )

    assert c_default._cache_key("p", None) != c_mistral._cache_key("p", None)
    assert c_default._cache_key("p", None) != c_none._cache_key("p", None)
    assert c_default._cache_key("p", None) == c_low_upper._cache_key("p", None)


def test_openrouter_client_http200_response_error_retryable_fails_over(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(*, kwargs, status_error, timeout_error, connection_error):
        if kwargs["model"] == "anthropic/claude-haiku-5.5":
            return SimpleNamespace(
                choices=[],
                error={"code": 502, "message": "upstream bad gateway"},
            )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="fallback ok"))]
        )

    sleeps: list[float] = []
    monkeypatch.setattr("mp_ocr.clients.time.sleep", sleeps.append)
    _, create_calls, _, _ = _install_fake_openrouter_openai(monkeypatch, handler)

    client = OpenRouterClient(api_key="or-secret")
    assert client.generate_text("hello") == "fallback ok"
    assert [c["model"] for c in create_calls] == [
        "anthropic/claude-haiku-5.5",
        "anthropic/claude-sonnet-5.5",
    ]
    assert sleeps == []


def test_openrouter_client_http200_response_error_string_code_object_fails_over(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(*, kwargs, status_error, timeout_error, connection_error):
        if kwargs["model"] == "anthropic/claude-haiku-5.5":
            return SimpleNamespace(
                choices=[],
                error=SimpleNamespace(code="503", message="upstream unavailable"),
            )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="recovered"))]
        )

    _, create_calls, _, _ = _install_fake_openrouter_openai(monkeypatch, handler)
    client = OpenRouterClient(api_key="or-secret")
    assert client.generate_text("hello") == "recovered"
    assert [c["model"] for c in create_calls] == [
        "anthropic/claude-haiku-5.5",
        "anthropic/claude-sonnet-5.5",
    ]


def test_openrouter_client_http200_response_error_non_retryable_raises_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(*, kwargs, status_error, timeout_error, connection_error):
        return SimpleNamespace(
            choices=[],
            error={"code": 400, "message": "invalid model parameters"},
        )

    sleeps: list[float] = []
    monkeypatch.setattr("mp_ocr.clients.time.sleep", sleeps.append)
    _, create_calls, _, _ = _install_fake_openrouter_openai(monkeypatch, handler)

    client = OpenRouterClient(api_key="or-secret")
    with pytest.raises(LLMClientError, match="400.*invalid model parameters"):
        client.generate_text("hello")
    assert [c["model"] for c in create_calls] == ["anthropic/claude-haiku-5.5"]
    assert sleeps == []


def test_openrouter_client_http200_finish_reason_error_failover_and_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 1. finish_reason == "error" with no code triggers failover to fallback model
    def failover_handler(*, kwargs, status_error, timeout_error, connection_error):
        if kwargs["model"] == "anthropic/claude-haiku-5.5":
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason="error",
                        message=SimpleNamespace(content=""),
                    )
                ]
            )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content="fallback text"),
                )
            ]
        )

    _, failover_calls, _, _ = _install_fake_openrouter_openai(monkeypatch, failover_handler)
    client = OpenRouterClient(api_key="or-secret", max_retries=0)
    assert client.generate_text("hello") == "fallback text"
    assert [c["model"] for c in failover_calls] == [
        "anthropic/claude-haiku-5.5",
        "anthropic/claude-sonnet-5.5",
    ]

    # 2. Persistent finish_reason == "error" exhausts retries and raises LLMClientError (never "")
    def always_error_handler(*, kwargs, status_error, timeout_error, connection_error):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="error",
                    error={"code": 503, "message": "provider overloaded"},
                    message=SimpleNamespace(content=""),
                )
            ]
        )

    sleeps: list[float] = []
    monkeypatch.setattr("mp_ocr.clients.time.sleep", sleeps.append)
    _, exhausted_calls, _, _ = _install_fake_openrouter_openai(monkeypatch, always_error_handler)
    exhausted_client = OpenRouterClient(api_key="or-secret", max_retries=1, retry_backoff_s=0.5)
    with pytest.raises(LLMClientError, match="503.*provider overloaded"):
        exhausted_client.generate_text("hello")
    assert [c["model"] for c in exhausted_calls] == [
        "anthropic/claude-haiku-5.5",
        "anthropic/claude-sonnet-5.5",
        "anthropic/claude-haiku-5.5",
        "anthropic/claude-sonnet-5.5",
    ]
    assert sleeps == [0.5]

    # 3. Choice-level non-retryable error raises immediately without failover
    def choice_401_handler(*, kwargs, status_error, timeout_error, connection_error):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="error",
                    error={"code": 401, "message": "invalid credentials"},
                    message=SimpleNamespace(content=""),
                )
            ]
        )

    sleeps.clear()
    _, auth_calls, _, _ = _install_fake_openrouter_openai(monkeypatch, choice_401_handler)
    auth_client = OpenRouterClient(api_key="or-secret")
    with pytest.raises(LLMClientError, match="401.*invalid credentials"):
        auth_client.generate_text("hello")
    assert [c["model"] for c in auth_calls] == ["anthropic/claude-haiku-5.5"]
    assert sleeps == []


def test_cached_client_does_not_cache_openrouter_http200_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state = {"fail": True}

    def handler(*, kwargs, status_error, timeout_error, connection_error):
        if state["fail"]:
            return SimpleNamespace(
                choices=[],
                error={"code": 400, "message": "bad payload"},
            )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="clean text"))]
        )

    _, create_calls, _, _ = _install_fake_openrouter_openai(monkeypatch, handler)
    cache_dir = tmp_path / "cache"
    cached = CachedLLMClient(OpenRouterClient(api_key="or-secret"), cache_dir=cache_dir)

    with pytest.raises(LLMClientError, match="bad payload"):
        cached.generate_text("same prompt")
    assert list(cache_dir.glob("*.json")) == []

    state["fail"] = False
    assert cached.generate_text("same prompt") == "clean text"
    assert cached.generate_text("same prompt") == "clean text"
    assert len(create_calls) == 2


@pytest.mark.parametrize("retryable_code", [408, 409, 429, 500, 502, 503, 504, 529])
def test_openrouter_client_retries_expanded_transient_status_codes(
    monkeypatch: pytest.MonkeyPatch, retryable_code: int
) -> None:
    def handler(*, kwargs, status_error, timeout_error, connection_error):
        if kwargs["model"] == "anthropic/claude-haiku-5.5":
            raise status_error(retryable_code)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])

    _, create_calls, _, _ = _install_fake_openrouter_openai(monkeypatch, handler)
    client = OpenRouterClient(api_key="or-secret", max_retries=0)
    assert client.generate_text("hello") == "ok"
    assert [c["model"] for c in create_calls] == [
        "anthropic/claude-haiku-5.5",
        "anthropic/claude-sonnet-5.5",
    ]


@pytest.mark.parametrize("non_retryable_code", [400, 401, 402, 403, 404, 422])
def test_openrouter_client_does_not_retry_non_retryable_status_codes(
    monkeypatch: pytest.MonkeyPatch, non_retryable_code: int
) -> None:
    def handler(*, kwargs, status_error, timeout_error, connection_error):
        raise status_error(non_retryable_code)

    sleeps: list[float] = []
    monkeypatch.setattr("mp_ocr.clients.time.sleep", sleeps.append)
    _, create_calls, status_error, _ = _install_fake_openrouter_openai(monkeypatch, handler)

    client = OpenRouterClient(api_key="or-secret")
    with pytest.raises(status_error, match=f"status {non_retryable_code}"):
        client.generate_text("hello")
    assert [c["model"] for c in create_calls] == ["anthropic/claude-haiku-5.5"]
    assert sleeps == []


def test_openrouter_client_retry_exhaustion_backoff_and_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def always_503(*, kwargs, status_error, timeout_error, connection_error):
        raise status_error(503)

    sleeps: list[float] = []
    monkeypatch.setattr("mp_ocr.clients.time.sleep", sleeps.append)
    _, create_calls, status_error, _ = _install_fake_openrouter_openai(monkeypatch, always_503)

    client = OpenRouterClient(api_key="or-secret", max_retries=2, retry_backoff_s=1.0)
    with pytest.raises(status_error, match="status 503"):
        client.generate_text("hello")
    assert [c["model"] for c in create_calls] == [
        "anthropic/claude-haiku-5.5",
        "anthropic/claude-sonnet-5.5",
        "anthropic/claude-haiku-5.5",
        "anthropic/claude-sonnet-5.5",
        "anthropic/claude-haiku-5.5",
        "anthropic/claude-sonnet-5.5",
    ]
    assert sleeps == [1.0, 2.0]

    # APIConnectionError triggers failover and retry
    attempts = {"n": 0}

    def conn_err_handler(*, kwargs, status_error, timeout_error, connection_error):
        attempts["n"] += 1
        if attempts["n"] <= 2:
            raise connection_error("connection reset")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="reconnected"))]
        )

    sleeps.clear()
    _, conn_calls, _, _ = _install_fake_openrouter_openai(monkeypatch, conn_err_handler)
    conn_client = OpenRouterClient(api_key="or-secret", max_retries=1, retry_backoff_s=0.25)
    assert conn_client.generate_text("hello") == "reconnected"
    assert [c["model"] for c in conn_calls] == [
        "anthropic/claude-haiku-5.5",
        "anthropic/claude-sonnet-5.5",
        "anthropic/claude-haiku-5.5",
    ]
    assert sleeps == [0.25]


def test_openrouter_client_fallback_dedup_single_model_and_omits_empty_extra_body(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # 1. fallback_model == model deduplicates to one attempt per round
    def always_503(*, kwargs, status_error, timeout_error, connection_error):
        raise status_error(503)

    sleeps: list[float] = []
    monkeypatch.setattr("mp_ocr.clients.time.sleep", sleeps.append)
    _, dedup_calls, status_error, _ = _install_fake_openrouter_openai(monkeypatch, always_503)

    dedup_client = OpenRouterClient(
        api_key="or-secret",
        model="anthropic/claude-sonnet-5.5",
        fallback_model="anthropic/claude-sonnet-5.5",
        max_retries=1,
        retry_backoff_s=0.5,
    )
    with pytest.raises(status_error, match="status 503"):
        dedup_client.generate_text("hello")
    assert [c["model"] for c in dedup_calls] == [
        "anthropic/claude-sonnet-5.5",
        "anthropic/claude-sonnet-5.5",
    ]
    assert sleeps == [0.5]

    # 2. fallback_model=None retries single model and recovers
    attempts = {"n": 0}

    def single_retry(*, kwargs, status_error, timeout_error, connection_error):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise status_error(502)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="single ok"))]
        )

    sleeps.clear()
    _, single_calls, _, _ = _install_fake_openrouter_openai(monkeypatch, single_retry)
    single_client = OpenRouterClient(
        api_key="or-secret",
        model="anthropic/claude-haiku-5.5",
        fallback_model=None,
        pdf_engine=None,
        reasoning_effort=None,
        max_retries=2,
        retry_backoff_s=0.5,
    )
    assert single_client.generate_text("hello") == "single ok"
    assert [c["model"] for c in single_calls] == ["anthropic/claude-haiku-5.5"] * 3
    assert sleeps == [0.5, 1.0]
    assert "extra_body" not in single_calls[0]

    pdf = tmp_path / "deed.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    assert single_client.generate_text_with_pdf("read", str(pdf)) == "single ok"
    assert "extra_body" not in single_calls[-1]


def test_openrouter_client_collect_response_text_edge_cases() -> None:
    assert OpenRouterClient._collect_response_text(SimpleNamespace(choices=[])) == ""
    assert (
        OpenRouterClient._collect_response_text(
            SimpleNamespace(choices=[SimpleNamespace(message=None)])
        )
        == ""
    )
    assert (
        OpenRouterClient._collect_response_text(
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None))])
        )
        == ""
    )
    assert (
        OpenRouterClient._collect_response_text(
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=[
                                SimpleNamespace(type="thinking", text="secret thought"),
                                SimpleNamespace(type="reasoning", text="more thought"),
                                SimpleNamespace(type="text", text="visible "),
                                SimpleNamespace(type="text", text="answer"),
                            ]
                        )
                    )
                ]
            )
        )
        == "visible answer"
    )


def test_openrouter_client_validation_hardening(monkeypatch: pytest.MonkeyPatch) -> None:
    client_inits, _, _, _ = _install_fake_openrouter_openai(
        monkeypatch,
        lambda **kwargs: SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
        ),
    )

    # Whitespace-only api_key rejected even when env var is populated
    monkeypatch.setenv("OPENROUTER_API_KEY", "valid-env-key")
    with pytest.raises(LLMConfigurationError, match="OPENROUTER_API_KEY"):
        OpenRouterClient(api_key="   \n\t ")

    # Whitespace-only env var rejected
    monkeypatch.setenv("OPENROUTER_API_KEY", "   \n ")
    with pytest.raises(LLMConfigurationError, match="OPENROUTER_API_KEY"):
        OpenRouterClient()

    # Surrounding whitespace/newline trimmed from api_key and trailing slash trimmed from base_url
    client = OpenRouterClient(
        api_key="  or-trimmed-key\n",
        base_url="  https://openrouter.ai/api/v1/  ",
    )
    assert client.base_url == "https://openrouter.ai/api/v1"
    assert client_inits[-1]["api_key"] == "or-trimmed-key"
    assert client_inits[-1]["base_url"] == "https://openrouter.ai/api/v1"

    # Hostless URLs and non-int / bool max_retries rejected
    for bad_kwargs in (
        {"base_url": "https://"},
        {"base_url": "http://"},
        {"base_url": "https:///api/v1"},
        {"max_retries": 1.5},
        {"max_retries": True},
    ):
        with pytest.raises(LLMConfigurationError):
            OpenRouterClient(api_key="or-secret", **bad_kwargs)  # type: ignore[arg-type]


def test_cached_client_openrouter_base_url_and_cross_provider_isolation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_fake_openrouter_openai(
        monkeypatch,
        lambda **kwargs: SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
        ),
    )
    c_default = CachedLLMClient(
        OpenRouterClient(api_key="k", base_url="https://openrouter.ai/api/v1"),
        cache_dir=tmp_path / "cache",
    )
    c_slash = CachedLLMClient(
        OpenRouterClient(api_key="k", base_url="https://openrouter.ai/api/v1/"),
        cache_dir=tmp_path / "cache",
    )
    c_other_host = CachedLLMClient(
        OpenRouterClient(api_key="k", base_url="https://proxy.example.com/api/v1"),
        cache_dir=tmp_path / "cache",
    )
    assert c_default._cache_key("p", None) == c_slash._cache_key("p", None)
    assert c_default._cache_key("p", None) != c_other_host._cache_key("p", None)

    c_openai = CachedLLMClient(
        OpenAIClient(api_key="k", model="gpt-5.2"), cache_dir=tmp_path / "cache"
    )
    c_openrouter_same_slug = CachedLLMClient(
        OpenRouterClient(api_key="k", model="gpt-5.2", fallback_model=None, reasoning_effort=None),
        cache_dir=tmp_path / "cache",
    )
    assert c_openai._cache_key("p", None) != c_openrouter_same_slug._cache_key("p", None)


def test_openrouter_client_strips_openai_org_project_headers_and_webhook_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_ORG_ID", "org-secret-123")
    monkeypatch.setenv("OPENAI_PROJECT_ID", "proj-secret-456")
    monkeypatch.setenv("OPENAI_WEBHOOK_SECRET", "whsec_secret_789")

    captured_headers: dict[str, str] = {}

    def transport_handler(request: httpx.Request) -> httpx.Response:
        captured_headers.update({k.lower(): v for k, v in request.headers.items()})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    client = OpenRouterClient(api_key="or-test")
    assert getattr(client._client, "organization", None) is None
    assert getattr(client._client, "project", None) is None
    assert getattr(client._client, "webhook_secret", None) is None

    client._client._client = httpx.Client(transport=httpx.MockTransport(transport_handler))
    assert client.generate_text("hello") == "ok"
    assert "openai-organization" not in captured_headers
    assert "openai-project" not in captured_headers
    assert captured_headers.get("authorization") == "Bearer or-test"


def test_openrouter_client_security_url_and_header_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_openrouter_openai(
        monkeypatch,
        lambda **kwargs: SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
        ),
    )

    # Loopback HTTP URLs remain permitted for local proxies/tests
    for loopback_url in (
        "http://localhost:11434/api/v1",
        "http://127.0.0.1:8080/api/v1/",
        "http://[::1]:8080/api/v1",
    ):
        c = OpenRouterClient(api_key="or-secret", base_url=loopback_url)
        assert c.base_url == loopback_url.rstrip("/")

    # Remote cleartext HTTP, embedded credentials, query/fragment, and control chars rejected
    for bad_base_url in (
        "http://openrouter.ai/api/v1",
        "http://example.com/api/v1",
        "https://user:pass@openrouter.ai/api/v1",
        "https://user@openrouter.ai/api/v1",
        "https://openrouter.ai/api/v1?foo=bar",
        "https://openrouter.ai/api/v1#section",
        "https://openrouter.ai/api/v1\nX-Injected: 1",
        "https://openrouter.ai/api/v1\x7f",
    ):
        with pytest.raises(LLMConfigurationError):
            OpenRouterClient(api_key="or-secret", base_url=bad_base_url)

    # Control characters / non-ASCII in api_key, site_url, app_name rejected fail-fast
    for bad_key in ("or-secret\r\nX-Evil: 1", "or-secret\x00", "or-secret-é"):
        with pytest.raises(LLMConfigurationError):
            OpenRouterClient(api_key=bad_key)

    for bad_site_url in (
        "https://example.com\r\nX-Evil: 1",
        "https://exämple.com",
        "ftp://example.com",
        "javascript:alert(1)",
        "not-a-url",
        "https://user:pass@example.com",
    ):
        with pytest.raises(LLMConfigurationError):
            OpenRouterClient(api_key="or-secret", site_url=bad_site_url)

    for bad_app_name in ("MetesParser\r\nX-Evil: 1", "MetesParser\x7f", "MetesParser™"):
        with pytest.raises(LLMConfigurationError):
            OpenRouterClient(api_key="or-secret", app_name=bad_app_name)


def test_openrouter_client_http200_sdk_fidelity_edge_cases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 1. json.JSONDecodeError triggers failover and raises LLMClientError on exhaustion
    def decode_err_failover(*, kwargs, status_error, timeout_error, connection_error):
        if kwargs["model"] == "anthropic/claude-haiku-5.5":
            raise json.JSONDecodeError("Expecting value", "<html>bad</html>", 0)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="fallback json ok"))]
        )

    _, failover_calls, _, _ = _install_fake_openrouter_openai(monkeypatch, decode_err_failover)
    client = OpenRouterClient(api_key="or-secret", max_retries=0)
    assert client.generate_text("hello") == "fallback json ok"
    assert [c["model"] for c in failover_calls] == [
        "anthropic/claude-haiku-5.5",
        "anthropic/claude-sonnet-5.5",
    ]

    def always_decode_err(*, kwargs, status_error, timeout_error, connection_error):
        raise json.JSONDecodeError("Expecting value", "<html>bad</html>", 0)

    _install_fake_openrouter_openai(monkeypatch, always_decode_err)
    exhausted_json = OpenRouterClient(api_key="or-secret", fallback_model=None, max_retries=0)
    with pytest.raises(LLMClientError, match="invalid JSON") as exc_info:
        exhausted_json.generate_text("hello")
    assert isinstance(exc_info.value.__cause__, json.JSONDecodeError)

    # 2. HTTP 200 HTML string / bytes / None response treated as retryable LLMClientError
    for bad_payload in ("<html>502 Bad Gateway</html>", b"<html>503</html>", None):

        def bad_payload_failover(
            *, kwargs, status_error, timeout_error, connection_error, payload=bad_payload
        ):
            if kwargs["model"] == "anthropic/claude-haiku-5.5":
                return payload
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="recovered payload"))]
            )

        _, payload_calls, _, _ = _install_fake_openrouter_openai(monkeypatch, bad_payload_failover)
        c_payload = OpenRouterClient(api_key="or-secret", max_retries=0)
        assert c_payload.generate_text("hello") == "recovered payload"
        assert [c["model"] for c in payload_calls] == [
            "anthropic/claude-haiku-5.5",
            "anthropic/claude-sonnet-5.5",
        ]

        _install_fake_openrouter_openai(
            monkeypatch,
            lambda payload=bad_payload, **kwargs: payload,
        )
        c_exhaust = OpenRouterClient(api_key="or-secret", fallback_model=None, max_retries=0)
        with pytest.raises(LLMClientError):
            c_exhaust.generate_text("hello")

    # 3. Empty dict error ({"error": {}}) is still caught and raises LLMClientError (never "")
    _install_fake_openrouter_openai(
        monkeypatch,
        lambda **kwargs: SimpleNamespace(choices=[], error={}),
    )
    c_empty_err = OpenRouterClient(api_key="or-secret", max_retries=0)
    with pytest.raises(LLMClientError):
        c_empty_err.generate_text("hello")

    # 4. Non-list truthy choices does not raise KeyError: 0
    _install_fake_openrouter_openai(
        monkeypatch,
        lambda **kwargs: SimpleNamespace(choices={"unexpected": "dict"}),
    )
    c_dict_choices = OpenRouterClient(api_key="or-secret", max_retries=0)
    assert c_dict_choices.generate_text("hello") == ""

    # 5. Extended reasoning/thinking content block types are skipped
    assert (
        OpenRouterClient._collect_response_text(
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=[
                                {"type": "reasoning_text", "text": "skip-1"},
                                {"type": "reasoning_summary", "text": "skip-2"},
                                {"type": "thinking_delta", "text": "skip-3"},
                                {"type": "text", "text": "kept text"},
                            ]
                        )
                    )
                ]
            )
        )
        == "kept text"
    )


def test_cached_client_does_not_persist_empty_or_whitespace_responses(tmp_path: Path) -> None:
    class FlakyEmptyClient:
        model = "flaky"

        def __init__(self) -> None:
            self.responses = ["", "   \n\t ", "real output"]
            self.calls = 0

        def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
            self.calls += 1
            return self.responses.pop(0)

        def generate_text_with_pdf(
            self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
        ) -> str:
            self.calls += 1
            return self.responses.pop(0)

    cache_dir = tmp_path / "cache"
    text_client = FlakyEmptyClient()
    cached_text = CachedLLMClient(text_client, cache_dir=cache_dir)

    assert cached_text.generate_text("prompt") == ""
    assert list(cache_dir.glob("*.json")) == []
    assert cached_text.generate_text("prompt") == "   \n\t "
    assert list(cache_dir.glob("*.json")) == []
    assert cached_text.generate_text("prompt") == "real output"
    assert len(list(cache_dir.glob("*.json"))) == 1
    assert cached_text.generate_text("prompt") == "real output"
    assert text_client.calls == 3

    pdf_cache_dir = tmp_path / "pdf_cache"
    pdf = tmp_path / "deed.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    pdf_client = FlakyEmptyClient()
    cached_pdf = CachedLLMClient(pdf_client, cache_dir=pdf_cache_dir)

    assert cached_pdf.generate_text_with_pdf("extract", str(pdf)) == ""
    assert list(pdf_cache_dir.glob("*.json")) == []
    assert cached_pdf.generate_text_with_pdf("extract", str(pdf)) == "   \n\t "
    assert list(pdf_cache_dir.glob("*.json")) == []
    assert cached_pdf.generate_text_with_pdf("extract", str(pdf)) == "real output"
    assert len(list(pdf_cache_dir.glob("*.json"))) == 1
    assert cached_pdf.generate_text_with_pdf("extract", str(pdf)) == "real output"
    assert pdf_client.calls == 3
