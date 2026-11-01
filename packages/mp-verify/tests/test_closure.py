"""Tests for mp_verify closure verification."""

from __future__ import annotations


def test_verify_closure_square():
    """A perfect 100ft square should close with near-zero misclosure."""
    from mp_models import DeedCall
    from mp_verify import verify_closure

    calls = [
        DeedCall(
            course=1,
            direction_text="North",
            bearing_quadrant="N 00\u00b000' E",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=100.0,
        ),
        DeedCall(
            course=2,
            direction_text="East",
            bearing_quadrant="N 90\u00b000' E",
            bearing_azimuth_deg_from_north=90.0,
            distance_ft=100.0,
        ),
        DeedCall(
            course=3,
            direction_text="South",
            bearing_quadrant="S 00\u00b000' E",
            bearing_azimuth_deg_from_north=180.0,
            distance_ft=100.0,
        ),
        DeedCall(
            course=4,
            direction_text="West",
            bearing_quadrant="N 90\u00b000' W",
            bearing_azimuth_deg_from_north=270.0,
            distance_ft=100.0,
        ),
    ]
    result = verify_closure(calls)
    assert result.closure_passed
    assert result.misclosure_ft < 0.01
    assert abs(result.area_sq_ft - 10000.0) < 1.0


def test_verify_closure_returns_closure_result():
    """verify_closure should return a ClosureResult model."""
    from mp_models import ClosureResult, DeedCall
    from mp_verify import verify_closure

    calls = [
        DeedCall(
            course=1,
            direction_text="North",
            bearing_quadrant="N 00\u00b000' E",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=100.0,
        ),
        DeedCall(
            course=2,
            direction_text="East",
            bearing_quadrant="N 90\u00b000' E",
            bearing_azimuth_deg_from_north=90.0,
            distance_ft=100.0,
        ),
        DeedCall(
            course=3,
            direction_text="South",
            bearing_quadrant="S 00\u00b000' E",
            bearing_azimuth_deg_from_north=180.0,
            distance_ft=100.0,
        ),
        DeedCall(
            course=4,
            direction_text="West",
            bearing_quadrant="N 90\u00b000' W",
            bearing_azimuth_deg_from_north=270.0,
            distance_ft=100.0,
        ),
    ]
    result = verify_closure(calls)
    assert isinstance(result, ClosureResult)
    assert result.perimeter_ft == 400.0
    assert result.area_acres > 0


def test_verify_closure_open_traverse_fails():
    """A traverse that doesn't close should fail."""
    from mp_models import DeedCall
    from mp_verify import verify_closure

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
    result = verify_closure(calls)
    assert not result.closure_passed
    assert result.misclosure_ft > 0.01


def test_verify_closure_stated_area_warning():
    """Should warn when computed area differs from stated area by >5%."""
    from mp_models import DeedCall
    from mp_verify import verify_closure

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
    # Stated area is wildly different from 10000 sq ft
    result = verify_closure(calls, stated_area_sq_ft=50000.0)
    assert any("differs from stated" in w for w in result.warnings)


def test_verify_closure_has_confidence_score():
    """verify_closure should attach a confidence_score to the result."""
    from mp_models import DeedCall
    from mp_verify import verify_closure

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
    result = verify_closure(calls)
    assert result.confidence_score is not None
    assert 0.0 <= result.confidence_score <= 1.0


def test_get_closure_summary_contains_sections():
    """get_closure_summary should produce a string with key sections."""
    from mp_models import DeedCall
    from mp_verify import get_closure_summary, verify_closure

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
    result = verify_closure(calls)
    summary = get_closure_summary(result, calls)
    assert "CLOSURE VERIFICATION SUMMARY" in summary
    assert "Misclosure" in summary
    assert "Area" in summary
    assert "Verification Checks" in summary


import pytest  # noqa: E402


@pytest.mark.parametrize("bad_chord", ["S 0 E", "S34-57E", "South"])
def test_unparseable_chord_bearing_blocks_instead_of_raising(bad_chord):
    """#72: an unparseable chord bearing must block the curve check, not crash."""
    from mp_models import DeedCall
    from mp_verify import verify_closure

    calls = [
        DeedCall(
            course=1,
            direction_text="N",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=100.0,
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
            course=3,
            direction_text="S",
            bearing_azimuth_deg_from_north=180.0,
            distance_ft=100.0,
        ),
    ]
    result = verify_closure(calls)
    assert not result.geometry_verified
    assert any("chord bearing" in w.lower() for w in result.warnings)
    curve = next(c for c in result.checks if c.name == "curve_consistency")
    assert curve.status == "blocked"


def test_bad_chord_on_one_call_does_not_strip_chord_from_same_course_number():
    """PR #60 review: a bad chord must only block its own call, not a sibling sharing a course number."""
    from mp_models import DeedCall
    from mp_verify import verify_closure

    def curve(chord: str | None) -> DeedCall:
        return DeedCall(
            course=2,
            direction_text="curve",
            bearing_azimuth_deg_from_north=90.0,
            distance_ft=100.0,
            curve_dir="right",
            radius_ft=100.0,
            delta_deg=60.0,
            arc_length_ft=104.72,
            chord_bearing=chord,
        )

    valid = curve("S 30° E")
    bad = curve("South")
    from mp_verify.traverse import traverse_positions

    # Only the unreadable-chord call is blocked; its sibling stays positioned.
    assert traverse_positions([valid, bad])[1] == [True, False]
    combined = verify_closure([valid, bad])
    assert combined.misclosure_available is False
    assert any("South" in w and "chord bearing" in w.lower() for w in combined.warnings)
