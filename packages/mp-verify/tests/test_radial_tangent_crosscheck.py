"""A tangent curve's stated radial bearing is cross-checked against its stated tangent."""

from __future__ import annotations

import pytest
from mp_models import DeedCall
from mp_verify.checks import check_curve_consistency
from mp_verify.closure import verify_closure


def _curve(direction: str, tangent: float, radial: str, **extra: object) -> DeedCall:
    data: dict[str, object] = {
        "course": 2,
        "direction_text": "recorded",
        "curve_dir": direction,
        "radius_ft": 300.0,
        "delta_deg": 20.0,
        "arc_length_ft": 104.72,
        "distance_ft": 104.72,
        "bearing_azimuth_deg_from_north": tangent,
        "radial_bearing": radial,
    }
    data.update(extra)
    return DeedCall(**data)  # type: ignore[arg-type]


def _line(course: int, azimuth: float) -> DeedCall:
    return DeedCall(
        course=course,
        direction_text="recorded",
        bearing_azimuth_deg_from_north=azimuth,
        distance_ft=100.0,
    )


# Right curve: radial = tangent + 90. Left curve: radial = tangent - 90.
CASES = {
    "right": (45.0, "S 45°00'00\" E", "S 80°00'00\" E"),  # radial 135 ok; 100 bad
    "left": (45.0, "N 45°00'00\" W", "N 10°00'00\" W"),  # radial 315 ok; 350 bad
}


@pytest.mark.parametrize("direction", ["right", "left"])
def test_consistent_radial_and_tangent_pass(direction):
    tangent, good, _ = CASES[direction]
    call = _curve(direction, tangent, good)
    passed, warnings = check_curve_consistency([call])
    assert passed, warnings
    result = verify_closure([_line(1, 0.0), call, _line(3, 180.0), _line(4, 270.0)])
    assert not any("radial" in w for w in result.warnings)


@pytest.mark.parametrize("direction", ["right", "left"])
def test_inconsistent_radial_and_tangent_fail(direction):
    tangent, _, bad = CASES[direction]
    call = _curve(direction, tangent, bad)
    passed, warnings = check_curve_consistency([call])
    assert not passed
    assert "stated tangent and radial bearings are inconsistent" in warnings[-1]
    result = verify_closure([_line(1, 0.0), call, _line(3, 180.0), _line(4, 270.0)])
    assert result.curve_consistency_passed is False
    assert any("tangent and radial" in w for w in result.warnings)


def test_non_tangent_curve_is_not_cross_checked_against_stated_bearing():
    call = _curve("right", 45.0, CASES["right"][2], non_tangent=True)
    passed, warnings = check_curve_consistency([call])
    assert passed, warnings
