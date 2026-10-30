"""PR #60 round 10: radial courses, tangent + chord curves, dead reference helpers.

1. A straight course run *along* a radial line keeps the bearing in its radial
   clause; only radial clauses that describe a curve's center (on a curve call) or
   the radius point of the curve reached at the end of a line are removed. A
   radial clause without a comma ends at its bearing.
2. A curve stating its tangent, chord bearing, chord length and radius (no delta
   or arc) has a determined delta: twice the tangent-to-chord deflection, whose
   sign must match the curve direction. Consistent elements derive the delta (for
   the arc only; ``delta_deg`` stays None) and the arc; inconsistent ones are kept,
   flagged and positioned by the chord only, so the curve check never passes.
3. The unused ``_without_chord_bearing``/``_without_radial_bearing`` helpers are gone.
"""

from __future__ import annotations

import math

import pytest
from mp_models import CheckResult
from mp_parse import calls as package_calls
from mp_parse.calls import extract_single_call as package_single_call
from mp_verify.closure import verify_closure as package_verify

from metesparser import call_extractor as monolith_calls
from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker
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


# --- 1. A straight course along a radial line -----------------------------------

ALONG_RADIAL = [
    "thence along a radial line bearing S 30°00'00\" W, 25.00 feet to a point",
    "thence along a radial line bearing S 30°00'00\" W 25.00 feet to a point",
    "thence along the radial line of said curve S 30°00'00\" W 25.00 feet to a point",
    "thence along said radial line bearing S 30°00'00\" W 25.00 feet to a point",
    "thence radially S 30°00'00\" W 25.00 feet to a point",
]


@pytest.mark.parametrize("text", ALONG_RADIAL)
def test_course_along_radial_line_keeps_its_bearing(parse, text):
    call = parse(text)
    assert call is not None
    assert call.bearing_azimuth_deg_from_north == pytest.approx(210.0)
    assert call.direction_text == "S 30°00'00\" W"
    assert call.distance_ft == pytest.approx(25.0)
    assert call.radial_bearing is None
    assert call.non_tangent is False
    assert call.curve_dir is None


def test_along_radial_line_then_next_curves_radius_point(parse):
    call = parse(
        "thence along a radial line bearing S 30° W 25.00 feet to a point on a curve, "
        "the radius point of which bears S 30° W"
    )
    assert call.bearing_azimuth_deg_from_north == pytest.approx(210.0)
    assert call.direction_text == "S 30° W"
    assert call.radial_bearing is None


def test_line_to_next_curves_radius_point_without_comma(parse):
    # The radial clause ends at its bearing; the course bearing before it stands.
    call = parse(
        "thence N 80° E 100.00 feet to a point on a curve the radius point of which "
        "bears N 10° W and continuing"
    )
    assert call.bearing_azimuth_deg_from_north == pytest.approx(80.0)
    assert call.direction_text == "N 80° E"


def test_curve_radial_clause_without_comma_ends_at_its_bearing(parse):
    # On a curve the radial clause is removed, but only up to its bearing: the
    # stated tangent that follows it is still read.
    call = parse(
        "thence along a curve to the left the radius point of which bears S 10° W "
        "on a tangent bearing N 80° E having a radius of 500 feet, an arc length of "
        "50 feet to a point"
    )
    assert call.radial_bearing == "S 10° W"
    assert call.bearing_azimuth_deg_from_north == pytest.approx(80.0)
    assert call.direction_text == "N 80° E"


def test_curve_along_radial_phrase_is_still_not_the_tangent(parse):
    # A curve never runs along a radial line: its radial clause is always removed.
    call = parse(
        "thence along a curve to the right having a radius of 50.00 feet, along the "
        "radial line of N 10° W, an arc length of 30.00 feet to a point"
    )
    assert call.bearing_azimuth_deg_from_north is None
    assert call.radial_bearing == "N 10° W"


# --- 2. Tangent + chord + radius curves -----------------------------------------

TANGENT_CHORD = (
    "thence N 10°00'00\" E along a curve to the {side} having a radius of 500.00 feet, "
    "the chord of which bears N {chord_deg}°00'00\" E {chord} feet to a point"
)
DELTA_RAD = math.radians(70.0)
DERIVED_ARC = 500.0 * DELTA_RAD
INCONSISTENT_NOTE = "stated tangent, chord and radius are inconsistent"


def test_consistent_tangent_and_chord_derive_delta_and_arc(parse):
    call = parse(TANGENT_CHORD.format(side="right", chord_deg=45, chord="573.58"))
    assert call is not None
    assert call.bearing_azimuth_deg_from_north == pytest.approx(10.0)
    assert call.delta_deg is None  # only an explicitly stated delta is stored
    assert call.arc_length_ft == pytest.approx(DERIVED_ARC)
    assert call.distance_ft == pytest.approx(DERIVED_ARC)
    assert call.chord_length_ft == pytest.approx(573.58)
    assert not call.is_chord_only_curve()
    notes = call.notes or ""
    assert "delta derived from tangent and chord bearings" in notes
    assert "positioned by chord only" not in notes
    assert INCONSISTENT_NOTE not in notes


def test_consistent_left_curve(parse):
    # Left curve: chord = tangent - delta/2.
    call = parse(
        "thence N 80°00'00\" E along a curve to the left having a radius of 500.00 feet, "
        "the chord of which bears N 45°00'00\" E 573.58 feet to a point"
    )
    assert call.arc_length_ft == pytest.approx(DERIVED_ARC)
    assert not call.is_chord_only_curve()


@pytest.mark.parametrize(
    "side,chord_deg,chord",
    [
        ("right", 45, "99.93"),  # delta 70 fixes chord ~573.6
        ("left", 45, "573.58"),  # deflection to the right on a left curve
        ("right", 10, "100.00"),  # zero deflection
    ],
)
def test_inconsistent_tangent_chord_radius_is_flagged(parse, side, chord_deg, chord):
    call = parse(TANGENT_CHORD.format(side=side, chord_deg=chord_deg, chord=chord))
    assert call is not None
    assert call.bearing_azimuth_deg_from_north == pytest.approx(10.0)
    assert call.delta_deg is None
    assert call.arc_length_ft is None
    assert call.is_chord_only_curve()
    assert call.distance_ft == pytest.approx(float(chord))
    assert INCONSISTENT_NOTE in (call.notes or "")


def test_non_tangent_curve_does_not_derive_delta_from_its_bearing(parse):
    call = parse(
        "thence N 10°00'00\" E along a non-tangent curve to the right having a radius of "
        "500.00 feet, the chord of which bears N 45°00'00\" E 573.58 feet to a point"
    )
    assert call.arc_length_ft is None
    assert call.is_chord_only_curve()
    assert INCONSISTENT_NOTE not in (call.notes or "")


PARSE_VERIFY = {
    "package": (package_single_call, package_verify),
    "monolith": (CallExtractor.extract_single_call, ClosureChecker.verify_closure),
}


def _triangle(impl, chord):
    single, verify = PARSE_VERIFY[impl]
    curve = single(TANGENT_CHORD.format(side="right", chord_deg=45, chord=chord), 1)
    leg = float(chord) * math.sqrt(0.5)
    south = single(f"THENCE due South {leg:.2f} feet to a point", 2)
    west = single(f"THENCE due West {leg:.2f} feet to the point of beginning", 3)
    return verify([curve, south, west])


def _curve_check(result) -> CheckResult:
    return next(check for check in result.checks if check.name == "curve_consistency")


@pytest.mark.parametrize("impl", PARSE_VERIFY)
def test_consistent_tangent_chord_curve_passes_curve_check(impl):
    result = _triangle(impl, "573.58")
    assert result.curve_consistency_passed is True
    assert _curve_check(result).status == "passed"
    assert not any("positioned by chord only" in w for w in result.warnings)


@pytest.mark.parametrize("impl", PARSE_VERIFY)
def test_inconsistent_tangent_chord_curve_never_passes_curve_check(impl):
    result = _triangle(impl, "99.93")
    assert result.curve_consistency_passed is False
    assert _curve_check(result).status in ("failed", "blocked")


# --- 3. Dead reference-bearing helpers --------------------------------------------


@pytest.mark.parametrize("module", [package_calls, monolith_calls])
def test_unused_reference_helpers_are_removed(module):
    assert not hasattr(module, "_without_chord_bearing")
    assert not hasattr(module, "_without_radial_bearing")
