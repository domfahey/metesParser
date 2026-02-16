"""Phase 5b: Output & Reporting Enhancements — Quality & Confidence Scoring."""

from __future__ import annotations

from metesparser.closure_checker import ClosureChecker
from metesparser.models import ClosureResult, DeedCall

# ---------------------------------------------------------------------------
# Step 1: Model field tests
# ---------------------------------------------------------------------------


class TestModelFields:
    """Verify quality/confidence fields exist on models."""

    def test_deed_call_has_quality_field_default_none(self) -> None:
        call = DeedCall(
            course=1,
            direction_text="N 45° E",
            bearing_quadrant="N 45° E",
            bearing_azimuth_deg_from_north=45.0,
            distance_ft=100.0,
        )
        assert call.quality is None

    def test_deed_call_accepts_quality_values(self) -> None:
        for quality in ("high", "medium", "low"):
            call = DeedCall(
                course=1,
                direction_text="N 45° E",
                bearing_quadrant="N 45° E",
                bearing_azimuth_deg_from_north=45.0,
                distance_ft=100.0,
                quality=quality,
            )
            assert call.quality == quality

    def test_closure_result_has_confidence_score_default_none(self) -> None:
        result = ClosureResult(
            misclosure_x_ft=0.0,
            misclosure_y_ft=0.0,
            misclosure_ft=0.0,
            area_sq_ft=1000.0,
            area_acres=1000.0 / 43560.0,
            perimeter_ft=200.0,
            closure_passed=True,
            angle_check_passed=True,
            curve_consistency_passed=True,
        )
        assert result.confidence_score is None

    def test_closure_result_accepts_confidence_score(self) -> None:
        result = ClosureResult(
            misclosure_x_ft=0.0,
            misclosure_y_ft=0.0,
            misclosure_ft=0.0,
            area_sq_ft=1000.0,
            area_acres=1000.0 / 43560.0,
            perimeter_ft=200.0,
            closure_passed=True,
            angle_check_passed=True,
            curve_consistency_passed=True,
            confidence_score=0.95,
        )
        assert result.confidence_score == 0.95


# ---------------------------------------------------------------------------
# Step 2: score_call_quality tests
# ---------------------------------------------------------------------------

PERMANENT_MONUMENTS = {"iron_rod", "iron_pin", "iron_pipe", "concrete", "brass_cap",
                       "rebar", "capped_pin", "capped_rod", "railroad_spike"}


def _make_call(**overrides) -> DeedCall:
    """Helper to build a DeedCall with sensible defaults."""
    defaults = {
        "course": 1,
        "direction_text": "N 45° E",
        "bearing_quadrant": "N 45° E",
        "bearing_azimuth_deg_from_north": 45.0,
        "distance_ft": 100.0,
    }
    defaults.update(overrides)
    return DeedCall(**defaults)


class TestScoreCallQuality:
    """Tests for ClosureChecker.score_call_quality()."""

    def test_high_quality_complete_bearing_permanent_monument(self) -> None:
        call = _make_call(monument_type="iron_pin")
        assert ClosureChecker.score_call_quality(call) == "high"

    def test_high_quality_complete_bearing_no_monument_still_high(self) -> None:
        """Complete bearing without monument is still high (monument is bonus)."""
        call = _make_call()
        assert ClosureChecker.score_call_quality(call) == "high"

    def test_medium_quality_complete_bearing_non_permanent_monument(self) -> None:
        call = _make_call(monument_type="wooden_post")
        assert ClosureChecker.score_call_quality(call) == "medium"

    def test_medium_quality_complete_bearing_meander(self) -> None:
        """Meander flag downgrades quality even with complete bearing."""
        call = _make_call(
            is_meander=True,
            curve_dir="right",
            radius_ft=500.0,
            arc_length_ft=100.0,
        )
        assert ClosureChecker.score_call_quality(call) == "medium"

    def test_low_quality_no_bearing(self) -> None:
        call = _make_call(bearing_azimuth_deg_from_north=None)
        assert ClosureChecker.score_call_quality(call) == "low"

    def test_low_quality_indefinite(self) -> None:
        call = _make_call(is_indefinite=True)
        assert ClosureChecker.score_call_quality(call) == "low"

    def test_low_quality_indefinite_and_meander(self) -> None:
        call = _make_call(
            bearing_azimuth_deg_from_north=None,
            is_indefinite=True,
            is_meander=True,
            curve_dir="left",
            radius_ft=500.0,
            arc_length_ft=50.0,
        )
        assert ClosureChecker.score_call_quality(call) == "low"

    def test_natural_monument_is_medium(self) -> None:
        call = _make_call(monument_type="tree")
        assert ClosureChecker.score_call_quality(call) == "medium"

    def test_all_permanent_monuments_score_high(self) -> None:
        for monument in PERMANENT_MONUMENTS:
            call = _make_call(monument_type=monument)
            assert ClosureChecker.score_call_quality(call) == "high", f"Failed for {monument}"
