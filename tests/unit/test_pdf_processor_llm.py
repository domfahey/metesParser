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

    processor = PDFProcessor(client=RecordingClient(), cache=False)
    assert isinstance(processor.client, RecordingClient)


def test_extract_text_from_pdf_uses_llm_client(tmp_path):
    client = RecordingClient()
    processor = PDFProcessor(client=client, cache=False)

    fake_pdf = tmp_path / "fake.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4\n%Test")

    extracted = processor.extract_text_from_pdf(str(fake_pdf))
    assert extracted == "RAW DOCUMENT TEXT"

    args, kwargs = _find_call(client, "generate_text_with_pdf")
    assert args[1] == str(fake_pdf)
    assert kwargs["response_mime_type"] is None


def test_extract_legal_description_passes_document_text(tmp_path):
    client = RecordingClient()
    processor = PDFProcessor(client=client, cache=False)

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
    processor = PDFProcessor(client=client, cache=False)

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

    processor = PDFProcessor(cache=False)
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

    processor = PDFProcessor(provider="openai", cache=False)
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


def test_provider_env_selects_openrouter_and_reads_overrides(monkeypatch):
    created = {}

    class DummyOpenRouter(RecordingClient):
        def __init__(self, **kwargs):
            super().__init__()
            created.update(kwargs)

    monkeypatch.setenv("METESPARSER_LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "openai/gpt-6.1-terra")
    monkeypatch.setenv("OPENROUTER_FALLBACK_MODEL", "google/gemini-3.8-flash")
    monkeypatch.setenv("OPENROUTER_PDF_ENGINE", "mistral-ocr")
    monkeypatch.setenv("OPENROUTER_REASONING_EFFORT", "low")
    monkeypatch.setattr("metesparser.pdf_processor.OpenRouterClient", DummyOpenRouter)

    processor = PDFProcessor(cache=False)
    assert isinstance(processor.client, DummyOpenRouter)
    assert created == {
        "api_key": None,
        "model": "openai/gpt-6.1-terra",
        "fallback_model": "google/gemini-3.8-flash",
        "pdf_engine": "mistral-ocr",
        "reasoning_effort": "low",
    }


def test_openrouter_provider_audit_metadata_in_package_and_monolith(monkeypatch, tmp_path):
    from mp_ocr.clients import OpenRouterClient as PackageOpenRouterClient
    from mp_ocr.extract import PDFProcessor as PackagePDFProcessor

    from metesparser.llm_clients import OpenRouterClient as MonolithOpenRouterClient

    pdf = tmp_path / "deed.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    legal_text = (
        "BEGINNING at a point; "
        "thence N 00°00'00\" E 100.00 feet; "
        "thence S 90°00'00\" E 100.00 feet; "
        "thence S 00°00'00\" W 100.00 feet; "
        "thence N 90°00'00\" W 100.00 feet to the point of beginning."
    )

    fake_resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=legal_text))]
    )

    mono_client = MonolithOpenRouterClient(api_key="or-offline", model="openai/gpt-6.1-terra")
    monkeypatch.setattr(mono_client._client.chat.completions, "create", lambda **kw: fake_resp)
    mono_proc = PDFProcessor(client=mono_client, cache=False)
    _, mono_ctx = mono_proc.process_deed_pdf(str(pdf), audit=True)
    assert mono_ctx.run_metadata.llm_provider == "openrouter"
    assert mono_ctx.run_metadata.llm_model == "openai/gpt-6.1-terra"
    assert all(stage.provider == "openrouter" for stage in mono_ctx.extraction_record.llm_stages)

    pkg_client = PackageOpenRouterClient(api_key="or-offline", model="openai/gpt-6.1-terra")
    monkeypatch.setattr(pkg_client._client.chat.completions, "create", lambda **kw: fake_resp)
    pkg_proc = PackagePDFProcessor(client=pkg_client, cache=False)
    pkg_proc.extract_legal_description(str(pdf), audit=True)
    pkg_ctx = pkg_proc._build_audit_context(
        pdf_path=str(pdf),
        legal_desc_text=legal_text,
        normalized_text=legal_text,
        distance_unit="feet",
    )
    assert pkg_ctx.run_metadata.llm_provider == "openrouter"
    assert pkg_ctx.run_metadata.llm_model == "openai/gpt-6.1-terra"


def test_cli_accepts_openrouter_llm_provider(monkeypatch, tmp_path):
    from metesparser import cli

    captured = {}

    def fake_extract(pdf, output=None, llm_provider=None, no_cache=False):
        captured["pdf"] = pdf
        captured["llm_provider"] = llm_provider
        captured["no_cache"] = no_cache

    monkeypatch.setattr(cli, "extract_command", fake_extract)
    monkeypatch.setattr(
        "sys.argv",
        ["metesparser", "extract", str(tmp_path / "d.pdf"), "--llm-provider", "openrouter"],
    )
    cli.main()
    assert captured["llm_provider"] == "openrouter"


def test_openrouter_env_escape_hatches_disable_fallback_and_reasoning(monkeypatch):
    created: dict[str, object] = {}

    class DummyOpenRouter(RecordingClient):
        def __init__(self, **kwargs):
            super().__init__()
            created.clear()
            created.update(kwargs)

    monkeypatch.setattr("metesparser.pdf_processor.OpenRouterClient", DummyOpenRouter)
    for var in (
        "OPENROUTER_MODEL",
        "OPENROUTER_FALLBACK_MODEL",
        "OPENROUTER_PDF_ENGINE",
        "OPENROUTER_REASONING_EFFORT",
    ):
        monkeypatch.delenv(var, raising=False)

    # Unset env vars leave defaults intact (not passed in kwargs)
    PDFProcessor(provider="openrouter", cache=False)
    assert created == {"api_key": None}

    # Disable fallback with "", "none", "off", "disabled"
    for disable_val in ("", "  ", "none", "off", "DISABLED"):
        monkeypatch.setenv("OPENROUTER_FALLBACK_MODEL", disable_val)
        PDFProcessor(provider="openrouter", cache=False)
        assert "fallback_model" in created and created["fallback_model"] is None

    monkeypatch.delenv("OPENROUTER_FALLBACK_MODEL", raising=False)

    # Disable reasoning with "", "off", "disabled"
    for disable_val in ("", "  ", "off", "disabled"):
        monkeypatch.setenv("OPENROUTER_REASONING_EFFORT", disable_val)
        PDFProcessor(provider="openrouter", cache=False)
        assert "reasoning_effort" in created and created["reasoning_effort"] is None

    # Explicit "none" preserves reasoning_effort="none"
    monkeypatch.setenv("OPENROUTER_REASONING_EFFORT", "none")
    PDFProcessor(provider="openrouter", cache=False)
    assert created["reasoning_effort"] == "none"
