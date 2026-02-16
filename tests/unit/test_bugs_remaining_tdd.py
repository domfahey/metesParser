from __future__ import annotations

import json
import math
from pathlib import Path
from unittest.mock import MagicMock

from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker
from metesparser.models import DeedCall
from metesparser.pdf_processor import PDFProcessor
from metesparser.text_parser import TextParser


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


# --- Bug #40: "to the right/left of" clauses dropped from `to` field ---


def test_to_the_right_of_intersection_preserved_in_to_field() -> None:
    """'to the right of intersection' is a spatial descriptor, not curve direction."""
    _along, to = TextParser.extract_along_to_fields("N 45° E 100 feet to the right of intersection")
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
    _along, to = TextParser.extract_along_to_fields("along a curve to the right")
    assert to == ""


# ---------------------------------------------------------------------------
# Bug #35: str.format crashes when extracted text contains braces
# ---------------------------------------------------------------------------

TEXT_WITH_BRACES = "Lot {A} Block 3, BEGINNING at a point N 45° E 100 feet to {POB}"


def _make_processor_with_mock_client() -> tuple[PDFProcessor, MagicMock]:
    """Build a PDFProcessor whose LLM client is a mock returning brace-laden text."""
    mock_client = MagicMock()
    mock_client.generate_text_with_pdf.return_value = TEXT_WITH_BRACES
    mock_client.generate_text.return_value = TEXT_WITH_BRACES
    processor = PDFProcessor(client=mock_client, cache=False)
    return processor, mock_client


def test_extract_legal_description_does_not_crash_on_braces(tmp_path: Path) -> None:
    processor, mock_client = _make_processor_with_mock_client()

    dummy_pdf = tmp_path / "deed.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4 fake")

    result = processor.extract_legal_description(str(dummy_pdf))

    assert result == TEXT_WITH_BRACES
    assert mock_client.generate_text.called


def test_normalize_legal_description_does_not_crash_on_braces() -> None:
    processor, mock_client = _make_processor_with_mock_client()

    result = processor.normalize_legal_description(TEXT_WITH_BRACES)

    assert result == TEXT_WITH_BRACES
    assert mock_client.generate_text.called


def test_extract_calls_ai_does_not_crash_on_braces() -> None:
    mock_client = MagicMock()
    mock_client.generate_text.return_value = json.dumps({"calls": []})
    processor = PDFProcessor(client=mock_client, cache=False)

    result = processor.extract_calls_ai(TEXT_WITH_BRACES)

    assert result == []
    assert mock_client.generate_text.called


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


# ── Bug: abbreviated cardinal directions (NW, SW, NE, SE) not recognized ──


def test_extract_direction_abbreviated_sw() -> None:
    """extract_direction() must match abbreviated cardinal 'SW'."""
    result = CallExtractor.extract_direction(
        "SW, FORMING AN INTERIOR ANGLE OF 89°43'30\", 200 FEET"
    )
    assert result != "", "Abbreviated 'SW' should be recognized as a direction"
    assert "sw" in result.lower()


def test_extract_direction_abbreviated_ne() -> None:
    """extract_direction() must match abbreviated cardinal 'NE'."""
    result = CallExtractor.extract_direction("NE FORMING AN INTERIOR ANGLE")
    assert result != ""
    assert "ne" in result.lower()


def test_extract_direction_abbreviated_nw() -> None:
    """extract_direction() must match abbreviated cardinal 'NW'."""
    result = CallExtractor.extract_direction(
        "NW ALONG THE SW LINE OF HADDON AVENUE 129 FEET"
    )
    assert result != ""
    assert "nw" in result.lower()


def test_cardinal_only_pattern_matches_abbreviations() -> None:
    """_CARDINAL_ONLY_PATTERN must match abbreviated cardinals."""
    from metesparser.call_extractor import _CARDINAL_ONLY_PATTERN

    for abbr in ["NW", "SW", "NE", "SE"]:
        assert _CARDINAL_ONLY_PATTERN.fullmatch(abbr), (
            f"_CARDINAL_ONLY_PATTERN should match '{abbr}'"
        )


def test_extract_calls_retains_abbreviated_cardinal_calls() -> None:
    """Calls with LLM-abbreviated cardinals (NW/SW/NE/SE) must be retained."""
    text = (
        "BEGINNING AT THE WEST CORNER; THENCE\n"
        "1. NW ALONG THE SW LINE 129 FEET; THENCE\n"
        "2. SW, FORMING AN INTERIOR ANGLE OF 89°43'30\", "
        "200 FEET TO THE NE LINE; THENCE\n"
        "3. SE, FORMING AN INTERIOR ANGLE OF 90°16'10\", "
        "129 FEET TO THE NW LINE; AND THENCE\n"
        "4. NE FORMING AN INTERIOR ANGLE OF 89°43'30\", "
        "200 FEET TO THE SW LINE AND PLACE OF BEGINNING."
    )
    calls = CallExtractor.extract_calls(text)
    assert len(calls) == 4, f"Expected 4 calls, got {len(calls)}"
    for call in calls:
        assert call.notes == "incomplete bearing - cardinal only"
