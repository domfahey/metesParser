"""PR #60 round 15: a tangent-less curve fixed by chord and delta gets topology checks.

Radius, delta, direction and chord bearing fully determine the arc, so its
tangents are computed internally (chord -/+ dir * delta / 2) for interior angles
and boundary topology, never stored on the call. Chord-only curves stay blocked.
"""

from __future__ import annotations

import mp_models
import pytest
from mp_verify.closure import verify_closure as package_verify

from metesparser import models as monolith_models
from metesparser.closure_checker import ClosureChecker

IMPLS = {
    "package": (mp_models, package_verify),
    "monolith": (monolith_models, ClosureChecker.verify_closure),
}


def _parcel(m, *, width: float = 100.0, **curve):
    """East `width`, tangent-less left curve north (chord 100), west `width`, south 100."""
    arc = {
        "course": 2,
        "direction_text": "curve",
        "distance_ft": 100.0,
        "curve_dir": "left",
        "radius_ft": 100.0,
        "delta_deg": 60.0,
        "chord_bearing": "N 0°00' W",
    }
    arc.update(curve)
    return [
        m.DeedCall(
            course=1, direction_text="E", bearing_azimuth_deg_from_north=90.0, distance_ft=width
        ),
        m.DeedCall(**arc),
        m.DeedCall(
            course=3, direction_text="W", bearing_azimuth_deg_from_north=270.0, distance_ft=width
        ),
        m.DeedCall(
            course=4, direction_text="S", bearing_azimuth_deg_from_north=180.0, distance_ft=100.0
        ),
    ]


def _status(result, name):
    return next(check for check in result.checks if check.name == name)


@pytest.mark.parametrize("impl", IMPLS)
def test_chord_and_delta_curve_gets_topology_and_angle_checks(impl):
    m, verify = IMPLS[impl]
    calls = _parcel(m)
    result = verify(calls)

    assert result.misclosure_ft < 1e-9
    assert _status(result, "traverse_closure").status == "passed"
    assert _status(result, "boundary_intersections").status == "passed"
    # Evaluated like a tangent-stated curve: the straight-polygon sum does not apply.
    angles = _status(result, "interior_angles")
    assert angles.status == "not_applicable"
    assert angles.reason == "curved_boundary"
    assert not any("incomplete bearing" in warning for warning in result.warnings)
    assert result.warnings == []
    assert result.is_fully_verified()
    # Tangents are internal only: the call is not rewritten.
    assert calls[1].bearing_azimuth_deg_from_north is None


@pytest.mark.parametrize("impl", IMPLS)
def test_chord_and_delta_curve_matches_tangent_stated_equivalent(impl):
    m, verify = IMPLS[impl]
    tangentless = verify(_parcel(m))
    # Tangent-in = chord - dir * delta / 2 = 0 - (-1) * 30 = 30 (left curve).
    stated = verify(_parcel(m, chord_bearing=None, bearing_azimuth_deg_from_north=30.0))
    for name in ("interior_angles", "boundary_intersections", "traverse_closure"):
        assert _status(tangentless, name).status == _status(stated, name).status
    assert tangentless.area_sq_ft == pytest.approx(stated.area_sq_ft, abs=1e-6)


@pytest.mark.parametrize("impl", IMPLS)
def test_chord_and_delta_curve_self_intersection_fails(impl):
    m, verify = IMPLS[impl]
    # A right curve bulges left (west) of its northward chord by R(1 - cos 30) ~ 13.4 ft,
    # across the closing course only 10 ft away.
    result = verify(_parcel(m, width=10.0, curve_dir="right"))
    assert result.misclosure_ft < 1e-9
    assert _status(result, "boundary_intersections").status == "failed"
    assert not result.is_fully_verified()


@pytest.mark.parametrize("impl", IMPLS)
def test_chord_only_curve_topology_stays_blocked(impl):
    m, verify = IMPLS[impl]
    result = verify(_parcel(m, delta_deg=None, chord_length_ft=100.0))
    assert _status(result, "boundary_intersections").status == "blocked"
    assert not result.is_fully_verified()


@pytest.mark.parametrize(
    ("curve_dir", "expected"),
    [("left", (30.0, 330.0)), ("right", (330.0, 30.0))],
)
def test_curve_tangents_from_chord_and_delta(curve_dir, expected):
    from mp_verify.tangents import curve_tangents

    arc = _parcel(mp_models, curve_dir=curve_dir)[1]
    assert curve_tangents(arc) == pytest.approx(expected)
    chord_only = _parcel(mp_models, delta_deg=None, chord_length_ft=100.0)[1]
    assert curve_tangents(chord_only) is None
