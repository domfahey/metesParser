from __future__ import annotations

import math
import sys

import pytest

from metesparser import cli
from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker
from metesparser.models import ClosureResult, ConversionFactors, DeedCall
from metesparser.text_parser import TextParser


def test_unknown_distance_unit_raises_error() -> None:
    with pytest.raises(ValueError, match="Unsupported distance unit"):
        ConversionFactors.convert_to_feet(10.0, "fott")


def test_plss_township_south_parses_as_south() -> None:
    metadata = TextParser.extract_plss_metadata("Township 15 South")
    assert metadata["township"] == "15 S"


def test_perimeter_uses_line_distance_for_zero_deflection_curve() -> None:
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

    assert math.isclose(ClosureChecker.calculate_perimeter([call]), 100.0, abs_tol=0.001)


def test_curve_delta_parses_textual_minutes_tokens() -> None:
    curve_info = CallExtractor.extract_curve_info(
        "curve to the right radius of 100 feet delta angle of 90 degrees 30 minutes"
    )
    delta = curve_info.get("delta_deg")
    assert isinstance(delta, float)
    assert math.isclose(delta, 90.5, abs_tol=0.0001)


def test_cli_no_longer_exposes_broken_export_subcommand(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["metesparser", "export", "calls.csv"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


def test_closure_status_with_warnings_requires_review() -> None:
    result = ClosureResult(
        misclosure_x_ft=0.0,
        misclosure_y_ft=0.0,
        misclosure_ft=0.001,
        area_sq_ft=100.0,
        area_acres=100.0 / 43560.0,
        perimeter_ft=40.0,
        closure_passed=True,
        angle_check_passed=True,
        curve_consistency_passed=True,
        warnings=["area mismatch"],
        points=[],
    )

    assert result.get_closure_status() == "NEEDS REVIEW"


def test_extract_poc_detects_pob_abbreviation() -> None:
    text = "COMMENCING at an iron pin; THENCE N 45° E 10 feet to the POB; THENCE N 45° E"
    poc = TextParser.extract_poc(text)
    assert "iron pin" in poc


def test_principal_meridian_keeps_multiword_name() -> None:
    metadata = TextParser.extract_plss_metadata("in Mount Diablo Principal Meridian")
    assert metadata["principal_meridian"] == "Mount Diablo Principal Meridian"


def test_ocr_style_dms_minutes_not_parsed_as_apostrophe_distance() -> None:
    value = CallExtractor.extract_distance_alternate("N 45 30' along the north line")
    assert value == 0.0
