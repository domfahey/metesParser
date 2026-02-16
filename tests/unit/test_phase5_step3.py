"""Phase 5 Step 3: Extended Curve Properties (T, E, M) tests."""

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
        result = BearingConverter.calculate_curve_properties(500.0, delta_deg=10.0)
        assert result["external_distance_ft"] < 5.0
        assert result["middle_ordinate_ft"] < 5.0
        assert result["tangent_length_ft"] < 50.0

    def test_calculate_missing_curve_elements_includes_e_and_m(self) -> None:
        result = BearingConverter.calculate_missing_curve_elements(radius_ft=100.0, delta_deg=90.0)
        assert "external_distance_ft" in result
        assert "middle_ordinate_ft" in result
        assert abs(result["external_distance_ft"] - 41.421) < 0.01
        assert abs(result["middle_ordinate_ft"] - 29.289) < 0.01

    def test_calculate_curve_properties_from_arc(self) -> None:
        """Properties should also work when computing from arc length."""
        result = BearingConverter.calculate_curve_properties(100.0, arc_length_ft=157.08)
        # arc=157.08 ≈ 100 * π/2 → delta ≈ 90°
        assert "tangent_length_ft" in result
        assert "external_distance_ft" in result
        assert "middle_ordinate_ft" in result
        assert abs(result["tangent_length_ft"] - 100.0) < 0.5
