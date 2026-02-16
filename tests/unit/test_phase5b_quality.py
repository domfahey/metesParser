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


# ---------------------------------------------------------------------------
# Step 3: calculate_confidence_score tests
# ---------------------------------------------------------------------------


def _make_closure_result(**overrides) -> ClosureResult:
    """Helper to build a ClosureResult with sensible defaults."""
    defaults = {
        "misclosure_x_ft": 0.0,
        "misclosure_y_ft": 0.0,
        "misclosure_ft": 0.0,
        "area_sq_ft": 10000.0,
        "area_acres": 10000.0 / 43560.0,
        "perimeter_ft": 400.0,
        "closure_passed": True,
        "angle_check_passed": True,
        "curve_consistency_passed": True,
        "warnings": [],
    }
    defaults.update(overrides)
    return ClosureResult(**defaults)


class TestCalculateConfidenceScore:
    """Tests for ClosureChecker.calculate_confidence_score()."""

    def test_perfect_survey_scores_high(self) -> None:
        """All checks pass, all bearings complete, permanent monuments."""
        calls = [
            _make_call(course=1, monument_type="iron_pin"),
            _make_call(course=2, monument_type="iron_rod",
                       bearing_azimuth_deg_from_north=135.0,
                       direction_text="S 45° E"),
            _make_call(course=3, monument_type="concrete",
                       bearing_azimuth_deg_from_north=225.0,
                       direction_text="S 45° W"),
            _make_call(course=4, monument_type="rebar",
                       bearing_azimuth_deg_from_north=315.0,
                       direction_text="N 45° W"),
        ]
        result = _make_closure_result()
        score = ClosureChecker.calculate_confidence_score(result, calls)
        assert 0.9 <= score <= 1.0

    def test_poor_closure_scores_lower(self) -> None:
        """Failed closure should drag score down vs perfect closure."""
        calls = [_make_call(course=i) for i in range(1, 5)]
        good = _make_closure_result()
        bad = _make_closure_result(misclosure_ft=5.0, closure_passed=False)
        good_score = ClosureChecker.calculate_confidence_score(good, calls)
        bad_score = ClosureChecker.calculate_confidence_score(bad, calls)
        assert bad_score < good_score
        assert bad_score < 0.85

    def test_all_incomplete_bearings_scores_lower(self) -> None:
        """No complete bearings → lower than all-complete bearings."""
        complete_calls = [_make_call(course=i) for i in range(1, 3)]
        incomplete_calls = [
            _make_call(course=1, bearing_azimuth_deg_from_north=None),
            _make_call(course=2, bearing_azimuth_deg_from_north=None),
        ]
        result = _make_closure_result()
        complete_score = ClosureChecker.calculate_confidence_score(result, complete_calls)
        incomplete_score = ClosureChecker.calculate_confidence_score(result, incomplete_calls)
        assert incomplete_score < complete_score
        assert incomplete_score < 0.7

    def test_meander_calls_reduce_confidence(self) -> None:
        """Meander calls should reduce confidence vs identical non-meander calls."""
        base_calls = [_make_call(course=i) for i in range(1, 5)]
        meander_calls = [
            _make_call(
                course=i,
                is_meander=True,
                curve_dir="right",
                radius_ft=500.0,
                arc_length_ft=100.0,
            )
            for i in range(1, 5)
        ]
        result = _make_closure_result()
        base_score = ClosureChecker.calculate_confidence_score(result, base_calls)
        meander_score = ClosureChecker.calculate_confidence_score(result, meander_calls)
        assert meander_score < base_score

    def test_returns_float_between_0_and_1(self) -> None:
        calls = [_make_call(course=1)]
        result = _make_closure_result()
        score = ClosureChecker.calculate_confidence_score(result, calls)
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_warnings_reduce_confidence(self) -> None:
        """Warnings should reduce confidence vs clean result."""
        calls = [_make_call(course=i) for i in range(1, 5)]
        clean = _make_closure_result()
        warned = _make_closure_result(warnings=["Something unusual", "Another issue"])
        clean_score = ClosureChecker.calculate_confidence_score(clean, calls)
        warned_score = ClosureChecker.calculate_confidence_score(warned, calls)
        assert warned_score < clean_score

    def test_failed_angle_check_reduces_confidence(self) -> None:
        calls = [_make_call(course=i) for i in range(1, 5)]
        good = _make_closure_result()
        bad = _make_closure_result(angle_check_passed=False)
        assert ClosureChecker.calculate_confidence_score(bad, calls) < \
            ClosureChecker.calculate_confidence_score(good, calls)

    def test_empty_calls_returns_zero(self) -> None:
        result = _make_closure_result()
        score = ClosureChecker.calculate_confidence_score(result, [])
        assert score == 0.0
