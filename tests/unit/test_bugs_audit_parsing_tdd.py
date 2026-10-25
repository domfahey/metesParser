"""Regression tests for audited parser defects across package and monolith APIs."""

from __future__ import annotations

import math

import pytest
from mp_parse import extract_calls as package_extract_calls
from mp_parse import extract_direction as package_extract_direction
from mp_parse.metadata import extract_along_to_fields as package_extract_along_to_fields

from metesparser.call_extractor import CallExtractor as MonolithCallExtractor
from metesparser.text_parser import TextParser as MonolithTextParser

NUMBERED_CALLS = (
    "1. N 45° E 100 feet to an iron pin;\n"
    "2. S 45° E 100 feet to a stone;\n"
    "3. S 45° W 100 feet to an iron pipe;\n"
    "4. N 45° W 100 feet to the point of beginning."
)


@pytest.mark.parametrize(
    "extract_calls",
    [package_extract_calls, MonolithCallExtractor.extract_calls],
    ids=["package", "monolith"],
)
def test_numbered_multiline_calls_are_preserved(extract_calls) -> None:
    calls = extract_calls(NUMBERED_CALLS)
    assert len(calls) == 4
    assert [call.to for call in calls] == [
        "an iron pin",
        "a stone",
        "an iron pipe",
        "the point of beginning",
    ]


@pytest.mark.parametrize("marker", ["1)", "(1)"], ids=["bare-paren", "parenthesized"])
@pytest.mark.parametrize(
    "extract_calls",
    [package_extract_calls, MonolithCallExtractor.extract_calls],
    ids=["package", "monolith"],
)
def test_numbered_call_marker_variants_are_preserved(marker, extract_calls) -> None:
    text = NUMBERED_CALLS.replace("1.", marker, 1).replace("2.", marker.replace("1", "2"), 1)
    calls = extract_calls(text)
    assert len(calls) == 4


@pytest.mark.parametrize(
    "extract_calls",
    [package_extract_calls, MonolithCallExtractor.extract_calls],
    ids=["package", "monolith"],
)
def test_wrapped_numbered_call_keeps_its_continuation(extract_calls) -> None:
    text = (
        "1. N 45° E 100 feet along the north\n"
        "boundary to an iron pin;\n"
        "2. S 45° W 100 feet to a stone"
    )
    calls = extract_calls(text)
    assert len(calls) == 2
    assert calls[0].along.casefold() == "the north boundary"
    assert calls[0].to == "an iron pin"


@pytest.mark.parametrize(
    "extract_direction,extract_calls",
    [
        (package_extract_direction, package_extract_calls),
        (MonolithCallExtractor.extract_direction, MonolithCallExtractor.extract_calls),
    ],
    ids=["package", "monolith"],
)
@pytest.mark.parametrize(
    "packed,expected",
    [
        ("46.1631", 46 + 16 / 60 + 31 / 3600),
        ("12.3045", 12 + 30 / 60 + 45 / 3600),
        ("46.16315", 46 + 16 / 60 + 31.5 / 3600),
        ("46.16", 46 + 16 / 60),
    ],
)
def test_packed_dms_retains_minutes_and_seconds(
    extract_direction, extract_calls, packed: str, expected: float
) -> None:
    text = f"THENCE N {packed}° E 100 feet to an iron pin"
    call = extract_calls(text)[0]
    assert math.isclose(call.bearing_azimuth_deg_from_north, expected, abs_tol=1e-8)


@pytest.mark.parametrize(
    "extract_direction",
    [package_extract_direction, MonolithCallExtractor.extract_direction],
    ids=["package", "monolith"],
)
def test_invalid_packed_dms_is_rejected(extract_direction) -> None:
    with pytest.raises(ValueError):
        extract_direction("THENCE N 12.5960° E 100 feet")


@pytest.mark.parametrize(
    "extract_calls,extract_along_to_fields",
    [
        (package_extract_calls, package_extract_along_to_fields),
        (MonolithCallExtractor.extract_calls, MonolithTextParser.extract_along_to_fields),
    ],
    ids=["package", "monolith"],
)
@pytest.mark.parametrize(
    "delimiter",
    [";", ". The next corner", ""],
    ids=["semicolon", "sentence period", "end"],
)
@pytest.mark.parametrize(
    "monument_text",
    ["a 1.5 inch iron pipe", "a 1.5 in. iron pipe"],
    ids=["decimal", "inch abbreviation"],
)
def test_decimal_monument_size_is_not_a_sentence_boundary(
    extract_calls, extract_along_to_fields, delimiter: str, monument_text: str
) -> None:
    text = f"THENCE N 45° E 100 feet along the boundary to {monument_text}{delimiter}"
    call = extract_calls(text)[0]
    assert call.to == monument_text
    assert call.monument_type == "iron_pipe"
    along, to = extract_along_to_fields(text)
    assert along == "the boundary"
    assert to == call.to


@pytest.mark.parametrize(
    "extract_calls,extract_along_to_fields",
    [
        (package_extract_calls, package_extract_along_to_fields),
        (MonolithCallExtractor.extract_calls, MonolithTextParser.extract_along_to_fields),
    ],
    ids=["package", "monolith"],
)
def test_endpoint_preserves_route_initials(extract_calls, extract_along_to_fields) -> None:
    text = "THENCE N 45° E 100 feet to the corner of U.S. Route 1. The next call follows."
    call = extract_calls(text)[0]
    assert call.to == "the corner of U.S. Route 1"
    assert extract_along_to_fields(text)[1] == call.to
