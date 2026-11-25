"""Regression tests for Section 2 review items: Core Models, Logging, OCR, Prompts & Cache."""

from __future__ import annotations

import io
import json
import logging
import math
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
import structlog
import yaml
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _RecordingClient:
    """Minimal LLM client double recording prompts passed to PDF/text methods."""

    model = "test-model"

    def __init__(self, response: str = "EXTRACTED TEXT") -> None:
        self.response = response
        self.pdf_calls: list[tuple[str, str, str | None]] = []
        self.text_calls: list[tuple[str, str | None]] = []

    def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
        self.text_calls.append((prompt, response_mime_type))
        return self.response

    def generate_text_with_pdf(
        self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
    ) -> str:
        self.pdf_calls.append((prompt, pdf_path, response_mime_type))
        return self.response


def _processor_classes():
    from mp_ocr.extract import PDFProcessor as PkgProcessor

    from metesparser.pdf_processor import PDFProcessor as MonoProcessor

    return [PkgProcessor, MonoProcessor]


def _confidence_fns():
    from mp_ocr.extract import compute_llm_confidence as pkg_fn

    from metesparser.pdf_processor import PDFProcessor as MonoProcessor

    return [pkg_fn, MonoProcessor._compute_llm_confidence]


def _closure_result_classes():
    from mp_models import ClosureResult as PkgClosureResult

    from metesparser.models import ClosureResult as MonoClosureResult

    return [PkgClosureResult, MonoClosureResult]


def _deed_call_classes():
    from mp_models import DeedCall as PkgDeedCall

    from metesparser.models import DeedCall as MonoDeedCall

    return [PkgDeedCall, MonoDeedCall]


def _legal_desc_classes():
    from mp_models import LegalDescription as PkgLegalDesc

    from metesparser.models import LegalDescription as MonoLegalDesc

    return [PkgLegalDesc, MonoLegalDesc]


# ---------------------------------------------------------------------------
# 1. OCR system_prompt in extract_text_from_pdf()
# ---------------------------------------------------------------------------


class TestExtractTextSystemPrompt:
    @pytest.mark.parametrize("proc_cls", _processor_classes(), ids=["mp_ocr", "monolith"])
    def test_extract_text_from_pdf_includes_system_prompt(
        self, proc_cls: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        client = _RecordingClient()
        processor = proc_cls(client=client, cache=False)
        pdf = tmp_path / "deed.pdf"
        pdf.write_bytes(b"%PDF-1.4")

        monkeypatch.setattr(
            processor,
            "_load_prompt",
            lambda _name: {
                "system_prompt": "  SYSTEM INSTRUCTIONS  \n",
                "user_prompt_template": "USER TEMPLATE",
                "response_mime_type": None,
            },
        )

        result = processor.extract_text_from_pdf(str(pdf))

        assert result == "EXTRACTED TEXT"
        assert len(client.pdf_calls) == 1
        sent_prompt = client.pdf_calls[0][0]
        assert sent_prompt == "SYSTEM INSTRUCTIONS\n\nUSER TEMPLATE"

    @pytest.mark.parametrize("proc_cls", _processor_classes(), ids=["mp_ocr", "monolith"])
    def test_extract_text_from_pdf_skips_blank_system_prompt(
        self, proc_cls: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        client = _RecordingClient()
        processor = proc_cls(client=client, cache=False)
        pdf = tmp_path / "deed.pdf"
        pdf.write_bytes(b"%PDF-1.4")

        monkeypatch.setattr(
            processor,
            "_load_prompt",
            lambda _name: {
                "system_prompt": "   \n  ",
                "user_prompt_template": "USER TEMPLATE",
                "response_mime_type": None,
            },
        )

        processor.extract_text_from_pdf(str(pdf))
        assert client.pdf_calls[0][0] == "USER TEMPLATE"


# ---------------------------------------------------------------------------
# 2. compute_llm_confidence() heuristic fixes
# ---------------------------------------------------------------------------


class TestComputeLlmConfidenceHeuristics:
    @pytest.mark.parametrize("fn", _confidence_fns(), ids=["mp_ocr", "monolith"])
    @pytest.mark.parametrize(
        "text",
        [
            "N 45° E 100 ft; S 30° W 100 ft; N 60° E 50 ft;",
            "North 45 degrees East 100 ft; South 30 deg. West 100 ft; N 60 deg E 50 ft;",
            "N 12°30' E 100 ft; S 12°30' W 100 ft; N 45°00'00\" W 50 ft;",
        ],
    )
    def test_has_bearing_calls_matches_degree_symbols_and_deg_variants(
        self, fn: Any, text: str
    ) -> None:
        _, signals = fn(text)
        assert signals["has_bearing_calls"] is True

    @pytest.mark.parametrize("fn", _confidence_fns(), ids=["mp_ocr", "monolith"])
    @pytest.mark.parametrize(
        "distance_phrase",
        [
            "100 feet",
            "150.25 ft",
            "12 poles",
            "10.5 rods",
            "8 perches",
            "4 chains",
            "25 links",
            "120 varas",
            "2.5 arpents",
            "15 toises",
            "3 furlongs",
            "45.5 meters",
            "1 mile",
        ],
    )
    def test_has_distances_matches_integer_and_survey_units(
        self, fn: Any, distance_phrase: str
    ) -> None:
        _, signals = fn(f"thence North 45° East {distance_phrase} to a pin")
        assert signals["has_distances"] is True, f"Failed for {distance_phrase}"

    @pytest.mark.parametrize("fn", _confidence_fns(), ids=["mp_ocr", "monolith"])
    def test_has_plss_uses_word_boundaries(self, fn: Any) -> None:
        _, false_signals = fn(
            "BEGINNING at the intersection of Oak Street and Orange Avenue; thence N 45° E 100 feet."
        )
        assert false_signals["has_plss"] is False

        for plss_text in ("Section 12", "Township 4N", "Range 2W", "T4N R2W"):
            _, true_signals = fn(f"Situated in {plss_text}, containing 10 acres.")
            assert true_signals["has_plss"] is True, f"Expected PLSS match for {plss_text}"


# ---------------------------------------------------------------------------
# 3. normalize_text.yaml contradictions & sync
# ---------------------------------------------------------------------------


class TestNormalizeTextPromptConsistency:
    PROMPT_PATHS = (
        REPO_ROOT / "prompts" / "normalize_text.yaml",
        REPO_ROOT / "src" / "metesparser" / "prompts" / "normalize_text.yaml",
        REPO_ROOT / "packages" / "mp-ocr" / "src" / "mp_ocr" / "prompts" / "normalize_text.yaml",
    )

    def test_all_three_normalize_text_files_are_byte_identical(self) -> None:
        base = self.PROMPT_PATHS[0].read_bytes()
        for path in self.PROMPT_PATHS[1:]:
            assert path.read_bytes() == base

    def test_decrees_rule_is_consistent_and_not_labeled_cardinal(self) -> None:
        content = self.PROMPT_PATHS[0].read_text(encoding="utf-8")
        assert '"DECREES" → "DEGREES"' not in content
        assert 'cardinal directions (e.g., "DECREES"' not in content
        assert '"DECREES" with °' in content

    def test_example_2_preserves_southwesterly_capitalization(self) -> None:
        data = yaml.safe_load(self.PROMPT_PATHS[0].read_text(encoding="utf-8"))
        user_tpl = data["user_prompt_template"]
        ex2_section = user_tpl.split("<example_2_numbered_calls>")[1].split(
            "</example_2_numbered_calls>"
        )[0]
        after_section = ex2_section.split("After:")[1]
        assert "along southwesterly line" not in after_section
        assert "to southwesterly line" not in after_section
        assert after_section.count("Southwesterly") == 3


# ---------------------------------------------------------------------------
# 4. CachedLLMClient cross-impl cache key
# ---------------------------------------------------------------------------


def _install_fake_openai(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    module = ModuleType("openai")

    class FakeResponses:
        def create(self, **kwargs: Any) -> Any:
            calls.append(kwargs["model"])
            return SimpleNamespace(output_text="openai-response")

    class FakeOpenAI:
        def __init__(self, api_key: str) -> None:
            self.responses = FakeResponses()

    module.OpenAI = FakeOpenAI  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", module)
    return calls


def _install_fake_gemini(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    google_mod = ModuleType("google")
    genai_mod = ModuleType("google.genai")
    errors_mod = ModuleType("google.genai.errors")
    types_mod = ModuleType("google.genai.types")

    class FakeClientError(Exception):
        status_code = 400

    class FakeServerError(Exception):
        status_code = 500

    errors_mod.ClientError = FakeClientError  # type: ignore[attr-defined]
    errors_mod.ServerError = FakeServerError  # type: ignore[attr-defined]
    types_mod.Part = SimpleNamespace(  # type: ignore[attr-defined]
        from_text=lambda text: SimpleNamespace(text=text),
        from_bytes=lambda data, mime_type: SimpleNamespace(data=data, mime_type=mime_type),
    )
    types_mod.Content = lambda role, parts: SimpleNamespace(role=role, parts=parts)  # type: ignore[attr-defined]
    types_mod.GenerateContentConfig = lambda **kwargs: kwargs  # type: ignore[attr-defined]

    class FakeClient:
        def __init__(self, api_key: str) -> None:
            self.models = SimpleNamespace(
                generate_content=lambda *, model, contents, config: (
                    calls.append(model) or SimpleNamespace(text="gemini-response")
                )
            )

    genai_mod.Client = FakeClient  # type: ignore[attr-defined]
    genai_mod.errors = errors_mod  # type: ignore[attr-defined]
    genai_mod.types = types_mod  # type: ignore[attr-defined]
    google_mod.genai = genai_mod  # type: ignore[attr-defined]
    google_mod.__path__ = []
    monkeypatch.setitem(sys.modules, "google", google_mod)
    monkeypatch.setitem(sys.modules, "google.genai", genai_mod)
    monkeypatch.setitem(sys.modules, "google.genai.errors", errors_mod)
    monkeypatch.setitem(sys.modules, "google.genai.types", types_mod)
    return calls


class TestCrossImplCacheKey:
    def test_openai_clients_share_cache_across_package_and_monolith(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from mp_ocr.cache import CachedLLMClient as PkgCache
        from mp_ocr.clients import OpenAIClient as PkgOpenAI

        from metesparser.llm_cache import CachedLLMClient as MonoCache
        from metesparser.llm_clients import OpenAIClient as MonoOpenAI

        calls = _install_fake_openai(monkeypatch)
        cache_dir = tmp_path / "cache"

        pkg_cached = PkgCache(PkgOpenAI(api_key="test-key", model="gpt-5.2"), cache_dir=cache_dir)
        mono_cached = MonoCache(
            MonoOpenAI(api_key="test-key", model="gpt-5.2"), cache_dir=cache_dir
        )

        assert pkg_cached._cache_key("p", None) == mono_cached._cache_key("p", None)
        assert pkg_cached.generate_text("p") == "openai-response"
        assert mono_cached.generate_text("p") == "openai-response"
        assert len(calls) == 1

    def test_gemini_clients_share_cache_across_package_and_monolith(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from mp_ocr.cache import CachedLLMClient as PkgCache
        from mp_ocr.clients import GeminiClient as PkgGemini

        from metesparser.llm_cache import CachedLLMClient as MonoCache
        from metesparser.llm_clients import GeminiClient as MonoGemini

        calls = _install_fake_gemini(monkeypatch)
        cache_dir = tmp_path / "cache"

        pkg_cached = PkgCache(PkgGemini(api_key="test-key"), cache_dir=cache_dir)
        mono_cached = MonoCache(MonoGemini(api_key="test-key"), cache_dir=cache_dir)

        assert pkg_cached._cache_key("p", None) == mono_cached._cache_key("p", None)
        assert pkg_cached.generate_text("p") == "gemini-response"
        assert mono_cached.generate_text("p") == "gemini-response"
        assert len(calls) == 1


# ---------------------------------------------------------------------------
# 5. Logging fixes (mp_* loggers, no cache_logger_on_first_use, no locals)
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("isolate_logging_state")
class TestLoggingFixes:
    @pytest.mark.parametrize(
        "logger_name",
        [
            "metesparser",
            "mp_models",
            "mp_bearing",
            "mp_ocr",
            "mp_parse",
            "mp_verify",
            "mp_export",
            "mp_review",
        ],
    )
    def test_package_mode_attaches_handlers_to_all_mp_loggers(self, logger_name: str) -> None:
        from mp_models.logging import configure_logging

        stream = io.StringIO()
        configure_logging(level="INFO", log_format="json", stream=stream, take_over_root=False)

        logging.getLogger(f"{logger_name}.sub").info("hello from %s", logger_name)
        lines = [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]
        assert len(lines) == 1
        assert lines[0]["logger"] == f"{logger_name}.sub"
        assert logging.getLogger(logger_name).propagate is False

    def test_reconfigure_logging_updates_already_obtained_structlog_logger(self) -> None:
        from mp_models.logging import configure_logging

        stream1 = io.StringIO()
        configure_logging(level="INFO", log_format="console", stream=stream1, take_over_root=False)

        early_logger = structlog.get_logger("mp_parse.reconfig")
        early_logger.info("first")
        assert "first" in stream1.getvalue()

        stream2 = io.StringIO()
        configure_logging(level="INFO", log_format="json", stream=stream2, take_over_root=False)
        early_logger.info("second")

        lines = [json.loads(line) for line in stream2.getvalue().splitlines() if line.strip()]
        assert len(lines) == 1
        assert lines[0]["event"] == "second"

    def test_json_exception_does_not_leak_local_variables(self) -> None:
        from mp_models.logging import configure_logging

        stream = io.StringIO()
        configure_logging(level="INFO", log_format="json", stream=stream, take_over_root=False)

        def _failing_with_secret() -> None:
            api_key = "sk-secret-123"
            _ = api_key
            raise RuntimeError("boom")

        try:
            _failing_with_secret()
        except RuntimeError:
            structlog.get_logger("mp_ocr.client").exception("request failed")

        raw_output = stream.getvalue()
        assert "sk-secret-123" not in raw_output
        parsed = json.loads(raw_output.strip())
        assert parsed["exception"][0]["exc_type"] == "RuntimeError"
        for frame in parsed["exception"][0]["frames"]:
            assert not frame.get("locals")


# ---------------------------------------------------------------------------
# 6. mp_ocr.PDFProcessor _audit_stage_records state leak
# ---------------------------------------------------------------------------


def test_mp_ocr_repeated_extract_text_audit_does_not_accumulate_stale_records(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mp_ocr.extract import PDFProcessor

    client = _RecordingClient()
    processor = PDFProcessor(client=client, cache=False)
    monkeypatch.setattr(
        processor,
        "_load_prompt",
        lambda _name: {
            "system_prompt": "SYS",
            "user_prompt_template": "USR",
            "response_mime_type": None,
        },
    )

    pdf1 = tmp_path / "one.pdf"
    pdf2 = tmp_path / "two.pdf"
    pdf1.write_bytes(b"%PDF-1")
    pdf2.write_bytes(b"%PDF-2")

    client.response = "FIRST"
    processor.extract_text_from_pdf(str(pdf1), audit=True)
    assert processor._audit_stage_records is not None
    assert len(processor._audit_stage_records) == 1

    client.response = "SECOND"
    processor.extract_text_from_pdf(str(pdf2), audit=True)
    assert processor._audit_stage_records is not None
    assert len(processor._audit_stage_records) == 1
    assert processor._audit_stage_records[0].response == "SECOND"


# ---------------------------------------------------------------------------
# 7. ClosureResult.get_closure_status() semantics
# ---------------------------------------------------------------------------


class TestClosureStatusSemantics:
    @pytest.mark.parametrize(
        "closure_cls", _closure_result_classes(), ids=["mp_models", "monolith"]
    )
    @pytest.mark.parametrize(
        "failed_flag",
        ["closure_passed", "angle_check_passed", "curve_consistency_passed"],
    )
    def test_failed_verification_check_never_reports_passing_status(
        self, closure_cls: Any, failed_flag: str
    ) -> None:
        kwargs: dict[str, Any] = {
            "misclosure_x_ft": 0.0,
            "misclosure_y_ft": 0.0,
            "misclosure_ft": 0.001,
            "area_sq_ft": 100.0,
            "area_acres": 100.0 / 43560.0,
            "perimeter_ft": 40.0,
            "closure_passed": True,
            "angle_check_passed": True,
            "curve_consistency_passed": True,
            "warnings": [],
            "points": [],
        }
        kwargs[failed_flag] = False
        result = closure_cls(**kwargs)
        assert result.get_closure_status() == "NEEDS REVIEW"


# ---------------------------------------------------------------------------
# 8. Pydantic model strictness
# ---------------------------------------------------------------------------


class TestModelStrictness:
    @pytest.mark.parametrize("ld_cls", _legal_desc_classes(), ids=["mp_models", "monolith"])
    @pytest.mark.parametrize("bad_area", [0.0, -50.0])
    def test_legal_description_rejects_non_positive_stated_area(
        self, ld_cls: Any, bad_area: float
    ) -> None:
        with pytest.raises(ValidationError):
            ld_cls(stated_area_sq_ft=bad_area)

    @pytest.mark.parametrize(
        "closure_cls", _closure_result_classes(), ids=["mp_models", "monolith"]
    )
    @pytest.mark.parametrize(
        "field_name",
        ["misclosure_ft", "area_sq_ft", "area_acres", "perimeter_ft"],
    )
    def test_closure_result_rejects_negative_non_signed_metrics(
        self, closure_cls: Any, field_name: str
    ) -> None:
        kwargs: dict[str, Any] = {
            "misclosure_x_ft": 0.0,
            "misclosure_y_ft": 0.0,
            "misclosure_ft": 0.0,
            "area_sq_ft": 100.0,
            "area_acres": 100.0 / 43560.0,
            "perimeter_ft": 40.0,
            "closure_passed": True,
            "angle_check_passed": True,
            "curve_consistency_passed": True,
        }
        kwargs[field_name] = -0.1
        with pytest.raises(ValidationError):
            closure_cls(**kwargs)

    @pytest.mark.parametrize("call_cls", _deed_call_classes(), ids=["mp_models", "monolith"])
    @pytest.mark.parametrize(
        "curve_attr",
        [
            {"non_tangent": True},
            {"radial_bearing": "N 15°22' E"},
            {"curve_type": "simple"},
            {"chord_bearing": "N 45°00' E"},
        ],
    )
    def test_deed_call_rejects_curve_metadata_without_curve_dir(
        self, call_cls: Any, curve_attr: dict[str, Any]
    ) -> None:
        with pytest.raises(ValidationError, match="curve_dir"):
            call_cls(
                course=1,
                direction_text="North",
                distance_ft=100.0,
                **curve_attr,
            )

    @pytest.mark.parametrize("bad_float", [math.nan, math.inf, -math.inf])
    def test_envelope_messages_reject_non_finite_floats(self, bad_float: float) -> None:
        from mp_models.envelope import ClosureResultMessage, RawTextMessage

        with pytest.raises(ValidationError):
            RawTextMessage(
                source="deed.pdf",
                text="txt",
                llm_provider="openai",
                llm_model="gpt-5",
                confidence=bad_float,
            )

        with pytest.raises(ValidationError):
            ClosureResultMessage(
                source="deed.pdf",
                is_verified=True,
                misclosure_ft=bad_float,
            )

        with pytest.raises(ValidationError):
            ClosureResultMessage(
                source="deed.pdf",
                is_verified=True,
                misclosure_ft=0.0,
                area_sq_ft=bad_float,
            )
