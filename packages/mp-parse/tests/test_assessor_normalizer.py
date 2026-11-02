"""Tests for assessor abbreviation normalization (compressed county assessor notation).

TDD tests — written BEFORE implementation.
Covers expand_assessor_abbreviations() for compressed assessor notation patterns:
  DEG/D → degrees, M → minutes, S/SEC → seconds (contextual),
  TH → thence, FT → feet, directional abbreviations, POB, ALG, COR, BEG, deg.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 1. Individual abbreviation expansion tests
# ---------------------------------------------------------------------------


class TestDegreeExpansion:
    """DEG and D as degree markers."""

    def test_deg_after_number(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        assert "0 degrees" in expand_assessor_abbreviations("S0DEG")

    def test_deg_with_space(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        assert "88 degrees" in expand_assessor_abbreviations("S88DEG")

    def test_d_after_number(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations("N 88D 25M")
        assert "88 degrees" in result

    def test_d_single_digit(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations("N 0D 07M")
        assert "0 degrees" in result

    def test_deg_dot(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations("26 deg. 00 41")
        assert "26 degrees" in result


class TestMinuteExpansion:
    """M as minutes when after degrees context."""

    def test_m_after_degrees(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations("S0DEG 32M")
        assert "32 minutes" in result

    def test_m_with_d_notation(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations("N 88D 25M")
        assert "25 minutes" in result

    def test_m_after_number_in_dms(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations("S88DEG 23M 20S E")
        assert "23 minutes" in result


class TestSecondExpansion:
    """S as seconds — must NOT confuse with S=South."""

    def test_s_seconds_after_minutes(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations("S0DEG 32M 50S W")
        # The first S is South, the 50S is seconds
        assert "50 seconds" in result

    def test_s_south_not_converted(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations("S0DEG 49M 20S W 175FT")
        # First S must stay as a directional, not become "seconds"
        assert result.startswith("S") or result.startswith("S ")
        # Must not start with "seconds"
        assert not result.lower().startswith("seconds")

    def test_s_south_standalone(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        # Standalone S at beginning should stay as S (South)
        result = expand_assessor_abbreviations("S 45 FT")
        assert "S " in result
        assert "seconds" not in result.lower()

    def test_sec_suffix_seconds(self) -> None:
        """SEC (as in 3SEC or 40SEC from deed 50484) should become seconds."""
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations("89D 05M 3SEC W")
        assert "3 seconds" in result

    def test_40sec_seconds(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations("89D 07M 40SEC E")
        assert "40 seconds" in result


class TestThenceExpansion:
    """TH, TH., th. → thence."""

    def test_th_uppercase(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations("FROM NE COR TH S0DEG")
        assert "thence" in result.lower()

    def test_th_dot(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations("BEG TH. S0DEG")
        assert "thence" in result.lower()

    def test_th_lowercase(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations("from ne cor th. s0deg")
        assert "thence" in result.lower()

    def test_th_not_in_middle_of_word(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        # "THE" should NOT become "thenceE"
        result = expand_assessor_abbreviations("THE ABOVE")
        assert "THE" in result.upper()
        assert "thence" not in result.lower()

    def test_th_not_in_thereof(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations("EXC E 60FT THEREOF")
        assert "THEREOF" in result.upper() or "thereof" in result.lower()
        assert result.upper().count("THENCE") == 0


class TestFeetExpansion:
    """FT suffix → feet."""

    def test_ft_no_space(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations("175FT")
        assert "175 feet" in result

    def test_ft_decimal(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations("401.55FT")
        assert "401.55 feet" in result

    def test_ft_with_space(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        # "90 FT" should still expand
        result = expand_assessor_abbreviations("90 FT")
        assert "90 feet" in result

    def test_ft_at_end_of_text(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations("W 61.26FT POB")
        assert "61.26 feet" in result


class TestDirectionalAbbreviations:
    """SLY, NLY, ELY, WLY → southerly, northerly, easterly, westerly."""

    def test_sly(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        assert "southerly" in expand_assessor_abbreviations("TH SLY 90 FT").lower()

    def test_nly(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        assert "northerly" in expand_assessor_abbreviations("TH NLY 90.02 FT").lower()

    def test_ely(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        assert "easterly" in expand_assessor_abbreviations("ALG ELY LINE").lower()

    def test_wly(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        assert "westerly" in expand_assessor_abbreviations("TH WLY 2 FT").lower()


class TestPobExpansion:
    """POB / P OB / P.O.B. → point of beginning."""

    def test_pob(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        assert "point of beginning" in expand_assessor_abbreviations("TO POB").lower()

    def test_p_ob(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        assert "point of beginning" in expand_assessor_abbreviations("TO P OB").lower()

    def test_p_dot_o_dot_b_dot(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        assert "point of beginning" in expand_assessor_abbreviations("TO P.O.B.").lower()


class TestMiscAbbreviations:
    """ALG, COR, BEG."""

    def test_alg(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        assert "along" in expand_assessor_abbreviations("ALG ELY LINE").lower()

    def test_cor(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        assert "corner" in expand_assessor_abbreviations("NE COR SEC 36").lower()

    def test_beg(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations("BEG S0DEG 32M")
        assert "beginning" in result.lower()


# ---------------------------------------------------------------------------
# 2. Full legal description normalization (from ground truth files)
# ---------------------------------------------------------------------------


class TestDeed50062:
    """Deed 50062: S0DEG 49M 20S W 175FT pattern."""

    LEGAL = (
        "36F8B PT OF NE 1/4 SEC 36 T2S R8E BEG S0DEG 32M 50S W 401.55FT "
        "AND N80DEG 29M 20S W 480.49FT AND S0DEG 49M 20S W 142.75FT "
        "AND N89DEG 10M 40S W 2FT FROM NE COR SEC 36 TH S0DEG 49M 20S W 175FT "
        "TH N89DEG 10M 40S W 61.23FT TH NODEG 49M E 175FT "
        "TH S89DEG 10M 40S E 61.26FT POB 0.25 AC"
    )

    def test_deg_expanded(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(self.LEGAL)
        assert "DEG" not in result

    def test_m_expanded(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(self.LEGAL)
        # All bare M markers should be replaced
        # "32M" → "32 minutes", etc.
        assert "32 minutes" in result
        assert "49 minutes" in result
        assert "29 minutes" in result
        assert "10 minutes" in result

    def test_seconds_expanded(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(self.LEGAL)
        assert "50 seconds" in result
        assert "20 seconds" in result
        assert "40 seconds" in result

    def test_ft_expanded(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(self.LEGAL)
        assert "FT" not in result
        assert "401.55 feet" in result
        assert "175 feet" in result

    def test_th_expanded(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(self.LEGAL)
        # " TH " should become " thence "
        assert "thence" in result.lower()

    def test_pob_expanded(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(self.LEGAL)
        assert "point of beginning" in result.lower()

    def test_cor_expanded(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(self.LEGAL)
        assert "corner" in result.lower()

    def test_beg_expanded(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(self.LEGAL)
        assert "beginning" in result.lower()

    def test_south_preserved(self) -> None:
        """S direction at start of bearing must stay as S, not 'seconds'."""
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(self.LEGAL)
        # "S0DEG" should become "S 0 degrees" — S preserved as South direction
        assert "S 0 degrees" in result or "S0 degrees" in result

    def test_nodeg_typo_handled(self) -> None:
        """NODEG (typo for N0DEG) should still expand."""
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations("NODEG 49M E")
        # "NODEG" → We expect the O to be treated as 0 (OCR-like typo)
        # or at minimum DEG to be expanded. The NO should ideally become N 0.
        assert "degrees" in result.lower()


class TestDeed50305:
    """Deed 50305: TH SLY 90 FT ALG ELY LINE pattern (directional abbrevs)."""

    LEGAL = (
        "W MORANG THAT PT OF 20 DESC AS FOLS BEG AT NE COR OF LOT 20 "
        "TH SLY 90 FT ALG ELY LINE OF SAID LOT TH WLY 2 FT "
        "TH NLY 90.02 FT TO P OB ALSO LOTS 19&18 LEIGH G COOPERS "
        "CADIEUX-SEVEN MILE DR SUB L56 P68 PLATS. W C R 21/873 40 IRREG"
    )

    def test_sly_expanded(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(self.LEGAL)
        assert "southerly" in result.lower()

    def test_ely_expanded(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(self.LEGAL)
        assert "easterly" in result.lower()

    def test_wly_expanded(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(self.LEGAL)
        assert "westerly" in result.lower()

    def test_nly_expanded(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(self.LEGAL)
        assert "northerly" in result.lower()

    def test_alg_expanded(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(self.LEGAL)
        assert "along" in result.lower()

    def test_p_ob_expanded(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(self.LEGAL)
        assert "point of beginning" in result.lower()

    def test_th_expanded(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(self.LEGAL)
        assert "thence" in result.lower()

    def test_ft_expanded(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(self.LEGAL)
        assert "90 feet" in result
        assert "2 feet" in result
        assert "90.02 feet" in result

    def test_beg_expanded(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(self.LEGAL)
        assert "beginning" in result.lower()

    def test_cor_expanded(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(self.LEGAL)
        assert "corner" in result.lower()


class TestDeed50426:
    """Deed 50426: N 88D 25M 31S E pattern."""

    LEGAL = (
        "23J1B PT OF THE SE 1/4 OF SEC 23 T4S R10E DESC AS BEG N 88D 25M 31S E "
        "330.00 FT AND N 01D 41M 46S W 222.00 FT FROM THE S 1/4 COR OF SEC 23: "
        "TH N 01D 41M 46S W 538.05 FT TH S 89D 50M 17S E 130.07 FT "
        "TH S 01D 41M 46S E 696.11 FT TH S 88D 25M 31S W 68.00 FT "
        "TH N 01D 41M 46S W 162.00 FT TH S 88D 25M 31S W 62.00 FT 1.85 AC."
    )

    def test_d_expanded(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(self.LEGAL)
        assert "88 degrees" in result
        assert "01 degrees" in result or "1 degrees" in result

    def test_m_expanded(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(self.LEGAL)
        assert "25 minutes" in result
        assert "41 minutes" in result
        assert "50 minutes" in result

    def test_s_seconds_expanded(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(self.LEGAL)
        assert "31 seconds" in result
        assert "46 seconds" in result
        assert "17 seconds" in result

    def test_s_south_preserved(self) -> None:
        """S as South direction must not become 'seconds'."""
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(self.LEGAL)
        # "S 89D" — S is South, not seconds
        # After expansion: "S 89 degrees ..." — S still present as direction
        assert "S 89 degrees" in result or "S 89D" in result

    def test_ft_expanded(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(self.LEGAL)
        assert "330.00 feet" in result
        assert "538.05 feet" in result

    def test_th_expanded(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(self.LEGAL)
        assert "thence" in result.lower()


class TestDeed50484:
    """Deed 50484: N89DEG 06M W 60FT + SEC suffix for seconds."""

    LEGAL = (
        "10L6B3A1A PART OF SE 1/4 SEC 10 T2S R9E BEG N89DEG 06M W 60FT "
        "AND N00DEG 07M E 1561.58FT FROM SE COR OF SEC 10 "
        "TH N89DEG 05M 23S W 317.77FT TH NOODEG 07M E 61.39FT "
        "TH S89DEG 33M 30S E 201.89FT TH S74DEG 45M E 147.99FT "
        "TH N00DEG 07M E 30FT TH S74DEG 45M E 34.18FT "
        "TH S0DEG 07M W 47.92FT TH N89DEG 05M 23S W 60FT POB "
        "EXC E 60FT THEREOF 0.41AC"
    )

    LEGAL2 = (
        "10M6B1A1 THAT PART OF THE SE 1/4 OF SEC 10 DESCRIBED AS "
        "BEGINNING AT A POINT ON THE W LINE OF MERRIMAN ROAD DISTANT "
        "N 89D 06M W 60.0 FT AND N 0D 07M E 1423.21 FT FROM THE SE CORNER "
        "OF SEC 10 AND PROCEEDING TH N 0D 07M E ALONG SAID W LINE 136.93 FT "
        "TH N 89D 05M 3SEC W 318.12 FT TH S 0D 07M W 137.57 FT "
        "TH S 89D 07M 40SEC E 318.12 FT TO THE POB 1.00 ACRE."
    )

    def test_deg_expanded(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(self.LEGAL)
        assert "DEG" not in result

    def test_sec_suffix_expanded(self) -> None:
        """3SEC and 40SEC should become '3 seconds' and '40 seconds'."""
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(self.LEGAL2)
        assert "3 seconds" in result
        assert "40 seconds" in result

    def test_sec_not_section(self) -> None:
        """SEC in 'SEC 10' (section) must NOT become 'seconds'."""
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(self.LEGAL)
        # "SEC 10" should remain — SEC is section, not seconds
        # We only convert SEC when preceded by a number (like 3SEC or 40SEC)
        assert "SEC 10" in result.upper() or "section 10" in result.lower()

    def test_ft_expanded(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(self.LEGAL)
        assert "FT" not in result
        assert "60 feet" in result
        assert "317.77 feet" in result

    def test_pob_expanded(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(self.LEGAL)
        assert "point of beginning" in result.lower()

    def test_thereof_preserved(self) -> None:
        """THEREOF should not be mangled."""
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(self.LEGAL)
        assert "thereof" in result.lower()

    def test_pob_in_legal2(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(self.LEGAL2)
        assert "point of beginning" in result.lower()


class TestDeed50633:
    """Deed 50633: S88DEG 23M 20S E 371FT pattern."""

    LEGAL = (
        "13H2C D PART OF NW 1/4 SEC 13 T4S R9E BEG AT NW COR SEC 13 "
        "TH S88DEG 23M 20S E 371FT TH S0DEG 02M 20S W 165FT "
        "TH N88DEG 23M 20S W 371FT TH NODEG 02M 20S E 165FT POB 1.40 AC"
    )

    def test_deg_expanded(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(self.LEGAL)
        assert "DEG" not in result
        assert "88 degrees" in result

    def test_m_expanded(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(self.LEGAL)
        assert "23 minutes" in result
        assert "02 minutes" in result or "2 minutes" in result

    def test_s_seconds_expanded(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(self.LEGAL)
        assert "20 seconds" in result

    def test_ft_expanded(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(self.LEGAL)
        assert "371 feet" in result
        assert "165 feet" in result

    def test_nodeg_expanded(self) -> None:
        """NODEG (N + O-as-zero + DEG) should expand."""
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(self.LEGAL)
        # NODEG should become N 0 degrees (O→0 OCR correction)
        assert "degrees" in result.lower()

    def test_cor_expanded(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations(self.LEGAL)
        assert "corner" in result.lower()


# ---------------------------------------------------------------------------
# 3. Integration: wired into normalize_legal_description
# ---------------------------------------------------------------------------


class TestNormalizeLegalDescriptionIntegration:
    """expand_assessor_abbreviations is called within normalize_legal_description."""

    def test_assessor_expansion_in_pipeline(self) -> None:
        from mp_parse.normalizer import normalize_legal_description

        text = "TH S88DEG 23M 20S E 371FT"
        result = normalize_legal_description(text)
        # After full normalization:
        # 1. expand_assessor_abbreviations: S 88 degrees 23 minutes 20 seconds E 371 feet
        # 2. standardize_cardinal_directions: S 88°23'20" E 371 feet
        assert "°" in result or "degrees" in result
        assert "371" in result
        assert "thence" in result.lower()

    def test_full_50426_through_pipeline(self) -> None:
        from mp_parse.normalizer import normalize_legal_description

        text = "TH N 01D 41M 46S W 538.05 FT"
        result = normalize_legal_description(text)
        # Should be parseable as a bearing now
        assert "°" in result or "degrees" in result
        assert "538.05" in result


# ---------------------------------------------------------------------------
# 4. Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Tricky patterns and boundary conditions."""

    def test_empty_string(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        assert expand_assessor_abbreviations("") == ""

    def test_no_assessor_notation(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        text = "thence South 45 degrees 30 minutes East 100 feet"
        result = expand_assessor_abbreviations(text)
        # Should pass through unchanged (mostly)
        assert "45" in result
        assert "100" in result

    def test_s_as_south_before_number_without_deg(self) -> None:
        """S followed by a number but no DEG/D should remain S (South)."""
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations("S 45 FT")
        assert result.startswith("S ")
        assert "seconds" not in result.lower()

    def test_ac_not_expanded(self) -> None:
        """AC (acres) should not be affected."""
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations("0.25 AC")
        assert "AC" in result.upper() or "ac" in result.lower()

    def test_fols_not_expanded(self) -> None:
        """FOLS (follows) in assessor text should not be mangled."""
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations("DESC AS FOLS BEG")
        assert "FOLS" in result.upper() or "fols" in result.lower()

    def test_mixed_case(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations("s88deg 23m 20s e 371ft")
        assert "degrees" in result
        assert "minutes" in result
        assert "seconds" in result
        assert "feet" in result

    def test_noodeg_typo(self) -> None:
        """NOODEG (OCR for N00DEG) should be handled."""
        from mp_parse.normalizer import expand_assessor_abbreviations

        result = expand_assessor_abbreviations("NOODEG 07M E")
        assert "degrees" in result.lower()
