"""Red-Green TDD regressions for v0.7.0 Core Models, Logging, Bearing & OCR fixes."""

from __future__ import annotations

import io
import json
import logging
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import mp_bearing
import mp_models
import mp_ocr
import pytest
import structlog
from mp_models.envelope import ClosureResultMessage, RawTextMessage
from mp_ocr.cache import CachedLLMClient as PackageCachedClient
from mp_ocr.clients import GeminiClient as PackageGeminiClient
from mp_ocr.clients import OpenAIClient as PackageOpenAIClient
from mp_ocr.extract import PDFProcessor as PackagePDFProcessor
from mp_ocr.extract import compute_llm_confidence
from pydantic import ValidationError

from metesparser import models as monolith_models
from metesparser.bearing_converter import BearingConverter
from metesparser.llm_cache import CachedLLMClient as MonolithCachedClient
from metesparser.llm_clients import GeminiClient as MonolithGeminiClient
from metesparser.llm_clients import OpenAIClient as MonolithOpenAIClient
from metesparser.pdf_processor import PDFProcessor as MonolithPDFProcessor

MODEL_IMPLS = [("package", mp_models), ("monolith", monolith_models)]
CACHE_IMPLS = [("package", PackageCachedClient), ("monolith", MonolithCachedClient)]
PDF_PROCESSOR_IMPLS = [("package", PackagePDFProcessor), ("monolith", MonolithPDFProcessor)]


# ---------------------------------------------------------------------------
# 1. DeedCall azimuth wrap & bool rejection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("_name,models", MODEL_IMPLS)
def test_deedcall_clamps_negative_tiny_azimuth_wrap_to_zero(_name: str, models: Any) -> None:
    call = models.DeedCall(
        course=1,
        direction_text="N 0° W",
        distance_ft=100.0,
        bearing_azimuth_deg_from_north=-1e-16,
    )
    assert call.bearing_azimuth_deg_from_north == 0.0


@pytest.mark.parametrize("_name,models", MODEL_IMPLS)
@pytest.mark.parametrize("bad_bool", [True, False])
def test_deedcall_rejects_bool_azimuth_and_radius(_name: str, models: Any, bad_bool: bool) -> None:
    with pytest.raises(
        ValidationError, match="bearing_azimuth_deg_from_north must be a number, not a boolean"
    ):
        models.DeedCall(
            course=1,
            direction_text="N 0° E",
            distance_ft=100.0,
            bearing_azimuth_deg_from_north=bad_bool,
        )
    with pytest.raises(ValidationError, match="radius_ft must be a number, not a boolean"):
        models.DeedCall(
            course=1,
            direction_text="curve",
            distance_ft=100.0,
            curve_dir="right",
            radius_ft=bad_bool,
            delta_deg=45.0,
        )


# ---------------------------------------------------------------------------
# 2. Model bounds, ClosureResult.get_closure_status(), and envelope.py
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("_name,models", MODEL_IMPLS)
@pytest.mark.parametrize("bad_area", [0.0, -50.0])
def test_stated_area_sq_ft_requires_gt_zero(_name: str, models: Any, bad_area: float) -> None:
    with pytest.raises(
        ValidationError, match=r"(?s)stated_area_sq_ft.*Input should be greater than 0"
    ):
        models.LegalDescription(stated_area_sq_ft=bad_area)
    with pytest.raises(
        ValidationError, match=r"(?s)stated_area_sq_ft.*Input should be greater than 0"
    ):
        models.Tract(label="Tract 1", tract_type="main", stated_area_sq_ft=bad_area)


@pytest.mark.parametrize("_name,models", MODEL_IMPLS)
@pytest.mark.parametrize(
    "field_name",
    ["misclosure_ft", "area_sq_ft", "area_acres", "perimeter_ft"],
)
def test_closure_result_rejects_negative_measurements(
    _name: str, models: Any, field_name: str
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
    kwargs[field_name] = -0.01
    with pytest.raises(
        ValidationError, match=rf"(?s){field_name}.*Input should be greater than or equal to 0"
    ):
        models.ClosureResult(**kwargs)


@pytest.mark.parametrize("_name,models", MODEL_IMPLS)
@pytest.mark.parametrize(
    "overrides",
    [
        {"closure_passed": False},
        {"angle_check_passed": False},
        {"curve_consistency_passed": False},
    ],
)
def test_closure_status_never_excellent_when_flags_fail_even_without_warnings(
    _name: str, models: Any, overrides: dict[str, Any]
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
        "warnings": [],
    }
    kwargs.update(overrides)
    result = models.ClosureResult(**kwargs)
    assert result.get_closure_status() == "NEEDS REVIEW"


@pytest.mark.parametrize("_name,models", MODEL_IMPLS)
def test_closure_status_needs_review_when_check_blocked_without_warnings(
    _name: str, models: Any
) -> None:
    result = models.ClosureResult(
        misclosure_x_ft=0.0,
        misclosure_y_ft=0.0,
        misclosure_ft=0.0,
        area_sq_ft=100.0,
        area_acres=100.0 / 43560.0,
        perimeter_ft=40.0,
        closure_passed=True,
        angle_check_passed=True,
        curve_consistency_passed=True,
        warnings=[],
        checks=[
            models.CheckResult(name="traverse_closure", status="passed", detail="ok"),
            models.CheckResult(name="interior_angles", status="passed", detail="ok"),
            models.CheckResult(name="curve_consistency", status="blocked", detail="blocked"),
        ],
    )
    assert result.get_closure_status() == "NEEDS REVIEW"


@pytest.mark.parametrize("non_finite", [float("nan"), float("inf"), float("-inf")])
def test_envelope_rejects_non_finite_floats(non_finite: float) -> None:
    with pytest.raises(ValidationError, match=r"(?s)confidence.*Input should be a finite number"):
        RawTextMessage(
            source="deed.pdf",
            text="hello",
            llm_provider="openai",
            llm_model="gpt-5.2",
            confidence=non_finite,
        )
    with pytest.raises(
        ValidationError, match=r"(?s)misclosure_ft.*Input should be a finite number"
    ):
        ClosureResultMessage(
            source="deed.pdf",
            is_verified=False,
            misclosure_ft=non_finite,
        )
    with pytest.raises(ValidationError, match=r"(?s)area_sq_ft.*Input should be a finite number"):
        ClosureResultMessage(
            source="deed.pdf",
            is_verified=False,
            misclosure_ft=0.0,
            area_sq_ft=non_finite,
        )
    with pytest.raises(ValidationError, match=r"(?s)confidence.*Input should be a finite number"):
        ClosureResultMessage(
            source="deed.pdf",
            is_verified=False,
            misclosure_ft=0.0,
            confidence=non_finite,
        )


# ---------------------------------------------------------------------------
# 3. Logging
# ---------------------------------------------------------------------------


def test_monolith_logging_config_reexports_mp_models_logging() -> None:
    from mp_models import logging as pkg_logging

    from metesparser import logging_config

    assert logging_config.configure_logging is pkg_logging.configure_logging
    assert logging_config.get_log_format is pkg_logging.get_log_format


def test_configure_logging_disables_logger_caching(
    isolate_logging_state: None,
) -> None:
    from mp_models.logging import configure_logging

    console_stream = io.StringIO()
    configure_logging(level="INFO", log_format="console", stream=console_stream)
    assert structlog.get_config()["cache_logger_on_first_use"] is False

    reused_logger = structlog.get_logger("mp_ocr.reconfigure_test")
    reused_logger.info("first event", stage="console")
    assert "first event" in console_stream.getvalue()

    json_stream = io.StringIO()
    configure_logging(level="INFO", log_format="json", stream=json_stream)
    reused_logger.info("second event", stage="json")

    assert "second event" not in console_stream.getvalue()
    lines = [line for line in json_stream.getvalue().splitlines() if line.strip()]
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["event"] == "second event"
    assert payload["stage"] == "json"


def test_json_logging_exception_does_not_leak_local_secrets(
    isolate_logging_state: None,
) -> None:
    from mp_models.logging import configure_logging

    stream = io.StringIO()
    configure_logging(level="INFO", log_format="json", stream=stream)

    def _fail_with_secret() -> None:
        api_key = "super-secret-api-key-98765"  # noqa: F841
        raise RuntimeError("boom")

    try:
        _fail_with_secret()
    except RuntimeError:
        logging.getLogger("mp_ocr.clients").exception("client failed")

    output = stream.getvalue()
    assert "super-secret-api-key-98765" not in output
    payload = json.loads(output.splitlines()[0])
    assert payload["exception"][0]["exc_type"] == "RuntimeError"


# ---------------------------------------------------------------------------
# 4. Bearing & Curve Math
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("bad_value", "expected_match"),
    [
        (-45.1631, "Packed DMS value must be non-negative"),
        (-0.0001, "Packed DMS value must be non-negative"),
        (45.6000, r"Invalid packed DMS: minutes=60 \(must be 0-59\)"),
        (45.15999, r"Invalid packed DMS: seconds=99\.9 \(must be 0-59\)"),
        (45.1560, r"Invalid packed DMS: seconds=60 \(must be 0-59\)"),
        (float("nan"), "Invalid packed DMS value: nan"),
        (float("inf"), "Invalid packed DMS value: inf"),
    ],
)
def test_parse_packed_dms_rejects_invalid_and_negative_values(
    bad_value: float, expected_match: str
) -> None:
    with pytest.raises(ValueError, match=expected_match):
        mp_bearing.parse_packed_dms(bad_value)
    with pytest.raises(ValueError, match=expected_match):
        BearingConverter.parse_packed_dms(bad_value)


def test_quadrant_pattern_requires_word_boundaries() -> None:
    assert mp_bearing.QUADRANT_PATTERN.search("RUNS 45° WEST") is None
    assert BearingConverter.QUADRANT_PATTERN.search("RUNS 45° WEST") is None
    assert mp_bearing.parse_quadrant_bearing("RUNS 45° WEST") is None
    assert BearingConverter.parse_quadrant_bearing("RUNS 45° WEST") is None
    assert mp_bearing.parse_quadrant_bearing("N 45° E") == ("N", 45.0, "E")
    assert BearingConverter.parse_quadrant_bearing("(S 56°40' W)") is not None


def test_quadrant_to_azimuth_normalizes_validates_and_clamps() -> None:
    assert mp_bearing.quadrant_to_azimuth(" n ", 45.0, " e ") == 45.0
    assert BearingConverter.quadrant_to_azimuth(" s ", 45.0, " w ") == 225.0
    assert mp_bearing.quadrant_to_azimuth("N", 1e-16, "W") == 0.0
    assert BearingConverter.quadrant_to_azimuth("N", 1e-16, "W") == 0.0

    for bad_deg in (-0.1, 90.1, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="Degrees must be finite and between 0 and 90"):
            mp_bearing.quadrant_to_azimuth("N", bad_deg, "E")
        with pytest.raises(ValueError, match="Degrees must be finite and between 0 and 90"):
            BearingConverter.quadrant_to_azimuth("N", bad_deg, "E")


def test_calculate_chord_bearing_validates_curve_dir_and_clamps() -> None:
    assert mp_bearing.calculate_chord_bearing(0.0, 2e-16, "left") == 0.0
    assert BearingConverter.calculate_chord_bearing(0.0, 2e-16, "left") == 0.0

    for bad_dir in ("straight", "", "RIGHT"):
        with pytest.raises(ValueError, match="curve_dir"):
            mp_bearing.calculate_chord_bearing(90.0, 30.0, bad_dir)
        with pytest.raises(ValueError, match="curve_dir"):
            BearingConverter.calculate_chord_bearing(90.0, 30.0, bad_dir)


@pytest.mark.parametrize(
    ("kwargs", "expected_match"),
    [
        ({"radius_ft": -100.0, "delta_deg": 30.0}, "Radius must be positive and finite"),
        ({"radius_ft": 0.0, "delta_deg": 30.0}, "Radius must be positive and finite"),
        ({"radius_ft": 100.0, "arc_length_ft": -10.0}, "Arc length must be positive and finite"),
        ({"radius_ft": 100.0, "arc_length_ft": 0.0}, "Arc length must be positive and finite"),
        (
            {"radius_ft": 100.0, "chord_length_ft": -10.0},
            "Chord length must be non-negative and finite",
        ),
        (
            {"radius_ft": 100.0, "chord_length_ft": 0.0},
            "Chord length must be positive when computing delta from radius",
        ),
        ({"radius_ft": 100.0, "delta_deg": -10.0}, "Delta angle must be 0-360 degrees"),
        ({"radius_ft": 100.0, "delta_deg": 370.0}, "Delta angle must be 0-360 degrees"),
        ({"radius_ft": 10.0, "arc_length_ft": 100.0}, "Computed delta angle .* exceeds 360"),
        ({"radius_ft": float("nan"), "delta_deg": 30.0}, "Radius must be positive and finite"),
        ({"radius_ft": 100.0, "delta_deg": float("inf")}, "Delta angle must be finite"),
    ],
)
def test_calculate_missing_curve_elements_validates_bounds(
    kwargs: dict[str, float], expected_match: str
) -> None:
    with pytest.raises(ValueError, match=expected_match):
        mp_bearing.calculate_missing_curve_elements(**kwargs)
    with pytest.raises(ValueError, match=expected_match):
        BearingConverter.calculate_missing_curve_elements(**kwargs)


def test_monolith_calculate_missing_curve_elements_supports_degree_of_curvature() -> None:
    pkg = mp_bearing.calculate_missing_curve_elements(degree_of_curvature=2.0, delta_deg=30.0)
    mono = BearingConverter.calculate_missing_curve_elements(
        degree_of_curvature=2.0, delta_deg=30.0
    )
    assert mono["radius_ft"] == pytest.approx(pkg["radius_ft"])
    assert mono["arc_length_ft"] == pytest.approx(pkg["arc_length_ft"])


# ---------------------------------------------------------------------------
# 5. OCR, Clients, Cache & Prompts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename",
    ["extract_legal_description.yaml", "extract_text_from_pdf.yaml", "normalize_text.yaml"],
)
def test_prompt_copies_are_in_sync_and_reconciled(filename: str) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    root_text = (repo_root / "prompts" / filename).read_text(encoding="utf-8")
    pkg_text = (repo_root / "packages/mp-ocr/src/mp_ocr/prompts" / filename).read_text(
        encoding="utf-8"
    )
    mono_text = (repo_root / "src/metesparser/prompts" / filename).read_text(encoding="utf-8")

    assert pkg_text == root_text
    assert mono_text == root_text

    if filename == "normalize_text.yaml":
        assert 'cardinal directions (e.g., "DECREES"' not in root_text
        assert "along Southwesterly line of Concord Drive" in root_text
        assert "along southwesterly line of Concord Drive" not in root_text
        assert "NEVER emit Markdown" in root_text
        assert "UNDER AND SUBJECT" in root_text
    if filename == "extract_legal_description.yaml":
        assert "MULTI-TRACT / MULTI-SCHEDULE DEEDS" in root_text
        assert "NEVER emit Markdown" in root_text
        assert "FULL DMS SURVEY" in root_text
    if filename == "extract_text_from_pdf.yaml":
        assert "NEVER add Markdown formatting" in root_text


@pytest.mark.parametrize("_name,proc_cls", PDF_PROCESSOR_IMPLS)
def test_extract_text_from_pdf_passes_system_prompt(
    _name: str, proc_cls: Any, tmp_path: Path
) -> None:
    captured: list[str] = []

    class RecordingClient:
        def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
            return ""

        def generate_text_with_pdf(
            self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
        ) -> str:
            captured.append(prompt)
            return "RAW"

    pdf = tmp_path / "deed.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    processor = proc_cls(client=RecordingClient(), cache=False)
    processor.extract_text_from_pdf(str(pdf))

    system_prompt = processor._load_prompt("extract_text_from_pdf")["system_prompt"]
    assert system_prompt.strip() in captured[0]


@pytest.mark.parametrize(
    "scorer",
    [compute_llm_confidence, MonolithPDFProcessor._compute_llm_confidence],
)
def test_compute_llm_confidence_handles_normalized_symbols_units_and_plss_boundaries(
    scorer: Any,
) -> None:
    normalized_deed = (
        "BEGINNING at an iron pin at the intersection of Elm Street; "
        "thence N 33°20'00\" E 60 feet; "
        "thence S 26 deg. 00 41 E 12 chains; "
        "thence S 56°40' W 5 rods; "
        "to the POINT OF BEGINNING."
    )
    confidence, signals = scorer(normalized_deed)
    assert signals["has_bearing_calls"] is True
    assert signals["has_distances"] is True
    assert signals["has_plss"] is False  # "intersection" must NOT match "Section"
    assert confidence > 0.7

    plss_deed = (
        "Section 12, Township 3N, Range 2W; BEGINNING at a corner; "
        "thence N 0° E 100 poles to the POINT OF BEGINNING."
    )
    _, plss_signals = scorer(plss_deed)
    assert plss_signals["has_plss"] is True
    assert plss_signals["has_distances"] is True


def test_standalone_extract_text_from_pdf_resets_audit_stages(tmp_path: Path) -> None:
    class RecordingClient:
        model = "test-model"

        def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
            return ""

        def generate_text_with_pdf(
            self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
        ) -> str:
            return "OCR"

    pdf = tmp_path / "deed.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    processor = PackagePDFProcessor(client=RecordingClient(), cache=False)
    processor.extract_text_from_pdf(str(pdf), audit=True)
    processor.extract_text_from_pdf(str(pdf), audit=True)
    assert processor._audit_stage_records is not None
    assert len(processor._audit_stage_records) == 1


def test_monolith_process_deed_pdf_normalizes_empty_pob_to_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class DummyClient:
        pass

    pdf = tmp_path / "deed.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    processor = MonolithPDFProcessor(client=DummyClient(), cache=False)
    monkeypatch.setattr(processor, "extract_legal_description", lambda _: "TEXT")
    monkeypatch.setattr(processor, "normalize_legal_description", lambda _: "TEXT")
    monkeypatch.setattr("metesparser.text_parser.TextParser.extract_plss_metadata", lambda _: {})
    monkeypatch.setattr(
        "metesparser.text_parser.TextParser.extract_poc_and_pob", lambda _: ("", "")
    )
    monkeypatch.setattr("metesparser.text_parser.TextParser.extract_area_statement", lambda _: None)
    monkeypatch.setattr("metesparser.text_parser.TextParser.infer_distance_unit", lambda _: None)
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
        lambda calls, **_kw: calls,
    )
    monkeypatch.setattr("metesparser.text_parser.TextParser.extract_deed_clauses", lambda _: [])
    monkeypatch.setattr(
        "metesparser.text_parser.TextParser.extract_subdivision_reference", lambda _: None
    )
    monkeypatch.setattr("metesparser.text_parser.TextParser.extract_witness_trees", lambda _: [])
    monkeypatch.setattr(
        "metesparser.text_parser.TextParser.extract_coordinate_system", lambda _: (None, None)
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

    ld = processor.process_deed_pdf(str(pdf))
    assert ld.poc_description is None
    assert ld.pob_description is None


@pytest.mark.parametrize("_name,proc_cls", PDF_PROCESSOR_IMPLS)
def test_build_audit_context_prefers_metesparser_log_level(
    _name: str, proc_cls: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    class DummyClient:
        model = "m"

    monkeypatch.setenv("METESPARSER_LOG_LEVEL", "WARNING")
    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    processor = proc_cls(client=DummyClient(), cache=False)
    ctx = processor._build_audit_context(
        pdf_path="deed.pdf",
        legal_desc_text="raw",
        normalized_text="norm",
        distance_unit="feet",
    )
    assert ctx.run_metadata.config["log_level"] == "WARNING"


def test_mp_ocr_exports_llm_configuration_error() -> None:
    assert "LLMConfigurationError" in mp_ocr.__all__
    assert issubclass(mp_ocr.LLMConfigurationError, mp_ocr.LLMClientError)


@pytest.mark.parametrize("client_cls", [PackageOpenAIClient, MonolithOpenAIClient])
def test_openai_client_hides_api_key_and_internal_fields(
    monkeypatch: pytest.MonkeyPatch, client_cls: Any
) -> None:
    openai_mod = ModuleType("openai")
    openai_mod.OpenAI = lambda api_key: SimpleNamespace(responses=SimpleNamespace())
    monkeypatch.setitem(sys.modules, "openai", openai_mod)

    client = client_cls(api_key="sk-secret-value-123")
    assert "sk-secret-value-123" not in repr(client)
    assert "_client=" not in repr(client)
    with pytest.raises(TypeError, match="unexpected keyword argument '_client'"):
        client_cls(api_key="sk-secret-value-123", _client=object())


@pytest.mark.parametrize("client_cls", [PackageGeminiClient, MonolithGeminiClient])
def test_gemini_client_hides_api_key_and_internal_fields(
    monkeypatch: pytest.MonkeyPatch, client_cls: Any
) -> None:
    google_mod = ModuleType("google")
    genai_mod = ModuleType("google.genai")
    errors_mod = ModuleType("google.genai.errors")
    types_mod = ModuleType("google.genai.types")
    genai_mod.Client = lambda api_key: SimpleNamespace(models=SimpleNamespace())
    genai_mod.errors = errors_mod
    genai_mod.types = types_mod
    google_mod.genai = genai_mod
    google_mod.__path__ = []
    monkeypatch.setitem(sys.modules, "google", google_mod)
    monkeypatch.setitem(sys.modules, "google.genai", genai_mod)
    monkeypatch.setitem(sys.modules, "google.genai.errors", errors_mod)
    monkeypatch.setitem(sys.modules, "google.genai.types", types_mod)

    client = client_cls(api_key="gm-secret-value-456")
    assert "gm-secret-value-456" not in repr(client)
    assert "_client=" not in repr(client)
    assert "_types=" not in repr(client)
    assert "_errors=" not in repr(client)
    with pytest.raises(TypeError, match="unexpected keyword argument '_client'"):
        client_cls(api_key="gm-secret-value-456", _client=object())


def test_cached_client_uses_class_name_for_cross_impl_cache_keys(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    openai_mod = ModuleType("openai")
    openai_mod.OpenAI = lambda api_key: SimpleNamespace(responses=SimpleNamespace())
    monkeypatch.setitem(sys.modules, "openai", openai_mod)

    pkg_client = PackageOpenAIClient(api_key="k1")
    mono_client = MonolithOpenAIClient(api_key="k1")

    pkg_cached = PackageCachedClient(pkg_client, cache_dir=tmp_path / "cache")
    mono_cached = MonolithCachedClient(mono_client, cache_dir=tmp_path / "cache")
    assert pkg_cached._cache_key("prompt", None) == mono_cached._cache_key("prompt", None)


@pytest.mark.parametrize("_name,cache_cls", CACHE_IMPLS)
def test_cached_client_handles_oserror_on_read_and_write_and_uses_atomic_replace(
    _name: str, cache_cls: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class FakeClient:
        model = "fake-model"

        def __init__(self) -> None:
            self.calls = 0

        def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
            self.calls += 1
            return "fresh-unicode-\u00b0"

        def generate_text_with_pdf(
            self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
        ) -> str:
            self.calls += 1
            return "fresh-pdf"

    replace_calls: list[tuple[str, str]] = []
    real_replace = __import__("os").replace

    def tracking_replace(src: Any, dst: Any) -> None:
        replace_calls.append((str(src), str(dst)))
        real_replace(src, dst)

    monkeypatch.setattr("os.replace", tracking_replace)

    fake = FakeClient()
    cached = cache_cls(fake, cache_dir=tmp_path / "cache")
    assert cached.generate_text("p1") == "fresh-unicode-\u00b0"
    assert len(replace_calls) == 1
    assert list((tmp_path / "cache").glob("*.tmp")) == []

    # OSError during write must not fail the LLM call and must leave no temp files
    def failing_replace(src: Any, dst: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("os.replace", failing_replace)
    assert cached.generate_text("p2") == "fresh-unicode-\u00b0"
    assert list((tmp_path / "cache").glob("*.tmp")) == []

    # OSError during read must degrade to cache miss
    def failing_read_text(*args: Any, **kwargs: Any) -> str:
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "read_text", failing_read_text)
    assert cached.generate_text("p1") == "fresh-unicode-\u00b0"
    assert fake.calls == 3
