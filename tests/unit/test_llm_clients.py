from __future__ import annotations

import base64
import io
import json
import sys
from types import ModuleType, SimpleNamespace

import pytest

from metesparser.llm_clients import (
    GeminiClient,
    LLMConfigurationError,
    OpenAIClient,
    _read_pdf,
)
from metesparser.logging_config import configure_logging

pytestmark = pytest.mark.usefixtures("isolate_logging_state")


def _json_log_lines(payload: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in payload.splitlines() if line.strip()]


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


def test_openai_client_emits_failure_telemetry(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    _install_fake_openai(monkeypatch)

    stream = io.StringIO()
    configure_logging(level="DEBUG", log_format="json", stream=stream)

    try:
        client = OpenAIClient()
        client._client.responses.create = lambda **kwargs: (_ for _ in ()).throw(
            RuntimeError("boom")
        )

        with pytest.raises(RuntimeError, match="boom"):
            client.generate_text("hello")
    finally:
        configure_logging(level="INFO", log_format="console", stream=io.StringIO())

    lines = [
        line
        for line in _json_log_lines(stream.getvalue())
        if line.get("logger") == "metesparser.llm_clients"
    ]
    failure = next(line for line in lines if line.get("event") == "LLM request failed")
    assert failure["provider"] == "openai"
    assert failure["model"] == "gpt-5.2"
    assert failure["attempt"] == 1
    assert failure["with_pdf"] is False
    assert failure["error_type"] == "RuntimeError"
    assert failure["error"] == "boom"
    assert failure["retrying"] is False
    assert failure["status_code"] is None
    assert isinstance(failure.get("elapsed_ms"), float)
    assert "exception" in failure


def test_openai_pdf_request_emits_failure_telemetry(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    _install_fake_openai(monkeypatch)
    pdf = tmp_path / "input.pdf"
    pdf.write_bytes(b"%PDF")

    stream = io.StringIO()
    configure_logging(level="DEBUG", log_format="json", stream=stream)

    try:
        client = OpenAIClient()
        client._client.responses.create = lambda **kwargs: (_ for _ in ()).throw(
            RuntimeError("pdf boom")
        )

        with pytest.raises(RuntimeError, match="pdf boom"):
            client.generate_text_with_pdf("prompt", str(pdf))
    finally:
        configure_logging(level="INFO", log_format="console", stream=io.StringIO())

    lines = [
        line
        for line in _json_log_lines(stream.getvalue())
        if line.get("logger") == "metesparser.llm_clients"
    ]
    failure = next(line for line in lines if line.get("event") == "LLM request failed")
    assert failure["provider"] == "openai"
    assert failure["model"] == "gpt-5.2"
    assert failure["attempt"] == 1
    assert failure["with_pdf"] is True
    assert failure["error_type"] == "RuntimeError"
    assert failure["error"] == "pdf boom"
    assert failure["retrying"] is False
    assert failure["status_code"] is None
    assert isinstance(failure.get("elapsed_ms"), float)
    assert "exception" in failure


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


def test_gemini_client_emits_retry_and_fallback_telemetry(monkeypatch):
    def handler(*, model, contents, config, client_error, server_error):
        if model == "gemini-2.5-pro":
            raise server_error(503)
        return SimpleNamespace(text="ok")

    _install_fake_gemini(monkeypatch, handler)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    stream = io.StringIO()
    configure_logging(level="DEBUG", log_format="json", stream=stream)

    try:
        client = GeminiClient(model="gemini-2.5-pro", fallback_model="gemini-2.5-flash")
        assert client.generate_text("hello") == "ok"
    finally:
        configure_logging(level="INFO", log_format="console", stream=io.StringIO())

    lines = [
        line
        for line in _json_log_lines(stream.getvalue())
        if line.get("logger") == "metesparser.llm_clients"
    ]
    assert any(
        line.get("event") == "LLM request attempt"
        and line.get("model") == "gemini-2.5-pro"
        and line.get("attempt") == 1
        for line in lines
    )

    retry_line = next(line for line in lines if line.get("event") == "LLM request failed")
    assert retry_line["provider"] == "gemini"
    assert retry_line["model"] == "gemini-2.5-pro"
    assert retry_line["attempt"] == 1
    assert retry_line["status_code"] == 503
    assert retry_line["retrying"] is True
    assert retry_line["next_model"] == "gemini-2.5-flash"

    fallback_success = next(
        line
        for line in lines
        if line.get("event") == "LLM request succeeded" and line.get("model") == "gemini-2.5-flash"
    )
    assert fallback_success["provider"] == "gemini"
    assert fallback_success["attempt"] == 2
    assert fallback_success["used_fallback"] is True
    assert isinstance(fallback_success.get("elapsed_ms"), float)


def test_gemini_client_re_raises_non_retryable_client_error(monkeypatch):
    def handler(*, model, contents, config, client_error, server_error):
        raise client_error(400)

    _, client_error, _ = _install_fake_gemini(monkeypatch, handler)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    client = GeminiClient(model="gemini-2.5-pro", fallback_model=None)

    with pytest.raises(client_error, match="client 400"):
        client.generate_text("hello")
