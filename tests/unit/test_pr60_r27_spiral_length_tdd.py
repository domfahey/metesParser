"""PR #60 round 27: a spiral stated by direction and length (no chord) is representable.

For a spiral the stated "length" is the stated curve length; it is stored in
``arc_length_ft`` (never R * delta) and is the course distance. With no stated chord
the spiral is unpositioned: closure, area and perimeter are not determined and the
curve check is blocked as spiral_geometry_unverified.
"""

from __future__ import annotations

import mp_models
import pytest
from mp_parse.calls import extract_calls as package_extract_calls
from mp_verify.closure import calculate_perimeter
from mp_verify.closure import verify_closure as package_verify

from metesparser import models as monolith_models
from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker

TAIL = "; thence S 0° E 100 feet; thence S 90° W 100 feet to the point of beginning."


def _deed(course: str) -> str:
    return "BEGINNING at a pin; thence N 0° E 100 feet; thence " + course + TAIL


LENGTH_ONLY = "along a spiral curve to the right having a length of 150.00 feet to a point"
RADIUS_LENGTH = (
    "along a spiral curve to the right having a radius of 1000.00 feet and a length "
    "of 150.00 feet to a point"
)
LENGTH_NO_DIR = "along a spiral curve having a length of 150.00 feet to a point"
CIRCULAR = (
    "along a curve to the right having a radius of 1000 feet and a length of 150.00 feet to a point"
)

IMPLS = {
    "package": (
        lambda t, strict: package_extract_calls(t, strict=strict)[0],
        package_verify,
        mp_models,
    ),
    "monolith": (
        lambda t, strict: CallExtractor.extract_calls(t, strict=strict),
        ClosureChecker.verify_closure,
        monolith_models,
    ),
}


@pytest.mark.parametrize("impl", IMPLS)
@pytest.mark.parametrize("course", [LENGTH_ONLY, RADIUS_LENGTH, LENGTH_NO_DIR])
def test_spiral_length_parses_strict_and_is_unpositioned(impl, course):
    extract, verify, _ = IMPLS[impl]
    calls = extract(_deed(course), True)
    spiral = calls[1]
    assert spiral.curve_type == "spiral"
    assert spiral.arc_length_ft == pytest.approx(150.0)
    assert spiral.distance_ft == pytest.approx(150.0)
    assert spiral.chord_length_ft is None
    assert spiral.delta_deg is None
    result = verify(calls)
    assert not result.area_available
    assert not result.perimeter_available
    assert not result.closure_passed
    curve_checks = [c for c in result.checks if c.name == "curve_consistency"]
    assert curve_checks and curve_checks[0].status == "blocked"
    assert "spiral_geometry_unverified" in str(result.checks)
    assert any("spiral cannot be positioned" in w for w in result.warnings)


@pytest.mark.parametrize("impl", IMPLS)
def test_spiral_length_perimeter_is_stated_length_not_circular(impl):
    _, _, m = IMPLS[impl]
    call = m.DeedCall(
        course=1,
        direction_text="spiral",
        distance_ft=150.0,
        curve_type="spiral",
        curve_dir="right",
        radius_ft=1000.0,
        arc_length_ft=150.0,
    )
    assert call.is_curve()
    assert calculate_perimeter([call]) == pytest.approx(150.0)


@pytest.mark.parametrize("impl", IMPLS)
def test_circular_length_unchanged(impl):
    extract, _, _ = IMPLS[impl]
    curve = extract(_deed(CIRCULAR), True)[1]
    assert curve.curve_type == "simple"
    assert curve.arc_length_ft == pytest.approx(150.0)
    assert curve.radius_ft == pytest.approx(1000.0)


@pytest.mark.parametrize("impl", IMPLS)
def test_spiral_with_chord_unchanged(impl):
    extract, _, _ = IMPLS[impl]
    course = (
        "along a spiral curve to the right having a radius of 1000.00 feet, a chord bearing "
        "of N 3° E and a chord distance of 99.50 feet to a point"
    )
    spiral = extract(_deed(course), True)[1]
    assert spiral.curve_type == "spiral"
    assert spiral.chord_length_ft == pytest.approx(99.5)
    assert spiral.distance_ft == pytest.approx(99.5)
    assert spiral.arc_length_ft is None
