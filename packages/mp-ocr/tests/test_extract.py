"""Verify PDF processor extraction logic."""


def test_compute_llm_confidence_high():
    from mp_ocr.extract import compute_llm_confidence

    text = (
        "BEGINNING at an iron pin found in the Southerly line of Elm Street; "
        "thence South 56 degrees 40 minutes East, a distance of 150.00 feet; "
        "thence North 33 degrees 20 minutes East, 125.00 feet; "
        "thence North 56 degrees 40 minutes West, 150.00 feet; "
        "to the POINT OF BEGINNING. "
        "Section 12, Township 3N, Range 2W. "
        "CONTAINING 0.43 acres more or less."
    )
    confidence, signals = compute_llm_confidence(text)
    assert confidence > 0.7
    assert signals["has_pob"] is True
    assert signals["has_bearing_calls"] is True


def test_compute_llm_confidence_low():
    from mp_ocr.extract import compute_llm_confidence

    confidence, signals = compute_llm_confidence("This is not a legal description at all.")
    assert confidence < 0.3


def test_package_pdf_processor_openrouter_env_overrides(monkeypatch):
    from mp_ocr.extract import PDFProcessor

    created: dict[str, object] = {}

    class DummyOpenRouter:
        def __init__(self, **kwargs):
            created.update(kwargs)

        def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
            return ""

        def generate_text_with_pdf(
            self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
        ) -> str:
            return ""

    monkeypatch.setenv("METESPARSER_LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "anthropic/claude-sonnet-5.5")
    monkeypatch.setenv("OPENROUTER_FALLBACK_MODEL", "google/gemini-3.8-flash")
    monkeypatch.setenv("OPENROUTER_PDF_ENGINE", "mistral-ocr")
    monkeypatch.setenv("OPENROUTER_REASONING_EFFORT", "medium")
    monkeypatch.setattr("mp_ocr.extract.OpenRouterClient", DummyOpenRouter)

    processor = PDFProcessor(cache=False)
    assert isinstance(processor.client, DummyOpenRouter)
    assert created == {
        "api_key": None,
        "model": "anthropic/claude-sonnet-5.5",
        "fallback_model": "google/gemini-3.8-flash",
        "pdf_engine": "mistral-ocr",
        "reasoning_effort": "medium",
    }


def test_package_pdf_processor_openrouter_env_escape_hatches(monkeypatch):
    from mp_ocr.extract import PDFProcessor

    created: dict[str, object] = {}

    class DummyOpenRouter:
        def __init__(self, **kwargs):
            created.clear()
            created.update(kwargs)

        def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
            return ""

        def generate_text_with_pdf(
            self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
        ) -> str:
            return ""

    monkeypatch.setattr("mp_ocr.extract.OpenRouterClient", DummyOpenRouter)
    for var in (
        "OPENROUTER_MODEL",
        "OPENROUTER_FALLBACK_MODEL",
        "OPENROUTER_PDF_ENGINE",
        "OPENROUTER_REASONING_EFFORT",
    ):
        monkeypatch.delenv(var, raising=False)

    # Disabling fallback via empty string, "none", "off", "disabled"
    for disable_val in ("", "   ", "none", "NONE", "off", "disabled"):
        monkeypatch.setenv("OPENROUTER_FALLBACK_MODEL", disable_val)
        PDFProcessor(provider="openrouter", cache=False)
        assert "fallback_model" in created and created["fallback_model"] is None

    monkeypatch.delenv("OPENROUTER_FALLBACK_MODEL", raising=False)

    # Disabling reasoning via empty string, "off", "disabled"
    for disable_val in ("", "  ", "off", "OFF", "disabled"):
        monkeypatch.setenv("OPENROUTER_REASONING_EFFORT", disable_val)
        PDFProcessor(provider="openrouter", cache=False)
        assert "reasoning_effort" in created and created["reasoning_effort"] is None

    # Explicit "none" passes through to reasoning_effort="none"
    monkeypatch.setenv("OPENROUTER_REASONING_EFFORT", "none")
    PDFProcessor(provider="openrouter", cache=False)
    assert created["reasoning_effort"] == "none"
