"""Tests for call_extractor.py - Rule-based call parsing."""

import pytest

from metesparser.call_extractor import CallExtractor
from metesparser.models import DeedCall


class TestExtractBearing:
    """Test bearing extraction from call text."""

    def test_extract_quadrant_bearing(self):
        """Extract quadrant bearing: N 45° E."""
        bearing, notes = CallExtractor.extract_bearing("N 45° E 100 feet")
        assert bearing == "N 45° E"
        assert notes == ""

    def test_extract_bearing_with_minutes(self):
        """Extract bearing with minutes: N 33°20' E."""
        bearing, notes = CallExtractor.extract_bearing("N 33°20' E 60 feet")
        assert bearing == "N 33°20' E"
        assert notes == ""

    def test_extract_bearing_with_seconds(self):
        """Extract bearing with seconds: S 45°30'15\" W."""
        bearing, notes = CallExtractor.extract_bearing('S 45°30\'15" W 100 feet')
        assert 'S 45°30\'15" W' in bearing
        assert notes == ""

    def test_cardinal_only_northerly(self):
        """Cardinal-only 'northerly' flagged as incomplete."""
        bearing, notes = CallExtractor.extract_bearing("northerly 50 feet")
        assert bearing is None or bearing == ""
        assert "incomplete" in notes.lower() or "cardinal" in notes.lower()

    def test_cardinal_only_southwesterly(self):
        """Cardinal-only 'southwesterly' flagged as incomplete."""
        bearing, notes = CallExtractor.extract_bearing("southwesterly along the creek")
        assert bearing is None or bearing == ""
        assert "incomplete" in notes.lower() or "cardinal" in notes.lower()

    def test_meander_flagged(self):
        """'meander' flagged as incomplete."""
        bearing, notes = CallExtractor.extract_bearing("meander along the stream")
        assert bearing is None or bearing == ""
        assert "meander" in notes.lower() or "incomplete" in notes.lower()


class TestExtractDistance:
    """Test distance extraction from call text."""

    def test_extract_feet(self):
        """Extract distance in feet."""
        distance = CallExtractor.extract_distance("N 45° E 100.50 feet")
        assert distance == 100.50

    def test_extract_poles(self):
        """Extract distance in poles (convert to feet)."""
        distance = CallExtractor.extract_distance("N 45° E 10 poles")
        # 10 poles × 16.5 = 165 feet
        assert distance == 165.0

    def test_extract_rods(self):
        """Extract distance in rods (convert to feet)."""
        distance = CallExtractor.extract_distance("N 45° E 5 rods")
        # 5 rods × 16.5 = 82.5 feet
        assert distance == 82.5

    def test_extract_chains(self):
        """Extract distance in chains (convert to feet)."""
        distance = CallExtractor.extract_distance("N 45° E 2 chains")
        # 2 chains × 66 = 132 feet
        assert distance == 132.0

    def test_no_distance(self):
        """Return 0.0 when no distance found."""
        distance = CallExtractor.extract_distance("along the boundary")
        assert distance == 0.0


class TestExtractCurveProperties:
    """Test curve property extraction."""

    def test_extract_curve_right(self):
        """Extract right curve properties."""
        text = "curve to the right, radius 100 feet, delta 45°30', arc 79.54 feet"
        curve_dir, radius, delta, arc = CallExtractor.extract_curve_properties(text)

        assert curve_dir == "right"
        assert radius == 100.0
        assert delta == 45.5  # 45°30' = 45.5°
        assert arc == 79.54

    def test_extract_curve_left(self):
        """Extract left curve properties."""
        text = "curve to the left, R=50.0, D=90°"
        curve_dir, radius, delta, arc = CallExtractor.extract_curve_properties(text)

        assert curve_dir == "left"
        assert radius == 50.0
        assert delta == 90.0

    def test_extract_radius_variants(self):
        """Extract radius from various notations."""
        # "radius 100 feet"
        text1 = "radius 100.5 feet"
        _, r1, _, _ = CallExtractor.extract_curve_properties(text1)
        assert r1 == 100.5

        # "R=100"
        text2 = "R=100"
        _, r2, _, _ = CallExtractor.extract_curve_properties(text2)
        assert r2 == 100.0

        # "R 100"
        text3 = "R 100"
        _, r3, _, _ = CallExtractor.extract_curve_properties(text3)
        assert r3 == 100.0

    def test_extract_delta_variants(self):
        """Extract delta from various notations."""
        # "delta 45°30'"
        text1 = "delta 45°30'"
        _, _, d1, _ = CallExtractor.extract_curve_properties(text1)
        assert d1 == 45.5

        # "D=90"
        text2 = "D=90"
        _, _, d2, _ = CallExtractor.extract_curve_properties(text2)
        assert d2 == 90.0

    def test_no_curve(self):
        """Return None values when no curve."""
        text = "N 45° E 100 feet"
        curve_dir, radius, delta, arc = CallExtractor.extract_curve_properties(text)

        assert curve_dir is None
        assert radius is None
        assert delta is None
        assert arc is None


class TestParseCall:
    """Test full call parsing."""

    def test_parse_straight_line(self):
        """Parse straight line call: N 33°20' E 60 feet."""
        call_text = "N 33°20' E 60.00 feet along the SW line to a point"
        call = CallExtractor.parse_call(1, call_text)

        assert call.course == 1
        assert call.bearing_quadrant == "N 33°20' E"
        assert call.bearing_azimuth_deg_from_north == pytest.approx(33.333333, abs=0.000001)
        assert call.distance_ft == 60.0
        assert call.curve_dir is None
        assert "SW line" in call.along
        assert "point" in call.to

    def test_parse_curve_call(self):
        """Parse curve call with radius and delta."""
        call_text = "curve to the right, radius 100 feet, delta 45°, arc 78.54 feet"
        call = CallExtractor.parse_call(2, call_text)

        assert call.course == 2
        assert call.curve_dir == "right"
        assert call.radius_ft == 100.0
        assert call.delta_deg == 45.0
        assert call.arc_length_ft == 78.54

    def test_parse_incomplete_bearing(self):
        """Parse call with incomplete bearing (cardinal only)."""
        call_text = "northerly 50 feet"
        call = CallExtractor.parse_call(3, call_text)

        assert call.course == 3
        assert call.bearing_azimuth_deg_from_north is None
        assert "incomplete" in call.notes.lower()
        assert call.distance_ft == 50.0

    def test_parse_meander(self):
        """Parse meander call (no bearing)."""
        call_text = "meander along the creek 125 feet"
        call = CallExtractor.parse_call(4, call_text)

        assert call.course == 4
        assert call.bearing_azimuth_deg_from_north is None
        assert "meander" in call.notes.lower()


class TestExtractCalls:
    """Test extracting multiple calls from text."""

    def test_extract_multiple_calls(self):
        """Extract multiple THENCE calls."""
        text = """
        THENCE N 33°20' E 60 feet to a point
        THENCE S 56°40' W 125 feet along the line
        THENCE S 33°20' W 60 feet
        """
        calls = CallExtractor.extract_calls(text)

        assert len(calls) == 3
        assert calls[0].bearing_quadrant == "N 33°20' E"
        assert calls[1].bearing_quadrant == "S 56°40' W"
        assert calls[2].bearing_quadrant == "S 33°20' W"

    def test_extract_with_pob(self):
        """Extract calls ignoring POB line."""
        text = """
        BEGINNING at a point
        THENCE N 45° E 100 feet
        THENCE S 45° E 100 feet
        """
        calls = CallExtractor.extract_calls(text)

        # Should not create a call for BEGINNING line
        assert len(calls) == 2
        assert calls[0].bearing_quadrant == "N 45° E"

    def test_sequential_course_numbers(self):
        """Course numbers should be sequential starting at 1."""
        text = """
        THENCE N 45° E 100 feet
        THENCE S 45° E 100 feet
        THENCE S 45° W 100 feet
        """
        calls = CallExtractor.extract_calls(text)

        assert calls[0].course == 1
        assert calls[1].course == 2
        assert calls[2].course == 3


class TestEnrichCallsWithAzimuths:
    """Test azimuth enrichment of calls."""

    def test_enrich_with_azimuths(self):
        """Enrich calls with computed azimuths."""
        calls = [
            DeedCall(
                course=1,
                direction_text="N 33°20' E 60 feet",
                bearing_quadrant="N 33°20' E",
                bearing_azimuth_deg_from_north=None,  # Not set yet
                distance_ft=60.0,
            ),
            DeedCall(
                course=2,
                direction_text="S 56°40' W 125 feet",
                bearing_quadrant="S 56°40' W",
                bearing_azimuth_deg_from_north=None,
                distance_ft=125.0,
            ),
        ]

        enriched = CallExtractor.enrich_calls_with_azimuths(calls)

        # N 33°20' E → azimuth ≈ 33.333°
        assert enriched[0].bearing_azimuth_deg_from_north == pytest.approx(33.333333, abs=0.000001)

        # S 56°40' W → azimuth ≈ 236.667°
        assert enriched[1].bearing_azimuth_deg_from_north == pytest.approx(236.666667, abs=0.000001)

    def test_enrich_skips_incomplete_bearings(self):
        """Enrich skips calls with no bearing."""
        calls = [
            DeedCall(
                course=1,
                direction_text="northerly",
                bearing_quadrant=None,
                bearing_azimuth_deg_from_north=None,
                distance_ft=50.0,
                notes="incomplete bearing",
            )
        ]

        enriched = CallExtractor.enrich_calls_with_azimuths(calls)

        # Should remain None
        assert enriched[0].bearing_azimuth_deg_from_north is None


class TestNeverFabricatesBearings:
    """Critical test: ensure we never fabricate missing bearings."""

    def test_southwesterly_returns_none(self):
        """'southwesterly' should return None, not fabricate S 45° W."""
        bearing, notes = CallExtractor.extract_bearing("southwesterly 100 feet")

        assert bearing is None or bearing == ""
        assert "incomplete" in notes.lower()

    def test_westerly_returns_none(self):
        """'westerly' should return None, not fabricate 270°."""
        bearing, notes = CallExtractor.extract_bearing("westerly along the creek")

        assert bearing is None or bearing == ""
        assert "incomplete" in notes.lower()

    def test_meander_returns_none(self):
        """'meander' should return None, never fabricate."""
        bearing, notes = CallExtractor.extract_bearing("meander 50 feet")

        assert bearing is None or bearing == ""
        assert "meander" in notes.lower() or "incomplete" in notes.lower()

    def test_incomplete_call_flagged(self):
        """Incomplete calls should be flagged in notes."""
        call = CallExtractor.parse_call(1, "northeasterly to a point")

        assert call.bearing_azimuth_deg_from_north is None
        assert call.notes is not None
        assert len(call.notes) > 0


class TestRealWorldCalls:
    """Test real-world deed call examples."""

    def test_18_pennbrook_call_1(self):
        """Parse: N 33°20' E 60.00 feet."""
        call = CallExtractor.parse_call(1, "N 33°20' E 60.00 feet to a point in division line")

        assert call.bearing_quadrant == "N 33°20' E"
        assert call.bearing_azimuth_deg_from_north == pytest.approx(33.333333, abs=0.000001)
        assert call.distance_ft == 60.0
        assert "division line" in call.to

    def test_18_pennbrook_call_2(self):
        """Parse: S 56°40' W 125.00 feet."""
        call = CallExtractor.parse_call(
            2, "S 56°40' W 125.00 feet along division line to corner of Lot 50"
        )

        assert call.bearing_quadrant == "S 56°40' W"
        assert call.bearing_azimuth_deg_from_north == pytest.approx(236.666667, abs=0.000001)
        assert call.distance_ft == 125.0
        assert "division line" in call.along
        assert "corner of Lot 50" in call.to

    def test_curve_with_chord(self):
        """Parse curve call with chord bearing."""
        call_text = "along a curve to the right, radius 50.00 feet, delta 45°30', arc 39.77 feet, chord bearing N 22°45' E, chord 38.27 feet"
        call = CallExtractor.parse_call(3, call_text)

        assert call.curve_dir == "right"
        assert call.radius_ft == 50.0
        assert call.delta_deg == 45.5
        assert call.arc_length_ft == 39.77
        # Chord bearing should be parsed
        assert call.chord_bearing is not None
        assert call.chord_length_ft == 38.27


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_call_text(self):
        """Handle empty call text gracefully."""
        call = CallExtractor.parse_call(1, "")

        assert call.course == 1
        assert call.distance_ft == 0.0

    def test_whitespace_only(self):
        """Handle whitespace-only call text."""
        call = CallExtractor.parse_call(1, "   \n\t  ")

        assert call.course == 1
        assert call.distance_ft == 0.0

    def test_malformed_bearing(self):
        """Handle malformed bearing notation."""
        call = CallExtractor.parse_call(1, "N 999° E 100 feet")

        # Should still attempt to parse (may succeed or fail based on implementation)
        assert call.distance_ft == 100.0

    def test_negative_distance(self):
        """Handle negative distance (unusual but possible in text)."""
        # Most regex won't match negative, so should default to 0.0
        distance = CallExtractor.extract_distance("N 45° E -50 feet")
        assert distance >= 0.0  # Should not be negative

    def test_very_long_call_text(self):
        """Handle very long call text with lots of description."""
        long_text = "N 45° E 100 feet " + "along the boundary " * 50 + "to a point"
        call = CallExtractor.parse_call(1, long_text)

        assert call.bearing_quadrant == "N 45° E"
        assert call.distance_ft == 100.0
        assert "boundary" in call.along
