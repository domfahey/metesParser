"""Tests for Phase 5 Step 9: Spiral Curves + State Plane Metadata."""

from __future__ import annotations

from metesparser.call_extractor import CallExtractor
from metesparser.text_parser import TextParser


class TestSpiralCurveDetection:
    """Tests for spiral (transition) curve detection."""

    def test_spiral_keyword_detected(self) -> None:
        text = "along a spiral curve to the right having a radius of 500 feet, delta of 15\u00b0, arc length of 130.90 feet"
        info = CallExtractor.extract_curve_info(text)
        assert info.get("curve_type") == "spiral"

    def test_transition_curve_detected(self) -> None:
        text = "along a transition curve to the left, radius 800 feet, delta 10\u00b0, arc distance of 139.63 feet"
        info = CallExtractor.extract_curve_info(text)
        assert info.get("curve_type") == "spiral"

    def test_regular_curve_not_spiral(self) -> None:
        text = "along a curve to the right having a radius of 500 feet, delta of 30\u00b0"
        info = CallExtractor.extract_curve_info(text)
        assert info.get("curve_type") != "spiral"


class TestStatePlaneMetadata:
    """Tests for State Plane coordinate system metadata extraction."""

    def test_extract_full_state_plane(self) -> None:
        text = "State Plane Coordinate System, Texas South Central Zone, FIPS 4204, NAD 83"
        system, fips = TextParser.extract_coordinate_system(text)
        assert system is not None
        assert "Texas South Central" in system
        assert fips == "4204"

    def test_extract_state_plane_no_fips(self) -> None:
        text = "Based on the Pennsylvania State Plane Coordinate System, South Zone"
        system, fips = TextParser.extract_coordinate_system(text)
        assert system is not None
        assert "Pennsylvania" in system or "South Zone" in system
        assert fips is None

    def test_extract_fips_code_only(self) -> None:
        text = "Coordinates referenced to FIPS Zone 3200, NAD 83"
        system, fips = TextParser.extract_coordinate_system(text)
        assert fips == "3200"

    def test_no_coordinate_system(self) -> None:
        text = "BEGINNING at an iron pin, thence N 45\u00b0 E 100 feet"
        system, fips = TextParser.extract_coordinate_system(text)
        assert system is None
        assert fips is None

    def test_extract_nad_83_reference(self) -> None:
        text = "All coordinates based on NAD 83, State Plane Coordinate System, Florida East Zone, FIPS 0901"
        system, fips = TextParser.extract_coordinate_system(text)
        assert system is not None
        assert fips == "0901"
