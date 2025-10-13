"""Tests for bearing_converter.py - Critical coordinate calculations."""

import math

import pytest

from metesparser.bearing_converter import BearingConverter
from metesparser.models import Point


class TestQuadrantParsing:
    """Test parsing of quadrant bearings from text."""

    def test_parse_nde_format(self):
        """Parse N 45° E format."""
        result = BearingConverter.parse_quadrant_bearing("N 45° E")
        assert result == ("N", 45.0, "E")

    def test_parse_with_minutes(self):
        """Parse N 45°30' E format."""
        result = BearingConverter.parse_quadrant_bearing("N 45°30' E")
        c1, deg, c2 = result
        assert c1 == "N"
        assert math.isclose(deg, 45.5, abs_tol=0.000001)  # 45 + 30/60 = 45.5
        assert c2 == "E"

    def test_parse_with_seconds(self):
        """Parse N 45°30'15\" E format."""
        result = BearingConverter.parse_quadrant_bearing('N 45°30\'15" E')
        c1, deg, c2 = result
        assert c1 == "N"
        assert math.isclose(deg, 45.504167, abs_tol=0.000001)  # 45 + 30/60 + 15/3600
        assert c2 == "E"

    def test_parse_all_quadrants(self):
        """Parse all four quadrants."""
        assert BearingConverter.parse_quadrant_bearing("N 33°20' E")[0] == "N"
        assert BearingConverter.parse_quadrant_bearing("S 56°40' W")[0] == "S"
        assert BearingConverter.parse_quadrant_bearing("S 45° E")[0] == "S"
        assert BearingConverter.parse_quadrant_bearing("N 90° W")[0] == "N"

    def test_parse_no_minutes(self):
        """Parse bearing with no minutes/seconds."""
        result = BearingConverter.parse_quadrant_bearing("S 45° W")
        assert result == ("S", 45.0, "W")

    def test_parse_invalid_format(self):
        """Return None for invalid formats."""
        assert BearingConverter.parse_quadrant_bearing("North 45 East") is None
        assert BearingConverter.parse_quadrant_bearing("southwesterly") is None
        assert BearingConverter.parse_quadrant_bearing("") is None


class TestQuadrantToAzimuth:
    """Test quadrant bearing to azimuth conversion."""

    def test_ne_quadrant(self):
        """N θ E → azimuth = θ."""
        azimuth = BearingConverter.quadrant_to_azimuth("N", 45.0, "E")
        assert azimuth == 45.0

        azimuth = BearingConverter.quadrant_to_azimuth("N", 33.333333, "E")
        assert math.isclose(azimuth, 33.333333, abs_tol=0.000001)

    def test_se_quadrant(self):
        """S θ E → azimuth = 180 - θ."""
        azimuth = BearingConverter.quadrant_to_azimuth("S", 45.0, "E")
        assert azimuth == 135.0

        azimuth = BearingConverter.quadrant_to_azimuth("S", 56.666667, "E")
        assert math.isclose(azimuth, 123.333333, abs_tol=0.000001)

    def test_sw_quadrant(self):
        """S θ W → azimuth = 180 + θ."""
        azimuth = BearingConverter.quadrant_to_azimuth("S", 45.0, "W")
        assert azimuth == 225.0

        azimuth = BearingConverter.quadrant_to_azimuth("S", 56.666667, "W")
        assert math.isclose(azimuth, 236.666667, abs_tol=0.000001)

    def test_nw_quadrant(self):
        """N θ W → azimuth = 360 - θ."""
        azimuth = BearingConverter.quadrant_to_azimuth("N", 45.0, "W")
        assert azimuth == 315.0

        azimuth = BearingConverter.quadrant_to_azimuth("N", 33.333333, "W")
        assert math.isclose(azimuth, 326.666667, abs_tol=0.000001)

    def test_cardinal_directions(self):
        """Test exact cardinal directions."""
        assert BearingConverter.quadrant_to_azimuth("N", 0.0, "E") == 0.0  # North
        assert BearingConverter.quadrant_to_azimuth("N", 90.0, "E") == 90.0  # East
        assert BearingConverter.quadrant_to_azimuth("S", 0.0, "E") == 180.0  # South
        assert BearingConverter.quadrant_to_azimuth("N", 90.0, "W") == 270.0  # West

    def test_modulo_360(self):
        """Azimuth should wrap around at 360°."""
        azimuth = BearingConverter.quadrant_to_azimuth("N", 0.0, "W")
        assert azimuth == 0.0  # 360 % 360 = 0


class TestDeltaCalculations:
    """Test dx, dy calculations for traverse."""

    def test_north_bearing(self):
        """0° (North) → dx=0, dy=distance."""
        dx, dy = BearingConverter.calculate_deltas(0.0, 100.0)
        assert math.isclose(dx, 0.0, abs_tol=0.000001)
        assert math.isclose(dy, 100.0, abs_tol=0.000001)

    def test_east_bearing(self):
        """90° (East) → dx=distance, dy=0."""
        dx, dy = BearingConverter.calculate_deltas(90.0, 100.0)
        assert math.isclose(dx, 100.0, abs_tol=0.000001)
        assert math.isclose(dy, 0.0, abs_tol=0.000001)

    def test_south_bearing(self):
        """180° (South) → dx=0, dy=-distance."""
        dx, dy = BearingConverter.calculate_deltas(180.0, 100.0)
        assert math.isclose(dx, 0.0, abs_tol=0.000001)
        assert math.isclose(dy, -100.0, abs_tol=0.000001)

    def test_west_bearing(self):
        """270° (West) → dx=-distance, dy=0."""
        dx, dy = BearingConverter.calculate_deltas(270.0, 100.0)
        assert math.isclose(dx, -100.0, abs_tol=0.000001)
        assert math.isclose(dy, 0.0, abs_tol=0.000001)

    def test_ne_45_degrees(self):
        """45° (NE) → dx=dy=distance/√2."""
        dx, dy = BearingConverter.calculate_deltas(45.0, 100.0)
        expected = 100.0 / math.sqrt(2)
        assert math.isclose(dx, expected, abs_tol=0.000001)
        assert math.isclose(dy, expected, abs_tol=0.000001)

    def test_real_world_bearing(self):
        """Test N 33°20' E (33.333°) for 60 ft."""
        azimuth = BearingConverter.quadrant_to_azimuth("N", 33.333333, "E")
        dx, dy = BearingConverter.calculate_deltas(azimuth, 60.0)
        # Expected: dx ≈ 32.9 ft, dy ≈ 50.2 ft
        assert math.isclose(dx, 32.9, abs_tol=0.1)
        assert math.isclose(dy, 50.2, abs_tol=0.1)


class TestCurveCalculations:
    """Test curve property calculations."""

    def test_arc_length_90_degree_curve(self):
        """L = R × Δ for 90° curve."""
        props = BearingConverter.calculate_curve_properties(100.0, delta_deg=90.0)
        expected = 100.0 * math.radians(90.0)  # ≈ 157.08 ft
        assert math.isclose(props["arc_length_ft"], expected, abs_tol=0.01)

    def test_arc_length_45_degree_curve(self):
        """L = R × Δ for 45° curve."""
        props = BearingConverter.calculate_curve_properties(100.0, delta_deg=45.0)
        expected = 100.0 * math.radians(45.0)  # ≈ 78.54 ft
        assert math.isclose(props["arc_length_ft"], expected, abs_tol=0.01)

    def test_chord_length_90_degree(self):
        """Chord = 2R × sin(Δ/2) for 90° curve."""
        props = BearingConverter.calculate_curve_properties(100.0, delta_deg=90.0)
        expected = 2 * 100.0 * math.sin(math.radians(90.0) / 2)  # ≈ 141.42 ft
        assert math.isclose(props["chord_length_ft"], expected, abs_tol=0.01)

    def test_chord_length_small_angle(self):
        """For small angles, chord ≈ arc."""
        radius = 1000.0
        delta = 1.0  # 1 degree
        props = BearingConverter.calculate_curve_properties(radius, delta_deg=delta)
        chord = props["chord_length_ft"]
        arc = props["arc_length_ft"]
        # Should be very close for small angles
        assert abs(chord - arc) < 0.01

    def test_chord_bearing_left_curve(self):
        """Chord bearing = tangent - Δ/2 for left curve."""
        chord_az = BearingConverter.calculate_chord_bearing(90.0, 90.0, "left")
        # 90° - 45° = 45°
        assert math.isclose(chord_az, 45.0, abs_tol=0.000001)

    def test_chord_bearing_right_curve(self):
        """Chord bearing = tangent + Δ/2 for right curve."""
        chord_az = BearingConverter.calculate_chord_bearing(90.0, 90.0, "right")
        # 90° + 45° = 135°
        assert math.isclose(chord_az, 135.0, abs_tol=0.000001)

    def test_chord_bearing_wraps_at_360(self):
        """Chord bearing wraps correctly at 360°."""
        chord_az = BearingConverter.calculate_chord_bearing(10.0, 40.0, "left")
        # 10° - 20° = -10° → 350°
        assert math.isclose(chord_az, 350.0, abs_tol=0.000001)


class TestCurveEndpoint:
    """Test curve endpoint calculation."""

    def test_90_degree_left_curve_from_north(self):
        """90° left curve from North (0°) ends to the left."""
        start = Point(x=0.0, y=0.0)
        tangent = 0.0  # North
        radius = 100.0
        delta = 90.0
        endpoint = BearingConverter.compute_curve_endpoint(start, tangent, radius, delta, "left")

        # Left curve from North goes counterclockwise (westward)
        # Chord bearing = 0° - 45° = 315° (NW)
        # Endpoint should be northwest of start
        assert endpoint.x < 0  # Westward component
        assert endpoint.y > 0  # Northward component

    def test_90_degree_right_curve_from_north(self):
        """90° right curve from North (0°) ends to the right."""
        start = Point(x=0.0, y=0.0)
        tangent = 0.0  # North
        radius = 100.0
        delta = 90.0
        endpoint = BearingConverter.compute_curve_endpoint(start, tangent, radius, delta, "right")

        # Right curve from North goes clockwise (eastward)
        # Chord bearing = 0° + 45° = 45° (NE)
        # Endpoint should be northeast of start
        assert endpoint.x > 0  # Eastward component
        assert endpoint.y > 0  # Northward component

    def test_180_degree_curve(self):
        """180° curve creates U-turn."""
        start = Point(x=0.0, y=0.0)
        tangent = 0.0  # North
        radius = 50.0
        delta = 180.0
        endpoint = BearingConverter.compute_curve_endpoint(start, tangent, radius, delta, "left")

        # 180° turn should reverse direction
        # Chord for 180° is straight line through center
        # Chord bearing = 0° - 90° = 270° (West)
        assert endpoint.x < 0  # Should be west of start
        assert math.isclose(endpoint.y, 0.0, abs_tol=0.1)  # Same y


class TestIntegrationQuadrantToDeltas:
    """Integration tests: quadrant bearing → azimuth → deltas."""

    def test_n33e_60ft(self):
        """N 33°20' E, 60.00 feet (from test parcel)."""
        # Parse
        parsed = BearingConverter.parse_quadrant_bearing("N 33°20' E")
        assert parsed is not None
        c1, decimal, c2 = parsed

        # Check DMS conversion
        assert math.isclose(decimal, 33.333333, abs_tol=0.000001)

        # Quadrant to azimuth
        azimuth = BearingConverter.quadrant_to_azimuth(c1, decimal, c2)
        assert math.isclose(azimuth, 33.333333, abs_tol=0.000001)

        # Calculate deltas
        dx, dy = BearingConverter.calculate_deltas(azimuth, 60.0)
        assert math.isclose(dx, 32.9, abs_tol=0.1)
        assert math.isclose(dy, 50.2, abs_tol=0.1)

    def test_s56w_125ft(self):
        """S 56°40' W, 125.00 feet (from test parcel)."""
        parsed = BearingConverter.parse_quadrant_bearing("S 56°40' W")
        assert parsed is not None
        c1, decimal, c2 = parsed

        assert math.isclose(decimal, 56.666667, abs_tol=0.000001)

        azimuth = BearingConverter.quadrant_to_azimuth(c1, decimal, c2)
        assert math.isclose(azimuth, 236.666667, abs_tol=0.000001)

        dx, dy = BearingConverter.calculate_deltas(azimuth, 125.0)
        # Expected: dx ≈ -104.5 ft, dy ≈ -68.7 ft
        assert math.isclose(dx, -104.5, abs_tol=0.1)
        assert math.isclose(dy, -68.7, abs_tol=0.1)
