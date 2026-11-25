"""Regression tests for project audit core fixes (Red-Green TDD)."""

from __future__ import annotations

import math
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# 1. Prompt YAML sync & extract_calls.yaml double-brace fix
# ---------------------------------------------------------------------------


class TestPromptYamlSync:
    """All 3 prompt directories must stay byte-for-byte identical and brace-clean."""

    PROMPT_FILES = (
        "extract_calls.yaml",
        "extract_legal_description.yaml",
        "extract_text_from_pdf.yaml",
        "normalize_text.yaml",
    )

    @pytest.mark.parametrize("filename", PROMPT_FILES)
    def test_prompt_dirs_are_byte_for_byte_identical(self, filename: str) -> None:
        root_bytes = (REPO_ROOT / "prompts" / filename).read_bytes()
        pkg_bytes = (
            REPO_ROOT / "packages" / "mp-ocr" / "src" / "mp_ocr" / "prompts" / filename
        ).read_bytes()
        mono_bytes = (REPO_ROOT / "src" / "metesparser" / "prompts" / filename).read_bytes()

        assert pkg_bytes == root_bytes, f"mp-ocr prompt {filename} differs from root prompts/"
        assert mono_bytes == root_bytes, f"monolith prompt {filename} differs from root prompts/"

    def test_extract_calls_yaml_has_no_double_braces(self) -> None:
        for base in (
            REPO_ROOT / "prompts",
            REPO_ROOT / "packages" / "mp-ocr" / "src" / "mp_ocr" / "prompts",
            REPO_ROOT / "src" / "metesparser" / "prompts",
        ):
            content = (base / "extract_calls.yaml").read_text(encoding="utf-8")
            assert "{{" not in content, f"Unexpected '{{{{' in {base / 'extract_calls.yaml'}"
            assert "}}" not in content, f"Unexpected '}}}}' in {base / 'extract_calls.yaml'}"


# ---------------------------------------------------------------------------
# 2. calculate_missing_curve_elements() validation
# ---------------------------------------------------------------------------


def _curve_element_fns():
    from mp_bearing import calculate_missing_curve_elements

    from metesparser.bearing_converter import BearingConverter

    return [calculate_missing_curve_elements, BearingConverter.calculate_missing_curve_elements]


class TestMissingCurveElementsValidation:
    """Reject non-positive radii/arcs, invalid deltas, negative chords, and overflow deltas."""

    @pytest.mark.parametrize("fn", _curve_element_fns(), ids=["mp_bearing", "monolith"])
    @pytest.mark.parametrize(
        "kwargs",
        [
            {"radius_ft": -10.0, "delta_deg": 30.0},
            {"radius_ft": 0.0, "delta_deg": 30.0},
            {"radius_ft": 100.0, "delta_deg": -5.0},
            {"radius_ft": 100.0, "delta_deg": 361.0},
            {"radius_ft": 100.0, "arc_length_ft": 0.0},
            {"radius_ft": 100.0, "arc_length_ft": -25.0},
            {"radius_ft": 100.0, "chord_length_ft": -10.0},
            {"chord_length_ft": 0.0, "delta_deg": 90.0},
            {"chord_length_ft": 100.0, "delta_deg": 360.0},
            {"radius_ft": 100.0, "arc_length_ft": 1000.0},
            {"radius_ft": 100.0, "chord_length_ft": 0.0},
        ],
    )
    def test_invalid_curve_inputs_raise_value_error(self, fn, kwargs: dict[str, float]) -> None:
        with pytest.raises(ValueError):
            fn(**kwargs)


# ---------------------------------------------------------------------------
# 3. parse_packed_dms() exact validation
# ---------------------------------------------------------------------------


def _packed_dms_fns():
    from mp_bearing import parse_packed_dms

    from metesparser.bearing_converter import BearingConverter

    return [parse_packed_dms, BearingConverter.parse_packed_dms]


class TestParsePackedDmsValidation:
    """Reject negative values and float-rounding-masked invalid seconds/minutes."""

    @pytest.mark.parametrize("fn", _packed_dms_fns(), ids=["mp_bearing", "monolith"])
    @pytest.mark.parametrize(
        "bad_value",
        [-46.1000, -10.0, -0.0001, 45.15999, 46.6000, 46.1560, math.nan, math.inf],
    )
    def test_invalid_packed_dms_raises(self, fn, bad_value: float) -> None:
        with pytest.raises(ValueError):
            fn(bad_value)

    @pytest.mark.parametrize("fn", _packed_dms_fns(), ids=["mp_bearing", "monolith"])
    def test_valid_packed_dms_exact_decimal_conversion(self, fn) -> None:
        result = fn(46.1631)
        expected = 46.0 + 16.0 / 60.0 + 31.0 / 3600.0
        assert math.isclose(result, expected, abs_tol=1e-12)


# ---------------------------------------------------------------------------
# 4. calculate_chord_bearing() curve_dir validation
# ---------------------------------------------------------------------------


def _chord_bearing_fns():
    from mp_bearing import calculate_chord_bearing

    from metesparser.bearing_converter import BearingConverter

    return [calculate_chord_bearing, BearingConverter.calculate_chord_bearing]


class TestCalculateChordBearingValidation:
    """Reject invalid curve_dir values and normalize whitespace/casing."""

    @pytest.mark.parametrize("fn", _chord_bearing_fns(), ids=["mp_bearing", "monolith"])
    @pytest.mark.parametrize("bad_dir", ["straight", "", "cw", "up"])
    def test_invalid_curve_dir_raises(self, fn, bad_dir: str) -> None:
        with pytest.raises(ValueError, match="curve_dir must be 'left' or 'right'"):
            fn(90.0, 30.0, bad_dir)

    @pytest.mark.parametrize("fn", _chord_bearing_fns(), ids=["mp_bearing", "monolith"])
    def test_normalizes_whitespace_and_case(self, fn) -> None:
        assert math.isclose(fn(90.0, 30.0, "  LEFT "), 75.0)
        assert math.isclose(fn(90.0, 30.0, " Right "), 105.0)


# ---------------------------------------------------------------------------
# 5. Azimuth -1e-16 % 360.0 == 360.0 & bool rejection
# ---------------------------------------------------------------------------


def _deed_call_classes():
    from mp_models import DeedCall as PkgDeedCall

    from metesparser.models import DeedCall as MonoDeedCall

    return [PkgDeedCall, MonoDeedCall]


class TestAzimuthWrapAndBoolRejection:
    """Guard against -1e-16 % 360.0 == 360.0 and bool coercion in numeric fields."""

    @pytest.mark.parametrize("call_cls", _deed_call_classes(), ids=["mp_models", "monolith"])
    def test_tiny_negative_azimuth_normalizes_to_zero(self, call_cls) -> None:
        call = call_cls(
            course=1,
            direction_text="North",
            distance_ft=100.0,
            bearing_azimuth_deg_from_north=-1e-16,
        )
        assert call.bearing_azimuth_deg_from_north == 0.0

    @pytest.mark.parametrize("call_cls", _deed_call_classes(), ids=["mp_models", "monolith"])
    @pytest.mark.parametrize("bad_bool", [True, False])
    def test_azimuth_and_radius_reject_bool(self, call_cls, bad_bool: bool) -> None:
        with pytest.raises(ValidationError):
            call_cls(
                course=1,
                direction_text="North",
                distance_ft=100.0,
                bearing_azimuth_deg_from_north=bad_bool,
            )

        with pytest.raises(ValidationError):
            call_cls(
                course=1,
                direction_text="Curve",
                distance_ft=100.0,
                curve_dir="right",
                radius_ft=bad_bool,
                delta_deg=30.0,
            )

    def test_quadrant_to_azimuth_clamps_360_to_zero(self) -> None:
        from mp_bearing import quadrant_to_azimuth

        from metesparser.bearing_converter import BearingConverter

        for fn in (quadrant_to_azimuth, BearingConverter.quadrant_to_azimuth):
            for deg in (0.0, 1e-16):
                az = fn("N", deg, "W")
                assert az == 0.0
                assert 0.0 <= az < 360.0

    @pytest.mark.parametrize("fn", _chord_bearing_fns(), ids=["mp_bearing", "monolith"])
    def test_chord_bearing_clamps_360_to_zero(self, fn) -> None:
        az = fn(0.0, 2e-16, "left")
        assert az == 0.0
        assert 0.0 <= az < 360.0


# ---------------------------------------------------------------------------
# 6. OCR / PDFProcessor / Cache fixes
# ---------------------------------------------------------------------------


class TestOcrAndCacheFixes:
    """Verify PDFProcessor, LLM clients, and CachedLLMClient fixes."""

    def test_monolith_pob_empty_string_becomes_none(self, monkeypatch, tmp_path: Path) -> None:
        from metesparser.pdf_processor import PDFProcessor

        class DummyClient:
            pass

        processor = PDFProcessor(client=DummyClient(), cache=False)
        pdf_path = tmp_path / "deed.pdf"
        pdf_path.write_bytes(b"%PDF")

        monkeypatch.setattr(processor, "extract_legal_description", lambda _: "TEXT")
        monkeypatch.setattr(processor, "normalize_legal_description", lambda _: "TEXT")
        monkeypatch.setattr(
            "metesparser.text_parser.TextParser.extract_plss_metadata", lambda _: {}
        )
        monkeypatch.setattr(
            "metesparser.text_parser.TextParser.extract_poc_and_pob", lambda _: ("", "")
        )
        monkeypatch.setattr(
            "metesparser.text_parser.TextParser.extract_area_statement", lambda _: None
        )
        monkeypatch.setattr(
            "metesparser.text_parser.TextParser.infer_distance_unit", lambda _: None
        )
        monkeypatch.setattr(
            "metesparser.call_extractor.CallExtractor.extract_calls",
            lambda *_a, **_kw: [],
        )
        monkeypatch.setattr(
            "metesparser.call_extractor.CallExtractor.enrich_calls_with_azimuths",
            lambda calls: calls,
        )
        monkeypatch.setattr(
            "metesparser.call_extractor.CallExtractor.mark_tie_in_calls",
            lambda calls, poc_description=None: calls,
        )
        monkeypatch.setattr(
            "metesparser.text_parser.TextParser.extract_basis_of_bearing", lambda _: None
        )
        monkeypatch.setattr(
            "metesparser.text_parser.TextParser.extract_surveyor_certification", lambda _: None
        )
        monkeypatch.setattr(
            "metesparser.text_parser.TextParser.extract_prior_conveyance", lambda _: None
        )
        monkeypatch.setattr("metesparser.text_parser.TextParser.extract_deed_clauses", lambda _: [])
        monkeypatch.setattr(
            "metesparser.text_parser.TextParser.extract_subdivision_reference", lambda _: None
        )
        monkeypatch.setattr(
            "metesparser.text_parser.TextParser.extract_witness_trees", lambda _: []
        )
        monkeypatch.setattr(
            "metesparser.text_parser.TextParser.extract_coordinate_system", lambda _: (None, None)
        )

        ld = processor.process_deed_pdf(str(pdf_path))
        assert ld.pob_description is None
        assert ld.poc_description is None

    def test_build_audit_context_reads_metesparser_log_level(self, monkeypatch) -> None:
        from mp_ocr.extract import PDFProcessor as PkgProcessor

        from metesparser.pdf_processor import PDFProcessor as MonoProcessor

        class DummyClient:
            model = "fake-model"

        monkeypatch.setenv("METESPARSER_LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("LOG_LEVEL", "ERROR")

        for proc_cls in (PkgProcessor, MonoProcessor):
            proc = proc_cls(client=DummyClient(), cache=False)
            ctx = proc._build_audit_context(
                pdf_path="deed.pdf",
                legal_desc_text="raw",
                normalized_text="norm",
                distance_unit="feet",
            )
            assert ctx.run_metadata.config["log_level"] == "DEBUG"

    def test_prior_conveyance_patterns_are_sorted_deterministically(self) -> None:
        from mp_models import PRIOR_CONVEYANCE_SIGNALS
        from mp_ocr import extract as pkg_extract

        from metesparser import pdf_processor as mono_proc

        expected = sorted(PRIOR_CONVEYANCE_SIGNALS)
        assert [p.pattern for p in pkg_extract._PRIOR_CONVEYANCE_PATTERNS] == expected
        assert [p.pattern for p in mono_proc._PRIOR_CONVEYANCE_PATTERNS] == expected

    def test_monolith_load_prompt_falls_back_to_package_prompts_dir(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        from metesparser.pdf_processor import PDFProcessor

        class DummyClient:
            pass

        def _fail_resources(_pkg: str):
            raise ModuleNotFoundError("no resources")

        monkeypatch.setattr("metesparser.pdf_processor.resources.files", _fail_resources)
        processor = PDFProcessor(client=DummyClient(), cache=False)
        processor.prompts_dir = tmp_path / "nonexistent"
        loaded = processor._load_prompt("normalize_text")
        assert loaded["name"] == "normalize_text"

    def test_client_repr_hides_api_key_and_internal_client(self, monkeypatch) -> None:
        import sys

        from mp_ocr.clients import GeminiClient as PkgGemini
        from mp_ocr.clients import OpenAIClient as PkgOpenAI

        from metesparser.llm_clients import GeminiClient as MonoGemini
        from metesparser.llm_clients import OpenAIClient as MonoOpenAI

        openai_mod = ModuleType("openai")
        openai_mod.OpenAI = lambda api_key: SimpleNamespace(responses=SimpleNamespace())
        monkeypatch.setitem(sys.modules, "openai", openai_mod)

        google_mod = ModuleType("google")
        genai_mod = ModuleType("google.genai")
        genai_mod.Client = lambda api_key: SimpleNamespace(models=SimpleNamespace())
        genai_mod.errors = SimpleNamespace(ClientError=Exception, ServerError=Exception)
        genai_mod.types = SimpleNamespace()
        google_mod.genai = genai_mod
        google_mod.__path__ = []
        monkeypatch.setitem(sys.modules, "google", google_mod)
        monkeypatch.setitem(sys.modules, "google.genai", genai_mod)
        monkeypatch.setitem(sys.modules, "google.genai.errors", genai_mod.errors)
        monkeypatch.setitem(sys.modules, "google.genai.types", genai_mod.types)

        secret = "sk-super-secret-value-12345"
        for cls in (PkgOpenAI, MonoOpenAI, PkgGemini, MonoGemini):
            client = cls(api_key=secret)
            r = repr(client)
            assert secret not in r
            assert "_client" not in r

    def test_gemini_missing_sdk_hint_mentions_uv(self, monkeypatch) -> None:
        import sys

        from mp_ocr.clients import GeminiClient as PkgGemini
        from mp_ocr.clients import LLMConfigurationError as PkgCfgErr

        from metesparser.llm_clients import GeminiClient as MonoGemini
        from metesparser.llm_clients import LLMConfigurationError as MonoCfgErr

        monkeypatch.setitem(sys.modules, "google", ModuleType("google"))
        monkeypatch.delitem(sys.modules, "google.genai", raising=False)

        for cls, err_cls in ((PkgGemini, PkgCfgErr), (MonoGemini, MonoCfgErr)):
            with pytest.raises(err_cls, match="uv "):
                cls(api_key="test-key")

    def test_cache_handles_oserror_on_read_and_writes_atomically(self, tmp_path: Path) -> None:
        from mp_ocr.cache import CachedLLMClient as PkgCache

        from metesparser.llm_cache import CachedLLMClient as MonoCache

        class StubClient:
            def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
                return "café ° ′ ″"

            def generate_text_with_pdf(
                self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
            ) -> str:
                return "pdf"

        for idx, cache_cls in enumerate((PkgCache, MonoCache)):
            cache_dir = tmp_path / f"cache_{idx}"
            cached = cache_cls(StubClient(), cache_dir=cache_dir)
            key = cached._cache_key("p", None)
            # Simulate OSError when reading cache path (directory instead of file)
            cached._cache_path(key).mkdir(parents=True)
            assert cached._read_cache(key) is None
            cached._cache_path(key).rmdir()

            result = cached.generate_text("p")
            assert result == "café ° ′ ″"
            assert cached.generate_text("p") == "café ° ′ ″"
            # No leftover temp files
            assert list(cache_dir.glob("*.tmp")) == []

    def test_mp_ocr_exports_llm_configuration_error(self) -> None:
        import mp_ocr

        assert hasattr(mp_ocr, "LLMConfigurationError")
        assert "LLMConfigurationError" in mp_ocr.__all__


# ---------------------------------------------------------------------------
# 7. Shared logging state between mp_models.logging and metesparser.logging_config
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("isolate_logging_state")
def test_logging_config_shares_state_with_mp_models_logging() -> None:
    import io

    from mp_models.logging import configure_logging as pkg_configure
    from mp_models.logging import get_log_format as pkg_get_format

    from metesparser.logging_config import configure_logging as mono_configure
    from metesparser.logging_config import get_log_format as mono_get_format

    pkg_configure(level="INFO", log_format="json", stream=io.StringIO())
    assert mono_get_format() == "json"

    mono_configure(level="INFO", log_format="console", stream=io.StringIO())
    assert pkg_get_format() == "console"


# ---------------------------------------------------------------------------
# 8. Packaging, py.typed, ConversionFactors, CurveType description, model_config
# ---------------------------------------------------------------------------


class TestCleanupsAndPackaging:
    """Verify py.typed markers, hoisted maps, and schema metadata cleanups."""

    def test_py_typed_markers_exist(self) -> None:
        assert (REPO_ROOT / "packages" / "mp-bearing" / "src" / "mp_bearing" / "py.typed").is_file()
        assert (REPO_ROOT / "packages" / "mp-ocr" / "src" / "mp_ocr" / "py.typed").is_file()

    def test_conversion_factors_has_class_level_unit_map(self) -> None:
        from mp_models import ConversionFactors as PkgCF

        from metesparser.models import ConversionFactors as MonoCF

        for cf in (PkgCF, MonoCF):
            assert hasattr(cf, "_UNIT_TO_FEET")
            assert isinstance(cf._UNIT_TO_FEET, dict)
            assert cf.convert_to_feet(2.0, "chains") == 132.0

    @pytest.mark.parametrize("call_cls", _deed_call_classes(), ids=["mp_models", "monolith"])
    def test_curve_type_description_mentions_spiral_and_no_inert_validate_assignment(
        self, call_cls
    ) -> None:
        desc = call_cls.model_fields["curve_type"].description or ""
        assert "spiral" in desc.lower()
        assert "validate_assignment" not in call_cls.model_config
