"""Circular topology must guard verified results without treating chords as arcs."""

import math

import pytest
from mp_export import export_verified_csv
from mp_models import DeedCall as PackageCall
from mp_verify import verify_closure

from metesparser.closure_checker import ClosureChecker
from metesparser.csv_builder import CSVBuilder
from metesparser.models import DeedCall as LegacyCall


@pytest.fixture(
    params=[
        (PackageCall, verify_closure, export_verified_csv),
        (LegacyCall, ClosureChecker.verify_closure, CSVBuilder.export_verified_csv),
    ],
    ids=["package", "legacy"],
)
def geometry(request):
    return request.param


def line(call_type, course, azimuth, distance):
    return call_type(
        course=course,
        direction_text="boundary",
        distance_ft=distance,
        bearing_azimuth_deg_from_north=azimuth,
    )


def arc(call_type, course, tangent, direction="right", delta=180):
    length = 100 * math.radians(delta)
    return call_type(
        course=course,
        direction_text="circular arc",
        distance_ft=length,
        bearing_azimuth_deg_from_north=tangent,
        radius_ft=100,
        delta_deg=delta,
        arc_length_ft=length,
        curve_dir=direction,
    )


def capped_semicircle(call_type, height, direction="right", chord=False):
    right = direction == "right"
    curved = arc(call_type, 1, 0 if right else 180, direction)
    if chord:
        curved = curved.model_copy(
            update={"chord_bearing": "N 90° E", "bearing_azimuth_deg_from_north": 90}
        )
    return [
        curved,
        line(call_type, 2, 0 if right else 180, height),
        line(call_type, 3, 270, 200),
        line(call_type, 4, 180 if right else 0, height),
    ]


@pytest.mark.parametrize(
    "height", [50, 99.9999, 100], ids=["crossing", "near-tangent-crossing", "tangent"]
)
@pytest.mark.parametrize("direction", ["right", "left"])
@pytest.mark.parametrize("chord", [False, True], ids=["tangent-bearing", "chord-bearing"])
def test_line_arc_self_intersection_blocks_verified_export(
    geometry, tmp_path, height, direction, chord
):
    call_type, verify, export = geometry
    calls = capped_semicircle(call_type, height, direction, chord)
    result = verify(calls)
    assert result.closure_passed
    assert result.curve_consistency_passed
    assert any(
        "Courses 1-3" in warning and "self-intersection" in warning for warning in result.warnings
    )
    assert not result.is_fully_verified()
    with pytest.raises(ValueError, match="verification checks failed"):
        export(calls, result, str(tmp_path / "crossing.csv"))
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("height", [100.0001, 150], ids=["near-tangent-miss", "disjoint"])
@pytest.mark.parametrize("direction", ["left", "right"])
def test_nonintersecting_circular_boundary_can_be_verified(geometry, height, direction):
    call_type, verify, _ = geometry
    result = verify(capped_semicircle(call_type, height, direction))
    assert result.is_fully_verified(), result.warnings


def test_arc_arc_crossing_is_detected_between_different_circles(geometry):
    call_type, verify, _ = geometry
    calls = [
        arc(call_type, 1, 0),
        line(call_type, 2, 270, 100),
        arc(call_type, 3, 90, "left"),
        line(call_type, 4, math.degrees(math.atan2(-100, -200)) % 360, math.hypot(100, 200)),
    ]
    result = verify(calls)
    assert result.closure_passed
    assert any("Courses 1-3" in w and "self-intersection" in w for w in result.warnings)


def test_adjacent_arcs_may_intersect_again_beyond_shared_endpoint(geometry):
    call_type, verify, _ = geometry
    calls = [
        arc(call_type, 1, 0),
        arc(call_type, 2, 270, delta=270),
        line(call_type, 3, math.degrees(math.atan2(-300, -100)) % 360, math.hypot(300, 100)),
    ]
    result = verify(calls)
    assert result.closure_passed
    assert any("Courses 1-2" in w and "self-intersection" in w for w in result.warnings)


def test_cocircular_overlapping_arcs_are_rejected(geometry):
    call_type, verify, _ = geometry
    calls = [
        arc(call_type, 1, 0, delta=270),
        arc(call_type, 2, 270),
        line(call_type, 3, 225, math.sqrt(2) * 100),
    ]
    result = verify(calls)
    assert result.closure_passed
    assert any("Courses 1-2" in w and "overlap" in w for w in result.warnings)
    assert not result.is_fully_verified()


def test_curve_delta_inferred_from_arc_length_still_checks_topology(geometry):
    call_type, verify, _ = geometry
    calls = capped_semicircle(call_type, 50)
    calls[0] = calls[0].model_copy(update={"delta_deg": None})
    assert not verify(calls).is_fully_verified()


def test_incomplete_curve_geometry_is_not_silently_treated_as_a_line(geometry):
    call_type, verify, _ = geometry
    calls = [
        arc(call_type, 1, 0).model_copy(update={"radius_ft": None}),
        line(call_type, 2, 90, 100),
        line(call_type, 3, 180, math.pi * 100),
        line(call_type, 4, 270, 100),
    ]
    result = verify(calls)
    assert result.closure_passed
    assert any("intersection check unavailable" in w for w in result.warnings)
    assert not result.is_fully_verified()


@pytest.mark.parametrize("gap", [0, 0.0001], ids=["nonadjacent-tangency", "near-miss"])
def test_circle_tangency_requires_contact_on_both_arc_sweeps(geometry, gap):
    call_type, verify, _ = geometry
    calls = [
        arc(call_type, 1, 0),
        line(call_type, 2, 180, 100),
        line(call_type, 3, 90, 100 + gap),
        arc(call_type, 4, 270),
        line(
            call_type,
            5,
            math.degrees(math.atan2(-300 - gap, -100)) % 360,
            math.hypot(300 + gap, 100),
        ),
    ]
    result = verify(calls)
    assert result.closure_passed
    pair_warning = any("Courses 1-4" in w for w in result.warnings)
    assert pair_warning == (gap == 0)


def test_intersecting_circles_with_disjoint_arc_sweeps_do_not_flag_that_pair(geometry):
    call_type, verify, _ = geometry
    calls = [
        arc(call_type, 1, 0),
        line(call_type, 2, math.degrees(math.atan2(-200, 100)) % 360, math.hypot(200, 100)),
        arc(call_type, 3, 0),
        line(call_type, 4, math.degrees(math.atan2(-200, -100)) % 360, math.hypot(200, 100)),
    ]
    result = verify(calls)
    assert result.closure_passed
    # The two supporting circles intersect below the second (upper) arc.
    assert not any("Courses 1-3" in w for w in result.warnings)


def test_curved_exception_crossing_cannot_supply_net_parcel_area(geometry):
    call_type, verify, _ = geometry
    main = [line(call_type, i + 1, bearing, 1000) for i, bearing in enumerate((0, 90, 180, 270))]
    exception = [
        call.model_copy(update={"is_exception": True, "course": i + 5})
        for i, call in enumerate(capped_semicircle(call_type, 50))
    ]
    result = verify(main + exception)
    assert result.area_sq_ft == 0
    assert any("net area unavailable" in w and "self-intersection" in w for w in result.warnings)


def test_independent_tract_cannot_bypass_curved_topology_checks(geometry):
    from mp_verify import verify_tract

    call_type, _, _ = geometry
    independent = verify_tract if call_type is PackageCall else ClosureChecker.verify_tract
    result = independent(capped_semicircle(call_type, 50))
    assert not result.is_fully_verified()
    assert any("Courses 1-3" in w for w in result.warnings)


def test_valid_curved_boundary_survives_verified_csv_roundtrip(geometry, tmp_path):
    from mp_export import csv_to_calls

    call_type, verify, export = geometry
    calls = capped_semicircle(call_type, 150)
    export(calls, verify(calls), str(tmp_path / "curved.csv"))
    load = csv_to_calls if call_type is PackageCall else CSVBuilder.csv_to_calls
    reloaded = verify(load(str(tmp_path / "curved_verified.csv")))
    assert reloaded.is_fully_verified(), reloaded.warnings


def test_touching_full_circle_loops_are_not_one_simple_boundary(geometry):
    call_type, verify, _ = geometry
    result = verify([arc(call_type, 1, 0, delta=360), arc(call_type, 2, 180, delta=360)])
    assert result.closure_passed
    assert any("self-intersection" in w for w in result.warnings)
    assert not result.is_fully_verified()


@pytest.mark.parametrize("direction", ["left", "right"])
def test_one_complete_circle_is_a_valid_boundary(geometry, direction):
    call_type, verify, _ = geometry
    result = verify([arc(call_type, 1, 0, direction=direction, delta=360)])
    assert result.is_fully_verified(), result.warnings
    assert result.area_sq_ft == pytest.approx(math.pi * 10000)


def test_unsupported_spiral_requires_review_instead_of_circular_certification(geometry):
    call_type, verify, _ = geometry
    calls = capped_semicircle(call_type, 150)
    calls[0] = calls[0].model_copy(update={"curve_type": "spiral"})
    result = verify(calls)
    assert any("intersection check unavailable" in w and "spiral" in w for w in result.warnings)
    assert not result.is_fully_verified()


def test_spiral_flag_without_geometry_is_not_silently_classified_as_a_line(geometry):
    call_type, verify, _ = geometry
    calls = [line(call_type, i + 1, bearing, 100) for i, bearing in enumerate((0, 90, 180, 270))]
    calls[0] = calls[0].model_copy(update={"curve_type": "spiral"})
    result = verify(calls)
    assert any("intersection check unavailable" in w and "spiral" in w for w in result.warnings)
    assert not result.is_fully_verified()


@pytest.mark.parametrize("rotation", [17, 113])
@pytest.mark.parametrize("offset", [(0, 0), (1000000, -2000000)])
@pytest.mark.parametrize("height,intersects", [(150, False), (100.0001, False), (99.9999, True)])
def test_arc_topology_is_rotation_and_translation_invariant(
    geometry, rotation, offset, height, intersects
):
    from mp_verify.checks import check_boundary_intersections
    from mp_verify.closure import compute_traverse

    call_type, _, _ = geometry
    calls = [
        call.model_copy(
            update={
                "bearing_azimuth_deg_from_north": (call.bearing_azimuth_deg_from_north + rotation)
                % 360
            }
        )
        for call in capped_semicircle(call_type, height)
    ]
    compute = compute_traverse if call_type is PackageCall else ClosureChecker.compute_traverse
    check = (
        check_boundary_intersections
        if call_type is PackageCall
        else ClosureChecker.check_boundary_intersections
    )
    points = [type(point)(x=point.x + offset[0], y=point.y + offset[1]) for point in compute(calls)]
    warnings = check(calls, points)
    if intersects:
        assert any("Courses 1-3" in warning for warning in warnings)
    else:
        assert warnings == []


@pytest.mark.parametrize("reverse", [False, True], ids=["large-first", "small-first"])
def test_unequal_radius_circle_intersections_do_not_depend_on_argument_order(reverse):
    from mp_verify.topology import _Arc, _arc_arc

    large = _Arc((0, 0), 50000, 0, math.tau, 1)
    small = _Arc((49999.3, 0), 1, 0, math.tau, 1)
    points, overlap = _arc_arc(small, large) if reverse else _arc_arc(large, small)
    assert not overlap
    assert len(points) == 2
    for x, y in points:
        assert math.hypot(x, y) == pytest.approx(50000, abs=1e-7)
        assert math.hypot(x - 49999.3, y) == pytest.approx(1, abs=1e-7)
    assert sorted(y for _, y in points) == pytest.approx([-0.7141478419, 0.7141478419], abs=1e-7)


def test_unequal_radius_arc_crossing_is_reported_by_both_verifiers(geometry):
    call_type, verify, _ = geometry
    large = arc(call_type, 1, 0).model_copy(
        update={
            "radius_ft": 50000,
            "arc_length_ft": math.pi * 50000,
            "distance_ft": math.pi * 50000,
        }
    )
    small = arc(call_type, 3, 0).model_copy(
        update={"radius_ft": 1, "arc_length_ft": math.pi, "distance_ft": math.pi}
    )
    calls = [large, line(call_type, 2, 270, 1.7), small, line(call_type, 4, 270, 100000.3)]
    result = verify(calls)
    assert result.closure_passed
    assert any(
        "Courses 1-3" in warning and "self-intersection" in warning for warning in result.warnings
    )
