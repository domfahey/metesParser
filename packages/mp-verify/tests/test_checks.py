"""Tests for mp_verify verification checks and confidence scoring."""

from __future__ import annotations

import math

import pytest


def test_confidence_scoring():
    """Confidence score matches the documented weighted formula for a closed traverse."""
    from mp_models import ClosureResult, DeedCall
    from mp_verify.confidence import calculate_confidence_score

    result = ClosureResult(
        misclosure_x_ft=0.001,
        misclosure_y_ft=0.001,
        misclosure_ft=0.002,
        area_sq_ft=10000.0,
        area_acres=0.23,
        perimeter_ft=400.0,
        closure_passed=True,
        angle_check_passed=True,
        curve_consistency_passed=True,
    )
    calls = [
        DeedCall(
            course=i,
            direction_text="North",
            bearing_quadrant="N 00\u00b000' E",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=100.0,
        )
        for i in range(1, 5)
    ]
    # 0.001 <= misclosure_ft < 0.01 -> closure_score = 0.9; all other components = 1.0.
    score = calculate_confidence_score(result, calls)
    assert score == pytest.approx(0.9 * 0.30 + 1.0 * 0.20 + 1.0 * 0.25 + 1.0 * 0.15 + 1.0 * 0.10)


def test_confidence_scoring_empty_calls():
    """Empty call list should return 0.0 confidence."""
    from mp_models import ClosureResult
    from mp_verify.confidence import calculate_confidence_score

    result = ClosureResult(
        misclosure_x_ft=0.0,
        misclosure_y_ft=0.0,
        misclosure_ft=0.0,
        area_sq_ft=0.0,
        area_acres=0.0,
        perimeter_ft=0.0,
        closure_passed=False,
        angle_check_passed=True,
        curve_consistency_passed=True,
    )
    score = calculate_confidence_score(result, [])
    assert score == 0.0


def test_score_call_quality_high():
    """A call with complete bearing and no flags should score high."""
    from mp_models import DeedCall
    from mp_verify.confidence import score_call_quality

    call = DeedCall(
        course=1,
        direction_text="N 45\u00b000' E",
        bearing_quadrant="N 45\u00b000' E",
        bearing_azimuth_deg_from_north=45.0,
        distance_ft=100.0,
    )
    assert score_call_quality(call) == "high"


def test_score_call_quality_low_incomplete():
    """A call without azimuth should score low."""
    from mp_models import DeedCall
    from mp_verify.confidence import score_call_quality

    call = DeedCall(
        course=1,
        direction_text="southwesterly",
        distance_ft=100.0,
    )
    assert score_call_quality(call) == "low"


def test_score_call_quality_medium_meander():
    """A meander call with complete bearing should score medium."""
    from mp_models import DeedCall
    from mp_verify.confidence import score_call_quality

    call = DeedCall(
        course=1,
        direction_text="N 45\u00b000' E",
        bearing_azimuth_deg_from_north=45.0,
        distance_ft=100.0,
        is_meander=True,
    )
    assert score_call_quality(call) == "medium"


def test_check_bearing_reversals_detects():
    """Adjacent courses ~180 degrees apart should be flagged."""
    from mp_models import DeedCall
    from mp_verify.checks import check_bearing_reversals

    calls = [
        DeedCall(
            course=1,
            direction_text="North",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=100.0,
        ),
        DeedCall(
            course=2,
            direction_text="South",
            bearing_azimuth_deg_from_north=178.0,
            distance_ft=100.0,
        ),
    ]
    warnings = check_bearing_reversals(calls)
    assert len(warnings) == 1
    assert "bearing reversal" in warnings[0].lower()


def test_check_bearing_reversals_no_false_positive():
    """Normal courses should not trigger reversal warnings."""
    from mp_models import DeedCall
    from mp_verify.checks import check_bearing_reversals

    calls = [
        DeedCall(
            course=1,
            direction_text="North",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=100.0,
        ),
        DeedCall(
            course=2,
            direction_text="East",
            bearing_azimuth_deg_from_north=90.0,
            distance_ft=100.0,
        ),
    ]
    warnings = check_bearing_reversals(calls)
    assert len(warnings) == 0


def test_check_distance_reasonableness_short():
    """Suspiciously short distances should be flagged."""
    from mp_models import DeedCall
    from mp_verify.checks import check_distance_reasonableness

    calls = [
        DeedCall(
            course=1,
            direction_text="North",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=0.1,
        ),
        DeedCall(
            course=2,
            direction_text="East",
            bearing_azimuth_deg_from_north=90.0,
            distance_ft=100.0,
        ),
    ]
    warnings = check_distance_reasonableness(calls)
    assert any("short" in w.lower() for w in warnings)


def test_check_curve_consistency_passes():
    """Consistent curve data should pass."""
    import math

    from mp_models import DeedCall
    from mp_verify.checks import check_curve_consistency

    radius = 100.0
    delta = 45.0
    arc = radius * math.radians(delta)
    calls = [
        DeedCall(
            course=1,
            direction_text="Curve",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=arc,
            curve_dir="right",
            radius_ft=radius,
            delta_deg=delta,
            arc_length_ft=arc,
        ),
    ]
    passed, warnings = check_curve_consistency(calls)
    assert passed
    assert len(warnings) == 0


def test_check_interior_angles_square():
    """A perfect square should pass interior angle check."""
    from mp_models import DeedCall
    from mp_verify.checks import check_interior_angles

    calls = [
        DeedCall(
            course=1,
            direction_text="North",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=100.0,
        ),
        DeedCall(
            course=2,
            direction_text="East",
            bearing_azimuth_deg_from_north=90.0,
            distance_ft=100.0,
        ),
        DeedCall(
            course=3,
            direction_text="South",
            bearing_azimuth_deg_from_north=180.0,
            distance_ft=100.0,
        ),
        DeedCall(
            course=4,
            direction_text="West",
            bearing_azimuth_deg_from_north=270.0,
            distance_ft=100.0,
        ),
    ]
    passed = check_interior_angles(calls, [])
    assert passed


def test_check_parallelism_no_warnings():
    """Normal calls without 'continuing' should not trigger warnings."""
    from mp_models import DeedCall
    from mp_verify.checks import check_parallelism

    calls = [
        DeedCall(
            course=1,
            direction_text="North",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=100.0,
        ),
        DeedCall(
            course=2,
            direction_text="East",
            bearing_azimuth_deg_from_north=90.0,
            distance_ft=100.0,
        ),
    ]
    warnings = check_parallelism(calls)
    assert len(warnings) == 0


def test_first_course_continuing_along_does_not_block_parallelism():
    """#49: course 0 has no predecessor, so a 'continuing' along must not block."""
    from mp_models import DeedCall
    from mp_verify import verify_closure

    specs = [(0.0, "North"), (90.0, "East"), (180.0, "South"), (270.0, "West")]
    calls = [
        DeedCall(
            course=i + 1,
            direction_text=text,
            bearing_azimuth_deg_from_north=az,
            distance_ft=100.0,
            along="continuing along the same line" if i == 0 else None,
        )
        for i, (az, text) in enumerate(specs)
    ]
    result = verify_closure(calls)
    parallel = next(c for c in result.checks if c.name == "parallelism")
    assert parallel.status != "blocked"
    assert result.geometry_verified


def test_check_parallelism_flags_bearing_jump_and_accepts_collinear_or_reversed():
    """'continuing' / 'same line' must match previous bearing within 1 deg (or 180 deg opposite)."""
    from mp_models import DeedCall
    from mp_verify.checks import check_parallelism

    base = DeedCall(
        course=1, direction_text="North", bearing_azimuth_deg_from_north=10.0, distance_ft=100.0
    )
    ok_same = DeedCall(
        course=2,
        direction_text="N 10°30' E",
        bearing_azimuth_deg_from_north=10.5,
        distance_ft=100.0,
        along="continuing along the street",
    )
    ok_rev = DeedCall(
        course=3,
        direction_text="S 10° W",
        bearing_azimuth_deg_from_north=190.0,
        distance_ft=100.0,
        along="same line reversed",
    )
    assert check_parallelism([base, ok_same, ok_rev]) == []

    bad = DeedCall(
        course=2,
        direction_text="N 25° E",
        bearing_azimuth_deg_from_north=25.0,
        distance_ft=100.0,
        along="continuing along the street",
    )
    warnings = check_parallelism([base, bad])
    assert len(warnings) == 1
    assert "Course 2" in warnings[0] and "15.0°" in warnings[0]


def test_curve_consistency_and_tangent_chord_edge_cases():
    """Cover empty block_curve_consistency, missing radius, >360 arc, and wrong-side chord."""
    from mp_models import CheckResult, DeedCall
    from mp_verify.checks import (
        block_curve_consistency,
        check_curve_consistency,
        tangent_chord_issue,
    )

    checks = [CheckResult(name="curve_consistency", status="passed", detail="ok")]
    assert block_curve_consistency(checks, []) is checks

    # Curve missing radius (constructed directly to reach guard).
    no_radius = DeedCall.model_construct(
        course=1, direction_text="curve", distance_ft=50.0, curve_dir="right"
    )
    passed, warnings = check_curve_consistency([no_radius])
    assert passed is True and warnings == []

    # Arc length exceeding 2*pi*R without explicit delta_deg.
    over_circle = DeedCall(
        course=2,
        direction_text="curve",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=700.0,
        curve_dir="right",
        radius_ft=100.0,
        arc_length_ft=700.0,
    )
    passed, warnings = check_curve_consistency([over_circle])
    assert passed is False
    assert any("exceeds full circle" in w for w in warnings)

    # Chord bearing on the left side of a right-curving tangent gives deflection <= 0.
    wrong_side = DeedCall(
        course=3,
        direction_text="curve right",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=50.0,
        curve_dir="right",
        radius_ft=100.0,
        delta_deg=30.0,
        chord_bearing="N 15° W",
    )
    issue = tangent_chord_issue(wrong_side)
    assert issue is not None and "not on the right side" in issue


def test_check_area_reasonableness_boundaries():
    from mp_verify.checks import check_area_reasonableness

    assert check_area_reasonableness(10000.0, 0.0) == []
    assert check_area_reasonableness(10000.0, -50.0) == []
    assert check_area_reasonableness(10400.0, 10000.0) == []
    warnings = check_area_reasonableness(11000.0, 10000.0)
    assert len(warnings) == 1
    assert "10.0%" in warnings[0]


class TestCompareDoubleEntry:
    def _line(self, **overrides):
        from mp_models import DeedCall

        base = {
            "course": 1,
            "direction_text": "N 0° E",
            "bearing_quadrant": "N 00°00' E",
            "bearing_azimuth_deg_from_north": 0.0,
            "distance_ft": 100.0,
        }
        base.update(overrides)
        return DeedCall(**base)

    def _curve(self, **overrides):
        from mp_models import DeedCall

        arc = 100.0 * math.radians(60.0)
        base = {
            "course": 1,
            "direction_text": "curve",
            "bearing_quadrant": "N 00°00' E",
            "bearing_azimuth_deg_from_north": 0.0,
            "distance_ft": arc,
            "curve_dir": "right",
            "curve_type": "simple",
            "radius_ft": 100.0,
            "delta_deg": 60.0,
            "arc_length_ft": arc,
            "chord_length_ft": 100.0,
            "chord_bearing": "N 30° E",
        }
        base.update(overrides)
        return DeedCall(**base)

    def test_matching_calls_including_zero_360_wraparound_have_no_discrepancies(self):
        from mp_verify.checks import compare_double_entry

        c1 = self._line(bearing_azimuth_deg_from_north=0.00002)
        c2 = self._line(bearing_azimuth_deg_from_north=359.99998)
        assert compare_double_entry([c1], [c2]) == []
        assert compare_double_entry([self._curve()], [self._curve()]) == []

    def test_count_bearing_azimuth_distance_and_flag_mismatches(self):
        from mp_verify.checks import compare_double_entry

        a = self._line()
        assert compare_double_entry([a], [a, a]) == ["Different number of calls: 1 vs 2"]

        b = self._line(
            bearing_quadrant="N 01°00' E",
            bearing_azimuth_deg_from_north=1.0,
            distance_ft=105.0,
            is_exception=True,
            is_tie_in=True,
            is_meander=True,
        )
        diffs = compare_double_entry([a], [b])
        joined = "\n".join(diffs)
        assert "Bearing mismatch" in joined
        assert "Azimuth mismatch" in joined
        assert "Distance mismatch" in joined
        assert "Exception flag mismatch" in joined
        assert "Tie-in flag mismatch" in joined
        assert "Meander flag mismatch" in joined

        # Azimuth presence mismatch (one None vs numeric).
        no_az = self._line(bearing_azimuth_deg_from_north=None)
        assert compare_double_entry([no_az], [no_az]) == []
        assert any("Azimuth presence mismatch" in d for d in compare_double_entry([a], [no_az]))

    def test_curve_and_stray_curve_field_mismatches(self):
        from mp_verify.checks import compare_double_entry

        line = self._line()
        curve = self._curve()
        diffs = compare_double_entry([line], [curve])
        assert any("Curve geometry presence mismatch" in d for d in diffs)
        assert any("Curve type mismatch" in d for d in diffs)
        assert any("Radius presence mismatch" in d for d in diffs)

        # Two curves differing in every curve attribute.
        c1 = self._curve(non_tangent=False, radial_bearing="N 90° E")
        c2 = self._curve(
            curve_dir="left",
            curve_type="compound",
            radius_ft=120.0,
            delta_deg=65.0,
            arc_length_ft=136.0,
            chord_length_ft=110.0,
            chord_bearing="N 30° W",
            non_tangent=True,
            radial_bearing="S 90° W",
        )
        cdiffs = "\n".join(compare_double_entry([c1], [c2]))
        for expected in (
            "Curve type mismatch",
            "Curve direction mismatch",
            "Radius mismatch",
            "Delta mismatch",
            "Arc length mismatch",
            "Chord length mismatch",
            "Chord bearing mismatch",
            "Non-tangent flag mismatch",
            "Radial bearing mismatch",
        ):
            assert expected in cdiffs

        # Stray curve field on non-curve (e.g. non_tangent=True) is still compared.
        stray = self._line(non_tangent=True, radial_bearing="N 45° E")
        sdiffs = "\n".join(compare_double_entry([line], [stray]))
        assert "Non-tangent flag mismatch" in sdiffs
        assert "Radial bearing mismatch" in sdiffs


class TestConfidenceAndTangentsInvariants:
    def test_score_call_quality_non_permanent_vs_permanent_monument(self):
        from mp_models import DeedCall
        from mp_verify.confidence import score_call_quality

        base = {
            "course": 1,
            "direction_text": "North",
            "bearing_azimuth_deg_from_north": 0.0,
            "distance_ft": 50.0,
        }
        assert score_call_quality(DeedCall(**base, monument_type="wooden_post")) == "medium"
        assert score_call_quality(DeedCall(**base, monument_type="iron_pin")) == "high"

    def test_confidence_derives_positioned_flags_when_misclosure_unavailable(self):
        from mp_models import CheckResult, ClosureResult, DeedCall
        from mp_verify.confidence import calculate_confidence_score

        base_result = ClosureResult(
            misclosure_x_ft=0.0,
            misclosure_y_ft=0.0,
            misclosure_ft=0.0,
            misclosure_available=False,
            area_sq_ft=0.0,
            area_acres=0.0,
            perimeter_ft=0.0,
            closure_passed=False,
            angle_check_passed=True,
            curve_consistency_passed=True,
            checks=[
                CheckResult(name="traverse_closure", status="blocked", detail="blocked"),
                CheckResult(name="interior_angles", status="not_applicable", detail="na"),
            ],
        )
        # All-exception boundary calls: falls back to non_tie, positioned -> non-zero score
        # with checks_score == 0.0 (no applicable non-closure checks).
        exc_call = DeedCall(
            course=1,
            direction_text="North",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=100.0,
            is_exception=True,
        )
        score = calculate_confidence_score(base_result, [exc_call])
        # closure=0, checks=0, bearing=1.0*0.25, quality=1.0*0.15, warning=1.0*0.10 = 0.50
        assert score == pytest.approx(0.50)

        # Boundary calls alongside a tie-in (len(boundary_calls) != len(calls)).
        tie_in = DeedCall(
            course=1,
            direction_text="North",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=50.0,
            is_tie_in=True,
        )
        main = DeedCall(
            course=2,
            direction_text="East",
            bearing_azimuth_deg_from_north=90.0,
            distance_ft=100.0,
        )
        assert calculate_confidence_score(base_result, [tie_in, main]) == pytest.approx(0.50)

        # Plain boundary calls with no tie-ins/exceptions reuse `records` directly.
        assert calculate_confidence_score(base_result, [main]) == pytest.approx(0.50)

        # Unpositioned boundary call (infeasible chord > 2R) with a determined tie-in returns 0.0.
        infeasible = DeedCall(
            course=2,
            direction_text="curve",
            distance_ft=300.0,
            curve_dir="right",
            radius_ft=100.0,
            chord_bearing="N 45° E",
            chord_length_ft=300.0,
        )
        assert calculate_confidence_score(base_result, [tie_in, infeasible]) == 0.0

    def test_tangent_helpers_edge_cases(self):
        from mp_models import DeedCall
        from mp_verify.tangents import (
            chord_is_feasible,
            chord_positioned_delta,
            determined_arc_sweep,
            exit_azimuth,
            line_distance,
        )

        # Spiral without stated length has distance_ft=None -> line_distance raises ValueError.
        spiral_no_len = DeedCall(
            course=1,
            direction_text="spiral",
            distance_ft=None,
            curve_type="spiral",
            curve_dir="right",
            radius_ft=200.0,
            delta_deg=10.0,
        )
        with pytest.raises(ValueError, match="distance not determined"):
            line_distance(spiral_no_len)
        assert chord_is_feasible(spiral_no_len) is True
        assert chord_positioned_delta(spiral_no_len) is None

        # Chord-positioned circular curve vs chord-only curve.
        circular_chord = DeedCall(
            course=2,
            direction_text="curve",
            distance_ft=104.72,
            curve_dir="right",
            radius_ft=100.0,
            delta_deg=60.0,
            chord_bearing="N 30° E",
        )
        assert chord_positioned_delta(circular_chord) == pytest.approx(60.0)
        assert exit_azimuth(circular_chord) == pytest.approx(60.0)

        # Curve without fixed start / zero delta / missing radius -> determined_arc_sweep None.
        unfixed_curve = DeedCall(
            course=3,
            direction_text="curve",
            distance_ft=50.0,
            curve_dir="right",
            radius_ft=100.0,
            delta_deg=30.0,
        )
        assert determined_arc_sweep(unfixed_curve) is None
        assert exit_azimuth(unfixed_curve) is None

        zero_delta = DeedCall(
            course=4,
            direction_text="curve",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=1.0,
            curve_dir="right",
            radius_ft=100.0,
            delta_deg=0.0,
        )
        assert determined_arc_sweep(zero_delta) is None

        no_radius_curve = DeedCall.model_construct(
            course=5,
            direction_text="curve",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=10.0,
            curve_dir="right",
            radius_ft=None,
            delta_deg=30.0,
        )
        assert determined_arc_sweep(no_radius_curve) is None
