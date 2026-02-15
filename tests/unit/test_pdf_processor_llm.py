from __future__ import annotations

from types import SimpleNamespace

import pytest

from metesparser.pdf_processor import PDFProcessor


class RecordingClient:
    """Test double that records LLM client calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def generate_text_with_pdf(
        self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
    ) -> str:
        self.calls.append(
            (
                "generate_text_with_pdf",
                (prompt, pdf_path),
                {"response_mime_type": response_mime_type},
            )
        )
        return "RAW DOCUMENT TEXT"

    def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
        self.calls.append(
            (
                "generate_text",
                (prompt,),
                {"response_mime_type": response_mime_type},
            )
        )
        if response_mime_type == "application/json":
            return '{"calls": []}'
        return "NORMALIZED TEXT"


def _find_call(client: RecordingClient, name: str):
    for call_name, args, kwargs in client.calls:
        if call_name == name:
            return args, kwargs
    raise AssertionError(f"Call {name} not recorded")


def test_pdf_processor_prefers_injected_client(monkeypatch):
    """Providing a client should bypass provider creation."""

    def _fail_factory(self, provider):
        raise AssertionError("Should not initialize internal client")

    monkeypatch.setattr(PDFProcessor, "_create_client", _fail_factory, raising=False)

    processor = PDFProcessor(client=RecordingClient())
    assert isinstance(processor.client, RecordingClient)


def test_extract_text_from_pdf_uses_llm_client(tmp_path):
    client = RecordingClient()
    processor = PDFProcessor(client=client)

    fake_pdf = tmp_path / "fake.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4\n%Test")

    extracted = processor.extract_text_from_pdf(str(fake_pdf))
    assert extracted == "RAW DOCUMENT TEXT"

    args, kwargs = _find_call(client, "generate_text_with_pdf")
    assert args[1] == str(fake_pdf)
    assert kwargs["response_mime_type"] is None


def test_extract_legal_description_passes_document_text(tmp_path):
    client = RecordingClient()
    processor = PDFProcessor(client=client)

    fake_pdf = tmp_path / "fake.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4\n%Test")

    processor.extract_legal_description(str(fake_pdf))

    _, _ = _find_call(client, "generate_text_with_pdf")
    (prompt,), _ = _find_call(client, "generate_text")
    prompt_config = processor._load_prompt("extract_legal_description")
    expected_prompt = (
        f"{prompt_config['system_prompt']}\n\n"
        f"{prompt_config['user_prompt_template'].format(document_text='RAW DOCUMENT TEXT')}"
    )
    assert prompt == expected_prompt


def test_extract_calls_ai_requests_json_response():
    client = RecordingClient()
    processor = PDFProcessor(client=client)

    calls = processor.extract_calls_ai("NORMALIZED TEXT")
    assert calls == []

    (prompt,), kwargs = _find_call(client, "generate_text")
    assert kwargs["response_mime_type"] == "application/json"
    assert "NORMALIZED TEXT" in prompt


def test_provider_env_selects_gemini(monkeypatch):
    created = {}

    class DummyGemini(RecordingClient):
        def __init__(self, api_key=None, model: str | None = None):
            super().__init__()
            created["api_key"] = api_key
            created["model"] = model

    monkeypatch.setenv("METESPARSER_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr("metesparser.pdf_processor.GeminiClient", DummyGemini)

    processor = PDFProcessor()
    assert isinstance(processor.client, DummyGemini)
    assert created["api_key"] is None


def test_provider_argument_overrides_env(monkeypatch):
    created = {}

    class DummyOpenAI(RecordingClient):
        def __init__(self, api_key=None, model: str | None = None):
            super().__init__()
            created["api_key"] = api_key
            created["model"] = model

    monkeypatch.setenv("METESPARSER_LLM_PROVIDER", "gemini")
    monkeypatch.setattr("metesparser.pdf_processor.OpenAIClient", DummyOpenAI)

    processor = PDFProcessor(provider="openai")
    assert isinstance(processor.client, DummyOpenAI)
    assert created["api_key"] is None


def test_invalid_provider_raises_value_error(monkeypatch):
    monkeypatch.delenv("METESPARSER_LLM_PROVIDER", raising=False)
    with pytest.raises(ValueError, match="Unsupported LLM provider"):
        PDFProcessor(provider="does-not-exist")


def test_gemini_client_fallback_to_flash(monkeypatch):
    """Gemini client should retry with fallback model on retryable errors."""
    from metesparser.llm_clients import GeminiClient

    calls: list[str] = []

    class StubServerError(Exception):
        def __init__(self, status_code: int):
            super().__init__(f"error {status_code}")
            self.status_code = status_code

    class StubClientError(Exception):
        def __init__(self, status_code: int):
            super().__init__(f"error {status_code}")
            self.status_code = status_code

    class DummyModels:
        def generate_content(self, *, model: str, contents, config):
            calls.append(model)
            if len(calls) == 1:
                raise StubServerError(503)
            return SimpleNamespace(text="ok")

    class DummyClient:
        def __init__(self, api_key: str):
            self.models = DummyModels()

    class DummyPart:
        @staticmethod
        def from_text(text: str):
            return ("text", text)

        @staticmethod
        def from_bytes(data: bytes, mime_type: str):
            return ("bytes", len(data), mime_type)

    class DummyContent:
        def __init__(self, role: str, parts):
            self.role = role
            self.parts = parts

    dummy_types = SimpleNamespace(
        Part=DummyPart,
        Content=DummyContent,
        GenerateContentConfig=lambda **kwargs: kwargs,
    )
    dummy_errors = SimpleNamespace(ServerError=StubServerError, ClientError=StubClientError)

    def fake_post_init(self):
        object.__setattr__(self, "_client", DummyClient(api_key="fake"))
        object.__setattr__(self, "_types", dummy_types)
        object.__setattr__(self, "_errors", dummy_errors)

    monkeypatch.setattr(GeminiClient, "__post_init__", fake_post_init, raising=False)

    client = GeminiClient(api_key="fake", model="gemini-2.5-pro", fallback_model="gemini-2.5-flash")
    result = client.generate_text("hello")

    assert result == "ok"
    assert calls == ["gemini-2.5-pro", "gemini-2.5-flash"]
