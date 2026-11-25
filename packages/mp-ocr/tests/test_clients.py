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
