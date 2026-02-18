"""Tests for configurable closure tolerance in verify_closure().

TDD tests for the tolerance_ft parameter and relaxed-tolerance warning.
Covers default behavior preservation, relaxed tolerance, strict tolerance,
and the real-world MIWAYN-50020-01181 deed scenario.
"""

from __future__ import annotations

from mp_models import DeedCall
from mp_verify import verify_closure
from mp_verify.closure import CLOSURE_TOLERANCE_FT

# ---------------------------------------------------------------------------
# Helpers: reusable call fixtures
# ---------------------------------------------------------------------------

def _perfect_square_calls() -> list[DeedCall]:
    """A perfect 100 ft square that closes exactly."""
    return [
        DeedCall(
            course=1,
            direction_text="N 00\u00b000' E",
            bearing_quadrant="N 00\u00b000' E",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=100.0,
        ),
        DeedCall(
            course=2,
            direction_text="N 90\u00b000' E",
            bearing_quadrant="N 90\u00b000' E",
            bearing_azimuth_deg_from_north=90.0,
            distance_ft=100.0,
        ),
        DeedCall(
            course=3,
            direction_text="S 00\u00b000' E",
            bearing_quadrant="S 00\u00b000' E",
            bearing_azimuth_deg_from_north=180.0,
            distance_ft=100.0,
        ),
        DeedCall(
            course=4,
            direction_text="N 90\u00b000' W",
            bearing_quadrant="N 90\u00b000' W",
            bearing_azimuth_deg_from_north=270.0,
            distance_ft=100.0,
        ),
    ]


def _near_closing_calls(offset_ft: float = 0.005) -> list[DeedCall]:
    """A square with a small offset on the last leg (misclosure ~ offset_ft)."""
    return [
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
            distance_ft=100.0 - offset_ft,
        ),
    ]


def _miwayn_50020_calls() -> list[DeedCall]:
    """Actual extracted calls from MIWAYN-50020-01181.

    Four calls from a Wayne County, Michigan deed:
      1) N 89 deg 50' E   439.98 ft
      2) S 30 deg 07'30" E 173.82 ft
      3) S 89 deg 50' W   526.89 ft
      4) N 0 deg 10' W    150.60 ft

    The bearings/distances are correctly extracted and match ground truth,
    but the traverse does not close within the default 0.01 ft threshold
    because the misclosure is inherent in the deed's stated measurements.
    """
    return [
        DeedCall(
            course=1,
            direction_text="N 89\u00b050' E",
            bearing_quadrant="N 89\u00b050' E",
            bearing_azimuth_deg_from_north=89.833333,
            distance_ft=439.98,
        ),
        DeedCall(
            course=2,
            direction_text="S 30\u00b007'30\" E",
            bearing_quadrant="S 30\u00b008' E",
            bearing_azimuth_deg_from_north=149.875,
            distance_ft=173.82,
        ),
        DeedCall(
            course=3,
            direction_text="S 89\u00b050' W",
            bearing_quadrant="S 89\u00b050' W",
            bearing_azimuth_deg_from_north=269.833333,
            distance_ft=526.89,
        ),
        DeedCall(
            course=4,
            direction_text="N 0\u00b010' W",
            bearing_quadrant="N 0\u00b010' W",
            bearing_azimuth_deg_from_north=359.833333,
            distance_ft=150.60,
        ),
    ]


# ---------------------------------------------------------------------------
# Test: default tolerance constant
# ---------------------------------------------------------------------------

class TestDefaultToleranceConstant:
    """Verify the module-level constant is 0.01 ft."""

    def test_closure_tolerance_ft_is_001(self):
        assert CLOSURE_TOLERANCE_FT == 0.01


# ---------------------------------------------------------------------------
# Test: default tolerance preserves existing behavior
# ---------------------------------------------------------------------------

class TestDefaultTolerancePreservesExistingBehavior:
    """When no tolerance is specified, behavior must be identical to before."""

    def test_perfect_square_passes_at_default(self):
        calls = _perfect_square_calls()
        result = verify_closure(calls)
        assert result.closure_passed is True
        assert result.misclosure_ft < 0.01

    def test_open_traverse_fails_at_default(self):
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
        assert result.closure_passed is False

    def test_near_closing_traverse_005ft_passes_at_default(self):
        """A traverse with ~0.005 ft misclosure passes default 0.01 threshold."""
        calls = _near_closing_calls(offset_ft=0.005)
        result = verify_closure(calls)
        assert result.misclosure_ft < 0.01
        assert result.closure_passed is True


# ---------------------------------------------------------------------------
# Test: relaxed tolerance allows near-closing traverses
# ---------------------------------------------------------------------------

class TestRelaxedTolerance:
    """A relaxed tolerance_ft should allow traverses that barely miss 0.01."""

    def test_relaxed_tolerance_passes(self):
        """A traverse failing at 0.01 should pass at 1.0 ft tolerance."""
        calls = _near_closing_calls(offset_ft=0.05)
        # Should fail at default
        result_default = verify_closure(calls)
        assert result_default.closure_passed is False
        assert result_default.misclosure_ft > 0.01

        # Should pass at relaxed 1.0
        result_relaxed = verify_closure(calls, closure_tolerance_ft=1.0)
        assert result_relaxed.closure_passed is True

    def test_relaxed_tolerance_warning_added(self):
        """When relaxed tolerance saves the day, a warning should be emitted."""
        calls = _near_closing_calls(offset_ft=0.05)
        result = verify_closure(calls, closure_tolerance_ft=1.0)
        assert result.closure_passed is True
        assert any("relaxed tolerance" in w.lower() for w in result.warnings)

    def test_relaxed_tolerance_warning_contains_misclosure_and_threshold(self):
        """Warning message should mention the actual misclosure and the threshold."""
        calls = _near_closing_calls(offset_ft=0.05)
        result = verify_closure(calls, closure_tolerance_ft=1.0)
        relaxed_warnings = [w for w in result.warnings if "relaxed tolerance" in w.lower()]
        assert len(relaxed_warnings) == 1
        warning = relaxed_warnings[0]
        # Should contain the misclosure value and the threshold
        assert "0.05" in warning or "misclosure" in warning.lower()
        assert "1.0" in warning or "threshold" in warning.lower()

    def test_no_relaxed_warning_when_would_pass_at_default(self):
        """If traverse would pass at default 0.01 anyway, no relaxed warning."""
        calls = _perfect_square_calls()
        result = verify_closure(calls, closure_tolerance_ft=1.0)
        assert result.closure_passed is True
        assert not any("relaxed tolerance" in w.lower() for w in result.warnings)


# ---------------------------------------------------------------------------
# Test: strict tolerance (0.0)
# ---------------------------------------------------------------------------

class TestStrictTolerance:
    """tolerance=0.0 should require mathematically exact closure."""

    def test_strict_tolerance_fails_for_near_closing(self):
        calls = _near_closing_calls(offset_ft=0.001)
        result = verify_closure(calls, closure_tolerance_ft=0.0)
        # Even a tiny misclosure should fail with 0.0 tolerance
        # (misclosure > 0 since offset_ft > 0, and 0 < 0.0 is False)
        assert result.closure_passed is False

    def test_strict_tolerance_perfect_square(self):
        """A mathematically perfect square should still pass at tolerance=0.0.

        The perfect square has floating-point misclosure near 0 but not
        identically 0, so with tolerance=0.0 the strict '<' comparison
        means the square's tiny float residual (typically ~1e-14) will
        NOT be < 0.0, so it should actually fail.
        """
        calls = _perfect_square_calls()
        result = verify_closure(calls, closure_tolerance_ft=0.0)
        # Even floating-point-perfect closure gives misclosure ~ 1e-14,
        # which is NOT < 0.0, so strict tolerance = 0.0 should fail.
        # This is the expected and correct behavior for "exact match only".
        assert result.closure_passed is False


# ---------------------------------------------------------------------------
# Test: MIWAYN-50020-01181 real-world deed
# ---------------------------------------------------------------------------

class TestMIWAYN50020Deed:
    """Real-world test using calls from MIWAYN-50020-01181 (Wayne County, MI).

    This deed has 4 correctly extracted calls matching ground truth,
    but the traverse does not close within the default 0.01 ft threshold.
    """

    def test_fails_at_default_tolerance(self):
        """MIWAYN-50020 should fail closure at the default 0.01 ft threshold."""
        calls = _miwayn_50020_calls()
        result = verify_closure(calls)
        assert result.closure_passed is False
        assert result.misclosure_ft > CLOSURE_TOLERANCE_FT

    def test_misclosure_is_reasonable(self):
        """Misclosure should be small (< 5 ft) -- it's a real deed, not garbage."""
        calls = _miwayn_50020_calls()
        result = verify_closure(calls)
        assert result.misclosure_ft < 5.0

    def test_passes_with_relaxed_tolerance(self):
        """With a sufficiently relaxed tolerance, MIWAYN-50020 should pass."""
        calls = _miwayn_50020_calls()
        # First, find the actual misclosure
        result_default = verify_closure(calls)
        misclosure = result_default.misclosure_ft

        # Use a tolerance slightly above the misclosure
        relaxed_tolerance = misclosure + 0.1
        result_relaxed = verify_closure(calls, closure_tolerance_ft=relaxed_tolerance)
        assert result_relaxed.closure_passed is True

    def test_relaxed_tolerance_emits_warning(self):
        """When MIWAYN-50020 passes with relaxed tolerance, warning is emitted."""
        calls = _miwayn_50020_calls()
        result_default = verify_closure(calls)
        misclosure = result_default.misclosure_ft
        relaxed_tolerance = misclosure + 0.1

        result = verify_closure(calls, closure_tolerance_ft=relaxed_tolerance)
        assert result.closure_passed is True
        assert any("relaxed tolerance" in w.lower() for w in result.warnings)

    def test_area_is_reasonable(self):
        """MIWAYN-50020 should compute a reasonable area (a residential parcel)."""
        calls = _miwayn_50020_calls()
        result = verify_closure(calls)
        # Area should be positive and in a plausible residential range
        assert result.area_sq_ft > 10_000
        assert result.area_sq_ft < 500_000

    def test_all_four_calls_used(self):
        """All 4 calls should have bearings and contribute to the traverse."""
        calls = _miwayn_50020_calls()
        for call in calls:
            assert call.bearing_azimuth_deg_from_north is not None
            assert call.distance_ft > 0

    def test_perimeter_is_sum_of_distances(self):
        """Perimeter should match sum of all four distances."""
        calls = _miwayn_50020_calls()
        result = verify_closure(calls)
        expected_perimeter = 439.98 + 173.82 + 526.89 + 150.60
        assert abs(result.perimeter_ft - expected_perimeter) < 0.01
