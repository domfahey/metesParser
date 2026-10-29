from __future__ import annotations

import pytest

from metesparser.closure_checker import ClosureChecker
from metesparser.models import DeedCall, Point


def test_calculate_area_closes_polygon_even_when_first_point_not_repeated() -> None:
    points = [
        Point(x=10.0, y=10.0),
        Point(x=20.0, y=10.0),
        Point(x=20.0, y=20.0),
        Point(x=10.0, y=20.0),
    ]
    assert ClosureChecker.calculate_area(points) == 100.0


def test_parallelism_handles_north_wraparound() -> None:
    calls = [
        DeedCall(
            course=1,
            direction_text="near north",
            bearing_azimuth_deg_from_north=359.8,
            distance_ft=100.0,
            along="north line",
        ),
        DeedCall(
            course=2,
            direction_text="near north",
            bearing_azimuth_deg_from_north=0.2,
            distance_ft=50.0,
            along="continuing along the same line",
        ),
    ]

    warnings = ClosureChecker.check_parallelism(calls)
    assert warnings == []


def test_compare_double_entry_flags_delta_mismatch() -> None:
    calls1 = [
        DeedCall(
            course=1,
            direction_text="curve",
            bearing_quadrant="N 0° E",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=100.0,
            curve_dir="left",
            radius_ft=50.0,
            delta_deg=90.0,
            arc_length_ft=78.54,
        )
    ]
    calls2 = [
        DeedCall(
            course=1,
            direction_text="curve",
            bearing_quadrant="N 0° E",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=100.0,
            curve_dir="left",
            radius_ft=50.0,
            delta_deg=95.0,
            arc_length_ft=82.9,
        )
    ]

    discrepancies = ClosureChecker.compare_double_entry(calls1, calls2)
    assert discrepancies == [
        "Course 1: Delta mismatch - 90.00 vs 95.00",
        "Course 1: Arc length mismatch - 78.54 vs 82.90",
    ]


def test_compare_double_entry_flags_curve_presence_mismatch() -> None:
    calls1 = [
        DeedCall(
            course=1,
            direction_text="curve",
            bearing_quadrant="N 0° E",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=100.0,
            curve_dir="right",
            radius_ft=50.0,
            delta_deg=90.0,
            arc_length_ft=78.54,
        )
    ]
    calls2 = [
        DeedCall(
            course=1,
            direction_text="line",
            bearing_quadrant="N 0° E",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=100.0,
        )
    ]

    discrepancies = ClosureChecker.compare_double_entry(calls1, calls2)
    assert discrepancies == [
        "Course 1: Curve geometry presence mismatch",
        "Course 1: Curve direction mismatch",
        "Course 1: Radius presence mismatch",
        "Course 1: Delta presence mismatch",
        "Course 1: Arc length presence mismatch",
    ]


def test_verify_closure_adds_double_entry_discrepancies_to_warnings() -> None:
    calls1 = [
        DeedCall(
            course=1, direction_text="North", bearing_azimuth_deg_from_north=0.0, distance_ft=100.0
        ),
        DeedCall(
            course=2, direction_text="East", bearing_azimuth_deg_from_north=90.0, distance_ft=100.0
        ),
        DeedCall(
            course=3,
            direction_text="South",
            bearing_azimuth_deg_from_north=180.0,
            distance_ft=100.0,
        ),
        DeedCall(
            course=4, direction_text="West", bearing_azimuth_deg_from_north=270.0, distance_ft=100.0
        ),
    ]
    calls2 = [
        DeedCall(
            course=1, direction_text="North", bearing_azimuth_deg_from_north=0.0, distance_ft=100.0
        ),
        DeedCall(
            course=2, direction_text="East", bearing_azimuth_deg_from_north=90.0, distance_ft=99.0
        ),
        DeedCall(
            course=3,
            direction_text="South",
            bearing_azimuth_deg_from_north=180.0,
            distance_ft=100.0,
        ),
        DeedCall(
            course=4, direction_text="West", bearing_azimuth_deg_from_north=270.0, distance_ft=100.0
        ),
    ]

    result = ClosureChecker.verify_closure(calls1, double_entry_calls=calls2)

    assert any(
        warning == "Double-entry discrepancy: Course 2: Distance mismatch - 100.00 vs 99.00"
        for warning in result.warnings
    )


def test_verify_closure_has_no_double_entry_warnings_for_matching_entries() -> None:
    calls = [
        DeedCall(
            course=1, direction_text="North", bearing_azimuth_deg_from_north=0.0, distance_ft=100.0
        ),
        DeedCall(
            course=2, direction_text="East", bearing_azimuth_deg_from_north=90.0, distance_ft=100.0
        ),
        DeedCall(
            course=3,
            direction_text="South",
            bearing_azimuth_deg_from_north=180.0,
            distance_ft=100.0,
        ),
        DeedCall(
            course=4, direction_text="West", bearing_azimuth_deg_from_north=270.0, distance_ft=100.0
        ),
    ]

    result = ClosureChecker.verify_closure(calls, double_entry_calls=calls)

    assert result.warnings == []


@pytest.mark.parametrize("bad_chord", ["S 0 E", "S34-57E", "South"])
def test_monolith_unparseable_chord_bearing_blocks_instead_of_raising(bad_chord):
    """#72: unparseable chord bearing must block the curve check, not crash."""
    from metesparser.closure_checker import ClosureChecker
    from metesparser.models import DeedCall

    calls = [
        DeedCall(
            course=1, direction_text="N", bearing_azimuth_deg_from_north=0.0, distance_ft=100.0
        ),
        DeedCall(
            course=2,
            direction_text="curve",
            bearing_azimuth_deg_from_north=90.0,
            distance_ft=100.0,
            curve_dir="right",
            radius_ft=100.0,
            delta_deg=60.0,
            arc_length_ft=104.72,
            chord_bearing=bad_chord,
        ),
        DeedCall(
            course=3, direction_text="S", bearing_azimuth_deg_from_north=180.0, distance_ft=100.0
        ),
    ]
    result = ClosureChecker.verify_closure(calls)
    assert not result.geometry_verified
    assert any("chord bearing" in w.lower() for w in result.warnings)
    curve = next(c for c in result.checks if c.name == "curve_consistency")
    assert curve.status == "blocked"


def test_monolith_multi_tract_does_not_overwrite_audit_context():
    """#73: per-tract verification must not write one audit context per tract."""
    from datetime import UTC, datetime

    from metesparser.closure_checker import ClosureChecker
    from metesparser.models import AuditContext, DeedCall, RunMetadata, Tract, TractType

    def square(size):
        return [
            DeedCall(
                course=i + 1,
                direction_text=str(a),
                bearing_azimuth_deg_from_north=a,
                distance_ft=size,
            )
            for i, a in enumerate((0, 90, 180, 270))
        ]

    tracts = [
        Tract(label="A", tract_type=TractType.MAIN, calls=square(100.0)),
        Tract(label="B", tract_type=TractType.MAIN, calls=square(50.0)),
    ]
    ctx = AuditContext(
        run_metadata=RunMetadata(
            parser_version="t",
            llm_provider="t",
            llm_model="t",
            prompt_hash="t",
            timestamp_utc=datetime.now(UTC),
            source_pdf="t.pdf",
            cache_enabled=False,
        )
    )
    ClosureChecker.verify_closure([], tracts=tracts, audit_context=ctx)
    assert ctx.verification_audit is None
