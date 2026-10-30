"""Round 19: a stated course length on a radius+delta curve is the stated arc."""

from __future__ import annotations

import pytest
from mp_parse.calls import extract_single_call as package_single_call
from mp_verify.checks import check_curve_consistency

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


STATED = (
    "thence N 80° E along a curve to the right having a radius of 500.00 feet and a "
    "central angle of 10°00'00\" a distance of 87.30 feet to a point"
)
UNSTATED = (
    "thence N 80° E along a curve to the right having a radius of 500.00 feet and a "
    "central angle of 10°00'00\" to a point"
)


def test_stated_length_is_kept_as_stated_arc(parse):
    call = parse(STATED)
    assert call.distance_ft == pytest.approx(87.30)
    assert call.arc_length_ft == pytest.approx(87.30)
    assert call.radius_ft == pytest.approx(500.0)
    assert call.delta_deg == pytest.approx(10.0)
    assert "computed" not in (call.notes or "").lower()


def test_unstated_length_is_computed_with_note(parse):
    call = parse(UNSTATED)
    assert call.distance_ft == pytest.approx(87.2665, abs=1e-3)
    assert call.arc_length_ft is None
    assert "computed from radius and delta" in (call.notes or "")


def test_stated_length_disagreeing_with_radius_delta_is_flagged(parse):
    call = parse(STATED.replace("87.30", "90.00"))
    assert call.arc_length_ft == pytest.approx(90.0)
    assert check_curve_consistency([call])[0] is False


def test_rounded_three_hundredths_discrepancy_is_flagged(parse):
    # 87.30 stated vs 87.2665 from R and delta: reported per the rounding-aware tolerance.
    ok, issues = check_curve_consistency([parse(STATED)])
    assert ok is False
    assert issues


def test_stated_length_consistent_passes(parse):
    call = parse(STATED.replace("87.30", "87.27"))
    assert check_curve_consistency([call])[0] is True


# --- center line vs curve-center element --------------------------------------

COURSE = (
    "thence N 80° E along a curve to the right having a radius of 500.00 feet "
    "and a central angle of 10°00'00\" {clause} a distance of 100.00 feet to a point"
)
NEGATIVE = [
    "along the center line of Route 9",
    "along the centerline of Route 9",
    "along the center-line of Route 9",
    "along the centre line of Route 9",
    "along the center of Route 9",
    "along the center of Main Street",
    "along the center of the road",
    "along the center of the creek",
]


@pytest.mark.parametrize("clause", NEGATIVE)
def test_center_line_is_not_a_curve_element(parse, clause):
    call = parse(COURSE.format(clause=clause))
    assert call.radius_ft == pytest.approx(500.0)
    assert call.distance_ft == pytest.approx(100.0)


POSITIVE = [
    "the center point being 500.00 feet away",
    "the center of the curve lying 500.00 feet away",
    "the center of said curve bearing N 10° E 500.00 feet",
    "center point 500.00 feet",
]


@pytest.mark.parametrize("clause", POSITIVE)
def test_genuine_center_element_is_not_the_course_length(parse, clause):
    call = parse(COURSE.format(clause=clause))
    assert call.distance_ft == pytest.approx(100.0)
