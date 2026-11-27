from __future__ import annotations

import base64
import json
import sys
from types import ModuleType, SimpleNamespace

import pytest

from metesparser.llm_clients import (
    GeminiClient,
    LLMClientError,
    LLMConfigurationError,
    OpenAIClient,
    OpenRouterClient,
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
        def __init__(self, api_key: str, http_options=None):
            self.api_key = api_key
            self.http_options = http_options
            init_options.append(http_options)
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

    init_options: list[object] = []

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
    types_module.HttpOptions = lambda **kwargs: SimpleNamespace(**kwargs)

    genai_module.Client = FakeClient
    genai_module.errors = errors_module
    genai_module.types = types_module
    genai_module._captured_http_options = init_options

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


def test_gemini_client_failover_and_retry_with_real_sdk_api_errors(monkeypatch):
    from google.genai import errors as genai_errors

    seen: list[str] = []
    sleeps: list[float] = []
    monkeypatch.setattr("metesparser.llm_clients.time.sleep", sleeps.append)

    def fake_generate(*, model: str, contents: object, config: object) -> object:
        seen.append(model)
        if len(seen) == 1:
            raise genai_errors.ClientError(
                429, {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}}
            )
        if len(seen) == 2:
            raise genai_errors.ServerError(
                503, {"error": {"code": 503, "message": "busy", "status": "UNAVAILABLE"}}
            )
        return SimpleNamespace(text="recovered on round 2", candidates=[])

    client = GeminiClient(api_key="test-key-unused-offline", max_retries=1, retry_backoff_s=0.5)
    monkeypatch.setattr(client._client.models, "generate_content", fake_generate)
    assert client.generate_text("hello") == "recovered on round 2"
    assert seen == ["gemini-3.6-flash", "gemini-3.8-flash", "gemini-3.6-flash"]
    assert sleeps == [0.5]


@pytest.mark.parametrize(
    ("bad_kwargs", "expected_match"),
    [
        ({"timeout_ms": 0}, "timeout_ms must be a positive integer"),
        ({"timeout_ms": -5}, "timeout_ms must be a positive integer"),
        ({"timeout_ms": True}, "timeout_ms must be a positive integer"),
        ({"max_retries": -1}, "max_retries must be a non-negative integer"),
        ({"max_retries": False}, "max_retries must be a non-negative integer"),
        ({"retry_backoff_s": -1.0}, "retry_backoff_s must be a non-negative finite number"),
        ({"retry_backoff_s": float("inf")}, "retry_backoff_s must be a non-negative finite number"),
        ({"thinking_budget": -2}, "thinking_budget must be >= -1"),
        ({"thinking_level": "  "}, "thinking_level must be a non-empty string or None"),
        ({"api_version": " "}, "api_version must be a non-empty string or None"),
    ],
)
def test_gemini_client_validates_config_parameters(monkeypatch, bad_kwargs, expected_match):
    _install_fake_gemini(monkeypatch, lambda **kwargs: SimpleNamespace(text="ok"))
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    with pytest.raises(LLMConfigurationError, match=expected_match):
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


def test_openrouter_client_real_openai_sdk_construction_and_parity(tmp_path):
    from mp_ocr.cache import CachedLLMClient as PackageCachedLLMClient
    from mp_ocr.clients import OpenRouterClient as PackageOpenRouterClient

    from metesparser.llm_cache import CachedLLMClient as MonolithCachedLLMClient

    mono = OpenRouterClient(
        api_key="or-test-key-offline",
        pdf_engine="mistral-ocr",
        reasoning_effort="low",
    )
    pkg = PackageOpenRouterClient(
        api_key="or-test-key-offline",
        pdf_engine="mistral-ocr",
        reasoning_effort="LOW",
    )
    assert mono.model == pkg.model == "anthropic/claude-haiku-5.5"
    assert mono.fallback_model == pkg.fallback_model == "anthropic/claude-sonnet-5.5"
    assert mono.reasoning_effort == pkg.reasoning_effort == "low"
    assert "or-test-key-offline" not in repr(mono)
    assert str(mono._client.base_url).rstrip("/") == "https://openrouter.ai/api/v1"
    assert mono._client.max_retries == 0
    assert PackageCachedLLMClient(pkg, tmp_path / "c")._cache_key(
        "prompt", None
    ) == MonolithCachedLLMClient(mono, tmp_path / "c")._cache_key("prompt", None)


def test_openrouter_client_monolith_pdf_failover_and_missing_key(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(LLMConfigurationError, match="OPENROUTER_API_KEY"):
        OpenRouterClient()

    calls: list[dict[str, object]] = []
    sleeps: list[float] = []
    monkeypatch.setattr("metesparser.llm_clients.time.sleep", sleeps.append)

    class FakeStatusError(Exception):
        def __init__(self, status_code: int) -> None:
            super().__init__(f"status {status_code}")
            self.status_code = status_code

    class FakeCompletions:
        def create(self, **kwargs: object) -> object:
            calls.append(kwargs)
            if kwargs["model"] == "anthropic/claude-haiku-5.5":
                raise FakeStatusError(503)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="fallback ok"))]
            )

    module = ModuleType("openai")
    module.OpenAI = lambda **kwargs: SimpleNamespace(  # type: ignore[attr-defined]
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    module.APIStatusError = FakeStatusError  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", module)

    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    client = OpenRouterClient(
        api_key="or-key",
        pdf_engine="native",
    )
    assert client.generate_text_with_pdf("extract", str(pdf)) == "fallback ok"
    assert [c["model"] for c in calls] == [
        "anthropic/claude-haiku-5.5",
        "anthropic/claude-sonnet-5.5",
    ]
    assert sleeps == []
    assert calls[0]["extra_body"] == {
        "plugins": [{"id": "file-parser", "pdf": {"engine": "native"}}],
        "reasoning": {"effort": "low"},
    }


def _install_fake_openrouter_openai(monkeypatch, handler):
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


def test_gemini_client_api_version_override_thinking_none_and_pdf_json(monkeypatch, tmp_path):
    captured_contents: list[object] = []
    captured_configs: list[dict[str, object]] = []

    def handler(*, model, contents, config, client_error, server_error):
        captured_contents.append(contents)
        captured_configs.append(config)
        return SimpleNamespace(text='{"calls": []}', candidates=[])

    # Use real google.genai types to also exercise ThinkingConfig with thinking_level=None
    calls, _, _ = _install_fake_gemini(monkeypatch, handler)
    captured_http_options = sys.modules["google.genai"]._captured_http_options

    explicit_beta = GeminiClient(
        api_key="gm-key",
        api_version=" v1beta ",
        thinking_level=None,
        fallback_model=None,
    )
    assert explicit_beta.api_version == "v1beta"
    assert captured_http_options[-1].api_version == "v1beta"
    assert explicit_beta.generate_text("hello") == '{"calls": []}'
    assert "thinking_config" not in captured_configs[-1]

    pdf = tmp_path / "deed.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

    fake_client = GeminiClient(
        api_key="gm-key",
        api_version="v1",
        thinking_level=None,
    )
    assert captured_http_options[-1].api_version == "v1"
    assert (
        fake_client.generate_text_with_pdf(
            "extract json", str(pdf), response_mime_type="application/json"
        )
        == '{"calls": []}'
    )
    assert calls == ["gemini-3.6-flash", "gemini-3.6-flash"]
    parts = captured_contents[-1][0].parts  # type: ignore[index,attr-defined]
    assert parts[0].data == b"%PDF-1.4\n%%EOF\n"
    assert parts[0].mime_type == "application/pdf"
    assert parts[1].text == "extract json"
    assert captured_configs[-1]["response_mime_type"] == "application/json"
    assert "thinking_config" not in captured_configs[-1]

    with pytest.raises(FileNotFoundError, match="PDF not found"):
        fake_client.generate_text_with_pdf("extract", str(tmp_path / "missing.pdf"))


def test_gemini_client_collect_response_text_skips_empty_candidates_and_empty_fallback(monkeypatch):
    responses = iter(
        [
            SimpleNamespace(
                text="unused",
                candidates=[
                    SimpleNamespace(content=None),
                    SimpleNamespace(content=SimpleNamespace(parts=[])),
                    SimpleNamespace(content=SimpleNamespace(parts=[SimpleNamespace(text="kept")])),
                ],
            ),
            SimpleNamespace(
                text=None,
                candidates=[
                    SimpleNamespace(content=None),
                    SimpleNamespace(content=SimpleNamespace(parts=None)),
                ],
            ),
        ]
    )
    _install_fake_gemini(monkeypatch, lambda **kwargs: next(responses))
    client = GeminiClient(api_key="gm-key", fallback_model=None)

    assert client.generate_text("first") == "kept"
    assert client.generate_text("second") == ""


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"api_key": "or-secret\r\nX-Evil: 1"}, "printable ASCII"),
        ({"api_key": "or-secret-é"}, "printable ASCII"),
        ({"model": "   "}, "model must be a non-empty string"),
        ({"fallback_model": "  "}, "fallback_model must be a non-empty string or None"),
        ({"base_url": "https://openrouter.ai/api/v1\nX: 1"}, "control characters"),
        ({"base_url": "https://openrouter.ai/api /v1"}, "whitespace"),
        ({"base_url": "https://[::1/api/v1"}, "valid http:// or https:// URL"),
        ({"base_url": "https://openrouter.ai:abc/api/v1"}, "valid http:// or https:// URL"),
        ({"base_url": "https://openrouter.ai:0/api/v1"}, "port must be a positive integer"),
        ({"base_url": "ftp://openrouter.ai/api/v1"}, "valid http:// or https:// URL"),
        ({"base_url": "https://"}, "valid http:// or https:// URL"),
        ({"base_url": "http://openrouter.ai/api/v1"}, "https:// for non-loopback"),
        ({"base_url": "https://user:pass@openrouter.ai/api/v1"}, "embedded credentials"),
        ({"base_url": "https://openrouter.ai/api/v1?foo=bar"}, "embedded credentials"),
        ({"base_url": "https://openrouter.ai/api/v1#frag"}, "embedded credentials"),
        ({"pdf_engine": "  "}, "pdf_engine must be a non-empty string or None"),
        ({"reasoning_effort": "  "}, "reasoning_effort must be a non-empty string or None"),
        ({"timeout_s": 0}, "timeout_s must be a positive finite number"),
        ({"timeout_s": True}, "timeout_s must be a positive finite number"),
        ({"timeout_s": float("nan")}, "timeout_s must be a positive finite number"),
        ({"max_retries": -1}, "max_retries must be a non-negative integer"),
        ({"max_retries": True}, "max_retries must be a non-negative integer"),
        ({"max_retries": 1.5}, "max_retries must be a non-negative integer"),
        ({"retry_backoff_s": -0.5}, "retry_backoff_s must be a non-negative finite number"),
        ({"retry_backoff_s": True}, "retry_backoff_s must be a non-negative finite number"),
        ({"retry_backoff_s": float("inf")}, "retry_backoff_s must be a non-negative finite number"),
        ({"site_url": "https://example.com\r\nX: 1"}, "printable ASCII"),
        ({"site_url": "https://exämple.com"}, "printable ASCII"),
        ({"site_url": "https://example.com/my app"}, "whitespace"),
        ({"site_url": "https://[::1/app"}, "valid http:// or https:// URL without credentials"),
        ({"site_url": "https://example.com:0"}, "site_url port must be a positive integer"),
        ({"site_url": "ftp://example.com"}, "valid http:// or https:// URL without credentials"),
        (
            {"site_url": "https://user:pass@example.com"},
            "valid http:// or https:// URL without credentials",
        ),
        ({"app_name": "MetesParser\r\nX: 1"}, "printable ASCII"),
        ({"app_name": "MetesParser™"}, "printable ASCII"),
    ],
)
def test_openrouter_client_rejects_invalid_configuration(monkeypatch, kwargs, match):
    _install_fake_openrouter_openai(
        monkeypatch,
        lambda **_: SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
        ),
    )
    params: dict[str, object] = {"api_key": "or-secret", **kwargs}
    with pytest.raises(LLMConfigurationError, match=match):
        OpenRouterClient(**params)  # type: ignore[arg-type]


def test_openrouter_client_site_url_headers_json_format_and_missing_sdk(monkeypatch):
    client_inits, create_calls, _, _ = _install_fake_openrouter_openai(
        monkeypatch,
        lambda **_: SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))]
        ),
    )

    client = OpenRouterClient(
        api_key="or-secret",
        base_url="http://localhost:8080/api/v1/",
        site_url="https://example.com:8443/app",
        app_name="MetesParser",
    )
    assert client.base_url == "http://localhost:8080/api/v1"
    assert client_inits[0]["default_headers"] == {
        "HTTP-Referer": "https://example.com:8443/app",
        "X-Title": "MetesParser",
    }
    assert client.generate_text("parse", response_mime_type="application/json") == '{"ok": true}'
    assert create_calls[0]["response_format"] == {"type": "json_object"}

    # Missing OpenAI callable in openai module raises LLMConfigurationError
    monkeypatch.setitem(sys.modules, "openai", ModuleType("openai"))
    with pytest.raises(LLMConfigurationError, match="openai package not installed"):
        OpenRouterClient(api_key="or-secret")


def test_openrouter_client_json_decode_error_failover_and_exhaustion(monkeypatch):
    def failover_handler(*, kwargs, status_error, timeout_error, connection_error):
        if kwargs["model"] == "anthropic/claude-haiku-5.5":
            raise json.JSONDecodeError("Expecting value", "<html>bad</html>", 0)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="recovered json"))]
        )

    _, failover_calls, _, _ = _install_fake_openrouter_openai(monkeypatch, failover_handler)
    client = OpenRouterClient(api_key="or-secret", max_retries=0)
    assert client.generate_text("hello") == "recovered json"
    assert [c["model"] for c in failover_calls] == [
        "anthropic/claude-haiku-5.5",
        "anthropic/claude-sonnet-5.5",
    ]

    def always_bad_json(*, kwargs, status_error, timeout_error, connection_error):
        raise json.JSONDecodeError("Expecting value", "<html>502</html>", 0)

    _install_fake_openrouter_openai(monkeypatch, always_bad_json)
    exhausted = OpenRouterClient(api_key="or-secret", fallback_model=None, max_retries=0)
    with pytest.raises(LLMClientError, match="invalid JSON") as exc_info:
        exhausted.generate_text("hello")
    assert isinstance(exc_info.value.__cause__, json.JSONDecodeError)


def test_openrouter_client_status_retry_backoff_and_non_retryable(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr("metesparser.llm_clients.time.sleep", sleeps.append)

    # Non-retryable 400 raises immediately with no failover or sleep
    _, err_calls, status_error, _ = _install_fake_openrouter_openai(
        monkeypatch,
        lambda *, status_error, **_: (_ for _ in ()).throw(status_error(400)),
    )
    client_400 = OpenRouterClient(api_key="or-secret", max_retries=2, retry_backoff_s=0.5)
    with pytest.raises(status_error, match="status 400"):
        client_400.generate_text("hello")
    assert [c["model"] for c in err_calls] == ["anthropic/claude-haiku-5.5"]
    assert sleeps == []

    # Retryable 503 across retries sleeps with exponential backoff and re-raises on exhaustion
    _, retry_calls, status_503, _ = _install_fake_openrouter_openai(
        monkeypatch,
        lambda *, status_error, **_: (_ for _ in ()).throw(status_error(503)),
    )
    client_503 = OpenRouterClient(api_key="or-secret", max_retries=2, retry_backoff_s=0.5)
    with pytest.raises(status_503, match="status 503"):
        client_503.generate_text("hello")
    assert len(retry_calls) == 6
    assert sleeps == [0.5, 1.0]


@pytest.mark.parametrize(
    ("bad_response", "expected_match", "should_failover"),
    [
        ("<html>502 Bad Gateway</html>", "unexpected response payload", True),
        (None, "unexpected response payload", True),
        ([], "unexpected response payload", True),
        (
            SimpleNamespace(choices=[], error={"code": 502, "message": "upstream bad gateway"}),
            "code=502.*upstream bad gateway",
            True,
        ),
        (
            SimpleNamespace(
                choices=[], error=SimpleNamespace(code="503", message="upstream unavailable")
            ),
            "code=503.*upstream unavailable",
            True,
        ),
        (
            SimpleNamespace(choices=[], error={"code": 400, "message": "invalid parameter"}),
            "code=400.*invalid parameter",
            False,
        ),
        (
            SimpleNamespace(choices=[], error={"code": "ERR_BAD", "message": ""}),
            "ERR_BAD",
            False,
        ),
        (
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason="error",
                        message=SimpleNamespace(content=""),
                    )
                ]
            ),
            "finish_reason=error.*upstream completion failed",
            True,
        ),
    ],
)
def test_openrouter_client_http200_error_payload_handling(
    monkeypatch, bad_response, expected_match, should_failover
):
    def failover_handler(*, kwargs, status_error, timeout_error, connection_error):
        if kwargs["model"] == "anthropic/claude-haiku-5.5":
            return bad_response
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="fallback ok"))]
        )

    _, failover_calls, _, _ = _install_fake_openrouter_openai(monkeypatch, failover_handler)
    client = OpenRouterClient(api_key="or-secret", max_retries=0)
    if should_failover:
        assert client.generate_text("hello") == "fallback ok"
        assert [c["model"] for c in failover_calls] == [
            "anthropic/claude-haiku-5.5",
            "anthropic/claude-sonnet-5.5",
        ]
    else:
        with pytest.raises(LLMClientError, match=expected_match):
            client.generate_text("hello")
        assert [c["model"] for c in failover_calls] == ["anthropic/claude-haiku-5.5"]

    # Always returning the error exhausts and raises LLMClientError
    _install_fake_openrouter_openai(monkeypatch, lambda **_: bad_response)
    exhausted = OpenRouterClient(api_key="or-secret", fallback_model=None, max_retries=0)
    with pytest.raises(LLMClientError, match=expected_match):
        exhausted.generate_text("hello")


def test_openrouter_client_collect_response_text_filters_reasoning_and_handles_empty(monkeypatch):
    responses = iter(
        [
            SimpleNamespace(choices=[]),
            SimpleNamespace(choices=[SimpleNamespace(message=None)]),
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None))]),
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=[
                                {"type": "thinking", "text": "skip-1"},
                                {"type": "reasoning", "text": "skip-2"},
                                {"type": "reasoning_text", "text": "skip-3"},
                                {"type": "thinking_delta", "text": "skip-4"},
                                SimpleNamespace(type="reasoning_summary", text="skip-5"),
                                {"type": "text", "text": "clean "},
                                SimpleNamespace(type="text", text="deed"),
                            ]
                        )
                    )
                ]
            ),
        ]
    )
    _install_fake_openrouter_openai(monkeypatch, lambda **_: next(responses))
    client = OpenRouterClient(api_key="or-secret", fallback_model=None, max_retries=0)
    assert client.generate_text("p1") == ""
    assert client.generate_text("p2") == ""
    assert client.generate_text("p3") == ""
    assert client.generate_text("p4") == "clean deed"
