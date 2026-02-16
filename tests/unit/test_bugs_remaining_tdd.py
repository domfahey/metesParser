from __future__ import annotations

import importlib.util
import json
import math
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker
from metesparser.models import ClosureResult, DeedCall, LegalDescription
from metesparser.pdf_processor import PDFProcessor
from metesparser.text_parser import TextParser


def _load_script_module(script_name: str):
    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "scripts" / script_name
    spec = importlib.util.spec_from_file_location(f"test_{script_name}", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sample_closure_result() -> ClosureResult:
    return ClosureResult(
        misclosure_x_ft=0.0,
        misclosure_y_ft=0.0,
        misclosure_ft=0.0,
        area_sq_ft=100.0,
        area_acres=100.0 / 43560.0,
        perimeter_ft=100.0,
        closure_passed=True,
        angle_check_passed=True,
        curve_consistency_passed=True,
        warnings=[],
    )


def test_extract_calls_skips_incomplete_curve_and_continues() -> None:
    text = (
        "THENCE along a curve to the right having a radius of 50 feet to a point; "
        "THENCE N 10° E 100 feet to a point"
    )

    calls = CallExtractor.extract_calls(text)
    assert len(calls) == 1
    assert calls[0].course == 1
    assert math.isclose(calls[0].distance_ft, 100.0, abs_tol=0.001)


def test_compute_traverse_moves_curve_with_radius_and_arc_length_without_delta() -> None:
    call = DeedCall(
        course=1,
        direction_text="curve",
        bearing_azimuth_deg_from_north=90.0,
        distance_ft=25.0,
        curve_dir="right",
        radius_ft=50.0,
        arc_length_ft=25.0,
    )

    points = ClosureChecker.compute_traverse([call])
    assert len(points) == 2
    assert math.hypot(points[-1].x, points[-1].y) > 0.0


def test_compute_traverse_treats_zero_delta_curve_as_straight_distance() -> None:
    call = DeedCall(
        course=1,
        direction_text="curve",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=100.0,
        curve_dir="left",
        radius_ft=50.0,
        delta_deg=0.0,
        arc_length_ft=0.0,
        chord_length_ft=0.0,
    )

    points = ClosureChecker.compute_traverse([call])
    assert len(points) == 2
    assert math.isclose(points[-1].x, 0.0, abs_tol=0.001)
    assert math.isclose(points[-1].y, 100.0, abs_tol=0.001)


def test_extract_sample_deeds_report_shows_zero_azimuth_and_runtime_timestamp(
    tmp_path: Path,
) -> None:
    module = _load_script_module("extract_sample_deeds.py")
    legal_desc = LegalDescription(
        source_doc="example.pdf",
        calls=[
            DeedCall(
                course=1,
                direction_text="N 0° E",
                bearing_quadrant="N 0° E",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=100.0,
            )
        ],
    )
    output_file = tmp_path / "report.txt"

    module.create_extraction_report(legal_desc, _sample_closure_result(), output_file)
    report = output_file.read_text()
    report_lines = report.splitlines()

    assert "Source PDF: example.pdf" in report_lines
    assert any(line == "Azimuth:         0.00°" for line in report_lines)
    date_lines = [line for line in report.splitlines() if line.startswith("Date Extracted: ")]
    assert len(date_lines) == 1
    date_line = date_lines[0]
    timestamp = date_line.removeprefix("Date Extracted: ").strip()
    datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


def test_31_pennbrook_script_prints_zero_azimuth(monkeypatch, capsys) -> None:
    module = _load_script_module("test_31_pennbrook_text.py")
    fake_call = DeedCall(
        course=1,
        direction_text="N 0° E",
        bearing_quadrant="N 0° E",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=10.0,
    )

    monkeypatch.setattr(
        module,
        "TextParser",
        SimpleNamespace(
            normalize_legal_description=lambda text: "normalized",
            extract_pob=lambda text: "POB",
            split_into_calls=lambda text: ["N 0° E 10 feet to a point"],
        ),
    )
    monkeypatch.setattr(
        module,
        "CallExtractor",
        SimpleNamespace(extract_calls=lambda text: [fake_call]),
    )
    monkeypatch.setattr(
        module,
        "ClosureChecker",
        SimpleNamespace(verify_closure=lambda calls: _sample_closure_result()),
    )

    module.main()
    output = capsys.readouterr().out
    output_lines = output.splitlines()
    assert "CALL 1:" in output_lines
    assert any(line == "  Azimuth:    0.00°" for line in output_lines)
    assert any(line.startswith("Closure Status: ") for line in output_lines)


# --- Bug #40: "to the right/left of" clauses dropped from `to` field ---


def test_to_the_right_of_intersection_preserved_in_to_field() -> None:
    """'to the right of intersection' is a spatial descriptor, not curve direction."""
    _along, to = TextParser.extract_along_to_fields(
        "N 45° E 100 feet to the right of intersection"
    )
    assert to != ""
    assert "right of intersection" in to


def test_to_the_left_of_centerline_preserved_in_to_field() -> None:
    """'to the left of the centerline' is a spatial descriptor, not curve direction."""
    _along, to = TextParser.extract_along_to_fields(
        "S 30° W 200 feet to the left of the centerline"
    )
    assert to != ""
    assert "left of the centerline" in to


def test_bare_to_the_right_still_filtered_as_curve_direction() -> None:
    """Bare 'to the right' (without 'of') is curve direction and should be filtered."""
    _along, to = TextParser.extract_along_to_fields(
        "along a curve to the right"
    )
    assert to == ""


# ---------------------------------------------------------------------------
# Bug #35: str.format crashes when prompt templates contain literal braces
# ---------------------------------------------------------------------------

_TEMPLATE_WITH_BRACES = (
    'Extract calls from:\n{document_text}\n\nJSON example: {"key": "val"}'
)
_NORMALIZE_TEMPLATE_WITH_BRACES = (
    'Normalize:\n{legal_description_text}\n\nExpected: {"result": true}'
)
_CALLS_TEMPLATE_WITH_BRACES = (
    'Parse:\n{legal_description_text}\n\nSchema: {"calls": []}'
)


def _make_processor_with_mock_client_and_prompts(
    user_template: str,
    system_prompt: str = "You are a parser.",
) -> tuple[PDFProcessor, MagicMock]:
    mock_client = MagicMock()
    mock_client.generate_text_with_pdf.return_value = "extracted text"
    mock_client.generate_text.return_value = "normalized text"
    processor = PDFProcessor(client=mock_client)
    processor._load_prompt = MagicMock(  # type: ignore[method-assign]
        return_value={
            "system_prompt": system_prompt,
            "user_prompt_template": user_template,
        }
    )
    return processor, mock_client


def test_extract_legal_description_does_not_crash_on_braces(tmp_path: Path) -> None:
    processor, mock_client = _make_processor_with_mock_client_and_prompts(
        _TEMPLATE_WITH_BRACES,
    )
    dummy_pdf = tmp_path / "deed.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4 fake")

    processor.extract_legal_description(str(dummy_pdf))

    assert mock_client.generate_text.called
    prompt_sent = mock_client.generate_text.call_args[0][0]
    assert "extracted text" in prompt_sent
    assert '{"key": "val"}' in prompt_sent


def test_normalize_legal_description_does_not_crash_on_braces() -> None:
    processor, mock_client = _make_processor_with_mock_client_and_prompts(
        _NORMALIZE_TEMPLATE_WITH_BRACES,
    )

    processor.normalize_legal_description("Lot {A} Block 3")

    assert mock_client.generate_text.called
    prompt_sent = mock_client.generate_text.call_args[0][0]
    assert "Lot {A} Block 3" in prompt_sent
    assert '{"result": true}' in prompt_sent


def test_extract_calls_ai_does_not_crash_on_braces() -> None:
    mock_client = MagicMock()
    mock_client.generate_text.return_value = json.dumps({"calls": []})
    processor = PDFProcessor(client=mock_client)
    processor._load_prompt = MagicMock(  # type: ignore[method-assign]
        return_value={
            "system_prompt": "You are a parser.",
            "user_prompt_template": _CALLS_TEMPLATE_WITH_BRACES,
        }
    )

    result = processor.extract_calls_ai("Lot {B} in {subdivision}")

    assert result == []
    assert mock_client.generate_text.called
    prompt_sent = mock_client.generate_text.call_args[0][0]
    assert "Lot {B} in {subdivision}" in prompt_sent
    assert '{"calls": []}' in prompt_sent


# --- Bug #41: Parse numeric ordinal principal meridians in PLSS metadata ---


def test_plss_numeric_ordinal_principal_meridian() -> None:
    text = "Section 10, Township 3 North, Range 2 East, 6th Principal Meridian"
    result = TextParser.extract_plss_metadata(text)
    assert result["principal_meridian"] == "6Th Principal Meridian"


def test_plss_numeric_ordinal_pm_abbreviation() -> None:
    text = "Section 5, Township 1 South, Range 4 West, 11TH P.M."
    result = TextParser.extract_plss_metadata(text)
    assert result["principal_meridian"] is not None


def test_plss_alphabetic_meridian_still_works() -> None:
    text = "Section 12, Township 2 North, Range 5 West, San Bernardino Principal Meridian"
    result = TextParser.extract_plss_metadata(text)
    assert result["principal_meridian"] == "San Bernardino Principal Meridian"


# --- Bug #45: Support comma-separated distances in numeric parsing ---


def test_extract_distance_comma_separated_integer() -> None:
    value, unit = TextParser.extract_distance("1,200 feet")
    assert value == 1200.0
    assert unit == "feet"


def test_extract_distance_comma_separated_with_decimal() -> None:
    value, unit = TextParser.extract_distance("3,500.00 ft")
    assert value == 3500.0
    assert unit == "feet"


def test_extract_distance_large_comma_separated() -> None:
    value, unit = TextParser.extract_distance("1,234,567.89 feet")
    assert value == 1234567.89
    assert unit == "feet"


def test_extract_single_call_with_comma_distance() -> None:
    calls = CallExtractor.extract_calls(
        "THENCE N 45° E 1,200 feet to a point"
    )
    assert len(calls) >= 1
    assert calls[0].distance_ft == 1200.0


def test_extract_curve_info_comma_radius() -> None:
    info = CallExtractor.extract_curve_info(
        "along a curve to the right having a radius of 10,000 feet, "
        "delta angle of 15°30', arc length of 2,705.26 feet"
    )
    assert info.get("radius_ft") == 10000.0
    assert math.isclose(info.get("arc_length_ft", 0.0), 2705.26, abs_tol=0.01)


def test_extract_distance_alternate_comma_separated() -> None:
    value = CallExtractor.extract_distance_alternate("1,200 feet along the line")
    assert value == 1200.0


# --- Bug #47: LLM extraction should prefer most detailed section in multi-section deeds ---


def test_extract_prompt_guides_llm_to_prefer_most_detailed_section() -> None:
    """Prompt must instruct the LLM to prefer the most complete metes and bounds
    section when a deed contains multiple legal descriptions (e.g., deed body
    vs Exhibit A)."""
    import yaml

    prompt_path = Path(__file__).resolve().parents[2] / "prompts" / "extract_legal_description.yaml"
    content = yaml.safe_load(prompt_path.read_text())

    system_prompt: str = content["system_prompt"]

    assert "most detailed" in system_prompt.lower() or "most complete" in system_prompt.lower(), (
        "Prompt must instruct LLM to prefer the most detailed/complete section"
    )

    assert "exhibit" in system_prompt.lower() and "attachment" in system_prompt.lower(), (
        "Prompt must mention Exhibit and attachment as preferred sources"
    )

    assert "bearings" in system_prompt.lower() or "distances" in system_prompt.lower(), (
        "Prompt must mention preferring the section with more bearings/distances"
    )


# --- Bug #36: Bearing-minute apostrophes after ° parsed as distances ---


def test_extract_distance_alternate_ignores_bearing_minutes_after_degree_symbol() -> None:
    """Minutes token in a bearing like N 45°30' must NOT be parsed as 30.0 feet."""
    result = CallExtractor.extract_distance_alternate("N 45°30' along the north line")
    assert result == 0.0


def test_extract_distance_alternate_ignores_bearing_minutes_with_space_after_degree() -> None:
    """Minutes token with a space after ° (N 45° 30') must NOT be parsed as 30.0 feet."""
    result = CallExtractor.extract_distance_alternate("N 45° 30' along the north line")
    assert result == 0.0


def test_extract_distance_alternate_still_finds_real_distance_after_bearing() -> None:
    """A real distance following a full bearing must still be extracted."""
    result = CallExtractor.extract_distance_alternate("S 89°59'30\" E 100 feet")
    assert result == 100.0


def test_extract_single_call_no_bogus_distance_from_bearing_minutes() -> None:
    """extract_single_call must NOT produce a bogus distance from bearing minutes.

    With no real distance in the text, the call should return None (no distance
    means no valid call per line 275 guard). The key assertion is that it does
    NOT return a call with distance_ft=30.0 from the minutes token.
    """
    call = CallExtractor.extract_single_call(
        "N 45° 30' along the north line", course=1
    )
    if call is not None:
        assert call.distance_ft != 30.0, "Minutes token was incorrectly parsed as distance"
    # call is None is also acceptable (no real distance in text)


# --- Bug #43: Wire packed-DMS bearing parsing into call extraction pipeline ---


def test_packed_dms_bearing_ne_quadrant() -> None:
    """N 46.1631° E should parse as packed DMS (46°16'31") with correct azimuth."""
    call = CallExtractor.extract_single_call("N 46.1631° E 100 feet", course=1)
    assert call is not None
    assert call.bearing_quadrant is not None
    assert call.bearing_azimuth_deg_from_north is not None
    assert math.isclose(call.bearing_azimuth_deg_from_north, 46.2753, abs_tol=0.01)
    assert math.isclose(call.distance_ft, 100.0, abs_tol=0.001)


def test_packed_dms_bearing_sw_quadrant() -> None:
    """S 30.4500° W should parse as packed DMS (30°45'00") with valid azimuth."""
    call = CallExtractor.extract_single_call("S 30.4500° W 200 feet", course=1)
    assert call is not None
    assert call.bearing_quadrant is not None
    assert call.bearing_azimuth_deg_from_north is not None
    expected_azimuth = 180.0 + 30.75  # S 30°45' W => 210.75°
    assert math.isclose(call.bearing_azimuth_deg_from_north, expected_azimuth, abs_tol=0.01)
    assert math.isclose(call.distance_ft, 200.0, abs_tol=0.001)


def test_standard_bearing_still_works_after_packed_dms_change() -> None:
    """Standard bearing N 45°30' E must continue to parse correctly."""
    call = CallExtractor.extract_single_call("N 45°30' E 100 feet", course=1)
    assert call is not None
    assert call.bearing_quadrant is not None
    assert call.bearing_azimuth_deg_from_north is not None
    assert math.isclose(call.bearing_azimuth_deg_from_north, 45.5, abs_tol=0.01)
    assert math.isclose(call.distance_ft, 100.0, abs_tol=0.001)


# --- Bug #38: Curve radius/arc length unit conversion ---


def test_extract_curve_info_radius_in_meters() -> None:
    """Radius expressed in meters should be converted to feet."""
    info = CallExtractor.extract_curve_info(
        "along a curve to the right having a radius of 50 meters, "
        "delta angle of 30°, arc length of 30 meters"
    )
    assert info.get("radius_ft") is not None
    assert math.isclose(info["radius_ft"], 50 * 3.28084, abs_tol=0.01)
    assert info.get("arc_length_ft") is not None
    assert math.isclose(info["arc_length_ft"], 30 * 3.28084, abs_tol=0.01)


def test_extract_curve_info_radius_in_chains() -> None:
    """Radius expressed in chains should be converted to feet."""
    info = CallExtractor.extract_curve_info(
        "along a curve to the left having a radius of 2 chains, "
        "delta angle of 45°, arc length of 1 chain"
    )
    assert info.get("radius_ft") is not None
    assert math.isclose(info["radius_ft"], 2 * 66.0, abs_tol=0.01)
    assert info.get("arc_length_ft") is not None
    assert math.isclose(info["arc_length_ft"], 1 * 66.0, abs_tol=0.01)


def test_extract_curve_info_radius_in_feet_unchanged() -> None:
    """Radius in feet (explicit) should remain unchanged."""
    info = CallExtractor.extract_curve_info(
        "along a curve to the right having a radius of 50 feet, "
        "delta angle of 20°, arc length of 17.45 feet"
    )
    assert info.get("radius_ft") is not None
    assert math.isclose(info["radius_ft"], 50.0, abs_tol=0.01)
    assert info.get("arc_length_ft") is not None
    assert math.isclose(info["arc_length_ft"], 17.45, abs_tol=0.01)


def test_extract_curve_info_no_unit_defaults_to_feet() -> None:
    """When no unit is specified, values should remain as feet (default)."""
    info = CallExtractor.extract_curve_info(
        "along a curve to the right having a radius of 100, "
        "delta angle of 10°"
    )
    assert info.get("radius_ft") is not None
    assert math.isclose(info["radius_ft"], 100.0, abs_tol=0.01)


def test_extract_curve_info_fallback_path_radius_in_meters() -> None:
    """Fallback regex path should also convert radius units."""
    info = CallExtractor.extract_curve_info(
        "curve to the right, radius of 25 meters, delta 15 degrees"
    )
    assert info.get("radius_ft") is not None
    assert math.isclose(info["radius_ft"], 25 * 3.28084, abs_tol=0.01)


def test_extract_curve_info_fallback_path_arc_length_in_meters() -> None:
    """Fallback regex path should also convert arc length units."""
    info = CallExtractor.extract_curve_info(
        "curve to the left, radius of 40 meters, "
        "delta 20 degrees, arc length of 14 meters"
    )
    assert info.get("arc_length_ft") is not None
    assert math.isclose(info["arc_length_ft"], 14 * 3.28084, abs_tol=0.01)
