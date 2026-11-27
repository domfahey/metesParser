"""Tests for county assessor abbreviation normalization.

Covers ``expand_assessor_abbreviations()`` and its integration in
``normalize_legal_description()`` for compressed county assessor notation:
DEG/D -> degrees, M -> minutes, S/SEC -> seconds (contextual), TH -> thence
(with ordinal/name/preposition/OCR-split guards), FT -> feet, directional
abbreviations (SLY/NLY/ELY/WLY), POB variants, ALG/COR/BEG, and OCR typos
(NODEG/NOODEG).
"""

from __future__ import annotations

import pytest
from mp_parse.normalizer import expand_assessor_abbreviations, normalize_legal_description

# ---------------------------------------------------------------------------
# 1. Individual abbreviation expansion rules
# ---------------------------------------------------------------------------


class TestIndividualExpansions:
    """Table-driven verification of each assessor abbreviation rule."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            # Degrees / minutes / seconds
            ("S0DEG", "S0 degrees"),
            ("S88DEG", "S88 degrees"),
            ("N 88D 25M", "N 88 degrees 25 minutes"),
            ("N 0D 07M", "N 0 degrees 07 minutes"),
            ("26 deg. 00 41", "26 degrees 00 41"),
            ("S0DEG 32M", "S0 degrees 32 minutes"),
            ("S88DEG 23M 20S E", "S88 degrees 23 minutes 20 seconds E"),
            ("S0DEG 32M 50S W", "S0 degrees 32 minutes 50 seconds W"),
            ("89D 05M 3SEC W", "89 degrees 05 minutes 3 seconds W"),
            ("89D 07M 40SEC E", "89 degrees 07 minutes 40 seconds E"),
            # OCR O-for-zero typos in bearings
            ("NODEG 49M E", "N0 degrees 49 minutes E"),
            ("NOODEG 07M E", "N00 degrees 07 minutes E"),
            # Feet suffix with and without spacing
            ("175FT", "175 feet"),
            ("401.55FT", "401.55 feet"),
            ("90 FT", "90 feet"),
            ("W 61.26FT POB", "W 61.26 feet to the point of beginning"),
            # Directional abbreviations
            ("TH SLY 90 FT", "thence southerly 90 feet"),
            ("TH NLY 90.02 FT", "thence northerly 90.02 feet"),
            ("ALG ELY LINE", "along easterly LINE"),
            ("TH WLY 2 FT", "thence westerly 2 feet"),
            # POB variants and misc abbreviations
            ("TO POB", "TO point of beginning"),
            ("TO P OB", "TO point of beginning"),
            ("TO P.O.B.", "TO point of beginning"),
            ("NE COR SEC 36", "NE corner SEC 36"),
            ("BEG S0DEG 32M", "beginning S0 degrees 32 minutes"),
            # Case insensitivity
            (
                "s88deg 23m 20s e 371ft",
                "s88 degrees 23 minutes 20 seconds e 371 feet",
            ),
            # TH variants in valid course contexts
            ("FROM NE COR TH S0DEG", "FROM NE corner thence S0 degrees"),
            ("BEG TH. S0DEG", "beginning thence S0 degrees"),
            ("from ne cor th. s0deg", "from ne corner thence s0 degrees"),
        ],
    )
    def test_exact_assessor_expansions(self, raw: str, expected: str) -> None:
        assert expand_assessor_abbreviations(raw) == expected

    def test_south_preserved_when_seconds_also_expanded(self) -> None:
        result = expand_assessor_abbreviations("S0DEG 49M 20S W 175FT")
        assert result == "S0 degrees 49 minutes 20 seconds W 175 feet"

    def test_standalone_south_before_distance_preserved(self) -> None:
        assert expand_assessor_abbreviations("S 45 FT") == "S 45 feet"


# ---------------------------------------------------------------------------
# 2. False-positive guards (non-expansion of words, sections, ordinals, OCR splits)
# ---------------------------------------------------------------------------


class TestAssessorGuards:
    """Non-abbreviations, section references, ordinals, names, and OCR splits stay intact."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("", ""),
            (
                "thence South 45 degrees 30 minutes East 100 feet",
                "thence South 45 degrees 30 minutes East 100 feet",
            ),
            # Ordinary words containing TH
            ("THE ABOVE", "THE ABOVE"),
            ("EXC E 60FT THEREOF", "EXC E 60 feet THEREOF"),
            # Non-expanded assessor tokens
            ("0.25 AC", "0.25 AC"),
            ("DESC AS FOLS BEG", "DESC AS FOLS beginning"),
            ("PART OF SE 1/4 SEC 10 T2S R9E", "PART OF SE 1/4 SEC 10 T2S R9E"),
            # Trailing TH at end of text (no following token)
            ("COURSE ENDS AT TH ", "COURSE ENDS AT TH "),
            # Preposition directly before TH
            ("along TH. line of Lot 4", "along TH. line of Lot 4"),
            ("corner of TH section", "corner of TH section"),
            # Title-case name after "Th." (e.g. Thomas Smith — preceded by non-preposition)
            ("owned by Th. Smith", "owned by Th. Smith"),
            # Ordinal numbers ("4 TH STREET", "20 th day")
            ("4 TH STREET", "4 TH STREET"),
            ("the 20 th day of May", "the 20 th day of May"),
            # OCR word splits ("TH E LINE", "TH AT CORNER", "TH EREOF", adjectival alley)
            ("TH E LINE OF SAID LOT", "TH E LINE OF SAID LOT"),
            ("TH AT CORNER", "TH AT CORNER"),
            ("PART TH EREOF", "PART TH EREOF"),
            ("TH E 10 foot alley", "TH E 10 foot alley"),
        ],
    )
    def test_guarded_phrases_not_mangled(self, raw: str, expected: str) -> None:
        assert expand_assessor_abbreviations(raw) == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            # "Th." before an actual bearing DOES expand
            ("Th. North 45 degrees East 100 FT", "thence North 45 degrees East 100 feet"),
            # Survey reference number before TH DOES expand
            ("LOT 4 TH N 10D E 50 FT", "LOT 4 thence N 10 degrees E 50 feet"),
            # Standalone East course after TH DOES expand
            ("POB TH E 50 FT", "point of beginning thence due East 50 feet"),
            # POB directly before "TH AT <number>" DOES expand
            ("BEG TH AT 10 FEET", "beginning thence AT 10 FEET"),
        ],
    )
    def test_valid_th_contexts_still_expand(self, raw: str, expected: str) -> None:
        assert expand_assessor_abbreviations(raw) == expected


# ---------------------------------------------------------------------------
# 3. Full county assessor legal descriptions (ground-truth deeds)
# ---------------------------------------------------------------------------


class TestFullAssessorDescriptions:
    """End-to-end normalization of representative compressed assessor deeds."""

    def test_deed_50062_deg_min_sec_and_nodeg(self) -> None:
        legal = (
            "36F8B PT OF NE 1/4 SEC 36 T2S R8E BEG S0DEG 32M 50S W 401.55FT "
            "AND N80DEG 29M 20S W 480.49FT AND S0DEG 49M 20S W 142.75FT "
            "AND N89DEG 10M 40S W 2FT FROM NE COR SEC 36 TH S0DEG 49M 20S W 175FT "
            "TH N89DEG 10M 40S W 61.23FT TH NODEG 49M E 175FT "
            "TH S89DEG 10M 40S E 61.26FT POB 0.25 AC"
        )
        result = expand_assessor_abbreviations(legal)
        assert "DEG" not in result
        assert "FT" not in result
        assert "SEC 36" in result
        assert "0.25 AC" in result
        assert "beginning S0 degrees 32 minutes 50 seconds W 401.55 feet" in result
        assert "FROM NE corner SEC 36 thence S0 degrees 49 minutes 20 seconds W 175 feet" in result
        assert "thence N0 degrees 49 minutes E 175 feet" in result
        assert "61.26 feet to the point of beginning" in result

    def test_deed_50305_directional_abbreviations_and_p_ob(self) -> None:
        legal = (
            "W MORANG THAT PT OF 20 DESC AS FOLS BEG AT NE COR OF LOT 20 "
            "TH SLY 90 FT ALG ELY LINE OF SAID LOT TH WLY 2 FT "
            "TH NLY 90.02 FT TO P OB ALSO LOTS 19&18 LEIGH G COOPERS "
            "CADIEUX-SEVEN MILE DR SUB L56 P68 PLATS. W C R 21/873 40 IRREG"
        )
        result = expand_assessor_abbreviations(legal)
        assert "DESC AS FOLS beginning AT NE corner OF LOT 20" in result
        assert "thence southerly 90 feet along easterly LINE OF SAID LOT" in result
        assert "thence westerly 2 feet thence northerly 90.02 feet TO point of beginning" in result

    def test_deed_50426_d_m_s_notation_preserves_south(self) -> None:
        legal = (
            "23J1B PT OF THE SE 1/4 OF SEC 23 T4S R10E DESC AS BEG N 88D 25M 31S E "
            "330.00 FT AND N 01D 41M 46S W 222.00 FT FROM THE S 1/4 COR OF SEC 23: "
            "TH N 01D 41M 46S W 538.05 FT TH S 89D 50M 17S E 130.07 FT "
            "TH S 01D 41M 46S E 696.11 FT TH S 88D 25M 31S W 68.00 FT "
            "TH N 01D 41M 46S W 162.00 FT TH S 88D 25M 31S W 62.00 FT 1.85 AC."
        )
        result = expand_assessor_abbreviations(legal)
        assert "N 88 degrees 25 minutes 31 seconds E 330.00 feet" in result
        assert "thence N 01 degrees 41 minutes 46 seconds W 538.05 feet" in result
        assert "thence S 89 degrees 50 minutes 17 seconds E 130.07 feet" in result
        assert "S 89D" not in result
        assert "SEC 23" in result
        assert "1.85 AC." in result

    def test_deed_50484_sec_suffix_vs_section_and_noodeg(self) -> None:
        legal1 = (
            "10L6B3A1A PART OF SE 1/4 SEC 10 T2S R9E BEG N89DEG 06M W 60FT "
            "AND N00DEG 07M E 1561.58FT FROM SE COR OF SEC 10 "
            "TH N89DEG 05M 23S W 317.77FT TH NOODEG 07M E 61.39FT "
            "TH S89DEG 33M 30S E 201.89FT TH S74DEG 45M E 147.99FT "
            "TH N00DEG 07M E 30FT TH S74DEG 45M E 34.18FT "
            "TH S0DEG 07M W 47.92FT TH N89DEG 05M 23S W 60FT POB "
            "EXC E 60FT THEREOF 0.41AC"
        )
        result1 = expand_assessor_abbreviations(legal1)
        assert "DEG" not in result1
        assert "FT" not in result1
        assert "SEC 10" in result1
        assert "thence N00 degrees 07 minutes E 61.39 feet" in result1
        assert "60 feet to the point of beginning EXC E 60 feet THEREOF 0.41AC" in result1

        legal2 = (
            "10M6B1A1 THAT PART OF THE SE 1/4 OF SEC 10 DESCRIBED AS "
            "BEGINNING AT A POINT ON THE W LINE OF MERRIMAN ROAD DISTANT "
            "N 89D 06M W 60.0 FT AND N 0D 07M E 1423.21 FT FROM THE SE CORNER "
            "OF SEC 10 AND PROCEEDING TH N 0D 07M E ALONG SAID W LINE 136.93 FT "
            "TH N 89D 05M 3SEC W 318.12 FT TH S 0D 07M W 137.57 FT "
            "TH S 89D 07M 40SEC E 318.12 FT TO THE POB 1.00 ACRE."
        )
        result2 = expand_assessor_abbreviations(legal2)
        assert "SEC 10" in result2
        assert "thence N 89 degrees 05 minutes 3 seconds W 318.12 feet" in result2
        assert (
            "thence S 89 degrees 07 minutes 40 seconds E 318.12 feet TO THE point of beginning"
            in result2
        )

    def test_deed_50633_nodeg_becomes_zero_degrees(self) -> None:
        legal = (
            "13H2C D PART OF NW 1/4 SEC 13 T4S R9E BEG AT NW COR SEC 13 "
            "TH S88DEG 23M 20S E 371FT TH S0DEG 02M 20S W 165FT "
            "TH N88DEG 23M 20S W 371FT TH NODEG 02M 20S E 165FT POB 1.40 AC"
        )
        result = expand_assessor_abbreviations(legal)
        assert "DEG" not in result
        assert "NODEG" not in result
        assert "beginning AT NW corner SEC 13" in result
        assert "thence S88 degrees 23 minutes 20 seconds E 371 feet" in result
        assert "thence S0 degrees 02 minutes 20 seconds W 165 feet" in result
        assert (
            "thence N0 degrees 02 minutes 20 seconds E 165 feet to the point of beginning" in result
        )


# ---------------------------------------------------------------------------
# 4. Integration: wired into normalize_legal_description
# ---------------------------------------------------------------------------


class TestNormalizeLegalDescriptionIntegration:
    """expand_assessor_abbreviations feeds cleanly into standardize_cardinal_directions."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("TH S88DEG 23M 20S E 371FT", "thence S 88°23'20\" E 371 feet"),
            ("TH N 01D 41M 46S W 538.05 FT", "thence N 01°41'46\" W 538.05 feet"),
            (
                "TH NODEG 02M 20S E 165FT POB",
                "thence N 0°02'20\" E 165 feet to the point of beginning",
            ),
        ],
    )
    def test_assessor_expansion_through_full_pipeline(self, raw: str, expected: str) -> None:
        assert normalize_legal_description(raw) == expected
