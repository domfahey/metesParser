"""Tests for call_extractor.py - Rule-based call parsing."""

import pytest

from metesparser.call_extractor import CallExtractor
from metesparser.models import DeedCall


class TestExtractDirection:
    """Test direction/bearing extraction from call text."""

    def test_extract_quadrant_bearing(self):
        """Extract quadrant bearing: N 45° E."""
        direction = CallExtractor.extract_direction("N 45° E 100 feet")
        assert "N 45° E" in direction or "N 45°" in direction

    def test_extract_bearing_with_minutes(self):
        """Extract bearing with minutes: N 33°20' E."""
        direction = CallExtractor.extract_direction("N 33°20' E 60 feet")
        assert "N 33°20' E" in direction or "N 33°" in direction

    def test_extract_cardinal_only(self):
        """Extract cardinal-only direction."""
        direction = CallExtractor.extract_direction("northerly 50 feet")
        assert "northerly" in direction.lower()

    def test_extract_southwesterly(self):
        """Extract 'southwesterly'."""
        direction = CallExtractor.extract_direction("southwesterly along the creek")
        assert "southwesterly" in direction.lower()

    def test_no_direction(self):
        """Return empty string when no direction found."""
        direction = CallExtractor.extract_direction("along the boundary")
        assert direction == ""


class TestExtractDistanceAlternate:
    """Test alternate distance extraction patterns."""

    def test_extract_feet_word(self):
        """Extract distance with 'feet' word: 100 feet."""
        distance = CallExtractor.extract_distance_alternate("100 feet along the line")
        assert distance == 100.0

    def test_extract_with_decimal(self):
        """Extract distance with decimal: 125.26 feet."""
        distance = CallExtractor.extract_distance_alternate("125.26 feet to a point")
        assert distance == 125.26

    def test_extract_with_ft(self):
        """Extract distance with 'ft' abbreviation: 60 ft."""
        distance = CallExtractor.extract_distance_alternate("60 ft along boundary")
        assert distance == 60.0

    def test_no_distance(self):
        """Return 0.0 when no distance found."""
        distance = CallExtractor.extract_distance_alternate("along the boundary")
        assert distance == 0.0


class TestExtractCurveInfo:
    """Test curve information extraction."""

    def test_extract_curve_right(self):
        """Extract right curve properties."""
        text = "curve to the right, radius of 100 feet, delta angle of 45°30', arc length of 79.54 feet"
        curve_info = CallExtractor.extract_curve_info(text)

        assert curve_info.get("direction") == "right"
        assert curve_info.get("radius_ft") == 100.0
        assert curve_info.get("delta_deg") == pytest.approx(45.5, abs=0.01)
        assert curve_info.get("arc_length_ft") == 79.54

    def test_extract_curve_left(self):
        """Extract left curve properties."""
        text = "curve to the left, radius of 50 feet, delta 90°"
        curve_info = CallExtractor.extract_curve_info(text)

        assert curve_info.get("direction") == "left"
        assert curve_info.get("radius_ft") == 50.0
        assert curve_info.get("delta_deg") == 90.0

    def test_no_curve(self):
        """Return empty dict when no curve."""
        text = "N 45° E 100 feet"
        curve_info = CallExtractor.extract_curve_info(text)

        assert curve_info == {}


class TestExtractSingleCall:
    """Test extracting a single call."""

    def test_extract_straight_line(self):
        """Extract straight line call: N 33°20' E 60 feet."""
        call_text = "N 33°20' E 60.00 feet along the SW line to a point"
        call = CallExtractor.extract_single_call(call_text, course=1)

        assert call is not None
        assert call.course == 1
        assert call.bearing_quadrant is not None
        assert "N 33°20' E" in call.bearing_quadrant or "N 33°" in call.bearing_quadrant
        assert call.bearing_azimuth_deg_from_north == pytest.approx(33.333333, abs=0.01)
        assert call.distance_ft == pytest.approx(60.0, abs=0.01)
        assert call.curve_dir is None

    def test_extract_incomplete_bearing(self):
        """Extract call with incomplete bearing (cardinal only)."""
        call_text = "northerly 50 feet"
        call = CallExtractor.extract_single_call(call_text, course=3)

        assert call is not None
        assert call.course == 3
        assert call.bearing_azimuth_deg_from_north is None
        assert "incomplete" in call.notes.lower() or "cardinal" in call.notes.lower()
        assert call.distance_ft == pytest.approx(50.0, abs=0.01)

    def test_extract_meander(self):
        """Extract meander call with cardinal direction."""
        call_text = "meander southwesterly 125 feet"
        call = CallExtractor.extract_single_call(call_text, course=4)

        assert call is not None
        assert call.course == 4
        assert "meander" in call.notes.lower()
        assert call.bearing_azimuth_deg_from_north is None  # No precise bearing


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
        assert all(isinstance(c, DeedCall) for c in calls)
        assert calls[0].course == 1
        assert calls[1].course == 2
        assert calls[2].course == 3

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
                bearing_azimuth_deg_from_north=None,
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

        assert enriched[0].bearing_azimuth_deg_from_north == pytest.approx(33.333333, abs=0.01)
        assert enriched[1].bearing_azimuth_deg_from_north == pytest.approx(236.666667, abs=0.01)

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
        assert enriched[0].bearing_azimuth_deg_from_north is None


class TestNeverFabricatesBearings:
    """Critical test: ensure we never fabricate missing bearings."""

    def test_southwesterly_no_fabrication(self):
        """'southwesterly' should not fabricate S 45° W."""
        call_text = "southwesterly 100 feet"
        call = CallExtractor.extract_single_call(call_text, course=1)

        assert call is not None
        assert call.bearing_azimuth_deg_from_north is None
        assert "incomplete" in call.notes.lower()

    def test_westerly_no_fabrication(self):
        """'westerly' should not fabricate 270°."""
        call_text = "westerly along the creek 75 feet"
        call = CallExtractor.extract_single_call(call_text, course=1)

        assert call is not None
        assert call.bearing_azimuth_deg_from_north is None
        assert "incomplete" in call.notes.lower()

    def test_meander_no_fabrication(self):
        """'meander' with direction should not fabricate precise bearing."""
        call_text = "meander westerly 50 feet"
        call = CallExtractor.extract_single_call(call_text, course=1)

        assert call is not None
        assert call.bearing_azimuth_deg_from_north is None
        assert "meander" in call.notes.lower()


class TestRealWorldCalls:
    """Test real-world deed call examples."""

    def test_18_pennbrook_call_1(self):
        """Parse: N 33°20' E 60.00 feet."""
        call_text = "N 33°20' E 60.00 feet to a point in division line"
        call = CallExtractor.extract_single_call(call_text, course=1)

        assert call is not None
        assert "N 33°20' E" in call.bearing_quadrant or "N 33°" in call.bearing_quadrant
        assert call.bearing_azimuth_deg_from_north == pytest.approx(33.333333, abs=0.01)
        assert call.distance_ft == pytest.approx(60.0, abs=0.01)

    def test_18_pennbrook_call_2(self):
        """Parse: S 56°40' W 125.00 feet."""
        call_text = "S 56°40' W 125.00 feet along division line to corner of Lot 50"
        call = CallExtractor.extract_single_call(call_text, course=2)

        assert call is not None
        assert "S 56°40' W" in call.bearing_quadrant or "S 56°" in call.bearing_quadrant
        assert call.bearing_azimuth_deg_from_north == pytest.approx(236.666667, abs=0.01)
        assert call.distance_ft == pytest.approx(125.0, abs=0.01)


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_call_text(self):
        """Handle empty call text gracefully."""
        call = CallExtractor.extract_single_call("", course=1)
        assert call is None

    def test_whitespace_only(self):
        """Handle whitespace-only call text."""
        call = CallExtractor.extract_single_call("   \n\t  ", course=1)
        assert call is None

    def test_no_direction(self):
        """Handle call with no direction."""
        call_text = "100 feet along the boundary"
        call = CallExtractor.extract_single_call(call_text, course=1)
        assert call is None
