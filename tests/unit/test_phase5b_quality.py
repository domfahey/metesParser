"""Phase 5b: Output & Reporting Enhancements — Quality & Confidence Scoring."""

from __future__ import annotations

from metesparser.models import ClosureResult, DeedCall  # noqa: E402

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
