"""Round 17: chord clause word orders and non-tangent spellings (package and monolith)."""

from __future__ import annotations

import pytest
from mp_bearing.azimuth import bearing_to_azimuth
from mp_parse.calls import extract_single_call as package_single_call

from metesparser.call_extractor import CallExtractor
from tests.fixtures.package_parser import extract_calls as package_extract_calls

CLOSING = "; THENCE due South 50 feet; THENCE due West 50 feet to the point of beginning."


def _via_calls(extract):
    return lambda text: extract(text + CLOSING, strict=True)[0]


ENTRY_POINTS = {
    "package-calls": _via_calls(package_extract_calls),
    "monolith-calls": _via_calls(CallExtractor.extract_calls),
    "package-single": lambda text: package_single_call(text, 1),
    "monolith-single": lambda text: CallExtractor.extract_single_call(text, 1),
}


@pytest.fixture(params=sorted(ENTRY_POINTS))
def parse(request):
    return ENTRY_POINTS[request.param]


BASE = "Thence along a curve to the right having a radius of 100.00 feet and {clause} to a point"

CHORD_CLAUSES = [
    "an arc length of 52.36 feet and a chord of 51.76 feet bearing N 45°00'00\" E",
    "an arc length of 52.36 feet, chord N 45°00'00\" E 51.76 feet",
    "an arc length of 52.36 feet, a chord distance of 51.76 feet on a bearing of N 45° E",
    "an arc length of 52.36 feet subtended by a chord of 51.76 feet which bears N 45° E",
    "an arc length of 52.36 feet, long chord N 45° E, 51.76 feet",
    "an arc length of 52.36 feet, chord length of 51.76 feet bears N 45° E",
]


@pytest.mark.parametrize("clause", CHORD_CLAUSES)
def test_chord_word_orders_record_chord_not_tangent(parse, clause):
    call = parse(BASE.format(clause=clause))
    assert call is not None
    assert call.chord_bearing is not None
    assert bearing_to_azimuth(call.chord_bearing) == pytest.approx(45.0, abs=1e-9)
    assert call.chord_length_ft == 51.76
    assert call.bearing_azimuth_deg_from_north == pytest.approx(30.0, abs=1e-3)


@pytest.mark.parametrize(
    "clause",
    [
        "an arc length of 52.36 feet, the chord is 51.76 feet",
        "an arc length of 52.36 feet, a chord of 51.76 feet",
    ],
)
def test_chord_length_without_bearing_creates_no_chord_bearing(parse, clause):
    call = parse(BASE.format(clause=clause))
    assert call is not None
    assert call.chord_bearing is None


@pytest.mark.parametrize(
    "spelling", ["non-tangent", "non tangent", "non–tangent", "nontangent", "non‐tangent"]
)
def test_non_tangent_spellings_are_not_tangent_statements(parse, spelling):
    call = parse(
        f"Thence along a {spelling} curve to the right having a radius of 100.00 feet, "
        "the radius point bears S 10°00'00\" E, an arc length of 52.36 feet"
    )
    assert call is not None
    assert call.non_tangent is True
