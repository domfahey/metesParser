"""Phase 5 Step 5: 32-Point Compass System tests."""

from metesparser.bearing_converter import BearingConverter
from metesparser.call_extractor import CallExtractor


class TestCompassPointSystem:
    """Tests for 32-point mariner's compass system."""

    def test_north(self) -> None:
        assert BearingConverter.compass_point_to_azimuth("North") == 0.0

    def test_north_by_east(self) -> None:
        assert abs(BearingConverter.compass_point_to_azimuth("North by East") - 11.25) < 0.01

    def test_north_northeast(self) -> None:
        assert abs(BearingConverter.compass_point_to_azimuth("North-Northeast") - 22.5) < 0.01

    def test_northeast(self) -> None:
        assert abs(BearingConverter.compass_point_to_azimuth("Northeast") - 45.0) < 0.01

    def test_east(self) -> None:
        assert abs(BearingConverter.compass_point_to_azimuth("East") - 90.0) < 0.01

    def test_south(self) -> None:
        assert abs(BearingConverter.compass_point_to_azimuth("South") - 180.0) < 0.01

    def test_west(self) -> None:
        assert abs(BearingConverter.compass_point_to_azimuth("West") - 270.0) < 0.01

    def test_southwest(self) -> None:
        assert abs(BearingConverter.compass_point_to_azimuth("Southwest") - 225.0) < 0.01

    def test_south_by_west(self) -> None:
        assert abs(BearingConverter.compass_point_to_azimuth("South by West") - 191.25) < 0.01

    def test_case_insensitive(self) -> None:
        assert abs(BearingConverter.compass_point_to_azimuth("NORTH BY EAST") - 11.25) < 0.01

    def test_invalid_point_returns_none(self) -> None:
        assert BearingConverter.compass_point_to_azimuth("Northish") is None

    def test_extract_direction_compass_point(self) -> None:
        result = CallExtractor.extract_direction("North by East 125 feet to an iron pin")
        assert result.lower() == "north by east"

    def test_extract_direction_northeast_by_north(self) -> None:
        result = CallExtractor.extract_direction("Northeast by North 200 feet")
        assert result.lower() == "northeast by north"

    def test_extract_direction_prefers_quadrant_over_compass(self) -> None:
        result = CallExtractor.extract_direction("S 45°30' E along the North line 100 feet")
        assert "45" in result  # quadrant bearing, not "North"
