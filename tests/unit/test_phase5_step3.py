"""Phase 5 Step 3: Extended Curve Properties (T, E, M) tests."""

import pytest

from metesparser.bearing_converter import BearingConverter


class TestExtendedCurveProperties:
    """Tests for tangent (T), external distance (E), and middle ordinate (M)."""

    def test_calculate_curve_properties_includes_tangent(self) -> None:
        result = BearingConverter.calculate_curve_properties(100.0, delta_deg=90.0)
        # T = 100 * tan(45°) = 100.0
        assert "tangent_length_ft" in result
        assert abs(result["tangent_length_ft"] - 100.0) < 0.01

    def test_calculate_curve_properties_external_distance(self) -> None:
        result = BearingConverter.calculate_curve_properties(100.0, delta_deg=90.0)
        # E = 100 * (1/cos(45°) - 1) = 100 * (1.41421 - 1) = 41.421
        assert "external_distance_ft" in result
        assert abs(result["external_distance_ft"] - 41.421) < 0.01

    def test_calculate_curve_properties_middle_ordinate(self) -> None:
        result = BearingConverter.calculate_curve_properties(100.0, delta_deg=90.0)
        # M = 100 * (1 - cos(45°)) = 100 * (1 - 0.70711) = 29.289
        assert "middle_ordinate_ft" in result
        assert abs(result["middle_ordinate_ft"] - 29.289) < 0.01

    def test_calculate_curve_properties_small_delta(self) -> None:
        import math

        result = BearingConverter.calculate_curve_properties(500.0, delta_deg=10.0)
        half_rad = math.radians(5.0)
        assert result["tangent_length_ft"] == pytest.approx(500.0 * math.tan(half_rad), rel=1e-6)
        assert result["external_distance_ft"] == pytest.approx(
            500.0 * (1.0 / math.cos(half_rad) - 1.0), rel=1e-6
        )
        assert result["middle_ordinate_ft"] == pytest.approx(
            500.0 * (1.0 - math.cos(half_rad)), rel=1e-6
        )

    def test_calculate_missing_curve_elements_includes_e_and_m(self) -> None:
        result = BearingConverter.calculate_missing_curve_elements(radius_ft=100.0, delta_deg=90.0)
        assert "external_distance_ft" in result
        assert "middle_ordinate_ft" in result
        assert abs(result["external_distance_ft"] - 41.421) < 0.01
        assert abs(result["middle_ordinate_ft"] - 29.289) < 0.01

    def test_calculate_curve_properties_from_arc(self) -> None:
        """Properties should also work when computing from arc length."""
        import math

        arc = 100.0 * (math.pi / 2.0)
        result = BearingConverter.calculate_curve_properties(100.0, arc_length_ft=arc)
        assert result["delta_deg"] == pytest.approx(90.0, rel=1e-6)
        assert result["tangent_length_ft"] == pytest.approx(100.0, rel=1e-6)
        assert result["external_distance_ft"] == pytest.approx(
            100.0 * (math.sqrt(2.0) - 1.0), rel=1e-6
        )
        assert result["middle_ordinate_ft"] == pytest.approx(
            100.0 * (1.0 - math.sqrt(0.5)), rel=1e-6
        )

    def test_calculate_curve_properties_180_degree_delta_returns_inf(self) -> None:
        """Delta of 180° makes tangent/external undefined — should return inf."""
        result = BearingConverter.calculate_curve_properties(100.0, delta_deg=180.0)
        assert result["tangent_length_ft"] == float("inf")
        assert result["external_distance_ft"] == float("inf")
        # Middle ordinate is still valid at 180°: M = R
        assert abs(result["middle_ordinate_ft"] - 100.0) < 0.01

    def test_calculate_missing_curve_elements_180_degree_delta_returns_inf(self) -> None:
        result = BearingConverter.calculate_missing_curve_elements(radius_ft=100.0, delta_deg=180.0)
        assert result["tangent_length_ft"] == float("inf")
        assert result["external_distance_ft"] == float("inf")

    def test_calculate_missing_curve_elements_rejects_chord_ge_arc(self) -> None:
        """Chord must be strictly less than arc length."""
        with pytest.raises(ValueError, match="Chord.*must be less than arc"):
            BearingConverter.calculate_missing_curve_elements(
                arc_length_ft=100.0, chord_length_ft=100.0
            )

    def test_calculate_missing_curve_elements_rejects_zero_arc(self) -> None:
        with pytest.raises(ValueError, match="Arc length must be positive"):
            BearingConverter.calculate_missing_curve_elements(
                arc_length_ft=0.0, chord_length_ft=50.0
            )
