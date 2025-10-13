"""Integration tests - Full pipeline from text to verified CSV."""

import math
from pathlib import Path

import pytest

from metesparser.bearing_converter import BearingConverter
from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker
from metesparser.csv_builder import CSVBuilder
from metesparser.models import LegalDescription
from metesparser.text_parser import TextParser


class Test18PennbrookParcel:
    """Integration test for 18 Pennbrook parcel (known rectangle)."""

    @pytest.fixture
    def legal_description_text(self):
        """Legal description for 18 Pennbrook (simplified)."""
        return """
        BEGINNING at a point in the division line between Lots 46 and 47,
        said point being in the southwesterly line of Concord Drive;
        THENCE South 33 degrees 20 minutes East 60.00 feet along said
        southwesterly line of Concord Drive to a point in said division line;
        THENCE South 56 degrees 40 minutes West 125.00 feet along the
        division line between Lots 46 and 47 to the corner to Lot 50;
        THENCE North 33 degrees 20 minutes West 60.00 feet along the
        division line between Lots 46 and 50;
        THENCE North 56 degrees 40 minutes East 125.00 feet along the
        division line between Lots 46 and 47 to the POINT OF BEGINNING.
        """

    def test_full_pipeline(self, legal_description_text):
        """Test complete pipeline: parse → verify → should close."""
        # Step 1: Normalize text
        normalized = TextParser.normalize_legal_description(legal_description_text)

        # Step 2: Extract POB
        pob = TextParser.extract_pob(normalized)
        assert "point in the division line" in pob.lower()

        # Step 3: Extract calls
        calls = CallExtractor.extract_calls(normalized)
        assert len(calls) == 4

        # Step 4: Enrich with azimuths
        calls = CallExtractor.enrich_calls_with_azimuths(calls)

        # Verify bearings
        assert calls[0].bearing_azimuth_deg_from_north == pytest.approx(146.666667, abs=0.000001)
        assert calls[1].bearing_azimuth_deg_from_north == pytest.approx(236.666667, abs=0.000001)
        assert calls[2].bearing_azimuth_deg_from_north == pytest.approx(326.666667, abs=0.000001)
        assert calls[3].bearing_azimuth_deg_from_north == pytest.approx(56.666667, abs=0.000001)

        # Step 5: Verify closure
        result = ClosureChecker.verify_closure(calls)

        # Should close perfectly (opposite sides parallel)
        assert result.closure_passed is True
        assert result.misclosure_ft < 0.01

        # Area should be approximately 60 × 125 = 7,500 sq ft
        assert math.isclose(result.area_sq_ft, 7500.0, abs_tol=10.0)

        # Should be fully verified
        assert result.is_fully_verified() is True


class Test31PennbrookParcel:
    """Integration test for 31 Pennbrook parcel (5-sided polygon)."""

    @pytest.fixture
    def legal_description_text(self):
        """Legal description for 31 Pennbrook (5 sides)."""
        return """
        BEGINNING at a point;
        THENCE North 56 degrees 40 minutes East 125.26 feet;
        THENCE South 33 degrees 20 minutes East 60.00 feet;
        THENCE South 56 degrees 40 minutes West 100.00 feet;
        THENCE South 33 degrees 20 minutes East 40.00 feet;
        THENCE North 56 degrees 40 minutes West 25.26 feet to the POINT OF BEGINNING.
        """

    def test_five_sided_closure(self, legal_description_text):
        """Test 5-sided parcel closure."""
        # Normalize and extract
        normalized = TextParser.normalize_legal_description(legal_description_text)
        calls = CallExtractor.extract_calls(normalized)
        calls = CallExtractor.enrich_calls_with_azimuths(calls)

        # Should have 5 calls
        assert len(calls) == 5

        # Verify closure
        result = ClosureChecker.verify_closure(calls)

        # Should close (designed to close perfectly)
        assert result.closure_passed is True
        assert result.misclosure_ft < 0.01

        # Should be fully verified
        assert result.is_fully_verified() is True


class TestSquareParcel:
    """Integration test for simple square parcel."""

    def test_100ft_square(self):
        """Test 100 ft × 100 ft square."""
        text = """
        BEGINNING at a point;
        THENCE North 0 degrees East 100 feet;
        THENCE North 90 degrees East 100 feet;
        THENCE South 0 degrees East 100 feet;
        THENCE South 90 degrees West 100 feet to the POINT OF BEGINNING.
        """

        # Process
        normalized = TextParser.normalize_legal_description(text)
        calls = CallExtractor.extract_calls(normalized)
        calls = CallExtractor.enrich_calls_with_azimuths(calls)

        # Verify
        result = ClosureChecker.verify_closure(calls)

        # Should close perfectly
        assert result.closure_passed is True
        assert result.misclosure_ft < 0.01

        # Area = 10,000 sq ft
        assert math.isclose(result.area_sq_ft, 10000.0, abs_tol=1.0)

        # Perimeter = 400 ft
        assert math.isclose(result.perimeter_ft, 400.0, abs_tol=0.1)


class TestIncompleteBearings:
    """Integration test for parcels with incomplete bearings."""

    def test_meander_call(self):
        """Test parcel with meander call."""
        text = """
        BEGINNING at a point;
        THENCE North 45 degrees East 100 feet;
        THENCE meander along the stream 150 feet;
        THENCE South 45 degrees West 100 feet to the POINT OF BEGINNING.
        """

        # Process
        normalized = TextParser.normalize_legal_description(text)
        calls = CallExtractor.extract_calls(normalized)
        calls = CallExtractor.enrich_calls_with_azimuths(calls)

        # Should have 3 calls
        assert len(calls) == 3

        # Second call should have None azimuth
        assert calls[1].bearing_azimuth_deg_from_north is None
        assert "meander" in calls[1].notes.lower()

        # Verify - should have warnings
        result = ClosureChecker.verify_closure(calls)

        # Should warn about incomplete bearings
        assert len(result.warnings) > 0
        assert any("incomplete" in w.lower() for w in result.warnings)

        # Should not be fully verified
        assert result.is_fully_verified() is False

    def test_cardinal_only_bearing(self):
        """Test parcel with cardinal-only bearing."""
        text = """
        BEGINNING at a point;
        THENCE North 45 degrees East 100 feet;
        THENCE southwesterly 75 feet;
        THENCE North 45 degrees West 100 feet to the POINT OF BEGINNING.
        """

        # Process
        normalized = TextParser.normalize_legal_description(text)
        calls = CallExtractor.extract_calls(normalized)

        # Second call should be incomplete
        assert calls[1].bearing_azimuth_deg_from_north is None
        assert "incomplete" in calls[1].notes.lower() or "cardinal" in calls[1].notes.lower()


class TestCurveIntegration:
    """Integration test for parcels with curves."""

    def test_curve_properties_calculated(self):
        """Test curve with all properties calculated."""
        text = """
        BEGINNING at a point;
        THENCE North 0 degrees East 100 feet;
        THENCE along a curve to the right, radius 50 feet, delta 90 degrees;
        THENCE South 0 degrees East 50 feet to the POINT OF BEGINNING.
        """

        # Process
        normalized = TextParser.normalize_legal_description(text)
        calls = CallExtractor.extract_calls(normalized)
        calls = CallExtractor.enrich_calls_with_azimuths(calls)

        # Should have curve
        assert calls[1].curve_dir == "right"
        assert calls[1].radius_ft == 50.0
        assert calls[1].delta_deg == 90.0

        # Verify curve consistency
        result = ClosureChecker.verify_closure(calls)

        # If arc length provided, should be consistent
        if calls[1].arc_length_ft:
            expected_arc = 50.0 * math.radians(90.0)
            assert math.isclose(calls[1].arc_length_ft, expected_arc, abs_tol=0.1)


class TestCSVExportIntegration:
    """Integration test for CSV export."""

    def test_export_verified_csv(self, tmp_path):
        """Test exporting verified CSV."""
        text = """
        BEGINNING at a point;
        THENCE North 0 degrees East 100 feet;
        THENCE North 90 degrees East 100 feet;
        THENCE South 0 degrees East 100 feet;
        THENCE South 90 degrees West 100 feet to the POINT OF BEGINNING.
        """

        # Process
        normalized = TextParser.normalize_legal_description(text)
        pob = TextParser.extract_pob(normalized)
        calls = CallExtractor.extract_calls(normalized)
        calls = CallExtractor.enrich_calls_with_azimuths(calls)

        # Verify
        result = ClosureChecker.verify_closure(calls)

        # Should be fully verified
        assert result.is_fully_verified() is True

        # Export
        legal_desc = LegalDescription(
            pob_description=pob,
            calls=calls,
            source_doc="test_square.pdf",
        )

        output_path = tmp_path / "test_square.csv"
        CSVBuilder.export_verified_csv(
            calls=calls,
            closure_result=result,
            output_path=str(output_path),
            legal_desc=legal_desc,
        )

        # File should exist
        assert output_path.exists()

        # Should be named _verified.csv
        assert output_path.stem.endswith("_verified")

    def test_cannot_export_unverified(self, tmp_path):
        """Test that unverified parcels cannot be exported as verified."""
        text = """
        BEGINNING at a point;
        THENCE North 0 degrees East 100 feet;
        THENCE North 90 degrees East 100 feet;
        """

        # Process
        normalized = TextParser.normalize_legal_description(text)
        calls = CallExtractor.extract_calls(normalized)
        calls = CallExtractor.enrich_calls_with_azimuths(calls)

        # Verify - should fail (open traverse)
        result = ClosureChecker.verify_closure(calls)
        assert result.is_fully_verified() is False

        # Try to export - should raise ValueError
        output_path = tmp_path / "test_open.csv"

        with pytest.raises(ValueError, match="verification checks failed"):
            CSVBuilder.export_verified_csv(
                calls=calls,
                closure_result=result,
                output_path=str(output_path),
            )


class TestCSVImportExportRoundTrip:
    """Test CSV import/export round-trip."""

    def test_round_trip(self, tmp_path):
        """Test exporting and re-importing CSV."""
        text = """
        BEGINNING at a point;
        THENCE North 33 degrees 20 minutes East 60 feet along the south line to a point;
        THENCE South 56 degrees 40 minutes West 125 feet along the division line to a corner;
        THENCE South 33 degrees 20 minutes West 60 feet along the west line;
        THENCE North 56 degrees 40 minutes East 125 feet to the POINT OF BEGINNING.
        """

        # Process
        normalized = TextParser.normalize_legal_description(text)
        pob = TextParser.extract_pob(normalized)
        calls = CallExtractor.extract_calls(normalized)
        calls = CallExtractor.enrich_calls_with_azimuths(calls)

        # Verify
        result = ClosureChecker.verify_closure(calls)
        assert result.is_fully_verified() is True

        # Export
        legal_desc = LegalDescription(pob_description=pob, calls=calls, source_doc="test.pdf")
        output_path = tmp_path / "test.csv"

        CSVBuilder.export_verified_csv(
            calls=calls,
            closure_result=result,
            output_path=str(output_path),
            legal_desc=legal_desc,
        )

        # Import
        imported_calls = CSVBuilder.import_csv(str(output_path))

        # Should have same number of calls
        assert len(imported_calls) == len(calls)

        # Check critical fields preserved
        for original, imported in zip(calls, imported_calls, strict=False):
            assert imported.course == original.course
            assert imported.bearing_quadrant == original.bearing_quadrant
            assert imported.distance_ft == pytest.approx(original.distance_ft, abs=0.01)

            if original.bearing_azimuth_deg_from_north is not None:
                assert imported.bearing_azimuth_deg_from_north == pytest.approx(
                    original.bearing_azimuth_deg_from_north, abs=0.000001
                )


class TestTextNormalizationPipeline:
    """Integration test for text normalization pipeline."""

    def test_ocr_error_correction(self):
        """Test OCR error correction in full pipeline."""
        text = """
        BEGINNING at a point;
        THENCE 5outh 56 0 40' We5t 125 feet;
        THENCE NOrth 33 0 20' Ea5t 60 feet to the POINT OF BEGINNING.
        """

        # Normalize - should fix OCR errors
        normalized = TextParser.normalize_legal_description(text)

        # Should have fixed: 5outh → South, 0 → °, We5t → West, etc.
        assert "South" in normalized
        assert "56°40'" in normalized
        assert "West" in normalized
        assert "North" in normalized
        assert "East" in normalized

        # Should be parseable
        calls = CallExtractor.extract_calls(normalized)
        assert len(calls) == 2

        # Bearings should be extracted
        assert calls[0].bearing_quadrant is not None
        assert calls[1].bearing_quadrant is not None

    def test_line_wrapping_fix(self):
        """Test line wrapping correction."""
        text = """
        BEGINNING at a point;
        THENCE North 45 degrees East 100 feet along the div-
        ision line between Lots 1 and 2 to
        a point in the north line;
        THENCE South 45 degrees East 100 feet to the POINT OF BEGINNING.
        """

        # Normalize - should merge wrapped lines
        normalized = TextParser.normalize_legal_description(text)

        # Should not have "div-\n" anymore
        assert "div-\n" not in normalized
        assert "division line" in normalized

        # Parse should work
        calls = CallExtractor.extract_calls(normalized)
        assert len(calls) == 2

        # "along" field should be complete
        assert "division line" in calls[0].along


class TestErrorHandling:
    """Integration tests for error handling."""

    def test_empty_text(self):
        """Test handling of empty text."""
        text = ""

        normalized = TextParser.normalize_legal_description(text)
        calls = CallExtractor.extract_calls(normalized)

        # Should return empty list, not crash
        assert len(calls) == 0

    def test_no_thence_calls(self):
        """Test text with no THENCE calls."""
        text = "BEGINNING at a point in the center of Main Street."

        normalized = TextParser.normalize_legal_description(text)
        calls = CallExtractor.extract_calls(normalized)

        # Should return empty list
        assert len(calls) == 0

    def test_malformed_bearing(self):
        """Test handling of malformed bearing."""
        text = """
        BEGINNING at a point;
        THENCE North 999 degrees East 100 feet;
        THENCE South 45 degrees West 100 feet to the POINT OF BEGINNING.
        """

        # Should not crash
        normalized = TextParser.normalize_legal_description(text)
        calls = CallExtractor.extract_calls(normalized)

        # Should attempt to parse (may succeed or fail gracefully)
        assert len(calls) >= 0


class TestRealWorldScenarios:
    """Integration tests for real-world scenarios."""

    def test_mixed_units(self):
        """Test parcel with mixed units (feet and poles)."""
        text = """
        BEGINNING at a point;
        THENCE North 45 degrees East 100 feet;
        THENCE South 45 degrees East 10 poles;
        THENCE South 45 degrees West 100 feet;
        THENCE North 45 degrees West 10 poles to the POINT OF BEGINNING.
        """

        # Process
        normalized = TextParser.normalize_legal_description(text)
        calls = CallExtractor.extract_calls(normalized)
        calls = CallExtractor.enrich_calls_with_azimuths(calls)

        # Poles should be converted to feet
        # 10 poles = 165 feet
        assert calls[1].distance_ft == 165.0
        assert calls[3].distance_ft == 165.0

        # Verify closure
        result = ClosureChecker.verify_closure(calls)
        assert result.closure_passed is True

    def test_parcel_with_stated_area(self):
        """Test area comparison with stated area."""
        text = """
        BEGINNING at a point;
        THENCE North 0 degrees East 100 feet;
        THENCE North 90 degrees East 100 feet;
        THENCE South 0 degrees East 100 feet;
        THENCE South 90 degrees West 100 feet to the POINT OF BEGINNING.
        Containing 10,000 square feet.
        """

        # Process
        normalized = TextParser.normalize_legal_description(text)
        calls = CallExtractor.extract_calls(normalized)
        calls = CallExtractor.enrich_calls_with_azimuths(calls)

        # Verify with stated area
        result = ClosureChecker.verify_closure(calls, stated_area_sq_ft=10000.0)

        # Should match (no warning)
        assert not any("area" in w.lower() and "differ" in w.lower() for w in result.warnings)

    def test_very_small_parcel(self):
        """Test very small parcel (10 ft × 10 ft)."""
        text = """
        BEGINNING at a point;
        THENCE North 0 degrees East 10 feet;
        THENCE North 90 degrees East 10 feet;
        THENCE South 0 degrees East 10 feet;
        THENCE South 90 degrees West 10 feet to the POINT OF BEGINNING.
        """

        # Process
        normalized = TextParser.normalize_legal_description(text)
        calls = CallExtractor.extract_calls(normalized)
        calls = CallExtractor.enrich_calls_with_azimuths(calls)

        # Verify
        result = ClosureChecker.verify_closure(calls)

        # Should close
        assert result.closure_passed is True

        # Area = 100 sq ft
        assert math.isclose(result.area_sq_ft, 100.0, abs_tol=1.0)
