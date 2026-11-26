"""Behavioral tests for mp_ocr.extract (PDFProcessor and confidence scoring)."""

from __future__ import annotations

import hashlib
import importlib.resources as importlib_resources
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from mp_ocr.cache import CachedLLMClient
from mp_ocr.clients import GeminiClient, LLMConfigurationError, OpenAIClient, OpenRouterClient
from mp_ocr.extract import PDFProcessor, compute_llm_confidence


class _RecordingClient:
    """Deterministic stub client recording every text and PDF request."""

    def __init__(
        self,
        *,
        text_responses: list[str] | None = None,
        pdf_responses: list[str] | None = None,
        model: str | None = "stub-model-v1",
        model_name: str | None = None,
        fail_on_text: Exception | None = None,
        fail_on_pdf: Exception | None = None,
    ) -> None:
        self._text_responses = list(text_responses or ["normalized text"])
        self._pdf_responses = list(pdf_responses or ["raw pdf text"])
        if model is not None:
            self.model = model
        if model_name is not None:
            self.model_name = model_name
        self._fail_on_text = fail_on_text
        self._fail_on_pdf = fail_on_pdf
        self.text_calls: list[tuple[str, str | None]] = []
        self.pdf_calls: list[tuple[str, str, str | None]] = []

    def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
        self.text_calls.append((prompt, response_mime_type))
        if self._fail_on_text is not None:
            raise self._fail_on_text
        return (
            self._text_responses.pop(0)
            if len(self._text_responses) > 1
            else self._text_responses[0]
        )

    def generate_text_with_pdf(
        self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
    ) -> str:
        self.pdf_calls.append((prompt, pdf_path, response_mime_type))
        if self._fail_on_pdf is not None:
            raise self._fail_on_pdf
        return (
            self._pdf_responses.pop(0) if len(self._pdf_responses) > 1 else self._pdf_responses[0]
        )


def test_compute_llm_confidence_high() -> None:
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
    assert confidence == pytest.approx(1.0)
    assert signals == {
        "has_pob": True,
        "has_bearing_calls": True,
        "has_closure_language": True,
        "has_distances": True,
        "text_length_reasonable": True,
        "has_plss": True,
        "no_garbled_chars": True,
    }


def test_compute_llm_confidence_low_and_garbled() -> None:
    confidence, signals = compute_llm_confidence("This is not a legal description at all.")
    assert confidence == pytest.approx(0.10)
    assert signals["has_pob"] is False
    assert signals["has_bearing_calls"] is False
    assert signals["text_length_reasonable"] is False
    assert signals["no_garbled_chars"] is True

    garbled_conf, garbled_signals = compute_llm_confidence("éñüøß" * 20)
    assert garbled_signals["no_garbled_chars"] is False
    assert garbled_conf == pytest.approx(0.10)  # only text_length_reasonable passes


def test_package_pdf_processor_openrouter_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    created: dict[str, object] = {}

    class DummyOpenRouter:
        def __init__(self, **kwargs: object) -> None:
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


def test_package_pdf_processor_openrouter_env_escape_hatches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: dict[str, object] = {}

    class DummyOpenRouter:
        def __init__(self, **kwargs: object) -> None:
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

    for disable_val in ("", "   ", "none", "NONE", "off", "disabled"):
        monkeypatch.setenv("OPENROUTER_FALLBACK_MODEL", disable_val)
        PDFProcessor(provider="openrouter", cache=False)
        assert "fallback_model" in created and created["fallback_model"] is None

    monkeypatch.delenv("OPENROUTER_FALLBACK_MODEL", raising=False)

    for disable_val in ("", "  ", "off", "OFF", "disabled"):
        monkeypatch.setenv("OPENROUTER_REASONING_EFFORT", disable_val)
        PDFProcessor(provider="openrouter", cache=False)
        assert "reasoning_effort" in created and created["reasoning_effort"] is None

    monkeypatch.setenv("OPENROUTER_REASONING_EFFORT", "none")
    PDFProcessor(provider="openrouter", cache=False)
    assert created["reasoning_effort"] == "none"


def test_pdf_processor_provider_selection_and_error_translation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[tuple[str, str | None]] = []

    class DummyOpenAI(_RecordingClient):
        def __init__(self, *, api_key: str | None = None) -> None:
            super().__init__(model="gpt-5.2")
            created.append(("openai", api_key))

    class DummyGemini(_RecordingClient):
        def __init__(self, *, api_key: str | None = None) -> None:
            super().__init__(model="gemini-3.6-flash")
            created.append(("gemini", api_key))

    monkeypatch.setattr("mp_ocr.extract.OpenAIClient", DummyOpenAI)
    monkeypatch.setattr("mp_ocr.extract.GeminiClient", DummyGemini)
    monkeypatch.delenv("METESPARSER_LLM_PROVIDER", raising=False)

    p_openai = PDFProcessor(api_key="sk-1", cache=False)
    assert isinstance(p_openai.client, DummyOpenAI)
    p_gemini = PDFProcessor(api_key="gm-1", provider="GEMINI", cache=False)
    assert isinstance(p_gemini.client, DummyGemini)
    assert created == [("openai", "sk-1"), ("gemini", "gm-1")]

    def failing_openai(*, api_key: str | None = None) -> object:
        raise LLMConfigurationError("missing openai key")

    monkeypatch.setattr("mp_ocr.extract.OpenAIClient", failing_openai)
    with pytest.raises(ValueError, match="missing openai key"):
        PDFProcessor(provider="openai", cache=False)

    with pytest.raises(ValueError, match="Unsupported LLM provider 'bogus'"):
        PDFProcessor(provider="bogus", cache=False)


def test_pdf_processor_caching_toggle_and_no_double_wrapping(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    inner = _RecordingClient(model="cached-model")
    cache_dir = tmp_path / "llm_cache"
    monkeypatch.setenv("METESPARSER_LLM_CACHE", "true")
    monkeypatch.setenv("METESPARSER_CACHE_DIR", str(cache_dir))

    wrapped = PDFProcessor(client=inner)
    assert isinstance(wrapped.client, CachedLLMClient)
    assert wrapped.normalize_legal_description("BEGINNING at pin") == "normalized text"
    assert wrapped.normalize_legal_description("BEGINNING at pin") == "normalized text"
    assert len(inner.text_calls) == 1
    assert len(list(cache_dir.glob("*.json"))) == 1

    # Passing an already-cached client unwraps it rather than nesting two CachedLLMClients:
    # an empty second cache directory misses and calls inner directly instead of hitting cache_dir.
    cache_dir_2 = tmp_path / "cache2"
    rewrapped = PDFProcessor(client=wrapped.client, cache=True, cache_dir=cache_dir_2)
    assert isinstance(rewrapped.client, CachedLLMClient)
    assert rewrapped.normalize_legal_description("BEGINNING at pin") == "normalized text"
    assert len(inner.text_calls) == 2
    assert len(list(cache_dir_2.glob("*.json"))) == 1
    assert rewrapped.normalize_legal_description("BEGINNING at pin") == "normalized text"
    assert len(inner.text_calls) == 2

    monkeypatch.setenv("METESPARSER_LLM_CACHE", "false")
    uncached = PDFProcessor(client=inner)
    assert uncached.client is inner


def test_prompt_loading_overrides_resources_fallback_and_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pdf = tmp_path / "deed.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    stub = _RecordingClient(
        pdf_responses=["raw pdf body"],
        text_responses=[
            "extracted legal body",
            "normalized legal body",
            json.dumps({"calls": []}),
            "custom normalized",
            "packaged normalized",
        ],
    )
    processor = PDFProcessor(client=stub, cache=False)

    # All four embedded prompts load and execute through the public extraction API.
    assert processor.extract_text_from_pdf(str(pdf)) == "raw pdf body"
    assert processor.extract_legal_description(str(pdf)) == "extracted legal body"
    assert processor.normalize_legal_description("BEGINNING at pin") == "normalized legal body"
    assert processor.extract_calls_ai("BEGINNING at pin") == []
    assert len(stub.pdf_calls) == 2
    assert len(stub.text_calls) == 3
    assert "raw pdf body" in stub.text_calls[0][0]
    assert "BEGINNING at pin" in stub.text_calls[1][0]
    assert "BEGINNING at pin" in stub.text_calls[2][0]

    # Custom prompts_dir takes precedence over package prompts.
    custom_dir = tmp_path / "prompts"
    custom_dir.mkdir()
    (custom_dir / "normalize_text.yaml").write_text(
        'system_prompt: Custom sys\nuser_prompt_template: "Custom user: {legal_description_text}"\n',
        encoding="utf-8",
    )
    processor.prompts_dir = custom_dir
    assert processor.normalize_legal_description("LOT 1") == "custom normalized"
    assert stub.text_calls[-1] == ("Custom sys\n\nCustom user: LOT 1", None)

    # Non-mapping YAML raises ValueError.
    (custom_dir / "normalize_text.yaml").write_text("- item1\n- item2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Prompt file 'normalize_text' did not contain a mapping"):
        processor.normalize_legal_description("LOT 1")

    # Fallback to importlib.resources works when filesystem candidates are absent.
    with monkeypatch.context() as mp:
        mp.setattr(Path, "exists", lambda self: False)
        assert processor.normalize_legal_description("LOT 1") == "packaged normalized"
        assert "LOT 1" in stub.text_calls[-1][0]
        assert "Custom sys" not in stub.text_calls[-1][0]

    # Missing packaged resource (is_file() -> False) raises FileNotFoundError.
    with monkeypatch.context() as mp:
        mp.setattr(Path, "exists", lambda self: False)
        mp.setattr(
            importlib_resources,
            "files",
            lambda _pkg: SimpleNamespace(
                joinpath=lambda *_parts: SimpleNamespace(is_file=lambda: False)
            ),
        )
        with pytest.raises(FileNotFoundError, match="Prompt file not found for 'normalize_text'"):
            processor.normalize_legal_description("LOT 1")

    # ModuleNotFoundError from importlib.resources.files also raises FileNotFoundError.
    def broken_files(_pkg: str) -> object:
        raise ModuleNotFoundError("no package")

    with monkeypatch.context() as mp:
        mp.setattr(Path, "exists", lambda self: False)
        mp.setattr(importlib_resources, "files", broken_files)
        with pytest.raises(FileNotFoundError, match="Prompt file not found for 'normalize_text'"):
            processor.normalize_legal_description("LOT 1")


def test_extract_text_legal_description_and_normalize_audit_chain(tmp_path: Path) -> None:
    pdf = tmp_path / "deed.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

    raw_pdf_text = (
        "WARRANTY DEED ... BEGINNING at a stake; N 0° E 100 ft; "
        "S 90° E 100 ft; S 0° W 100 ft; to POINT OF BEGINNING."
    )
    extracted_desc = (
        "BEGINNING at a stake; N 0° E 100 ft; S 90° E 100 ft; S 0° W 100 ft; to POINT OF BEGINNING."
    )
    normalized_desc = (
        "BEGINNING at an iron pin; North 00°00'00\" East 100.00 feet; "
        "South 90°00'00\" East 100.00 feet; South 00°00'00\" West 100.00 feet; "
        "to the POINT OF BEGINNING."
    )
    stub = _RecordingClient(
        pdf_responses=[raw_pdf_text],
        text_responses=[extracted_desc, normalized_desc],
        model="stub-ocr-1",
    )
    processor = PDFProcessor(client=stub, cache=False)

    # Non-audited calls record no audit stages.
    assert processor.extract_text_from_pdf(str(pdf)) == raw_pdf_text
    non_audited_ctx = processor._build_audit_context(
        pdf_path=str(pdf),
        legal_desc_text=raw_pdf_text,
        normalized_text=raw_pdf_text,
        distance_unit="feet",
    )
    assert non_audited_ctx.extraction_record is not None
    assert non_audited_ctx.extraction_record.llm_stages == []
    assert len(stub.pdf_calls) == 1
    assert stub.pdf_calls[0][1] == str(pdf)

    # Audited extract_legal_description -> normalize_legal_description preserves 3-stage chain.
    stub_chain = _RecordingClient(
        pdf_responses=[raw_pdf_text],
        text_responses=[
            extracted_desc,
            normalized_desc,
            "standalone 1",
            "standalone 2",
            "no-audit",
        ],
        model="stub-ocr-2",
    )
    p_chain = PDFProcessor(client=stub_chain, cache=False)
    desc = p_chain.extract_legal_description(str(pdf), audit=True)
    assert desc == extracted_desc
    assert raw_pdf_text in stub_chain.text_calls[0][0]

    norm = p_chain.normalize_legal_description(desc, audit=True)
    assert norm == normalized_desc
    chain_ctx = p_chain._build_audit_context(
        pdf_path=str(pdf),
        legal_desc_text=desc,
        normalized_text=norm,
        distance_unit="feet",
    )
    assert chain_ctx.extraction_record is not None
    assert [r.stage for r in chain_ctx.extraction_record.llm_stages] == [
        "extract_text_from_pdf",
        "extract_legal_description",
        "normalize_text",
    ]
    stage0 = chain_ctx.extraction_record.llm_stages[0]
    assert stage0.prompt_sha256 == hashlib.sha256(stage0.prompt.encode("utf-8")).hexdigest()
    assert stage0.response_sha256 == hashlib.sha256(raw_pdf_text.encode("utf-8")).hexdigest()
    assert stage0.provider == "unknown"
    assert stage0.model == "stub-ocr-2"

    # Repeated standalone normalize_legal_description(audit=True) resets the chain to 1 record.
    assert p_chain.normalize_legal_description("first standalone", audit=True) == "standalone 1"
    assert p_chain.normalize_legal_description("second standalone", audit=True) == "standalone 2"
    standalone_ctx = p_chain._build_audit_context(
        pdf_path=str(pdf),
        legal_desc_text="second standalone",
        normalized_text="standalone 2",
        distance_unit="feet",
    )
    assert standalone_ctx.extraction_record is not None
    assert [r.stage for r in standalone_ctx.extraction_record.llm_stages] == ["normalize_text"]
    assert standalone_ctx.extraction_record.llm_stages[0].response == "standalone 2"

    # Calling normalize_legal_description(audit=False) clears any prior audit stage records.
    p_chain.normalize_legal_description("kept", audit=True)
    p_chain.normalize_legal_description("other text", audit=False)
    cleared_ctx = p_chain._build_audit_context(
        pdf_path=str(pdf),
        legal_desc_text="other text",
        normalized_text="no-audit",
        distance_unit="feet",
    )
    assert cleared_ctx.extraction_record is not None
    assert cleared_ctx.extraction_record.llm_stages == []


def test_extract_text_from_pdf_without_system_prompt_and_error_cleanup(tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "extract_text_from_pdf.yaml").write_text(
        "system_prompt: '   '\nuser_prompt_template: Extract verbatim.\nresponse_mime_type: text/plain\n",
        encoding="utf-8",
    )
    stub = _RecordingClient(pdf_responses=["plain output"])
    processor = PDFProcessor(client=stub, cache=False)
    processor.prompts_dir = prompts_dir
    assert processor.extract_text_from_pdf("any.pdf", audit=True) == "plain output"
    assert stub.pdf_calls[0] == ("Extract verbatim.", "any.pdf", "text/plain")

    # Exceptions clear captured audit stages on all three stages.
    failing_pdf = PDFProcessor(
        client=_RecordingClient(fail_on_pdf=RuntimeError("pdf boom")), cache=False
    )
    with pytest.raises(RuntimeError, match="pdf boom"):
        failing_pdf.extract_text_from_pdf("any.pdf", audit=True)
    ctx_pdf = failing_pdf._build_audit_context(
        pdf_path="any.pdf", legal_desc_text="", normalized_text="", distance_unit="feet"
    )
    assert ctx_pdf.extraction_record is not None
    assert ctx_pdf.extraction_record.llm_stages == []

    with pytest.raises(RuntimeError, match="pdf boom"):
        failing_pdf.extract_legal_description("any.pdf", audit=True)
    ctx_desc = failing_pdf._build_audit_context(
        pdf_path="any.pdf", legal_desc_text="", normalized_text="", distance_unit="feet"
    )
    assert ctx_desc.extraction_record is not None
    assert ctx_desc.extraction_record.llm_stages == []

    failing_norm = PDFProcessor(
        client=_RecordingClient(fail_on_text=RuntimeError("text boom")), cache=False
    )
    with pytest.raises(RuntimeError, match="text boom"):
        failing_norm.normalize_legal_description("some text", audit=True)
    ctx_norm = failing_norm._build_audit_context(
        pdf_path="any.pdf", legal_desc_text="", normalized_text="", distance_unit="feet"
    )
    assert ctx_norm.extraction_record is not None
    assert ctx_norm.extraction_record.llm_stages == []


def test_extract_calls_ai_valid_empty_and_malformed_payloads() -> None:
    calls_payload = [{"course": 1, "direction_text": "N 45 E", "distance_ft": 100.0}]
    stub = _RecordingClient(
        text_responses=[
            json.dumps({"calls": calls_payload}),
            "",
            json.dumps([1, 2, 3]),
            json.dumps({"calls": "not-a-list"}),
        ]
    )
    processor = PDFProcessor(client=stub, cache=False)

    assert processor.extract_calls_ai("BEGINNING at POB...") == calls_payload
    assert stub.text_calls[0][1] == "application/json"
    assert processor.extract_calls_ai("empty") == []

    with pytest.raises(ValueError, match="non-object JSON"):
        processor.extract_calls_ai("bad array")

    with pytest.raises(ValueError, match="malformed calls payload"):
        processor.extract_calls_ai("bad calls type")


def test_build_audit_context_provider_detection_model_name_and_prompt_hash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("METESPARSER_LOG_LEVEL", "DEBUG")

    # 1. Custom client with model_name attribute only, wrapped in cache.
    named_stub = _RecordingClient(model=None, model_name="custom-named-model")
    p_custom = PDFProcessor(client=named_stub, cache=True, cache_dir=tmp_path / "cache")
    assert p_custom.model_name == "custom-named-model"

    p_custom.normalize_legal_description("BEGINNING at pin", audit=True)
    ctx = p_custom._build_audit_context(
        pdf_path=str(tmp_path / "sample_deed.pdf"),
        legal_desc_text="raw desc",
        normalized_text="BEGINNING at pin; North 0° E 100 feet; to POINT OF BEGINNING.",
        distance_unit="feet",
        parser_version="2.0.0",
    )
    assert ctx.run_metadata.llm_provider == "unknown"
    assert ctx.run_metadata.llm_model == "custom-named-model"
    assert ctx.run_metadata.source_pdf == "sample_deed.pdf"
    assert ctx.run_metadata.cache_enabled is True
    assert ctx.run_metadata.parser_version == "2.0.0"
    assert ctx.run_metadata.config["log_level"] == "DEBUG"
    assert ctx.run_metadata.config["distance_unit"] == "feet"
    assert re.fullmatch(r"[0-9a-f]{64}", ctx.run_metadata.prompt_hash)
    assert ctx.extraction_record is not None
    assert len(ctx.extraction_record.llm_stages) == 1
    # Building the audit context consumes the recorded stage buffer.
    follow_up_ctx = p_custom._build_audit_context(
        pdf_path=str(tmp_path / "sample_deed.pdf"),
        legal_desc_text="raw desc",
        normalized_text="norm",
        distance_unit="feet",
    )
    assert follow_up_ctx.extraction_record is not None
    assert follow_up_ctx.extraction_record.llm_stages == []

    # 2. Client with neither model nor model_name -> None / "unknown"; missing prompt -> "unknown".
    anon = _RecordingClient(model=None, model_name=None)
    p_anon = PDFProcessor(client=anon, cache=False)
    assert p_anon.model_name is None
    with monkeypatch.context() as mp:
        mp.setattr(Path, "exists", lambda self: False)
        mp.setattr(
            importlib_resources,
            "files",
            lambda _pkg: SimpleNamespace(
                joinpath=lambda *_parts: SimpleNamespace(is_file=lambda: False)
            ),
        )
        anon_ctx = p_anon._build_audit_context(
            pdf_path="anon.pdf",
            legal_desc_text="raw",
            normalized_text="norm",
            distance_unit="feet",
        )
    assert anon_ctx.run_metadata.llm_model == "unknown"
    assert anon_ctx.run_metadata.prompt_hash == "unknown"

    # 3. Real provider subclasses map to canonical provider names in audit metadata & stage records.
    class FakeOpenAI(OpenAIClient):
        def __init__(self) -> None:
            object.__setattr__(self, "model", "gpt-5.2")

        def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
            return "ok"

        def generate_text_with_pdf(
            self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
        ) -> str:
            return "ok"

    class FakeGemini(GeminiClient):
        def __init__(self) -> None:
            object.__setattr__(self, "model", "gemini-3.6-flash")

        def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
            return "ok"

        def generate_text_with_pdf(
            self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
        ) -> str:
            return "ok"

    class FakeOpenRouter(OpenRouterClient):
        def __init__(self) -> None:
            object.__setattr__(self, "model", "anthropic/claude-haiku-5.5")

        def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
            return "ok"

        def generate_text_with_pdf(
            self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
        ) -> str:
            return "ok"

    for fake_client, expected_provider in (
        (FakeOpenAI(), "openai"),
        (FakeGemini(), "gemini"),
        (FakeOpenRouter(), "openrouter"),
    ):
        proc = PDFProcessor(client=fake_client, cache=False)
        proc.normalize_legal_description("BEGINNING at corner", audit=True)
        audit_ctx = proc._build_audit_context(
            pdf_path="deed.pdf",
            legal_desc_text="raw",
            normalized_text="norm",
            distance_unit="feet",
        )
        assert audit_ctx.run_metadata.llm_provider == expected_provider
        assert audit_ctx.extraction_record is not None
        assert audit_ctx.extraction_record.llm_stages[0].provider == expected_provider


def test_check_prior_conveyance_detects_known_signals() -> None:
    processor = PDFProcessor(client=_RecordingClient(), cache=False)

    matched = processor.check_prior_conveyance(
        "BEING the same premises previously conveyed by deed dated May 1, 1990 "
        "and recorded in Book 120, Page 45."
    )
    assert "BEING the same premises" in matched
    assert "previously conveyed" in matched
    assert "by deed dated" in matched
    assert "recorded in Book" in matched

    assert processor.check_prior_conveyance("North 45°00' East 100.00 feet to an iron pin.") == []
