"""PR #60 round 7: fallout from chord-only curves (radius + chord, no delta/arc).

Each behavior runs through the package and the compatibility monolith.
"""

from __future__ import annotations

import pytest
from mp_models import DeedCall as PackageDeedCall
from mp_parse.calls import _expand_compact_dms as package_expand
from mp_parse.calls import extract_single_call as package_single_call
from mp_verify.closure import get_closure_summary as package_summary
from mp_verify.closure import verify_closure as package_verify

from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker
from metesparser.models import DeedCall as MonolithDeedCall

PARSERS = {"package": package_single_call, "monolith": CallExtractor.extract_single_call}
VERIFIERS = {
    "package": (PackageDeedCall, package_verify, package_summary),
    "monolith": (
        MonolithDeedCall,
        ClosureChecker.verify_closure,
        ClosureChecker.get_closure_summary,
    ),
}
# The monolith delegates DMS expansion to the package (one implementation).
EXPANDERS = {"package": package_expand}

CHORD_ONLY_TEXT = (
    "curve to the right having a radius of 500 feet, the chord of which bears "
    "N 45 deg 30 min E, 100 feet"
)


@pytest.mark.parametrize("impl", PARSERS)
def test_chord_only_curve_distance_is_the_stated_chord(impl):
    call = PARSERS[impl](CHORD_ONLY_TEXT, 1)
    assert call is not None and call.is_chord_only_curve()
    assert call.radius_ft == pytest.approx(500.0)
    assert call.chord_length_ft == pytest.approx(100.0)
    assert call.distance_ft == pytest.approx(100.0)


def _square(model, curve_kwargs):
    def line(course, azimuth):
        return model(
            course=course,
            direction_text="recorded",
            bearing_azimuth_deg_from_north=azimuth,
            distance_ft=100.0,
        )

    curve = model(
        course=2,
        direction_text="recorded",
        distance_ft=100.0,
        curve_dir="right",
        radius_ft=500.0,
        chord_length_ft=100.0,
        **curve_kwargs,
    )
    return [line(1, 0.0), curve, line(3, 180.0), line(4, 270.0)]


@pytest.mark.parametrize("impl", VERIFIERS)
def test_chord_only_curve_perimeter_not_determined(impl):
    model, verify, summary = VERIFIERS[impl]
    calls = _square(
        model,
        {"chord_bearing": "S 90° E", "bearing_azimuth_deg_from_north": 85.0},
    )
    result = verify(calls)
    assert result.perimeter_available is False
    assert result.perimeter_ft == 0.0
    assert result.precision_ratio is None
    assert "Perimeter: not determined" in summary(result)


@pytest.mark.parametrize("impl", VERIFIERS)
def test_unparseable_chord_on_chord_only_curve_blocks_closure_and_area(impl):
    model, verify, _ = VERIFIERS[impl]
    calls = _square(
        model,
        {"chord_bearing": "northeasterly", "bearing_azimuth_deg_from_north": 85.0},
    )
    result = verify(calls)
    checks = {c.name: c for c in result.checks}
    assert result.closure_passed is False
    assert checks["traverse_closure"].status == "blocked"
    assert checks["curve_consistency"].status == "blocked"
    assert checks["area_reasonableness"].inputs["area_available"] is False
    assert result.perimeter_available is False
    assert result.geometry_verified is False
    # The tangent (85 deg) is not run for distance_ft as a straight course.
    assert all(abs(p.x - 99.6194698) > 1e-3 for p in result.points)
    assert any("cannot be positioned" in w for w in result.warnings)


@pytest.mark.parametrize("impl", EXPANDERS)
@pytest.mark.parametrize(
    "text", ["Lot N 12-3 E", "Block S 4-15 W", "Route N 9-1 E", "No. N 12-3 E"]
)
def test_identifier_dash_sequences_are_not_bearings(impl, text):
    assert EXPANDERS[impl](text) == text


@pytest.mark.parametrize("impl", PARSERS)
def test_lot_identifier_does_not_become_the_course_bearing(impl):
    call = PARSERS[impl]("THENCE along Lot N 12-3 E, N 45°30' E 100 feet to a point", 1)
    assert call is not None
    assert call.bearing_azimuth_deg_from_north == pytest.approx(45.5)
