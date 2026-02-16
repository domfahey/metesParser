"""Phase 2 Enhanced Parsing tests.

TDD tests for Phase 2 features:
- parse_packed_dms
- chord bearing extraction
- non-tangent curve detection
- basis of bearing extraction
- surveyor certification extraction
- prior conveyance extraction
- extended distance extraction
- unit-inference heuristics
- CSV schema expansion (non_tangent, radial_bearing)
- pipeline wiring
"""

from pathlib import Path

import pytest

from metesparser.bearing_converter import BearingConverter
from metesparser.call_extractor import CallExtractor
from metesparser.csv_builder import CSVBuilder
from metesparser.models import DeedCall, LegalDescription
from metesparser.text_parser import TextParser


class TestParsePackedDMS:
    """Test BearingConverter.parse_packed_dms()."""

    @pytest.mark.parametrize(
        "packed, expected",
        [
            (46.1631, pytest.approx(46 + 16 / 60 + 31 / 3600, abs=1e-6)),
            (0.0000, pytest.approx(0.0, abs=1e-6)),
            (90.0000, pytest.approx(90.0, abs=1e-6)),
            (45.3000, pytest.approx(45.5, abs=1e-6)),
            (1.0130, pytest.approx(1 + 1 / 60 + 30 / 3600, abs=1e-6)),
            (89.5959, pytest.approx(89 + 59 / 60 + 59 / 3600, abs=1e-6)),
            (12.3045, pytest.approx(12 + 30 / 60 + 45 / 3600, abs=1e-6)),
            (56.4030, pytest.approx(56 + 40 / 60 + 30 / 3600, abs=1e-6)),
        ],
    )
    def test_packed_dms_conversions(self, packed: float, expected: float) -> None:
        result = BearingConverter.parse_packed_dms(packed)
        assert result == expected

    def test_invalid_minutes_raises(self) -> None:
        with pytest.raises(ValueError, match="minutes"):
            BearingConverter.parse_packed_dms(46.6000)

    def test_invalid_seconds_raises(self) -> None:
        with pytest.raises(ValueError, match="seconds"):
            BearingConverter.parse_packed_dms(46.1560)


class TestChordBearingExtraction:
    """Test chord bearing extraction from curve text."""

    def test_chord_bears_full_dms(self) -> None:
        text = (
            "along a curve to the right, radius of 300.00 feet, "
            "delta angle of 25°30'00\", arc length of 133.52 feet, "
            "chord of which bears S 34°57'37\" E, 254.22 feet"
        )
        info = CallExtractor.extract_curve_info(text)
        assert info.get("chord_bearing") is not None
        assert "34" in info["chord_bearing"]

    def test_chord_bears_degrees_minutes(self) -> None:
        text = (
            "along a curve to the left, radius of 500.00 feet, "
            "delta angle of 10°15', arc length of 89.40 feet, "
            "chord of which bears N 45°30' W"
        )
        info = CallExtractor.extract_curve_info(text)
        assert info.get("chord_bearing") is not None
        assert "45" in info["chord_bearing"]

    def test_chord_bearing_spelled_out_cardinals(self) -> None:
        text = (
            "along a curve to the right, radius of 200.00 feet, "
            "delta angle of 20 degrees 10 minutes, arc length of 70.37 feet, "
            "chord of which bears South 12 degrees 30 minutes East"
        )
        info = CallExtractor.extract_curve_info(text)
        assert info.get("chord_bearing") is not None

    def test_chord_length_extracted(self) -> None:
        text = (
            "along a curve to the right, radius of 300.00 feet, "
            "delta angle of 25°30', arc length of 133.52 feet, "
            "chord of which bears S 34°57' E, 254.22 feet"
        )
        info = CallExtractor.extract_curve_info(text)
        assert info.get("chord_length_ft") is not None
        assert info["chord_length_ft"] == pytest.approx(254.22, abs=0.5)

    def test_no_chord_bearing_no_match(self) -> None:
        text = (
            "along a curve to the right, radius of 300.00 feet, "
            "delta angle of 25°30', arc length of 133.52 feet"
        )
        info = CallExtractor.extract_curve_info(text)
        assert info.get("chord_bearing") is None

    def test_chord_bearing_flows_to_deed_call(self) -> None:
        text = (
            "S 10°00' E along a curve to the right, radius of 300.00 feet, "
            "delta angle of 25°30'00\", arc length of 133.52 feet, "
            "chord of which bears S 34°57'37\" E, 254.22 feet"
        )
        call = CallExtractor.extract_single_call(text, course=1)
        assert call is not None
        assert call.chord_bearing is not None

    def test_chord_bearing_with_chord_keyword_only(self) -> None:
        text = (
            "along a curve to the right, radius of 300.00 feet, "
            "delta angle of 25°30', arc length of 133.52 feet, "
            "the chord bears N 80°15' E"
        )
        info = CallExtractor.extract_curve_info(text)
        assert info.get("chord_bearing") is not None

    def test_chord_bearing_case_insensitive(self) -> None:
        text = (
            "along a curve to the left, radius of 100.00 feet, "
            "delta angle of 15°00', arc length of 26.18 feet, "
            "CHORD OF WHICH BEARS N 45°00' W"
        )
        info = CallExtractor.extract_curve_info(text)
        assert info.get("chord_bearing") is not None


class TestNonTangentCurveDetection:
    """Test non-tangent curve detection and radial bearing extraction."""

    def test_non_tangent_keyword(self) -> None:
        text = (
            "along a non-tangent curve to the right, radius of 200.00 feet, "
            "delta angle of 30°00', arc length of 104.72 feet"
        )
        info = CallExtractor.extract_curve_info(text)
        assert info.get("non_tangent") is True

    def test_nontangent_no_hyphen(self) -> None:
        text = (
            "along a nontangent curve to the left, radius of 150.00 feet, "
            "delta angle of 20°00', arc length of 52.36 feet"
        )
        info = CallExtractor.extract_curve_info(text)
        assert info.get("non_tangent") is True

    def test_radial_line_bears(self) -> None:
        text = (
            "along a curve to the right, radial line bears N 15°22' E, "
            "radius of 300.00 feet, delta angle of 25°30', arc length of 133.52 feet"
        )
        info = CallExtractor.extract_curve_info(text)
        assert info.get("non_tangent") is True
        assert info.get("radial_bearing") is not None
        assert "15" in info["radial_bearing"]

    def test_radial_bearing_of(self) -> None:
        text = (
            "along a curve to the left, radial bearing of S 45°00' W, "
            "radius of 500.00 feet, delta angle of 10°00', arc length of 87.27 feet"
        )
        info = CallExtractor.extract_curve_info(text)
        assert info.get("non_tangent") is True
        assert info.get("radial_bearing") is not None
        assert "45" in info["radial_bearing"]

    def test_case_insensitive_nontangent(self) -> None:
        text = (
            "along a NON-TANGENT curve to the right, radius of 200.00 feet, "
            "delta angle of 30°00', arc length of 104.72 feet"
        )
        info = CallExtractor.extract_curve_info(text)
        assert info.get("non_tangent") is True

    def test_tangent_curve_no_flag(self) -> None:
        text = (
            "along a curve to the right, radius of 300.00 feet, "
            "delta angle of 25°30', arc length of 133.52 feet"
        )
        info = CallExtractor.extract_curve_info(text)
        assert info.get("non_tangent") is not True

    def test_non_tangent_flows_to_deed_call(self) -> None:
        text = (
            "S 10°00' E along a non-tangent curve to the right, "
            "radial line bears N 15°22' E, "
            "radius of 300.00 feet, delta angle of 25°30', arc length of 133.52 feet"
        )
        call = CallExtractor.extract_single_call(text, course=1)
        assert call is not None
        assert call.non_tangent is True
        assert call.radial_bearing is not None

    def test_tangent_curve_deed_call_no_flag(self) -> None:
        text = (
            "S 10°00' E along a curve to the right, "
            "radius of 300.00 feet, delta angle of 25°30', arc length of 133.52 feet"
        )
        call = CallExtractor.extract_single_call(text, course=1)
        assert call is not None
        assert call.non_tangent is False
        assert call.radial_bearing is None

    def test_radial_bearing_with_seconds(self) -> None:
        text = (
            "along a curve to the right, radial line bears N 15°22'30\" E, "
            "radius of 300.00 feet, delta angle of 25°30', arc length of 133.52 feet"
        )
        info = CallExtractor.extract_curve_info(text)
        assert info.get("non_tangent") is True
        assert info.get("radial_bearing") is not None


class TestBasisOfBearingExtraction:
    """Test TextParser.extract_basis_of_bearing()."""

    def test_explicit_label(self) -> None:
        text = "Basis of Bearings: True North as determined by GPS observation."
        result = TextParser.extract_basis_of_bearing(text)
        assert result is not None
        assert "True North" in result

    def test_bearings_based_on(self) -> None:
        text = "All bearings are based on the North line of Section 12."
        result = TextParser.extract_basis_of_bearing(text)
        assert result is not None
        assert "North line" in result

    def test_referenced_to(self) -> None:
        text = "Bearings referenced to NAD 83 State Plane Coordinates."
        result = TextParser.extract_basis_of_bearing(text)
        assert result is not None
        assert "NAD 83" in result

    def test_blm_style(self) -> None:
        text = "Bearings based on BLM Dependent Resurvey of Township 15 North."
        result = TextParser.extract_basis_of_bearing(text)
        assert result is not None
        assert "BLM" in result

    def test_magnetic_bearing(self) -> None:
        text = "All bearings herein are magnetic."
        result = TextParser.extract_basis_of_bearing(text)
        assert result is not None

    def test_assumed_bearing(self) -> None:
        text = "Bearings are assumed for this survey."
        result = TextParser.extract_basis_of_bearing(text)
        assert result is not None

    def test_no_basis_found(self) -> None:
        text = "THENCE S 56°40' W 100.00 feet to an iron pin."
        result = TextParser.extract_basis_of_bearing(text)
        assert result is None

    def test_case_insensitive(self) -> None:
        text = "basis of bearings: magnetic north."
        result = TextParser.extract_basis_of_bearing(text)
        assert result is not None


class TestSurveyorCertificationExtraction:
    """Test TextParser.extract_surveyor_certification()."""

    def test_that_i_pattern(self) -> None:
        text = "That I, John Smith, a Licensed Surveyor, do hereby certify."
        result = TextParser.extract_surveyor_certification(text)
        assert result is not None
        assert "John Smith" in result

    def test_i_hereby_certify(self) -> None:
        text = "I hereby certify that this survey was conducted on January 1, 2024."
        result = TextParser.extract_surveyor_certification(text)
        assert result is not None

    def test_certified_by(self) -> None:
        text = "Certified by: Jane Doe, PLS No. 12345"
        result = TextParser.extract_surveyor_certification(text)
        assert result is not None
        assert "Jane Doe" in result

    def test_surveyed_by(self) -> None:
        text = "Surveyed by Robert Brown, Registered Land Surveyor, License No. 5678"
        result = TextParser.extract_surveyor_certification(text)
        assert result is not None

    def test_no_certification_found(self) -> None:
        text = "THENCE S 56°40' W 100.00 feet to an iron pin."
        result = TextParser.extract_surveyor_certification(text)
        assert result is None

    def test_model_field_exists(self) -> None:
        ld = LegalDescription(
            calls=[],
            surveyor_certification="John Smith, PLS",
        )
        assert ld.surveyor_certification == "John Smith, PLS"

    def test_model_field_default_none(self) -> None:
        ld = LegalDescription(calls=[])
        assert ld.surveyor_certification is None


class TestPriorConveyanceExtraction:
    """Test TextParser.extract_prior_conveyance()."""

    def test_being_same_premises(self) -> None:
        text = "BEING the same premises conveyed to John Smith by deed dated January 1, 2020."
        result = TextParser.extract_prior_conveyance(text)
        assert result is not None
        assert "John Smith" in result

    def test_deed_book_reference(self) -> None:
        text = "As recorded in Deed Book 1234, Page 567 of the County Records."
        result = TextParser.extract_prior_conveyance(text)
        assert result is not None
        assert "1234" in result

    def test_instrument_number(self) -> None:
        text = "Instrument Number 202300012345 recorded in the County Clerk's office."
        result = TextParser.extract_prior_conveyance(text)
        assert result is not None
        assert "202300012345" in result

    def test_official_records_book(self) -> None:
        text = "As recorded in Official Records Book 789, Page 12."
        result = TextParser.extract_prior_conveyance(text)
        assert result is not None

    def test_no_conveyance_found(self) -> None:
        text = "THENCE S 56°40' W 100.00 feet to an iron pin."
        result = TextParser.extract_prior_conveyance(text)
        assert result is None

    def test_model_field_exists(self) -> None:
        ld = LegalDescription(
            calls=[],
            prior_conveyance="Deed Book 1234, Page 567",
        )
        assert ld.prior_conveyance == "Deed Book 1234, Page 567"

    def test_model_field_default_none(self) -> None:
        ld = LegalDescription(calls=[])
        assert ld.prior_conveyance is None


class TestExtendedDistanceExtraction:
    """Test extended distance units in TextParser.extract_distance()."""

    @pytest.mark.parametrize(
        "text, expected_value, expected_unit",
        [
            ("125.26 feet", 125.26, "feet"),
            ("258 poles", 258.0, "poles"),
            ("10 chains", 10.0, "chains"),
            ("50 links", 50.0, "links"),
            ("15 rods", 15.0, "rods"),
            ("20 perches", 20.0, "perches"),
            ("100.5 varas", 100.5, "varas"),
            ("12 vara", 12.0, "varas"),
            ("5.0 arpents", 5.0, "arpents"),
            ("3 arpent", 3.0, "arpents"),
            ("8 toises", 8.0, "toises"),
            ("2 toise", 2.0, "toises"),
            ("4 furlongs", 4.0, "furlongs"),
            ("1 furlong", 1.0, "furlongs"),
            ("100 meters", 100.0, "meters"),
            ("50 meter", 50.0, "meters"),
            ("2.5 miles", 2.5, "miles"),
            ("1 mile", 1.0, "miles"),
        ],
    )
    def test_distance_extraction(
        self, text: str, expected_value: float, expected_unit: str
    ) -> None:
        value, unit = TextParser.extract_distance(text)
        assert value == pytest.approx(expected_value, abs=0.01)
        assert unit == expected_unit

    def test_existing_units_still_work(self) -> None:
        """Regression: existing units must still parse correctly."""
        value, unit = TextParser.extract_distance("125.26 ft")
        assert value == pytest.approx(125.26)
        assert unit == "feet"


class TestUnitInferenceHeuristics:
    """Test TextParser.infer_distance_unit()."""

    def test_texas_pre_1900_varas(self) -> None:
        result = TextParser.infer_distance_unit("some deed text", state="TX", year=1880)
        assert result == "varas"

    def test_texas_post_1900_no_inference(self) -> None:
        result = TextParser.infer_distance_unit("some deed text", state="TX", year=1950)
        assert result is None

    def test_louisiana_arpents(self) -> None:
        result = TextParser.infer_distance_unit("some deed text", state="LA")
        assert result == "arpents"

    def test_new_england_pre_1850_rods(self) -> None:
        for state in ("MA", "CT", "ME", "NH", "VT", "RI"):
            result = TextParser.infer_distance_unit("some text", state=state, year=1830)
            assert result == "rods", f"Expected rods for {state} pre-1850"

    def test_chains_and_links_keyword(self) -> None:
        result = TextParser.infer_distance_unit("measured in chains and links")
        assert result == "chains"

    def test_no_inference_generic_text(self) -> None:
        result = TextParser.infer_distance_unit("THENCE S 56°40' W 100.00 feet")
        assert result is None

    def test_none_state_none_year(self) -> None:
        result = TextParser.infer_distance_unit("some text")
        assert result is None

    def test_vara_keyword_in_text(self) -> None:
        result = TextParser.infer_distance_unit("measured in varas along the creek")
        assert result == "varas"


class TestCSVSchemaExpansion:
    """Test CSV schema now includes non_tangent and radial_bearing."""

    def test_fieldnames_include_new_fields(self) -> None:
        assert "non_tangent" in CSVBuilder.FIELDNAMES
        assert "radial_bearing" in CSVBuilder.FIELDNAMES

    def test_fieldnames_count(self) -> None:
        assert len(CSVBuilder.FIELDNAMES) == 19

    def test_non_tangent_in_exported_row(self) -> None:
        call = DeedCall(
            course=1,
            direction_text="S 10°00' E",
            bearing_quadrant="S 10°00' E",
            bearing_azimuth_deg_from_north=170.0,
            distance_ft=100.0,
            curve_dir="right",
            radius_ft=300.0,
            delta_deg=25.5,
            arc_length_ft=133.52,
            non_tangent=True,
            radial_bearing="N 15°22' E",
        )
        row = CSVBuilder._call_to_row(call)
        assert row["non_tangent"] == "true"
        assert row["radial_bearing"] == "N 15°22' E"

    def test_tangent_curve_row_values(self) -> None:
        call = DeedCall(
            course=1,
            direction_text="S 10°00' E",
            distance_ft=100.0,
            non_tangent=False,
        )
        row = CSVBuilder._call_to_row(call)
        assert row["non_tangent"] == "false"
        assert row["radial_bearing"] == ""

    def test_round_trip_csv(self, tmp_path: Path) -> None:
        call = DeedCall(
            course=1,
            direction_text="S 10°00' E",
            bearing_quadrant="S 10°00' E",
            bearing_azimuth_deg_from_north=170.0,
            distance_ft=100.0,
            curve_dir="right",
            radius_ft=300.0,
            delta_deg=25.5,
            arc_length_ft=133.52,
            non_tangent=True,
            radial_bearing="N 15°22' E",
        )
        csv_path = str(tmp_path / "test.csv")
        CSVBuilder.calls_to_csv([call], csv_path)
        loaded = CSVBuilder.csv_to_calls(csv_path)
        assert len(loaded) == 1
        assert loaded[0].non_tangent is True
        assert loaded[0].radial_bearing == "N 15°22' E"


class TestPipelineWiring:
    """Test that process_deed_pdf wires new extractors."""

    def test_legal_description_metadata_export(self, tmp_path: Path) -> None:
        """Test that new metadata fields are exported."""
        ld = LegalDescription(
            calls=[
                DeedCall(
                    course=1,
                    direction_text="N 45°00' E",
                    bearing_quadrant="N 45°00' E",
                    bearing_azimuth_deg_from_north=45.0,
                    distance_ft=100.0,
                )
            ],
            basis_of_bearing="True North",
            surveyor_certification="John Smith, PLS",
            prior_conveyance="Deed Book 1234, Page 567",
        )
        csv_path = str(tmp_path / "test.csv")
        CSVBuilder.legal_description_to_csv(ld, csv_path)

        metadata_path = tmp_path / "test.metadata.txt"
        assert metadata_path.exists()
        content = metadata_path.read_text()
        assert "basis_of_bearing" in content
        assert "surveyor_certification" in content
        assert "prior_conveyance" in content

    def test_new_fields_in_legal_description(self) -> None:
        ld = LegalDescription(
            calls=[],
            surveyor_certification="Jane Doe",
            prior_conveyance="Instrument 12345",
        )
        assert ld.surveyor_certification == "Jane Doe"
        assert ld.prior_conveyance == "Instrument 12345"

    def test_basis_of_bearing_field_used(self) -> None:
        ld = LegalDescription(
            calls=[],
            basis_of_bearing="NAD 83 State Plane",
        )
        assert ld.basis_of_bearing == "NAD 83 State Plane"
