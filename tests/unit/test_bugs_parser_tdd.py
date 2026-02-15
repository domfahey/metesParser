from __future__ import annotations

import math

from metesparser.call_extractor import CallExtractor
from metesparser.text_parser import TextParser


def test_extract_distance_accepts_singular_foot() -> None:
    value, unit = TextParser.extract_distance("1 foot")
    assert value == 1.0
    assert unit == "feet"


def test_extract_plss_range_west_not_misclassified_as_east() -> None:
    data = TextParser.extract_plss_metadata("Range 3 West")
    assert data["range"] == "3 W"


def test_extract_distance_alternate_matches_apostrophe_with_space_context() -> None:
    value = CallExtractor.extract_distance_alternate("N 45° E 125.26' along the north line")
    assert math.isclose(value, 125.26, abs_tol=0.001)


def test_extract_distance_alternate_rejects_minutes_collapsed_into_to_phrase() -> None:
    value = CallExtractor.extract_distance_alternate("N 45°30'to an iron pin")
    assert value == 0.0


def test_extract_along_to_fields_does_not_treat_alongside_as_along_clause() -> None:
    along, to = TextParser.extract_along_to_fields("N 45° E 100 feet alongside the north fence")
    assert along == ""
    assert to == ""


def test_split_into_calls_supports_parenthesized_numbers() -> None:
    calls = TextParser.split_into_calls("(1) N 45° E 100 feet\n(2) S 45° W 100 feet")
    assert calls == ["N 45° E 100 feet", "S 45° W 100 feet"]


def test_split_into_calls_supports_bare_number_paren_numbers() -> None:
    calls = TextParser.split_into_calls("1) N 45° E 100 feet\n2) S 45° W 100 feet")
    assert calls == ["N 45° E 100 feet", "S 45° W 100 feet"]


def test_split_exception_clauses_ignores_incidental_including_word() -> None:
    text = "THENCE N 45° E 100 feet along the line including lots 1 and 2; THENCE S 45° W 100 feet"
    assert TextParser.split_exception_clauses(text) == [(text, False)]


def test_extract_curve_info_accepts_decimal_degree_delta() -> None:
    curve = CallExtractor.extract_curve_info(
        "along a curve to the right having a radius of 100 feet and a delta angle of 90.5 degrees to a point"
    )
    assert math.isclose(float(curve["delta_deg"]), 90.5, abs_tol=0.0001)


def test_curve_direction_to_phrase_not_parsed_as_endpoint() -> None:
    along, to = TextParser.extract_along_to_fields(
        "N 45° E 100 feet along a curve to the right having a radius of 50 feet and an arc length of 78.54 feet"
    )
    assert along.startswith("a curve to the right")
    assert to == ""


def test_zero_delta_curve_does_not_drop_call_when_line_distance_exists() -> None:
    call = CallExtractor.extract_single_call(
        "N 45° E 100 feet along a curve to the right having a radius of 50 feet and a delta angle of 0 degrees",
        course=1,
    )
    assert call is not None
    assert math.isclose(call.distance_ft, 100.0, abs_tol=0.001)
