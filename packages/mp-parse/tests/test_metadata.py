"""Tests for mp_parse.metadata — metadata extraction functions."""

from __future__ import annotations

import pytest


class TestExtractPlssMetadata:
    def test_basic_plss(self) -> None:
        from mp_parse.metadata import extract_plss_metadata

        text = "the NW 1/4 of Section 12, Township 3 North, Range 2 West of the Willamette Meridian"
        result = extract_plss_metadata(text)
        assert result["section"] == "12"
        assert result["township"] == "3 N"
        assert result["range"] == "2 W"

    def test_no_plss_returns_nones(self) -> None:
        from mp_parse.metadata import extract_plss_metadata

        result = extract_plss_metadata("BEGINNING at an iron pin")
        assert result["section"] is None
        assert result["township"] is None
        assert result["range"] is None

    def test_principal_meridian(self) -> None:
        from mp_parse.metadata import extract_plss_metadata

        text = "Section 12, Township 3 North, Range 2 West of the Willamette Principal Meridian"
        result = extract_plss_metadata(text)
        assert result["principal_meridian"] is not None
        assert "Willamette" in result["principal_meridian"]


class TestExtractPocAndPob:
    def test_both_poc_and_pob(self) -> None:
        from mp_parse.metadata import extract_poc_and_pob

        text = "COMMENCING at an iron pin; thence North 100 feet to the POINT OF BEGINNING"
        poc, pob = extract_poc_and_pob(text)
        assert poc is not None and poc != ""
        assert pob is not None and pob != ""

    def test_pob_only(self) -> None:
        from mp_parse.metadata import extract_poc_and_pob

        text = "BEGINNING at an iron pin in the southerly line of Elm Street; THENCE North"
        poc, pob = extract_poc_and_pob(text)
        assert poc == ""
        assert pob != ""

    def test_no_pob(self) -> None:
        from mp_parse.metadata import extract_poc_and_pob

        text = "some random text without any points"
        poc, pob = extract_poc_and_pob(text)
        assert poc == ""
        assert pob == ""


class TestExtractAreaStatement:
    def test_sq_ft(self) -> None:
        from mp_parse.metadata import extract_area_statement

        text = "CONTAINING 7,500 sq ft"
        result = extract_area_statement(text)
        assert result is not None
        assert result["value_sq_ft"] == 7500.0
        assert result["unit"] == "sq_ft"

    def test_acres(self) -> None:
        from mp_parse.metadata import extract_area_statement

        text = "CONTAINING 2.5 acres more or less"
        result = extract_area_statement(text)
        assert result is not None
        assert result["unit"] == "acres"
        assert result["approximate"] is True

    def test_no_area(self) -> None:
        from mp_parse.metadata import extract_area_statement

        result = extract_area_statement("THENCE North 100 feet")
        assert result is None

    def test_non_string_returns_none(self) -> None:
        from mp_parse.metadata import extract_area_statement

        result = extract_area_statement(None)  # type: ignore[arg-type]
        assert result is None


class TestExtractBasisOfBearing:
    def test_bearings_based_on(self) -> None:
        from mp_parse.metadata import extract_basis_of_bearing

        text = "Bearings based on the Pennsylvania State Plane Coordinate System."
        result = extract_basis_of_bearing(text)
        assert result is not None
        assert "Pennsylvania" in result

    def test_no_basis(self) -> None:
        from mp_parse.metadata import extract_basis_of_bearing

        result = extract_basis_of_bearing("THENCE North 100 feet")
        assert result is None


class TestExtractSurveyorCertification:
    def test_i_hereby_certify(self) -> None:
        from mp_parse.metadata import extract_surveyor_certification

        text = "I hereby certify that this survey was made under my direction."
        result = extract_surveyor_certification(text)
        assert result is not None
        assert "certify" in result.lower()

    def test_no_certification(self) -> None:
        from mp_parse.metadata import extract_surveyor_certification

        result = extract_surveyor_certification("THENCE North 100 feet")
        assert result is None


class TestExtractPriorConveyance:
    def test_being_same_premises(self) -> None:
        from mp_parse.metadata import extract_prior_conveyance

        text = "BEING the same premises conveyed by Deed Book 123 Page 456."
        result = extract_prior_conveyance(text)
        assert result is not None
        assert "same premises" in result

    def test_no_prior_conveyance(self) -> None:
        from mp_parse.metadata import extract_prior_conveyance

        result = extract_prior_conveyance("THENCE North 100 feet")
        assert result is None


class TestExtractDeedClauses:
    def test_subject_to(self) -> None:
        from mp_parse.metadata import extract_deed_clauses

        text = "SUBJECT TO all easements and restrictions of record."
        result = extract_deed_clauses(text)
        assert len(result) >= 1
        assert result[0].clause_type == "subject_to"

    def test_no_clauses(self) -> None:
        from mp_parse.metadata import extract_deed_clauses

        result = extract_deed_clauses("THENCE North 100 feet")
        assert result == []


class TestExtractSubdivisionReference:
    def test_lot_and_block(self) -> None:
        from mp_parse.metadata import extract_subdivision_reference

        text = "Lot 5, Block 2, SUNRISE ESTATES, Plat Book 12, Page 34"
        result = extract_subdivision_reference(text)
        assert result is not None
        assert result.lot == "5"
        assert result.block == "2"

    def test_no_subdivision(self) -> None:
        from mp_parse.metadata import extract_subdivision_reference

        result = extract_subdivision_reference("THENCE North 100 feet")
        assert result is None


class TestExtractWitnessTrees:
    def test_witness_tree(self) -> None:
        from mp_parse.metadata import extract_witness_trees

        text = "a white oak 12 inches bears N 45 E dist 20 links"
        result = extract_witness_trees(text)
        assert len(result) >= 1
        assert "oak" in result[0].lower()

    def test_no_trees(self) -> None:
        from mp_parse.metadata import extract_witness_trees

        result = extract_witness_trees("THENCE North 100 feet")
        assert result == []


class TestExtractCoordinateSystem:
    def test_state_plane(self) -> None:
        from mp_parse.metadata import extract_coordinate_system

        text = "State Plane Coordinate System, Pennsylvania South Zone, FIPS 3702."
        coord_sys, fips = extract_coordinate_system(text)
        assert coord_sys is not None
        assert "State Plane" in coord_sys
        assert fips == "3702"

    def test_no_coordinate_system(self) -> None:
        from mp_parse.metadata import extract_coordinate_system

        coord_sys, fips = extract_coordinate_system("THENCE North 100 feet")
        assert coord_sys is None
        assert fips is None


class TestInferDistanceUnit:
    def test_varas_in_text(self) -> None:
        from mp_parse.metadata import infer_distance_unit

        result = infer_distance_unit("100 varas to an oak")
        assert result == "varas"

    def test_texas_pre_1900(self) -> None:
        from mp_parse.metadata import infer_distance_unit

        result = infer_distance_unit("100 feet to a pin", state="TX", year=1850)
        assert result == "varas"

    def test_louisiana(self) -> None:
        from mp_parse.metadata import infer_distance_unit

        result = infer_distance_unit("100 feet to a pin", state="LA")
        assert result == "arpents"

    def test_no_inference(self) -> None:
        from mp_parse.metadata import infer_distance_unit

        result = infer_distance_unit("100 feet to a pin")
        assert result is None


class TestIsIndefiniteCall:
    def test_cardinal_only(self) -> None:
        from mp_parse.metadata import is_indefinite_call

        assert is_indefinite_call("northeasterly", has_bearing=False) is True

    def test_with_bearing_not_indefinite(self) -> None:
        from mp_parse.metadata import is_indefinite_call

        assert is_indefinite_call("north", has_bearing=True) is False

    def test_empty_not_indefinite(self) -> None:
        from mp_parse.metadata import is_indefinite_call

        assert is_indefinite_call("", has_bearing=False) is False

    def test_wardly_suffix(self) -> None:
        from mp_parse.metadata import is_indefinite_call

        assert is_indefinite_call("northwardly", has_bearing=False) is True

    def test_physical_reference(self) -> None:
        from mp_parse.metadata import is_indefinite_call

        assert is_indefinite_call("down the creek", has_bearing=False) is True


class TestDetectMeander:
    def test_water_body(self) -> None:
        from mp_parse.metadata import detect_meander

        assert detect_meander("along the creek to a point") is True

    def test_meander_keyword(self) -> None:
        from mp_parse.metadata import detect_meander

        assert detect_meander("meander line along the river") is True

    def test_no_meander(self) -> None:
        from mp_parse.metadata import detect_meander

        assert detect_meander("THENCE North 100 feet") is False

    def test_empty_string(self) -> None:
        from mp_parse.metadata import detect_meander

        assert detect_meander("") is False


class TestIsClosureToPob:
    def test_to_beginning(self) -> None:
        from mp_parse.metadata import is_closure_to_pob

        assert is_closure_to_pob("thence North 100 feet to the point of beginning") is True

    def test_to_pob(self) -> None:
        from mp_parse.metadata import is_closure_to_pob

        assert is_closure_to_pob("thence N 45 E 50 feet to the POB") is True

    def test_not_closure(self) -> None:
        from mp_parse.metadata import is_closure_to_pob

        assert is_closure_to_pob("thence North 100 feet to an iron pin") is False


class TestSplitIntoCalls:
    def test_thence_separated(self) -> None:
        from mp_parse.metadata import split_into_calls

        text = "BEGINNING at pin; THENCE North 100 feet; THENCE East 50 feet"
        result = split_into_calls(text)
        assert len(result) == 2  # BEGINNING is excluded

    def test_numbered_calls(self) -> None:
        from mp_parse.metadata import split_into_calls

        text = "1. North 100 feet\n2. East 50 feet\n3. South 100 feet"
        result = split_into_calls(text)
        assert len(result) == 3


class TestExtractDistance:
    @pytest.mark.parametrize(
        "text",
        [
            "10 chains and 50 links, 3 rods from the corner",
            "10 chains and 50 links 3 rods from the corner",
        ],
    )
    def test_and_compound_not_merged_with_trailing_measurement(self, text: str) -> None:
        from mp_parse.metadata import extract_distance

        value, unit = extract_distance(text)
        assert value == pytest.approx(693.0)
        assert unit == "feet"

    def test_implicit_pair_followed_by_and_part_keeps_leading_component(self) -> None:
        from mp_parse.metadata import extract_distance

        value, unit = extract_distance("10 chains 50 links and 3 perches")
        assert value == pytest.approx(742.5)
        assert unit == "feet"

    def test_feet(self) -> None:
        from mp_parse.metadata import extract_distance

        value, unit = extract_distance("125.26 feet to an iron pin")
        assert value == 125.26
        assert unit == "feet"

    def test_poles(self) -> None:
        from mp_parse.metadata import extract_distance

        value, unit = extract_distance("10 poles to a stake")
        assert value == 10.0
        assert unit == "poles"

    def test_comma_number(self) -> None:
        from mp_parse.metadata import extract_distance

        value, unit = extract_distance("1,200 feet along the road")
        assert value == 1200.0
        assert unit == "feet"

    def test_no_distance(self) -> None:
        from mp_parse.metadata import extract_distance

        value, unit = extract_distance("along the creek")
        assert value == 0.0
        assert unit == "feet"


class TestSplitExceptionClauses:
    def test_no_exceptions(self) -> None:
        from mp_parse.metadata import split_exception_clauses

        result = split_exception_clauses("THENCE North 100 feet")
        assert len(result) == 1
        assert result[0][1] is False  # not an exception

    def test_except_clause(self) -> None:
        from mp_parse.metadata import split_exception_clauses

        text = "Main tract description. EXCEPT the southerly 10 feet"
        result = split_exception_clauses(text)
        assert len(result) >= 2
        # At least one should be an exception
        exceptions = [r for r in result if r[1] is True]
        assert len(exceptions) >= 1


def test_extract_distance_compound_without_and():
    from mp_parse.metadata import extract_distance

    assert extract_distance("N 10° E 2 chains 20 links") == (145.2, "feet")
    # Descending units form one measurement; equivalent units are two lengths
    # (ambiguous: neither is chosen).
    assert extract_distance("40 poles 5 feet") == (665.0, "feet")
    assert extract_distance("40 poles 2 rods") == (0.0, "feet")
    assert extract_distance("150 feet, 3 rods north of the oak") == (150.0, "feet")


_DISTANCE_TABLE = [
    # The fallback "and" compound must not skip the leading measurement. An
    # unsummable run returns 0.0, which callers reject as an unsupported
    # compound course distance rather than silently dropping the chain.
    ("1 chain, 2 rods and 3 links", (0.0, "feet")),
    ("10 chains 50 links and 3 perches", (742.5, "feet")),
    ("10 chains and 50 links, 3 rods from the corner", (693.0, "feet")),
    ("150 feet, 3 rods north of the oak", (150.0, "feet")),
    ("40 poles 2 rods", (0.0, "feet")),
    ("2 rods and 3 links", (34.98, "feet")),
    ("N 10 E 150 feet to a stake 2 chains 20 links west of a white oak", (150.0, "feet")),
    ("N 10 E 150 feet distant 2 chains 20 links from the oak", (150.0, "feet")),
    # An unlabelled second length is a second course length: ambiguous, none chosen.
    ("N 10 E 150 feet from a stake 2 chains 20 links west", (0.0, "feet")),
    ("N 10 E 150 feet to a stake 2 chains 20 links", (0.0, "feet")),
    ("N 10 E 2 chains 20 links to a stake", (145.2, "feet")),
    ("N 10 E 2 chains 20 links to a stake 3 chains 5 links west of an oak", (145.2, "feet")),
]


@pytest.mark.parametrize(("text", "expected"), _DISTANCE_TABLE)
def test_extract_distance_compound_table(text, expected):
    import re

    from mp_models.units import ConversionFactors
    from mp_parse.metadata import extract_distance

    value, unit = extract_distance(text)
    assert value == pytest.approx(expected[0])
    assert unit == expected[1]
    # Invariant: the result never omits the first measurement in the text.
    first = re.search(r"([\d.]+)\s*(chain|rod|pole|perch|feet|link)", text)
    plural = "feet" if first.group(2) == "feet" else first.group(2) + "s"
    first_ft = ConversionFactors.convert_to_feet(float(first.group(1)), plural)
    result_ft = ConversionFactors.convert_to_feet(value, unit)
    assert value == 0.0 or result_ft >= first_ft - 1e-9
    # ...and a larger result is only valid as a compound that starts at the
    # first measurement (a later chain/link pair must never replace it).
    if value != 0.0 and result_ft > first_ft + 1e-9:
        rest = text[first.end() :]
        assert re.match(r"[A-Za-z]*\s*(?:,|\band\b)?\s*[\d.]+\s*[A-Za-z]", rest)
