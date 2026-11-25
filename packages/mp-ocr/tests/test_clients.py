"""Unit tests for mp_ocr.clients and PDFProcessor client factory."""

from __future__ import annotations

import base64
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest


def _install_fake_openai(monkeypatch: pytest.MonkeyPatch) -> tuple[ModuleType, dict[str, Any]]:
    module = ModuleType("openai")
    outputs: dict[str, Any] = {"text": "ok"}

    class FakeResponses:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def create(self, **kwargs: Any) -> Any:
            self.calls.append(kwargs)
            return SimpleNamespace(output_text=outputs["text"])

    class FakeOpenAI:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key
            self.responses = FakeResponses()

    module.OpenAI = FakeOpenAI  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", module)
    return module, outputs


def _install_fake_gemini(
    monkeypatch: pytest.MonkeyPatch, generate_content_handler: Any
) -> tuple[list[str], type[Exception], type[Exception]]:
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
        def from_text(text: str) -> Any:
            return SimpleNamespace(text=text)

        @staticmethod
        def from_bytes(data: bytes, mime_type: str) -> Any:
            return SimpleNamespace(data=data, mime_type=mime_type)

    class FakeContent:
        def __init__(self, role: str, parts: Any) -> None:
            self.role = role
            self.parts = parts

    class FakeClient:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key
            self.models = SimpleNamespace(
                generate_content=lambda *, model, contents, config: _handle_generate(
                    model=model,
                    contents=contents,
                    config=config,
                )
            )

    def _handle_generate(*, model: str, contents: Any, config: Any) -> Any:
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

    google_module.genai = genai_module  # type: ignore[attr-defined]
    google_module.__path__ = []
    monkeypatch.setitem(sys.modules, "google", google_module)
    monkeypatch.setitem(sys.modules, "google.genai", genai_module)
    monkeypatch.setitem(sys.modules, "google.genai.errors", errors_module)
    monkeypatch.setitem(sys.modules, "google.genai.types", types_module)

    return generate_calls, FakeClientError, FakeServerError


def test_base_client_protocol() -> None:
    from mp_ocr import BaseLLMClient

    assert hasattr(BaseLLMClient, "generate_text")
    assert hasattr(BaseLLMClient, "generate_text_with_pdf")


def test_llm_client_error() -> None:
    from mp_ocr import LLMClientError

    assert issubclass(LLMClientError, RuntimeError)


def test_cached_client_importable() -> None:
    from mp_ocr import CachedLLMClient

    assert CachedLLMClient is not None


def test_read_pdf_reads_bytes_and_raises_when_missing(tmp_path: Path) -> None:
    from mp_ocr.clients import _read_pdf

    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4 binary")

    name, content = _read_pdf(str(pdf))
    assert name == "sample.pdf"
    assert content == b"%PDF-1.4 binary"

    with pytest.raises(FileNotFoundError, match="PDF not found at missing.pdf"):
        _read_pdf("missing.pdf")


def test_openai_client_configuration_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    from mp_ocr import LLMConfigurationError, OpenAIClient

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(LLMConfigurationError, match="OPENAI_API_KEY"):
        OpenAIClient()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "openai", ModuleType("openai"))
    with pytest.raises(LLMConfigurationError, match="openai package not installed"):
        OpenAIClient()


def test_openai_client_generate_text_and_pdf(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mp_ocr import OpenAIClient

    _, outputs = _install_fake_openai(monkeypatch)
    outputs["text"] = "response-text"
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    client = OpenAIClient(model="gpt-5.2")
    assert client.generate_text("hello") == "response-text"
    assert (
        client.generate_text("hello json", response_mime_type="application/json") == "response-text"
    )

    json_call = client._client.responses.calls[1]
    assert json_call["model"] == "gpt-5.2"
    assert json_call["text"] == {"format": {"type": "json_object"}}

    outputs["text"] = None
    assert client.generate_text("empty") == ""

    outputs["text"] = "pdf-ok"
    pdf = tmp_path / "deed.pdf"
    pdf.write_bytes(b"%PDF-raw")
    assert client.generate_text_with_pdf("extract", str(pdf)) == "pdf-ok"

    pdf_call = client._client.responses.calls[3]
    content = pdf_call["input"][0]["content"]
    assert content[0]["filename"] == "deed.pdf"
    file_data = content[0]["file_data"]
    assert file_data.startswith("data:application/pdf;base64,")
    assert base64.b64decode(file_data.split(",", 1)[1]) == b"%PDF-raw"
    assert content[1]["text"] == "extract"


def test_gemini_client_configuration_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    from mp_ocr import GeminiClient, LLMConfigurationError

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    _install_fake_gemini(monkeypatch, lambda **_kw: SimpleNamespace(text="ok"))
    with pytest.raises(LLMConfigurationError, match="GEMINI_API_KEY"):
        GeminiClient()

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "google", ModuleType("google"))
    monkeypatch.delitem(sys.modules, "google.genai", raising=False)
    with pytest.raises(LLMConfigurationError, match="google-genai package not installed"):
        GeminiClient()


@pytest.mark.parametrize("status_code", [429, 502, 503, 504])
def test_gemini_client_retries_retryable_errors_with_fallback(
    monkeypatch: pytest.MonkeyPatch, status_code: int
) -> None:
    from mp_ocr import GeminiClient

    def handler(*, model: str, contents: Any, config: Any, client_error: Any, server_error: Any):
        if model == "gemini-3-flash-preview":
            if status_code == 429:
                raise client_error(status_code)
            raise server_error(status_code)
        return SimpleNamespace(
            text="",
            candidates=[
                SimpleNamespace(
                    content=SimpleNamespace(
                        parts=[SimpleNamespace(text="part-1 "), SimpleNamespace(text="part-2")]
                    )
                )
            ],
        )

    calls, _, _ = _install_fake_gemini(monkeypatch, handler)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    client = GeminiClient(model="gemini-3-flash-preview", fallback_model="gemini-2.5-flash")
    assert client.generate_text("hello", response_mime_type="application/json") == "part-1 part-2"
    assert calls == ["gemini-3-flash-preview", "gemini-2.5-flash"]


def test_gemini_client_re_raises_non_retryable_and_handles_pdf(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mp_ocr import GeminiClient

    def failing_handler(
        *, model: str, contents: Any, config: Any, client_error: Any, server_error: Any
    ):
        raise client_error(400)

    calls, client_err, _ = _install_fake_gemini(monkeypatch, failing_handler)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    client = GeminiClient(model="gemini-3-flash-preview", fallback_model="gemini-2.5-flash")
    with pytest.raises(client_err, match="client 400"):
        client.generate_text("hello")
    assert calls == ["gemini-3-flash-preview"]

    _install_fake_gemini(monkeypatch, lambda **_kw: SimpleNamespace(text="pdf-extracted"))
    pdf = tmp_path / "parcel.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    client_ok = GeminiClient(model="gemini-3-flash-preview")
    assert client_ok.generate_text_with_pdf("read", str(pdf)) == "pdf-extracted"


def test_pdf_processor_create_client_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    from mp_ocr import GeminiClient, OpenAIClient, PDFProcessor

    _install_fake_openai(monkeypatch)
    _install_fake_gemini(monkeypatch, lambda **_kw: SimpleNamespace(text="ok"))
    monkeypatch.setenv("OPENAI_API_KEY", "oa-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gm-key")
    monkeypatch.setenv("METESPARSER_LLM_PROVIDER", "gemini")

    proc_env = PDFProcessor(cache=False)
    assert isinstance(proc_env.client, GeminiClient)

    proc_arg = PDFProcessor(provider="openai", cache=False)
    assert isinstance(proc_arg.client, OpenAIClient)

    with pytest.raises(ValueError, match="Unsupported LLM provider"):
        PDFProcessor(provider="invalid-provider", cache=False)

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        PDFProcessor(provider="openai", cache=False)
