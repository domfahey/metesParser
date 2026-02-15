"""Tests for call_extractor.py - Parsing deed calls."""

import math

import pytest

from metesparser.call_extractor import CallExtractor

from ..fixtures import sample_deeds


class TestBearingExtraction:
    """Test extraction of bearings from call text."""

    @pytest.mark.parametrize(
        "call_text,expected_quadrant",
        [
            # Note: extract_single_call expects already-normalized text
            # Use standardized format with ° symbol
            ("N 45° E 100 feet", "N 45°00' E"),
            ("S 56°40' W 125 feet", "S 56°40' W"),
            ("N 33°20' E 60.00 feet", "N 33°20' E"),
            ("S 00°00' W 100 feet", "S 0°00' W"),
        ],
    )
    def test_parse_quadrant_bearing(self, call_text, expected_quadrant):
        """Parse various quadrant bearing formats."""
        call = CallExtractor.extract_single_call(call_text, course=1)

        assert call is not None
        assert call.bearing_quadrant == expected_quadrant
        assert call.bearing_azimuth_deg_from_north is not None

    def test_extract_cardinal_only(self):
        """Cardinal-only bearing (e.g., 'southwesterly') should be flagged."""
        call = CallExtractor.extract_single_call("THENCE southwesterly 75 feet", course=1)

        assert call is not None
        assert call.bearing_quadrant is None
        assert call.bearing_azimuth_deg_from_north is None
        assert call.notes == "incomplete bearing - cardinal only"

    def test_meander_flagged(self):
        """Meander calls should be flagged as incomplete."""
        call = CallExtractor.extract_single_call(
            "THENCE meandering along the stream 150 feet", course=1
        )

        assert call is not None
        assert call.bearing_azimuth_deg_from_north is None
        assert "meander" in call.notes.lower()


class TestDistanceExtraction:
    """Test extraction of distances with various units."""

    @pytest.mark.parametrize(
        "call_text,expected_ft",
        [
            ("THENCE North 45 degrees East 100 feet", 100.0),
            ("THENCE North 45 degrees East 100.50 feet", 100.5),
            ("THENCE North 45 degrees East 10 poles", 165.0),  # 10 poles = 165 ft
            ("THENCE North 45 degrees East 1 chain", 66.0),  # 1 chain = 66 ft
        ],
    )
    def test_parse_distance_with_units(self, call_text, expected_ft):
        """Parse distance with various units."""
        call = CallExtractor.extract_single_call(call_text, course=1)

        assert call is not None
        assert math.isclose(call.distance_ft, expected_ft, abs_tol=0.01)

    def test_distance_from_alternate_format(self):
        """Parse distance in alternate format (e.g., '125.26 feet along...')."""
        # This tests distance extraction without bearing present
        call = CallExtractor.extract_single_call(
            "N 45° E 125.26 feet along the division line", course=1
        )

        assert call is not None
        assert math.isclose(call.distance_ft, 125.26, abs_tol=0.01)
        assert call.along is not None
        assert "division line" in call.along.lower()


class TestCurveExtraction:
    """Test extraction of curve information."""

    def test_curve_without_bearing_preserved(self):
        """Curve lacking a quadrant bearing should still produce a call."""
        call_text = (
            "along a curve to the right having a radius of 50.00 feet "
            "and an arc length of 78.54 feet to an iron pin"
        )
        call = CallExtractor.extract_single_call(call_text, course=1)

        assert call is not None
        assert call.direction_text.startswith("along a curve")
        assert call.bearing_quadrant is None
        assert math.isclose(call.distance_ft, 78.54, abs_tol=0.01)
        assert call.arc_length_ft is not None
        assert call.radius_ft is not None
        assert math.isclose(call.arc_length_ft, 78.54, abs_tol=0.01)
        assert math.isclose(call.radius_ft, 50.0, abs_tol=0.01)
        assert call.to == "an iron pin"
        assert call.along.startswith("a curve to the right")
        assert call.notes == "incomplete bearing"

    def test_curve_without_arc_length_uses_computed_value(self):
        """When only radius and delta are supplied, compute the arc length."""
        call_text = (
            "along a curve to the left having a radius of 100.00 feet "
            "and a delta angle of 45°00' to a point"
        )
        call = CallExtractor.extract_single_call(call_text, course=1)

        assert call is not None
        expected_arc = 100.0 * math.radians(45.0)
        assert math.isclose(call.distance_ft, expected_arc, abs_tol=0.01)
        assert call.arc_length_ft is not None
        assert math.isclose(call.arc_length_ft, expected_arc, abs_tol=0.01)
        assert call.notes == "incomplete bearing"

    @pytest.mark.curve
    def test_curve_with_full_properties(self):
        """Extract curve with radius, delta, and arc length."""
        call_text = (
            "THENCE along a curve to the right having a radius of 50 feet, "
            "a delta angle of 90 degrees 00 minutes, and an arc length of 78.54 feet"
        )
        call = CallExtractor.extract_single_call(call_text, course=1)

        assert call is not None
        assert call.curve_dir == "right"
        assert call.radius_ft is not None
        assert call.delta_deg is not None
        assert call.arc_length_ft is not None
        assert math.isclose(call.radius_ft, 50.0, abs_tol=0.1)
        assert math.isclose(call.delta_deg, 90.0, abs_tol=0.1)
        assert math.isclose(call.arc_length_ft, 78.54, abs_tol=0.1)


class TestAlongToFields:
    """Test extraction of 'along' and 'to' descriptive fields."""

    def test_extract_along_field(self):
        """Extract 'along' description."""
        call = CallExtractor.extract_single_call(
            "THENCE North 45 degrees East 100 feet along the division line", course=1
        )

        assert call is not None
        assert "division line" in call.along.lower()

    def test_extract_to_field(self):
        """Extract 'to' description."""
        call = CallExtractor.extract_single_call(
            "THENCE North 45 degrees East 100 feet to an iron pin", course=1
        )

        assert call is not None
        assert "iron pin" in call.to.lower()

    def test_extract_along_and_to(self):
        """Extract both 'along' and 'to' fields."""
        call = CallExtractor.extract_single_call(
            "THENCE North 45 degrees East 100 feet along the north line to a point",
            course=1,
        )

        assert call is not None
        assert "north line" in call.along.lower()
        assert "point" in call.to.lower()


class TestCallExtraction:
    """Test extraction of complete call lists from legal descriptions."""

    def test_extract_from_square(self, sample_legal_text):
        """Extract calls from simple square."""
        calls = CallExtractor.extract_calls(sample_deeds.SQUARE_100FT)

        assert len(calls) == 4
        # All should have complete bearings
        for call in calls:
            assert call.bearing_azimuth_deg_from_north is not None
            assert call.distance_ft == 100.0

    def test_extract_from_pennbrook_18(self):
        """Extract calls from 18 Pennbrook parcel."""
        calls = CallExtractor.extract_calls(sample_deeds.PENNBROOK_18)

        assert len(calls) == 4
        # Check first call
        assert calls[0].bearing_azimuth_deg_from_north is not None
        assert math.isclose(calls[0].bearing_azimuth_deg_from_north, 146.666667, abs_tol=0.01)
        assert math.isclose(calls[0].distance_ft, 60.0, abs_tol=0.01)

    def test_skip_pob_lines(self):
        """POB/BEGINNING lines should not create calls."""
        text = "BEGINNING at a point. THENCE North 45 degrees East 100 feet."
        calls = CallExtractor.extract_calls(text)

        # Should have 1 call (the THENCE), not 2
        assert len(calls) == 1
        assert calls[0].course == 1

    def test_enrich_with_azimuths(self, deed_call_factory):
        """Enrich calls with azimuths from quadrant bearings."""
        calls = [
            deed_call_factory(bearing_quadrant="N 45°00' E", bearing_azimuth_deg_from_north=None)
        ]

        enriched = CallExtractor.enrich_calls_with_azimuths(calls)

        assert enriched[0].bearing_azimuth_deg_from_north is not None
        assert math.isclose(enriched[0].bearing_azimuth_deg_from_north, 45.0, abs_tol=0.01)


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_text(self):
        """Empty text should return empty list."""
        calls = CallExtractor.extract_calls("")

        assert len(calls) == 0

    def test_no_thence_calls(self):
        """Text with no THENCE should return empty list."""
        calls = CallExtractor.extract_calls(sample_deeds.NO_THENCE)

        assert len(calls) == 0

    def test_invalid_bearing(self):
        """Invalid bearing (degrees > 90) should be handled gracefully."""
        calls = CallExtractor.extract_calls(sample_deeds.INVALID_BEARING)

        # Should not crash; malformed first call should be preserved as incomplete,
        # and later bearing should still parse.
        assert len(calls) == 2
        assert calls[0].course == 1
        assert calls[0].bearing_azimuth_deg_from_north is None
        assert calls[0].notes is not None and "incomplete" in calls[0].notes.lower()
        assert calls[-1].bearing_azimuth_deg_from_north is not None
        assert math.isclose(calls[-1].bearing_azimuth_deg_from_north, 225.0, abs_tol=0.01)
        assert math.isclose(calls[-1].distance_ft, 100.0, abs_tol=0.01)

    def test_with_ocr_errors(self):
        """Text with OCR errors should be corrected during normalization."""
        # The normalizer should fix "5outh" → "South", "0" → "°", etc.
        calls = CallExtractor.extract_calls(sample_deeds.WITH_OCR_ERRORS)

        # Should successfully parse despite OCR errors
        assert len(calls) == 2
        assert all(c.bearing_azimuth_deg_from_north is not None for c in calls)
