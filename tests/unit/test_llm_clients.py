from __future__ import annotations

import base64
import sys
from types import ModuleType, SimpleNamespace

import pytest

from metesparser.llm_clients import (
    LLMConfigurationError,
    OpenAIClient,
    GeminiClient,
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
    with pytest.raises(FileNotFoundError):
        _read_pdf("missing.pdf")


def test_openai_client_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(LLMConfigurationError):
        OpenAIClient()


def test_openai_client_raises_when_sdk_missing(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "key")
    monkeypatch.setitem(sys.modules, "openai", ModuleType("openai"))
    with pytest.raises(LLMConfigurationError):
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
    assert client.generate_text_with_pdf("prompt", str(pdf), response_mime_type="text/plain") == "ok"

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

    with pytest.raises(LLMConfigurationError):
        GeminiClient()


def test_gemini_client_retries_retryable_errors_and_collects_candidate_text(monkeypatch):
    def handler(*, model, contents, config, client_error, server_error):
        if model == "gemini-2.5-pro":
            raise server_error(503)
        return SimpleNamespace(
            text="",
            candidates=[SimpleNamespace(content=SimpleNamespace(parts=[SimpleNamespace(text="via candidates")]))],
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

    with pytest.raises(client_error):
        client.generate_text("hello")
