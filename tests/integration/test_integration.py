"""Integration tests - Full pipeline from text to verified CSV."""

import math

import pytest

from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker
from metesparser.csv_builder import CSVBuilder
from metesparser.models import LegalDescription
from metesparser.text_parser import TextParser
from tests.fixtures.sample_deeds import (
    CARDINAL_ONLY,
    EMPTY_TEXT,
    INVALID_BEARING,
    LINE_WRAPPING,
    MIXED_FEET_AND_POLES,
    NO_THENCE,
    OPEN_TRAVERSE,
    PARCEL_WITH_CURVE,
    PARCEL_WITH_MEANDER,
    PENNBROOK_18,
    PENNBROOK_31,
    RECTANGLE_60X125,
    SQUARE_100FT,
    VERY_SMALL_PARCEL,
    WITH_OCR_ERRORS,
    WITH_STATED_AREA,
)

pytestmark = pytest.mark.integration


class Test18PennbrookParcel:
    """Integration test for 18 Pennbrook parcel (known rectangle)."""

    @pytest.fixture
    def legal_description_text(self):
        """Legal description for 18 Pennbrook (simplified)."""
        return PENNBROOK_18

    def test_full_pipeline(self, legal_description_text):
        """Test complete pipeline: parse → verify → should close."""
        normalized = TextParser.normalize_legal_description(legal_description_text)

        pob = TextParser.extract_pob(normalized)
        assert "point in the division line" in pob.lower()

        calls = CallExtractor.extract_calls(normalized)
        assert len(calls) == 4

        calls = CallExtractor.enrich_calls_with_azimuths(calls)

        assert calls[0].bearing_azimuth_deg_from_north == pytest.approx(146.666667, abs=0.000001)
        assert calls[1].bearing_azimuth_deg_from_north == pytest.approx(236.666667, abs=0.000001)
        assert calls[2].bearing_azimuth_deg_from_north == pytest.approx(326.666667, abs=0.000001)
        assert calls[3].bearing_azimuth_deg_from_north == pytest.approx(56.666667, abs=0.000001)

        result = ClosureChecker.verify_closure(calls)

        assert result.closure_passed is True
        assert result.misclosure_ft < 0.01

        assert math.isclose(result.area_sq_ft, 7500.0, abs_tol=10.0)
        assert result.is_fully_verified() is True


class Test31PennbrookParcel:
    """Integration test for 31 Pennbrook parcel (5-sided polygon)."""

    @pytest.fixture
    def legal_description_text(self):
        """Legal description for 31 Pennbrook (5 sides)."""
        return PENNBROOK_31

    def test_five_sided_closure(self, legal_description_text):
        """Test 5-sided parcel parsing (note: test data doesn't actually close)."""
        normalized = TextParser.normalize_legal_description(legal_description_text)
        calls = CallExtractor.extract_calls(normalized)
        calls = CallExtractor.enrich_calls_with_azimuths(calls)

        assert len(calls) == 5

        for call in calls:
            if call.bearing_quadrant:
                assert call.bearing_azimuth_deg_from_north is not None
            else:
                assert call.bearing_azimuth_deg_from_north is None

        result = ClosureChecker.verify_closure(calls)

        assert result.misclosure_ft > 0.01
        assert result.area_sq_ft > 0


class TestSquareParcel:
    """Integration test for simple square parcel."""

    def test_100ft_square(self):
        """Test 100 ft × 100 ft square."""
        text = SQUARE_100FT

        normalized = TextParser.normalize_legal_description(text)
        calls = CallExtractor.extract_calls(normalized)
        calls = CallExtractor.enrich_calls_with_azimuths(calls)

        result = ClosureChecker.verify_closure(calls)

        assert result.closure_passed is True
        assert result.misclosure_ft < 0.01

        assert math.isclose(result.area_sq_ft, 10000.0, abs_tol=1.0)

        assert math.isclose(result.perimeter_ft, 400.0, abs_tol=0.1)


class TestIncompleteBearings:
    """Integration test for parcels with incomplete bearings."""

    def test_meander_call(self):
        """Test parcel with meander call."""
        text = PARCEL_WITH_MEANDER

        normalized = TextParser.normalize_legal_description(text)
        calls = CallExtractor.extract_calls(normalized)
        calls = CallExtractor.enrich_calls_with_azimuths(calls)

        assert len(calls) == 3

        assert calls[1].bearing_azimuth_deg_from_north is None
        assert "meander" in calls[1].notes.lower()

        result = ClosureChecker.verify_closure(calls)

        assert len(result.warnings) > 0
        assert any("incomplete bearings" in warning.lower() for warning in result.warnings)

        assert result.is_fully_verified() is False

    def test_cardinal_only_bearing(self):
        """Test parcel with cardinal-only bearing."""
        text = CARDINAL_ONLY

        normalized = TextParser.normalize_legal_description(text)
        calls = CallExtractor.extract_calls(normalized)

        assert calls[1].bearing_azimuth_deg_from_north is None
        assert calls[1].notes == "incomplete bearing - cardinal only"


class TestCurveIntegration:
    """Integration test for parcels with curves."""

    def test_curve_properties_calculated(self):
        """Test curve with all properties calculated."""
        text = PARCEL_WITH_CURVE

        normalized = TextParser.normalize_legal_description(text)
        calls = CallExtractor.extract_calls(normalized)
        calls = CallExtractor.enrich_calls_with_azimuths(calls)

        assert calls[1].curve_dir == "right"
        assert calls[1].radius_ft == 50.0
        assert calls[1].delta_deg == 90.0

        ClosureChecker.verify_closure(calls)
        expected_arc = 50.0 * math.radians(90.0)
        assert calls[1].arc_length_ft is not None
        assert math.isclose(calls[1].arc_length_ft, expected_arc, abs_tol=0.1)


class TestCSVExportIntegration:
    """Integration test for CSV export."""

    def test_export_verified_csv(self, tmp_path):
        """Test exporting verified CSV."""
        text = SQUARE_100FT

        normalized = TextParser.normalize_legal_description(text)
        pob = TextParser.extract_pob(normalized)
        calls = CallExtractor.extract_calls(normalized)
        calls = CallExtractor.enrich_calls_with_azimuths(calls)

        result = ClosureChecker.verify_closure(calls)

        assert result.is_fully_verified() is True

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

        verified_path = tmp_path / "test_square_verified.csv"
        assert verified_path.exists()
        assert verified_path.stem.endswith("_verified")

    def test_cannot_export_unverified(self, tmp_path):
        """Test that unverified parcels cannot be exported as verified."""
        text = OPEN_TRAVERSE

        normalized = TextParser.normalize_legal_description(text)
        calls = CallExtractor.extract_calls(normalized)
        calls = CallExtractor.enrich_calls_with_azimuths(calls)

        result = ClosureChecker.verify_closure(calls)
        assert result.is_fully_verified() is False

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
        text = RECTANGLE_60X125

        normalized = TextParser.normalize_legal_description(text)
        pob = TextParser.extract_pob(normalized)
        calls = CallExtractor.extract_calls(normalized)
        calls = CallExtractor.enrich_calls_with_azimuths(calls)

        result = ClosureChecker.verify_closure(calls)
        assert result.closure_passed is True

        legal_desc = LegalDescription(pob_description=pob, calls=calls, source_doc="test.pdf")
        output_path = tmp_path / "test.csv"

        CSVBuilder.legal_description_to_csv(
            legal_desc=legal_desc,
            output_path=str(output_path),
        )

        imported_calls = CSVBuilder.csv_to_calls(str(output_path))

        assert len(imported_calls) == len(calls)

        for original, imported in zip(calls, imported_calls, strict=True):
            assert imported.course == original.course
            assert imported.bearing_quadrant == original.bearing_quadrant
            assert imported.distance_ft == pytest.approx(original.distance_ft, abs=0.01)

            if original.bearing_azimuth_deg_from_north is not None:
                assert imported.bearing_azimuth_deg_from_north == pytest.approx(
                    original.bearing_azimuth_deg_from_north, abs=0.000001
                )
            else:
                assert imported.bearing_azimuth_deg_from_north is None


class TestTextNormalizationPipeline:
    """Integration test for text normalization pipeline."""

    def test_ocr_error_correction(self):
        """Test OCR error correction in full pipeline."""
        text = WITH_OCR_ERRORS
        normalized = TextParser.normalize_legal_description(text)
        assert "S" in normalized
        assert "W" in normalized
        assert "N" in normalized
        assert "E" in normalized
        assert "56°40'" in normalized
        assert "33°20'" in normalized

        calls = CallExtractor.extract_calls(normalized)
        assert len(calls) == 2
        assert calls[0].bearing_quadrant is not None
        assert calls[1].bearing_quadrant is not None

        assert calls[0].bearing_azimuth_deg_from_north is not None
        assert calls[1].bearing_azimuth_deg_from_north is not None

    def test_line_wrapping_fix(self):
        """Test line wrapping correction."""
        text = LINE_WRAPPING

        normalized = TextParser.normalize_legal_description(text)
        assert "div-\n" not in normalized
        assert "division line" in normalized

        calls = CallExtractor.extract_calls(normalized)
        assert len(calls) == 2
        assert "division line" in calls[0].along


class TestErrorHandling:
    """Integration tests for error handling."""

    def test_empty_text(self):
        """Test handling of empty text."""
        text = EMPTY_TEXT

        normalized = TextParser.normalize_legal_description(text)
        calls = CallExtractor.extract_calls(normalized)

        assert len(calls) == 0

    def test_no_thence_calls(self):
        """Test text with no THENCE calls."""
        text = NO_THENCE

        normalized = TextParser.normalize_legal_description(text)
        calls = CallExtractor.extract_calls(normalized)

        assert len(calls) == 0

    def test_malformed_bearing(self):
        """Test handling of malformed bearing."""
        text = INVALID_BEARING

        normalized = TextParser.normalize_legal_description(text)
        calls = CallExtractor.extract_calls(normalized)

        assert len(calls) == 2
        assert calls[0].course == 1
        assert calls[0].bearing_azimuth_deg_from_north is None
        assert calls[0].notes is not None and "incomplete" in calls[0].notes.lower()
        assert calls[-1].bearing_azimuth_deg_from_north is not None
        assert math.isclose(calls[-1].bearing_azimuth_deg_from_north, 225.0, abs_tol=0.01)
        assert math.isclose(calls[-1].distance_ft, 100.0, abs_tol=0.01)


class TestRealWorldScenarios:
    """Integration tests for real-world scenarios."""

    def test_mixed_units(self):
        """Test parcel with mixed units (feet and poles)."""
        text = MIXED_FEET_AND_POLES

        normalized = TextParser.normalize_legal_description(text)
        calls = CallExtractor.extract_calls(normalized)
        calls = CallExtractor.enrich_calls_with_azimuths(calls)

        assert calls[1].distance_ft == 165.0
        assert calls[3].distance_ft == 165.0

        result = ClosureChecker.verify_closure(calls)
        assert result.closure_passed is True

    def test_parcel_with_stated_area(self):
        """Test area comparison with stated area."""
        text = WITH_STATED_AREA

        normalized = TextParser.normalize_legal_description(text)
        calls = CallExtractor.extract_calls(normalized)
        calls = CallExtractor.enrich_calls_with_azimuths(calls)

        result = ClosureChecker.verify_closure(calls, stated_area_sq_ft=10000.0)
        assert result.warnings == []

    def test_very_small_parcel(self):
        """Test very small parcel (10 ft × 10 ft)."""
        text = VERY_SMALL_PARCEL

        normalized = TextParser.normalize_legal_description(text)
        calls = CallExtractor.extract_calls(normalized)
        calls = CallExtractor.enrich_calls_with_azimuths(calls)

        result = ClosureChecker.verify_closure(calls)

        assert result.closure_passed is True

        assert math.isclose(result.area_sq_ft, 100.0, abs_tol=1.0)
