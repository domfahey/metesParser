"""Regression cases for the geometry audit, across both public implementations."""

import math

import pytest
from mp_bearing import calculate_missing_curve_elements
from mp_models import DeedCall as PackageCall
from mp_verify import verify_closure
from mp_verify.checks import compare_double_entry

from metesparser.bearing_converter import BearingConverter
from metesparser.closure_checker import ClosureChecker
from metesparser.models import DeedCall as MonolithCall


@pytest.fixture(params=["package", "monolith"])
def geometry(request):
    if request.param == "package":
        return PackageCall, verify_closure, compare_double_entry, calculate_missing_curve_elements
    return (
        MonolithCall,
        ClosureChecker.verify_closure,
        ClosureChecker.compare_double_entry,
        BearingConverter.calculate_missing_curve_elements,
    )


def _lines(call_type, vertices):
    calls = []
    for index, (start, end) in enumerate(zip(vertices, vertices[1:] + vertices[:1], strict=True)):
        dx, dy = end[0] - start[0], end[1] - start[1]
        calls.append(
            call_type(
                course=index + 1,
                direction_text="boundary",
                bearing_azimuth_deg_from_north=math.degrees(math.atan2(dx, dy)) % 360,
                distance_ft=math.hypot(dx, dy),
            )
        )
    return calls


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize(
    "vertices,area",
    [
        ([(0, 0), (0, 100), (100, 100), (100, 0)], 10000),
        ([(0, 0), (0, 100), (50, 100), (50, 50), (100, 50), (100, 0)], 7500),
    ],
    ids=["square", "concave"],
)
def test_valid_polygons_verify_in_either_direction(geometry, reverse, vertices, area):
    call_type, verify, _, _ = geometry
    result = verify(_lines(call_type, list(reversed(vertices)) if reverse else vertices))
    assert result.is_fully_verified()
    assert result.area_sq_ft == pytest.approx(area)


def test_crossed_polygon_fails_angle_check(geometry):
    call_type, verify, _, _ = geometry
    result = verify(_lines(call_type, [(0, 0), (100, 100), (0, 100), (100, 0)]))
    assert not result.angle_check_passed
    assert not result.is_fully_verified()


@pytest.mark.parametrize(
    "direction,azimuths", [("right", [0, 90, 180, 270]), ("left", [0, 270, 180, 90])]
)
@pytest.mark.parametrize("implicit_delta", [False, True])
def test_circle_area_includes_circular_segments(geometry, direction, azimuths, implicit_delta):
    call_type, verify, _, _ = geometry
    calls = [
        call_type(
            course=i + 1,
            direction_text="quarter circle",
            bearing_azimuth_deg_from_north=azimuth,
            distance_ft=50 * math.pi,
            radius_ft=100,
            curve_dir=direction,
            delta_deg=None if implicit_delta else 90,
            arc_length_ft=50 * math.pi,
        )
        for i, azimuth in enumerate(azimuths)
    ]
    result = verify(calls, stated_area_sq_ft=10000 * math.pi)
    assert result.area_sq_ft == pytest.approx(10000 * math.pi)
    assert result.is_fully_verified()


@pytest.mark.parametrize("direction,return_azimuth", [("right", 270), ("left", 90)])
def test_semicircle_and_diameter_have_semicircle_area(geometry, direction, return_azimuth):
    call_type, verify, _, _ = geometry
    calls = [
        call_type(
            course=1,
            direction_text="semicircle",
            bearing_azimuth_deg_from_north=0,
            distance_ft=100 * math.pi,
            radius_ft=100,
            curve_dir=direction,
            delta_deg=180,
            arc_length_ft=100 * math.pi,
        ),
        call_type(
            course=2,
            direction_text="diameter",
            bearing_azimuth_deg_from_north=return_azimuth,
            distance_ft=200,
        ),
    ]
    result = verify(calls)
    assert result.closure_passed
    assert result.area_sq_ft == pytest.approx(5000 * math.pi)


@pytest.mark.parametrize("direction", ["left", "right"])
def test_single_full_circle_has_area(geometry, direction):
    call_type, verify, _, _ = geometry
    call = call_type(
        course=1,
        direction_text="full circle",
        bearing_azimuth_deg_from_north=0,
        distance_ft=200 * math.pi,
        radius_ft=100,
        curve_dir=direction,
        delta_deg=360,
        arc_length_ft=200 * math.pi,
    )
    result = verify([call], stated_area_sq_ft=10000 * math.pi)
    assert result.area_sq_ft == pytest.approx(10000 * math.pi)
    assert result.is_fully_verified()


def test_major_arc_sector_area(geometry):
    call_type, verify, _, _ = geometry
    calls = [
        call_type(
            course=1,
            direction_text="major arc",
            bearing_azimuth_deg_from_north=0,
            distance_ft=150 * math.pi,
            radius_ft=100,
            curve_dir="right",
            delta_deg=270,
            arc_length_ft=150 * math.pi,
        ),
        call_type(
            course=2, direction_text="radius", bearing_azimuth_deg_from_north=0, distance_ft=100
        ),
        call_type(
            course=3, direction_text="radius", bearing_azimuth_deg_from_north=270, distance_ft=100
        ),
    ]
    result = verify(calls)
    assert result.area_sq_ft == pytest.approx(7500 * math.pi)
    assert result.is_fully_verified()


def test_curved_exception_area_subtracted(geometry):
    call_type, verify, _, _ = geometry
    calls = _lines(call_type, [(0, 0), (0, 100), (100, 100), (100, 0)])
    calls += [
        call_type(
            course=i + 5,
            direction_text="exception arc",
            bearing_azimuth_deg_from_north=azimuth,
            distance_ft=5 * math.pi,
            radius_ft=10,
            curve_dir="right",
            delta_deg=90,
            arc_length_ft=5 * math.pi,
            is_exception=True,
        )
        for i, azimuth in enumerate([0, 90, 180, 270])
    ]
    result = verify(calls)
    assert result.area_sq_ft == pytest.approx(10000 - 100 * math.pi)


def test_double_entry_detects_numeric_bearing_changes(geometry):
    call_type, verify, compare, _ = geometry
    vertices = [(0, 0), (0, 100), (100, 100), (100, 0)]
    calls = _lines(call_type, vertices)
    rotated = [
        c.model_copy(
            update={"bearing_azimuth_deg_from_north": (c.bearing_azimuth_deg_from_north + 90) % 360}
        )
        for c in calls
    ]
    assert len(compare(calls, rotated)) == 4
    result = verify(calls, double_entry_calls=rotated)
    assert not result.is_fully_verified()


def test_double_entry_detects_numeric_bearing_presence(geometry):
    call_type, _, compare, _ = geometry
    calls = _lines(call_type, [(0, 0), (0, 100), (100, 100), (100, 0)])
    missing = [calls[0].model_copy(update={"bearing_azimuth_deg_from_north": None}), *calls[1:]]
    assert compare(calls, missing)


def test_double_entry_treats_north_wrap_as_same_bearing(geometry):
    call_type, _, compare, _ = geometry
    call = call_type(
        course=1, direction_text="north", bearing_azimuth_deg_from_north=359.99999, distance_ft=100
    )
    other = call.model_copy(update={"bearing_azimuth_deg_from_north": 0.00001})
    assert compare([call], [other]) == []


@pytest.mark.parametrize("delta", [0.01, 30, 90, 180, 270, 359.9, 360])
def test_arc_and_chord_recover_consistent_curve(geometry, delta):
    _, _, _, infer = geometry
    radius = 100
    arc = radius * math.radians(delta)
    chord = 0.0 if delta == 360 else 2 * radius * math.sin(math.radians(delta) / 2)
    result = infer(arc_length_ft=arc, chord_length_ft=chord)
    assert result["radius_ft"] == pytest.approx(radius, rel=1e-6)
    assert result["delta_deg"] == pytest.approx(delta, rel=1e-6)
    predicted_chord = 2 * result["radius_ft"] * math.sin(math.radians(result["delta_deg"]) / 2)
    assert predicted_chord == pytest.approx(chord, abs=1e-8)


def test_arc_and_negative_chord_rejected(geometry):
    _, _, _, infer = geometry
    with pytest.raises(ValueError, match="Chord.*non-negative"):
        infer(arc_length_ft=100, chord_length_ft=-10)
