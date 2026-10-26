"""Reject intersecting straight boundaries without rejecting smooth circular arcs."""

import math

import pytest
from mp_export.csv_writer import export_verified_csv
from mp_models import AuditContext as PackageAudit
from mp_models import DeedCall as PackageCall
from mp_verify import verify_closure
from mp_verify.checks import check_bearing_reversals

from metesparser.closure_checker import ClosureChecker
from metesparser.csv_builder import CSVBuilder
from metesparser.models import AuditContext as MonolithAudit
from metesparser.models import DeedCall as MonolithCall


@pytest.fixture(
    params=[
        (PackageCall, verify_closure, check_bearing_reversals, export_verified_csv, PackageAudit),
        (
            MonolithCall,
            ClosureChecker.verify_closure,
            ClosureChecker.check_bearing_reversals,
            CSVBuilder.export_verified_csv,
            MonolithAudit,
        ),
    ],
    ids=["package", "monolith"],
)
def geometry(request):
    return request.param


def _polygon(call_type, vertices):
    return [
        call_type(
            course=i + 1,
            direction_text="boundary",
            bearing_azimuth_deg_from_north=math.degrees(math.atan2(b[0] - a[0], b[1] - a[1])) % 360,
            distance_ft=math.hypot(b[0] - a[0], b[1] - a[1]),
        )
        for i, (a, b) in enumerate(zip(vertices, vertices[1:] + vertices[:1], strict=True))
    ]


def test_crossing_boundary_cannot_be_fully_verified_or_exported(geometry, tmp_path):
    call_type, verify, _, export, _ = geometry
    calls = _polygon(call_type, [(0, 0), (100, 0), (0, 100), (100, 100), (50, -50)])
    result = verify(calls)
    assert result.closure_passed
    assert result.angle_check_passed
    assert result.area_sq_ft == pytest.approx(5000)
    assert not result.is_fully_verified()
    assert any("self-intersection" in warning for warning in result.warnings)
    with pytest.raises(ValueError, match="verification checks failed"):
        export(calls, result, str(tmp_path / "crossing.csv"))
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "vertices",
    [
        [(0, 0), (100, 0), (100, 100), (50, 0), (0, 100)],  # nonadjacent touch
        [(0, 0), (100, 0), (100, 100), (25, 0), (75, 0), (0, 100)],  # overlap
    ],
    ids=["touch", "overlap"],
)
def test_nonadjacent_touches_and_overlaps_are_reported(geometry, vertices):
    call_type, verify, *_ = geometry
    result = verify(_polygon(call_type, vertices))
    intersecting_courses = "Courses 1-3" if len(vertices) == 5 else "Courses 1-4"
    assert any(
        "self-intersection" in warning and intersecting_courses in warning
        for warning in result.warnings
    )
    assert not result.is_fully_verified()


@pytest.mark.parametrize("reverse", [False, True], ids=["ccw", "cw"])
@pytest.mark.parametrize(
    "vertices",
    [
        [(0, 0), (100, 0), (100, 100), (50, 50), (0, 100)],  # concave
        [(0, 0), (50, 0), (100, 0), (100, 100), (0, 100)],  # collinear split
    ],
    ids=["concave", "collinear-split"],
)
def test_simple_boundaries_keep_both_orientations(geometry, vertices, reverse):
    call_type, verify, *_ = geometry
    if reverse:
        vertices = list(reversed(vertices))
    assert verify(_polygon(call_type, vertices)).is_fully_verified()


@pytest.mark.parametrize("parts", [2, 4])
@pytest.mark.parametrize("direction", ["right", "left"])
def test_smooth_circles_are_independent_of_arc_partition(geometry, parts, direction):
    call_type, verify, reversals, _, _ = geometry
    sign = 1 if direction == "right" else -1
    calls = [
        call_type(
            course=i + 1,
            direction_text="circular boundary",
            bearing_azimuth_deg_from_north=(sign * i * 360 / parts) % 360,
            distance_ft=200 * math.pi / parts,
            radius_ft=100,
            delta_deg=360 / parts,
            arc_length_ft=200 * math.pi / parts,
            curve_dir=direction,
        )
        for i in range(parts)
    ]
    result = verify(calls, stated_area_sq_ft=10000 * math.pi)
    assert result.closure_passed
    assert result.area_sq_ft == pytest.approx(10000 * math.pi)
    assert reversals(calls) == []
    assert result.is_fully_verified()


@pytest.mark.parametrize("second_azimuth", [176, 180, 184])
def test_straight_near_reversals_remain_flagged(geometry, second_azimuth):
    call_type, _, reversals, *_ = geometry
    calls = [
        call_type(
            course=i + 1,
            direction_text="straight",
            bearing_azimuth_deg_from_north=azimuth,
            distance_ft=100,
        )
        for i, azimuth in enumerate([0, second_azimuth])
    ]
    assert len(reversals(calls)) == 1


def test_intersection_check_is_recorded_with_straight_edge_scope(geometry):
    call_type, verify, _, _, audit_type = geometry
    ctx = audit_type(
        run_metadata={
            "parser_version": "test",
            "llm_provider": "none",
            "llm_model": "none",
            "prompt_hash": "test",
            "timestamp_utc": "2026-10-25T00:00:00Z",
            "source_pdf": "geometry.pdf",
            "cache_enabled": False,
        }
    )
    calls = _polygon(call_type, [(0, 0), (100, 0), (0, 100), (100, 100), (50, -50)])
    verify(calls, audit_context=ctx)
    check = next(
        check
        for check in ctx.verification_audit.checks
        if check.name == "straight_boundary_intersections"
    )
    assert not check.passed
    assert "arc intersections not evaluated" in check.detail


def test_self_intersecting_exception_cannot_supply_net_area(geometry):
    call_type, verify, *_ = geometry
    calls = _polygon(call_type, [(0, 0), (1000, 0), (1000, 1000), (0, 1000)])
    exceptions = _polygon(call_type, [(0, 0), (100, 0), (0, 100), (100, 100), (50, -50)])
    calls += [
        call.model_copy(update={"course": i + 5, "is_exception": True})
        for i, call in enumerate(exceptions)
    ]
    result = verify(calls)
    assert result.area_sq_ft == 0
    assert any("self-intersection" in warning for warning in result.warnings)


def test_close_parallel_edges_do_not_count_as_intersections(geometry):
    call_type, verify, *_ = geometry
    vertices = [
        (0, 0),
        (100, 0),
        (100, 100),
        (50, 100),
        (50, 0.0001),
        (25, 0.0001),
        (25, 100),
        (0, 100),
    ]
    assert verify(_polygon(call_type, vertices)).is_fully_verified()


def test_arc_chord_touch_does_not_create_a_boundary_intersection(geometry):
    call_type, verify, *_ = geometry
    calls = _polygon(call_type, [(0, 0), (100, -100), (50, -50), (50, 50)])
    calls[0] = call_type(
        course=1,
        direction_text="right 270 degree circular arc",
        bearing_azimuth_deg_from_north=0,
        distance_ft=150 * math.pi,
        radius_ft=100,
        delta_deg=270,
        arc_length_ft=150 * math.pi,
        curve_dir="right",
    )
    # The endpoint chord touches course 3 at (50, -50); the actual arc does not.
    assert verify(calls).is_fully_verified()
