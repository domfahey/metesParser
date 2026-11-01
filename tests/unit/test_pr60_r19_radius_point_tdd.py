"""Round 19: the length after a radius-point bearing is the radius."""

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


REPRO = (
    "thence along a non-tangent curve to the right, radius point bears N 10° E 500.00 feet, "
    "an arc length of 100.00 feet to a point"
)


def test_radius_point_length_is_radius(parse):
    call = parse(REPRO)
    assert call.radius_ft == pytest.approx(500.0)
    assert call.radial_bearing == "N 10° E"
    assert call.non_tangent is True
    assert call.arc_length_ft == pytest.approx(100.0)
    assert call.distance_ft == pytest.approx(100.0)


@pytest.mark.parametrize("subject", ["radius point", "center point", "radial line"])
def test_radial_subjects_agree(parse, subject):
    call = parse(REPRO.replace("radius point", subject))
    assert call.radius_ft == pytest.approx(500.0)


def test_stated_radius_wins_and_conflict_is_flagged(parse):
    call = parse(
        "thence along a non-tangent curve to the right with a radius of 400.00 feet, radius point "
        "bears N 10° E 500.00 feet, an arc length of 100.00 feet to a point"
    )
    assert call.radius_ft == pytest.approx(400.0)
    assert call.radial_bearing == "N 10° E"
    assert "radius" in (call.notes or "").lower()
    assert "conflict" in (call.notes or "").lower()


def test_agreeing_radius_is_not_flagged(parse):
    call = parse(
        "thence along a non-tangent curve to the right with a radius of 500.00 feet, radius point "
        "bears N 10° E 500.00 feet, an arc length of 100.00 feet to a point"
    )
    assert call.radius_ft == pytest.approx(500.0)
    assert "conflict" not in (call.notes or "").lower()
