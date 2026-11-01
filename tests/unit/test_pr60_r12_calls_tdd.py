"""Round 12: tangent curves with a stated radius point; cardinal-only chord curves."""

from __future__ import annotations

import pytest
from mp_parse.calls import extract_single_call as package_single_call

from metesparser.call_extractor import CallExtractor
from tests.fixtures.package_parser import extract_calls as package_extract_calls

CLOSING = "; THENCE due South 50 feet; THENCE due West 50 feet to the point of beginning."


def _via_calls(extract):
    return lambda text: extract(text + CLOSING, strict=True)[0]


def _via_single(extract):
    return lambda text: extract(text, 1)


ENTRY_POINTS = {
    "package-calls": _via_calls(package_extract_calls),
    "monolith-calls": _via_calls(CallExtractor.extract_calls),
    "package-single": _via_single(package_single_call),
    "monolith-single": _via_single(CallExtractor.extract_single_call),
}


@pytest.fixture(params=sorted(ENTRY_POINTS))
def parse(request):
    return ENTRY_POINTS[request.param]


CURVE = (
    "Thence along a curve to the right, {tan}having a radius of 100.00 feet, "
    "whose radius point bears S 10°00'00\" E, an arc length of 20.00 feet"
)


@pytest.mark.parametrize(
    "tan",
    [
        "tangent to the last course, ",
        "tangent to the preceding course, ",
        "being tangent, ",
        "a tangent curve, ",
    ],
)
def test_tangent_curve_with_radius_point_stays_tangent(parse, tan):
    call = parse(CURVE.format(tan=tan))
    assert call is not None
    assert call.non_tangent is False
    assert call.radial_bearing is not None


def test_radius_point_without_tangent_statement_is_non_tangent(parse):
    call = parse(CURVE.format(tan=""))
    assert call.non_tangent is True
    assert call.radial_bearing is not None


def test_explicit_non_tangent_wins_over_tangent_words(parse):
    call = parse(CURVE.format(tan="non-tangent, "))
    assert call.non_tangent is True


def test_chord_only_curve_keeps_cardinal_only_note(parse):
    call = parse(
        "Thence southwesterly along a curve to the right having a radius of 100.00 feet, "
        "the chord of which bears S 40°00'00\" W, 50.00 feet"
    )
    assert call is not None
    assert "incomplete bearing - cardinal only" in call.notes
    assert "positioned by chord only" in call.notes
