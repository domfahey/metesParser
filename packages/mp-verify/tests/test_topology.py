"""Analytic topology invariants for curved and mixed straight/arc boundaries."""

from __future__ import annotations

import math

import pytest
from mp_models import DeedCall, Point
from mp_verify import verify_closure
from mp_verify.closure import compute_traverse
from mp_verify.topology import check_curved_boundary_intersections


def _arc_call(
    course: int,
    *,
    tangent_deg: float | None = 0.0,
    radius: float | None = 100.0,
    delta_deg: float | None = 90.0,
    arc_length: float | None = None,
    curve_dir: str | None = "right",
    chord_bearing: str | None = None,
    chord_length: float | None = None,
    curve_type: str | None = "simple",
    non_tangent: bool = False,
) -> DeedCall:
    if arc_length is None and radius is not None and delta_deg is not None:
        arc_length = radius * math.radians(delta_deg)
    dist = arc_length if arc_length is not None else (chord_length or 100.0)
    return DeedCall(
        course=course,
        direction_text="curve",
        bearing_azimuth_deg_from_north=tangent_deg,
        distance_ft=dist,
        curve_dir=curve_dir,
        radius_ft=radius,
        delta_deg=delta_deg,
        arc_length_ft=arc_length,
        chord_bearing=chord_bearing,
        chord_length_ft=chord_length,
        curve_type=curve_type,
        non_tangent=non_tangent,
    )


def _line_call(course: int, azimuth: float, distance: float) -> DeedCall:
    return DeedCall(
        course=course,
        direction_text=f"az {azimuth}",
        bearing_azimuth_deg_from_north=azimuth,
        distance_ft=distance,
    )


class TestLineArcAndArcArcGeometry:
    def test_zero_length_segment_on_vs_off_arc_and_exact_tangent_line(self):
        # Semicircle from (0, 0) to (200, 0) curving right with radius 100 (center (100, 0), apex (100, 100)).
        semicircle = _arc_call(1, tangent_deg=0.0, radius=100.0, delta_deg=180.0, curve_dir="right")
        connector = _line_call(2, 0.0, 100.0)
        tangent_line = _line_call(3, 270.0, 200.0)

        # Non-adjacent tangent line along y=100 touches arc apex (100, 100) and is flagged.
        calls_tangent = [semicircle, connector, tangent_line]
        coords_tangent = compute_traverse(calls_tangent)
        warnings_tangent = check_curved_boundary_intersections(calls_tangent, coords_tangent)
        assert any(
            "Courses 1-3" in w and "curved boundary self-intersection" in w
            for w in warnings_tangent
        )

        # Non-adjacent line along y=200 misses the semicircle completely -> clear.
        calls_clear = [semicircle, _line_call(2, 0.0, 200.0), tangent_line]
        assert check_curved_boundary_intersections(calls_clear, compute_traverse(calls_clear)) == []

        # Degenerate zero-length non-adjacent segment on apex (100, 100) is flagged;
        # zero-length segment strictly off the circle at (100, 50) is not flagged.
        dummy_line = _line_call(3, 90.0, 1.0)
        coords_on = [
            Point(x=0.0, y=0.0),
            Point(x=200.0, y=0.0),
            Point(x=100.0, y=100.0),
            Point(x=100.0, y=100.0),
        ]
        warnings_on = check_curved_boundary_intersections(
            [semicircle, connector, dummy_line], coords_on
        )
        assert any("Courses 1-3" in w for w in warnings_on)

        coords_off = [
            Point(x=0.0, y=0.0),
            Point(x=200.0, y=0.0),
            Point(x=100.0, y=50.0),
            Point(x=100.0, y=50.0),
        ]
        assert (
            check_curved_boundary_intersections([semicircle, connector, dummy_line], coords_off)
            == []
        )

    def test_unequal_radii_crossing_externally_tangent_disjoint_and_concentric_arcs(self):
        # Unequal radii crossing (R1=20 > R2=10):
        # Arc 1: (0,0) -> (40,0) center (20,0) R=20; Line 2: (40,0) -> (45,0);
        # Arc 3: (45,0) -> (25,0) center (35,0) R=10 left -> crosses Arc 1.
        calls_cross = [
            _arc_call(1, tangent_deg=0.0, radius=20.0, delta_deg=180.0, curve_dir="right"),
            _line_call(2, 90.0, 5.0),
            _arc_call(3, tangent_deg=0.0, radius=10.0, delta_deg=180.0, curve_dir="left"),
        ]
        warnings_cross = check_curved_boundary_intersections(
            calls_cross, compute_traverse(calls_cross)
        )
        assert any(
            "Courses 1-3" in w and "curved boundary self-intersection" in w for w in warnings_cross
        )

        # Externally tangent non-adjacent arcs at (20, 0):
        # Arc 1: center (10,0) R=10; Line 2: (20,0) -> (40,0); Arc 3: center (30,0) R=10 left -> touches (20,0).
        calls_ext_tan = [
            _arc_call(1, tangent_deg=0.0, radius=10.0, delta_deg=180.0, curve_dir="right"),
            _line_call(2, 90.0, 20.0),
            _arc_call(3, tangent_deg=0.0, radius=10.0, delta_deg=180.0, curve_dir="left"),
        ]
        warnings_ext = check_curved_boundary_intersections(
            calls_ext_tan, compute_traverse(calls_ext_tan)
        )
        assert any(
            "Courses 1-3" in w and "curved boundary self-intersection" in w for w in warnings_ext
        )

        # Disjoint arcs (centers (10,0) and (130,0), R=10) -> clear.
        calls_disjoint = [
            _arc_call(1, tangent_deg=0.0, radius=10.0, delta_deg=180.0, curve_dir="right"),
            _line_call(2, 90.0, 100.0),
            _arc_call(3, tangent_deg=0.0, radius=10.0, delta_deg=180.0, curve_dir="right"),
        ]
        assert (
            check_curved_boundary_intersections(calls_disjoint, compute_traverse(calls_disjoint))
            == []
        )

        # Concentric arcs (same center (10,0), radii 10 and 5) -> clear.
        calls_concentric = [
            _arc_call(1, tangent_deg=0.0, radius=10.0, delta_deg=180.0, curve_dir="right"),
            _line_call(2, 270.0, 5.0),
            _arc_call(3, tangent_deg=180.0, radius=5.0, delta_deg=180.0, curve_dir="right"),
        ]
        assert (
            check_curved_boundary_intersections(
                calls_concentric, compute_traverse(calls_concentric)
            )
            == []
        )

    def test_coincident_ccw_wraparound_touching_clears_while_full_circle_overlap_flags(self):
        # Two adjacent CCW arcs on the same circle where the first wraps past polar angle 2*pi
        # (tangent 20 deg left 90 deg -> polar angle 340..430 deg) and the second continues smoothly
        # (tangent 290 deg left 90 deg -> polar angle 70..160 deg): touch only at shared endpoint -> clear.
        ccw_a = _arc_call(1, tangent_deg=20.0, radius=10.0, delta_deg=90.0, curve_dir="left")
        ccw_b = _arc_call(2, tangent_deg=290.0, radius=10.0, delta_deg=90.0, curve_dir="left")
        assert (
            check_curved_boundary_intersections([ccw_a, ccw_b], compute_traverse([ccw_a, ccw_b]))
            == []
        )

        # A 360-degree full-circle arc followed by a coincident 90-degree arc on the same circle
        # triggers both the full-circle loop warning and coincident arc overlap.
        full = _arc_call(1, tangent_deg=0.0, radius=10.0, delta_deg=360.0, curve_dir="right")
        part = _arc_call(2, tangent_deg=0.0, radius=10.0, delta_deg=90.0, curve_dir="right")
        coords = [Point(x=0.0, y=0.0), Point(x=0.0, y=0.0), Point(x=10.0, y=10.0)]
        warnings = check_curved_boundary_intersections([full, part], coords)
        assert any("full-circle loop" in w for w in warnings)
        assert any(
            "Courses 1-2" in w and "curved boundary self-intersection" in w for w in warnings
        )


class TestIncompleteCurveIntersectionGuards:
    def test_incomplete_or_mismatched_curves_report_unavailable_warnings(self):
        cases = [
            (
                DeedCall(
                    course=1,
                    direction_text="spiral",
                    distance_ft=50.0,
                    curve_type="spiral",
                    arc_length_ft=50.0,
                ),
                Point(x=50.0, y=0.0),
                "spiral",
            ),
            (
                DeedCall.model_construct(
                    course=1, direction_text="curve", distance_ft=50.0, curve_type="simple"
                ),
                Point(x=50.0, y=0.0),
                "radius or direction",
            ),
            (
                _arc_call(
                    1,
                    tangent_deg=None,
                    delta_deg=None,
                    chord_bearing="N 45° E",
                    chord_length=100.0,
                ),
                Point(x=70.71, y=70.71),
                "sweep",
            ),
            (
                _arc_call(1, chord_bearing="NOT A BEARING"),
                Point(x=100.0, y=100.0),
                "invalid chord bearing",
            ),
            (
                _arc_call(1, tangent_deg=0.0, non_tangent=True),
                Point(x=100.0, y=100.0),
                "missing tangent or chord bearing",
            ),
            (
                _arc_call(1, tangent_deg=0.0, radius=100.0, delta_deg=90.0, curve_dir="right"),
                Point(x=0.0, y=100.0),
                "does not match traverse endpoints",
            ),
        ]
        for call, end, expected_reason in cases:
            warnings = check_curved_boundary_intersections([call], [Point(x=0.0, y=0.0), end])
            assert len(warnings) == 1
            assert "boundary intersection check unavailable" in warnings[0]
            assert expected_reason in warnings[0]


class TestCurvedBoundaryIntersections:
    def test_closed_two_semicircle_loop_passes_without_false_positive(self):
        """Two 180-degree arcs forming a closed circle share both endpoints cleanly."""
        c1 = _arc_call(1, tangent_deg=0.0, radius=100.0, delta_deg=180.0, curve_dir="right")
        c2 = _arc_call(2, tangent_deg=180.0, radius=100.0, delta_deg=180.0, curve_dir="right")
        result = verify_closure([c1, c2])
        assert result.closure_passed is True
        assert result.geometry_verified is True
        assert result.area_sq_ft == pytest.approx(math.pi * 100.0**2, rel=1e-6)
        assert not any("self-intersection" in w.lower() for w in result.warnings)

    def test_crossing_arcs_in_figure_eight_are_flagged_and_block_verification(self):
        """Two arcs crossing each other must fail boundary intersection checks."""
        # Arc 1: from (0,0) north, curves right 180 deg to (200,0) via y=+100.
        # Line 2: from (200,0) west 100 ft to (100,0).
        # Arc 3: from (100,0) north, curves right 180 deg to (300,0) via y=+100 — crosses Arc 1!
        c1 = _arc_call(1, tangent_deg=0.0, radius=100.0, delta_deg=180.0, curve_dir="right")
        c2 = _line_call(2, 270.0, 100.0)
        c3 = _arc_call(3, tangent_deg=0.0, radius=100.0, delta_deg=180.0, curve_dir="right")
        result = verify_closure([c1, c2, c3])
        assert any(
            "Courses 1-3" in w and "curved boundary self-intersection" in w for w in result.warnings
        )
        assert result.geometry_verified is False

    def test_overlapping_coincident_arcs_are_flagged(self):
        """An arc retracing the previous arc along the same circle is an overlap."""
        c1 = _arc_call(1, tangent_deg=0.0, radius=100.0, delta_deg=90.0, curve_dir="right")
        # At (100, 100) facing east (90 deg), reversing to west (270 deg) curving left 90 deg
        # retraces the exact same circle back to (0, 0).
        c2 = _arc_call(2, tangent_deg=270.0, radius=100.0, delta_deg=90.0, curve_dir="left")
        result = verify_closure([c1, c2])
        assert any("curved boundary self-intersection" in w for w in result.warnings)
        assert result.geometry_verified is False

    def test_full_circle_loop_followed_by_another_course_is_flagged(self):
        """A 360-degree loop in a multi-course traverse closes prematurely."""
        c1 = _arc_call(1, tangent_deg=0.0, radius=50.0, delta_deg=360.0, curve_dir="right")
        c2 = _line_call(2, 90.0, 100.0)
        coords = [Point(x=0.0, y=0.0), Point(x=0.0, y=0.0), Point(x=100.0, y=0.0)]
        warnings = check_curved_boundary_intersections([c1, c2], coords)
        assert any("full-circle loop" in w for w in warnings)

    def test_incomplete_coordinates_report_unavailable_instead_of_false_clear(self):
        c1 = _arc_call(1, tangent_deg=0.0, radius=50.0, delta_deg=90.0, curve_dir="right")
        warnings = check_curved_boundary_intersections([c1], [Point(x=0.0, y=0.0)])
        assert warnings == [
            "Boundary intersection check unavailable: incomplete traverse coordinates"
        ]
