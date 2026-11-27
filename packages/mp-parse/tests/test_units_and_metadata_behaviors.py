"""High-signal behavioral tests for mp_parse.units and mp_parse.metadata.

Covers historical survey units, stated area edge cases (parent-tract context,
negative/scientific/zero areas, compound area failures), PLSS false-positive
guards, course-list helpers, malformed length prefixes, bracket/passing clause
edge cases, prior conveyance formats, subdivision article guards, distance-unit
inference, and strip-exception helpers.
"""

from __future__ import annotations

import pytest
from mp_models.units import ConversionFactors
from mp_parse.calls import extract_single_call
from mp_parse.metadata import (
    break_inline_course_enumerators,
    course_list_count_mismatches,
    detect_strip_exceptions,
    extract_area_statement,
    extract_course_clause,
    extract_deed_clauses,
    extract_plss_metadata,
    extract_pob,
    extract_prior_conveyance,
    extract_subdivision_reference,
    infer_distance_unit,
    read_course_length,
    split_into_calls,
    strip_exception_spans,
)
from mp_parse.units import normalize_unit_token

# ---------------------------------------------------------------------------
# 1. Units: historical survey units and normalization
# ---------------------------------------------------------------------------


class TestUnitTokenNormalization:
    """All supported historical and survey length units map to ConversionFactors keys."""

    @pytest.mark.parametrize(
        ("token", "expected"),
        [
            ("engineer chain", "engineer_chains"),
            ("Engineer Chains", "engineer_chains"),
            ("engineer link", "engineer_links"),
            ("engineer links", "engineer_links"),
            ("US survey foot", "us_survey_feet"),
            ("US survey feet", "us_survey_feet"),
            ("vara", "varas"),
            ("varas", "varas"),
            ("arpent", "arpents"),
            ("arpents", "arpents"),
            ("toise", "toises"),
            ("toises", "toises"),
            ("furlong", "furlongs"),
            ("furlongs", "furlongs"),
            ("unknown_unit", "feet"),
        ],
    )
    def test_normalize_unit_token_historical_and_fallback(self, token: str, expected: str) -> None:
        assert normalize_unit_token(token) == expected

    @pytest.mark.parametrize(
        ("unit_text", "value", "expected_unit"),
        [
            ("100 varas", 100.0, "varas"),
            ("2 arpents", 2.0, "arpents"),
            ("50 toises", 50.0, "toises"),
            ("1 furlong", 1.0, "furlongs"),
            ("3 engineer chains", 3.0, "engineer_chains"),
            ("25 engineer links", 25.0, "engineer_links"),
            ("100 US survey feet", 100.0, "us_survey_feet"),
        ],
    )
    def test_historical_units_converted_in_call_extraction(
        self, unit_text: str, value: float, expected_unit: str
    ) -> None:
        call = extract_single_call(f"thence N 45°00' E {unit_text} to an iron pin", 1)
        assert call is not None
        expected_ft = ConversionFactors.convert_to_feet(value, expected_unit)
        assert call.distance_ft == pytest.approx(expected_ft, rel=1e-6)


# ---------------------------------------------------------------------------
# 2. Stated area statements: parent-tract context, malformed/negative/zero areas
# ---------------------------------------------------------------------------


class TestAreaStatementEdgeCases:
    """Fail-closed area extraction and parent-tract exclusion."""

    def test_parent_tract_prefix_excluded_in_favor_of_parcel_area(self) -> None:
        text = (
            "Being part of a larger tract containing approx. 10.5 acres; "
            "the parcel herein conveyed containing 2.25 acres more or less."
        )
        area = extract_area_statement(text)
        assert area is not None
        assert area["unit"] == "acres"
        assert area["value_sq_ft"] == pytest.approx(2.25 * ConversionFactors.ACRE_TO_SQ_FEET)
        assert area["approximate"] is True

    def test_parent_tract_prefix_separated_by_sentence_period_allows_later_area(self) -> None:
        text = (
            "Being part of the original tract of land as recorded in Vol. 12. "
            "Containing 5,000 sq. ft. more or less."
        )
        area = extract_area_statement(text)
        assert area is not None
        assert area["value_sq_ft"] == pytest.approx(5000.0)
        assert area["unit"] == "sq_ft"

    def test_area_followed_by_parent_tract_reference_excluded(self) -> None:
        text = "Containing 2 acres 1 rood of the parent tract as surveyed."
        assert extract_area_statement(text) is None

    def test_area_with_abbreviation_period_before_parent_tract_excluded(self) -> None:
        text = "Containing 10,000 sq. ft. approx. of the original tract."
        assert extract_area_statement(text) is None

    def test_standalone_area_without_leading_space_supported(self) -> None:
        area = extract_area_statement("2.5 acres")
        assert area is not None
        assert area["unit"] == "acres"
        assert area["value_sq_ft"] == pytest.approx(2.5 * ConversionFactors.ACRE_TO_SQ_FEET)

    def test_sq_ft_sentence_break_before_parent_tract_keeps_parcel_area(self) -> None:
        text = "Containing 6,500 sq. ft. Said parcel is part of the parent tract."
        area = extract_area_statement(text)
        assert area is not None
        assert area["value_sq_ft"] == pytest.approx(6500.0)

    def test_conveyed_portion_recital_after_area_keeps_parcel_area(self) -> None:
        text = "Containing 1.5 acres, being a portion of the parent tract."
        area = extract_area_statement(text)
        assert area is not None
        assert area["value_sq_ft"] == pytest.approx(1.5 * ConversionFactors.ACRE_TO_SQ_FEET)

    def test_bare_area_in_prose_without_parcel_lead_returns_none(self) -> None:
        text = "Lying adjacent to a 5 acre municipal park in the county."
        assert extract_area_statement(text) is None

    def test_scientific_notation_area_fails_closed(self) -> None:
        area = extract_area_statement("CONTAINING approx. 1.5e3 sq ft")
        assert area is not None
        assert area["value_sq_ft"] == 0.0
        assert area["unit"] == "unsupported scientific notation (sq_ft)"
        assert area["approximate"] is True

    @pytest.mark.parametrize(
        ("text", "expected_sign"),
        [
            ("CONTAINING - 2.5 acres", -1),
            ("- 500 sq ft", -1),
            ("CONTAINING 0 acres more or less", 0),
        ],
    )
    def test_spaced_negative_and_zero_areas_fail_closed(
        self, text: str, expected_sign: int
    ) -> None:
        area = extract_area_statement(text)
        assert area is not None
        if expected_sign == 0:
            assert area["value_sq_ft"] == 0.0
        else:
            assert area["value_sq_ft"] < 0.0

    @pytest.mark.parametrize(
        "text",
        [
            "CONTAINING 2 acres and -50 perches",
            "CONTAINING 1 acre - 5 roods",
        ],
    )
    def test_compound_area_with_negative_component_fails_closed(self, text: str) -> None:
        area = extract_area_statement(text)
        assert area is not None
        assert area["unit"] == "compound"
        assert area["value_sq_ft"] < 0.0

    def test_area_clause_boundary_skips_abbreviation_period(self) -> None:
        text = "Being part of the parent tract. Containing approx. 2 acres."
        area = extract_area_statement(text)
        assert area is not None
        assert area["unit"] == "acres"
        assert area["value_sq_ft"] == pytest.approx(2.0 * ConversionFactors.ACRE_TO_SQ_FEET)
        assert area["approximate"] is True


# ---------------------------------------------------------------------------
# 3. PLSS metadata guards and POB edge cases
# ---------------------------------------------------------------------------


class TestPlssAndPobGuards:
    """PLSS false-positive guards for SEC, P.M., and aliquots, plus unterminated POB."""

    def test_sec_guards_reject_out_of_range_lengths_and_bearing_seconds(self) -> None:
        # Out-of-range section number (>36), length-followed SEC, and bearing seconds rejected;
        # valid survey reference ("LOT 12 SEC 10") is accepted.
        text = "SEC 40, SEC 10 FT, N 89 DEG 05 MIN 15 SEC 12, LOT 12 SEC 10 T2S R9E"
        plss = extract_plss_metadata(text)
        assert plss["section"] == "10"
        assert plss["township"] == "2 S"
        assert plss["range"] == "9 E"

    def test_time_of_day_pm_not_misread_as_principal_meridian(self) -> None:
        text = "Recorded at 3 P.M. and filed at 3 o'clock P.M., noon P.M. in Section 5, T1N, R2E."
        plss = extract_plss_metadata(text)
        assert plss["principal_meridian"] is None
        assert plss["section"] == "5"

    def test_abbreviated_principal_meridian_extracted_outside_time_phrase(self) -> None:
        text = "Section 5, Township 1 North, Range 2 East, 6th P.M."
        plss = extract_plss_metadata(text)
        assert plss["principal_meridian"] == "6Th Principal Meridian"

    def test_aliquot_guards_reject_bearings_lengths_and_unanchored_fractions(self) -> None:
        assert extract_plss_metadata("THENCE N 1/2° E 100 feet")["aliquot"] is None
        assert extract_plss_metadata("along the N 1/2 feet strip")["aliquot"] is None
        assert extract_plss_metadata("the N 1/2 of the building")["aliquot"] is None
        assert extract_plss_metadata("the N 1/2 of Section 12")["aliquot"] == "N 1/2"
        assert (
            extract_plss_metadata("the NE 1/4 of the NW 1/4")["aliquot"] == "NE 1/4 OF THE NW 1/4"
        )

    def test_extract_pob_without_sentence_terminator_returns_empty(self) -> None:
        assert extract_pob("BEGINNING at an iron pin on the north line of Main Street") == ""


# ---------------------------------------------------------------------------
# 4. Course-list helpers, length guards, and clause edge cases
# ---------------------------------------------------------------------------


class TestCourseListAndLengthGuards:
    """Header-led splitting, enumerators, malformed lengths, and passing/bracket clauses."""

    def test_split_into_calls_header_led_merges_digitless_continuation_and_keeps_single(
        self,
    ) -> None:
        # First header has a digitless continuation clause that stays glued to course 1;
        # second header has only one course after the semicolon so stays unsplit.
        text = (
            "THENCE the following two courses: N 10° E 100 feet; along the fence; "
            "S 80° E 50 feet. "
            "THENCE the following course: N 10° E 100 feet; along the fence."
        )
        result = split_into_calls(text)
        assert result == [
            "the following two courses:",
            "N 10° E 100 feet; along the fence",
            "S 80° E 50 feet",
            "the following course: N 10° E 100 feet; along the fence",
        ]

    def test_course_list_public_helpers_and_single_letter_guard(self) -> None:
        inline = "THENCE the following three courses: (1) N 10° E 100 feet; (2) S 80° E 50 feet. CONTAINING 1 acre."
        broken = break_inline_course_enumerators(inline)
        assert "\n(1) N 10° E 100 feet;" in broken
        assert "\n(2) S 80° E 50 feet." in broken
        assert course_list_count_mismatches(inline) == [(3, 2)]

        # Unenumerated counted header bounded by CONTAINING metadata boundary
        unenumerated = "THENCE the following three courses: N 10° E 100 feet; S 80° E 50 feet. CONTAINING 2 acres."
        assert course_list_count_mismatches(unenumerated) == [(3, 2)]

        # A lone lettered "(a)" without "(b)" is not rewritten as a course list
        lone_letter = "THENCE (a) N 10° E 100 feet to a pin."
        assert break_inline_course_enumerators(lone_letter) == lone_letter

    def test_unsupported_and_pair_vs_physical_monument_feature(self) -> None:
        # Unknown word after "and <n>" fails closed (0.0); physical monument count is allowed.
        assert read_course_length("N 45° E 10 chains and 5 widgets").value == 0.0
        allowed = read_course_length("N 45° E 10 chains and 5 oak trees")
        assert allowed.value == 10.0
        assert allowed.unit == "chains"

    @pytest.mark.parametrize(
        "text",
        [
            "N 45° E -100 feet to a pin",
            "N 45° E \u2212 100 feet to a pin",
            "- 100 feet to a pin",
            "N 45° E a distance of - 100 feet to a pin",
            "N 45° E 1e2 feet to a pin",
            "N 45° E 1e2' to a pin",
            "N 45° E -100' to a pin",
        ],
    )
    def test_malformed_negative_and_scientific_lengths_fail_closed(self, text: str) -> None:
        reading = read_course_length(text)
        assert reading.value == 0.0

    def test_foot_mark_after_unsigned_degrees_and_oversized_inches(self) -> None:
        # "30'" inside "N 45 30' E" is bearing minutes, not a foot-mark length.
        clause = extract_course_clause(
            "thence N 45 30' E 100' along Elm Street to a pin", trim_course_length=True
        )
        assert clause.along == "Elm Street"
        assert clause.to == "a pin"
        assert read_course_length("N 45 30' E 100' to a pin").value == 100.0

        # Foot-inch with >= 12 inches is unread and fails closed as ambiguous.
        oversized = read_course_length("N 45° E 10' 14\" to a pin")
        assert oversized.value == 0.0
        assert "10' 14\"" in oversized.ambiguous

    def test_extract_course_clause_stray_bracket_and_nested_passing(self) -> None:
        clause = extract_course_clause(
            "thence N 45° E 100 feet (passing a pipe and passing a stone) to a pin) extra"
        )
        assert clause.passing == ("passing a pipe and passing a stone",)
        assert "a pin" in clause.to


# ---------------------------------------------------------------------------
# 5. Prior conveyance, deed clauses, subdivision, unit inference, strip helpers
# ---------------------------------------------------------------------------


class TestMetadataExtractionVariants:
    """Remaining metadata extraction paths and false-positive guards."""

    def test_prior_conveyance_book_and_instrument_formats(self) -> None:
        assert (
            extract_prior_conveyance("Recorded in Deed Book 412, Page 88.")
            == "Deed Book 412, Page 88"
        )
        assert (
            extract_prior_conveyance("See Instrument Number 2024001234 of County Records.")
            == "Instrument Number 2024001234 of County Records"
        )

    def test_extract_deed_clauses_deduplicates_nested_keyword_in_same_sentence(self) -> None:
        text = "SUBJECT TO utility easements and SUBJECT TO drainage restrictions of record."
        clauses = extract_deed_clauses(text)
        assert len(clauses) == 1
        assert clauses[0].clause_type == "subject_to"
        assert "drainage restrictions" in clauses[0].text

    @pytest.mark.parametrize(
        ("text", "expected_name"),
        [
            ("Lot 4, THE OAKS ESTATES, Plat Book 9, Page 21", "THE OAKS ESTATES"),
            ("Lot 4, THE NORTH ESTATES, Plat Book 9, Page 21", "THE NORTH ESTATES"),
            ("Lot 4, THE FOLLOWING PREMISES", None),
            ("Lot 4, THE SOUTH HALF OF SAID LOT", None),
        ],
    )
    def test_subdivision_reference_the_prefix_guards(
        self, text: str, expected_name: str | None
    ) -> None:
        ref = extract_subdivision_reference(text)
        assert ref is not None
        assert ref.lot == "4"
        assert ref.subdivision_name == expected_name

    @pytest.mark.parametrize(
        ("text", "state", "year", "expected"),
        [
            ("running 10 chains and links to a stone", None, None, "chains"),
            ("measuring 4 arpents along the bayou", None, None, "arpents"),
            ("running north 20 to an oak", "MA", 1820, "rods"),
        ],
    )
    def test_infer_distance_unit_chains_arpents_and_new_england(
        self, text: str, state: str | None, year: int | None, expected: str
    ) -> None:
        assert infer_distance_unit(text, state=state, year=year) == expected

    def test_strip_exception_drops_thereof_purpose_and_deduplicates_overlapping_patterns(
        self,
    ) -> None:
        exceptions = detect_strip_exceptions("Subject to thereof over the West 30 feet.")
        assert len(exceptions) == 1
        assert exceptions[0]["direction"] == "West"
        assert exceptions[0]["width_ft"] == 30.0
        assert exceptions[0]["purpose"] is None

        # First pattern matches "except the West 30 feet thereof"; second overlapping
        # "subject to ... over the West 30 feet thereof" is deduplicated.
        text = "Subject to an easement, except the West 30 feet thereof, over the West 30 feet thereof."
        spans = strip_exception_spans(text)
        assert len(spans) == 1
        assert spans[0][2]["direction"] == "West"
        assert spans[0][2]["width_ft"] == 30.0
