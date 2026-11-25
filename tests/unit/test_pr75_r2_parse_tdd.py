"""Strict Red-Green TDD regressions for PR #75 round-2 mp-parse review findings."""

from __future__ import annotations

import re

import pytest

# ---------------------------------------------------------------------------
# #3. Fail-closed compound-distance truncation (metadata.py)
# ---------------------------------------------------------------------------


class TestCompoundDistanceFailClosed:
    @pytest.mark.parametrize(
        "text",
        [
            "100 feet and 2 nautical miles",
            "100 feet and 2 decametres",
            "100 feet and 2 Gunter links",
            "100 feet and 5 tenths",
            "100 feet and 25 hundredths",
            "10 feet and 25 cubits",
            "100 feet and 3 unknownunits",
        ],
    )
    def test_unsupported_second_component_fails_closed(self, text: str) -> None:
        from mp_parse.metadata import _unsupported_and_pair, extract_distance

        assert _unsupported_and_pair(text, 0) is True
        assert extract_distance(text) == (0.0, "feet")

    @pytest.mark.parametrize(
        "text",
        [
            "1 chain and 25 links and 2 nautical miles",
            "1 chain and 25 links and 5 tenths",
            "1 chain and 25 links and 25 hundredths",
            "1 chain and 25 links and 2 Gunter links",
            "1 chain and 25 links and 3 unknownunits",
        ],
    )
    def test_three_component_unsupported_tail_fails_closed(self, text: str) -> None:
        from mp_parse.metadata import extract_distance

        assert extract_distance(text) == (0.0, "feet")

    @pytest.mark.parametrize(
        "text",
        [
            "THENCE N 45° E 100 feet and 2 nautical miles to a corner",
            "THENCE N 45° E 100 feet and 2 decametres to a corner",
            "THENCE N 45° E 100 feet and 2 Gunter links to a corner",
            "THENCE N 45° E 100 feet and 5 tenths to a corner",
            "THENCE N 45° E 100 feet and 25 hundredths to a corner",
        ],
    )
    def test_extract_single_call_rejects_unsupported_compound_distance(self, text: str) -> None:
        from mp_parse.calls import extract_single_call

        with pytest.raises(ValueError):
            extract_single_call(text, 1)

    @pytest.mark.parametrize(
        "text",
        [
            "100 feet and 2 concrete monuments",
            "100 feet and 2 iron pins",
            "100 feet and 2 iron rods",
            "100 feet and 2 steel pipes",
            "100 feet and 2 wooden stakes",
            "100 feet and 2 stone bounds",
            "100 feet and 2 granite markers",
            "100 feet and 2 brass disks",
            "100 feet and 2 aluminum caps",
            "100 feet and 2 oak trees",
            "100 feet and 2 white oaks",
            "100 feet and 2 witness trees",
            "100 feet and 2 drill holes",
            "100 feet and 2 chiseled x",
            "100 feet and 2 stakes to a corner",
        ],
    )
    def test_monument_and_physical_feature_counts_remain_allowed(self, text: str) -> None:
        from mp_parse.metadata import _unsupported_and_pair, extract_distance

        assert _unsupported_and_pair(text, 0) is False
        assert extract_distance(text) == (100.0, "feet")

    def test_three_component_compound_followed_by_monument_count_allowed(self) -> None:
        from mp_parse.metadata import extract_distance

        value, unit = extract_distance("1 chain and 25 links and 2 concrete monuments")
        assert value == pytest.approx(82.5)
        assert unit == "feet"


# ---------------------------------------------------------------------------
# #4. Preserve 2-digit decimal commas in COMMA_NUMBER (numbers.py & calls.py)
# ---------------------------------------------------------------------------


class TestCommaNumberDecimalComma:
    @pytest.mark.parametrize(
        "token",
        [
            "1,200.50",
            "1,200,000",
            "300,07",
            "90,50",
            "35,00",
            "12,50",
            "100",
            "100.5",
        ],
    )
    def test_comma_number_fullmatch_accepts_valid_forms(self, token: str) -> None:
        from mp_parse.numbers import COMMA_NUMBER

        assert re.fullmatch(COMMA_NUMBER, token) is not None

    @pytest.mark.parametrize(
        "token",
        [
            "500,",
            "1,,2",
            "1,2,3",
            "12,3456",
            "12,34.5",
            "1234,567",
            "100,5",
        ],
    )
    def test_comma_number_fullmatch_rejects_malformed_commas(self, token: str) -> None:
        from mp_parse.numbers import COMMA_NUMBER

        assert re.fullmatch(COMMA_NUMBER, token) is None

    @pytest.mark.parametrize(
        "token",
        [
            "1,,2",
            "1,2,3",
            "12,3456",
            "1234,567",
            "100,5",
        ],
    )
    def test_comma_number_search_does_not_match_inner_suffix(self, token: str) -> None:
        from mp_parse.numbers import COMMA_NUMBER

        assert re.search(COMMA_NUMBER, token) is None

    def test_curve_pattern_reads_two_digit_decimal_comma_delta(self) -> None:
        from mp_parse.calls import extract_curve_info

        info_90 = extract_curve_info(
            "curve to the right with a radius of 100 feet and a delta of 90,50 degrees"
        )
        assert info_90["delta_deg"] == pytest.approx(90.5)

        info_35 = extract_curve_info(
            "curve to the right with a radius of 100 feet and a delta of 35,00 degrees"
        )
        assert info_35["delta_deg"] == pytest.approx(35.0)

        info_dms = extract_curve_info(
            "curve to the right with a radius of 100 feet and a delta of 45° 30' 12,50\""
        )
        assert info_dms["delta_deg"] == pytest.approx(45.0 + 30.0 / 60.0 + 12.5 / 3600.0)

    def test_curve_delta_fallback_reads_two_digit_decimal_comma(self) -> None:
        from mp_parse.calls import extract_curve_info

        info = extract_curve_info(
            "curve to the right having a delta angle of 90,50 degrees and an arc length of 157.08 feet"
        )
        assert info["delta_deg"] == pytest.approx(90.5)

    def test_curve_pattern_does_not_fabricate_from_malformed_comma_delta(self) -> None:
        from mp_parse.calls import extract_curve_info

        info = extract_curve_info(
            "curve to the right with a radius of 100 feet and a delta of 1,2,3 degrees"
        )
        assert info.get("delta_deg") is None


# ---------------------------------------------------------------------------
# #5. Never fabricate unstated radius_ft (calls.py)
# ---------------------------------------------------------------------------


class TestNoFabricatedRadius:
    def test_delta_and_arc_curve_without_radius_never_fabricates_radius(self) -> None:
        from mp_models import SkippedCourse
        from mp_parse.calls import extract_calls, extract_single_call

        curve_text = (
            "THENCE along a curve to the right having a delta angle of 90 degrees "
            "and an arc length of 157.08 feet to a point"
        )
        with pytest.raises(ValueError, match="Curve geometry requires radius_ft"):
            extract_single_call(curve_text, 1)

        skipped: list[SkippedCourse] = []
        calls, _ = extract_calls(curve_text, strict=False, skipped_courses=skipped)
        assert calls == []
        assert len(skipped) == 1
        assert "radius_ft" in skipped[0].error

    @pytest.mark.parametrize("delta_str", ["400 degrees", "0 degrees"])
    def test_delta_and_arc_curve_rejects_invalid_delta_range(self, delta_str: str) -> None:
        from mp_parse.calls import extract_single_call

        curve_text = (
            f"THENCE along a curve to the right having a delta angle of {delta_str} "
            "and an arc length of 157.08 feet to a point"
        )
        with pytest.raises(ValueError):
            extract_single_call(curve_text, 1)

    def test_non_course_curve_preamble_is_not_initial_course_prefix(self) -> None:
        from mp_parse.calls import _is_initial_course_prefix

        assert _is_initial_course_prefix("along the curve of Pine Road;") is False


# ---------------------------------------------------------------------------
# #10. Prevent false-positive PLSS aliquot extraction (metadata.py)
# ---------------------------------------------------------------------------


class TestPlssAliquotGuards:
    @pytest.mark.parametrize(
        "text",
        [
            "THENCE N 1/2 mile to the road",
            "THENCE S 1/4 mile",
            "THENCE N 1/2° E 100 feet",
            "THENCE N 1/2 deg E 100 feet",
            "THENCE N 1/2 feet to a corner",
            "THENCE S 1/4 rods to a stake",
            "THENCE N 1/2 to the corner",
            "Section 12, T3N, R4W; THENCE N 1/2 mile to the road",
            "Section 12, T3N, R4W; THENCE N 1/2° E 100 feet",
        ],
    )
    def test_non_plss_fractions_do_not_extract_aliquot(self, text: str) -> None:
        from mp_parse.metadata import extract_plss_metadata

        assert extract_plss_metadata(text)["aliquot"] is None

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("the N 1/2 of Section 12, T3N, R4W", "N 1/2"),
            ("the NE 1/4 of Section 12", "NE 1/4"),
            ("the SW¼ of Lot 3", "SW1/4"),
            ("Part of the E 1/2 of Government Lot 2", "E 1/2"),
            ("Part of the W 1/2 of Tract 5", "W 1/2"),
            ("the NE 1/4 of the SW 1/4", "NE 1/4 OF THE SW 1/4"),
            ("THENCE N 1/2 mile to the NE 1/4 of Section 12", "NE 1/4"),
        ],
    )
    def test_valid_plss_aliquots_still_extract(self, text: str, expected: str) -> None:
        from mp_parse.metadata import extract_plss_metadata

        assert extract_plss_metadata(text)["aliquot"] == expected


# ---------------------------------------------------------------------------
# #11. Guard TH -> thence expansion (normalizer.py)
# ---------------------------------------------------------------------------


class TestThExpansionGuards:
    @pytest.mark.parametrize(
        "text",
        [
            "4 TH STREET",
            "20 th day",
            "TH E LINE",
            "TH AT CORNER",
            "10 TH TO 12 TH",
            "THE THAT THIS THERE THEN",
        ],
    )
    def test_non_course_th_not_expanded(self, text: str) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(text)
        assert "thence" not in result.lower()
        assert result == text

    @pytest.mark.parametrize(
        ("text", "expected_substr"),
        [
            ("FROM NE COR TH N 45 E", "thence N 45 E"),
            ("FROM NE COR TH S 89D 05M W", "thence S 89 degrees 05 minutes W"),
            ("FROM NE COR TH E 100 FT", "thence due East 100 feet"),
            ("BEG TH ALONG THE LINE", "thence ALONG"),
            ("BEG TH WITH SAID LINE", "thence WITH"),
            ("BEG TH CURVING TO THE RIGHT", "thence CURVING"),
            ("BEG TH BY THE ROAD", "thence BY"),
            ("BEG TH ON SAID LINE", "thence ON"),
            ("BEG TH TO A PIN", "thence TO"),
            ("BEG TH DUE NORTH 100 FT", "thence DUE"),
            ("BEG TH NORTH 100 FT", "thence due North 100 feet"),
            ("BEG TH NE 100 FT", "thence NE"),
            ("BEG TH SLY 90 FT", "thence southerly"),
            ("BEG TH. S0DEG", "thence S0 degrees"),
            ("SEC 36 TH S0DEG 49M 20S W 175FT", "SEC 36 thence S0 degrees"),
            ("LOT 20 TH SLY 90 FT", "LOT 20 thence southerly"),
        ],
    )
    def test_genuine_assessor_th_expands(self, text: str, expected_substr: str) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(text)
        assert expected_substr in result


# ---------------------------------------------------------------------------
# #16. Bounded prefix slices and hoisted regex (normalizer.py & parcels.py)
# ---------------------------------------------------------------------------


class TestBoundedPrefixPerformance:
    def test_non_seconds_prefix_hoisted_to_module_level(self) -> None:
        from mp_parse import normalizer

        assert isinstance(getattr(normalizer, "_NON_SECONDS_PREFIX", None), re.Pattern)

    def test_bounded_slices_preserve_behavior_on_large_inputs(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations
        from mp_parse.parcels import detect_parcel_markers

        padding = "A" * 50_000 + " "
        norm = expand_assessor_abbreviations(padding + "LOT 12 SEC 4 AND 89D 05M 3SEC W")
        assert "LOT 12 SEC 4" in norm
        assert "3 seconds" in norm

        parcel_text = (
            padding
            + "along the west line of Parcel A: 100 feet;\n"
            + "Parcel B: BEGINNING at a pin; THENCE N 0° E 100 feet."
        )
        markers = detect_parcel_markers(parcel_text)
        assert [m["label"] for m in markers] == ["Parcel B"]
