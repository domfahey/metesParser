"""Tests for mp_parse.normalizer — text normalization functions."""

from __future__ import annotations


class TestExpandAbbreviations:
    def test_iron_pin_found(self) -> None:
        from mp_parse.normalizer import expand_abbreviations

        text = "to an IPF in the line of N/F Smith"
        result = expand_abbreviations(text)
        assert "iron pin found" in result
        assert "now or formerly" in result

    def test_iron_pin_set(self) -> None:
        from mp_parse.normalizer import expand_abbreviations

        result = expand_abbreviations("set an IPS at the corner")
        assert "iron pin set" in result

    def test_iron_rod_found_and_set(self) -> None:
        from mp_parse.normalizer import expand_abbreviations

        result = expand_abbreviations("IRF to IRS")
        assert "iron rod found" in result
        assert "iron rod set" in result

    def test_capped_iron_pin(self) -> None:
        from mp_parse.normalizer import expand_abbreviations

        result = expand_abbreviations("a CIP marked LS 1234")
        assert "capped iron pin" in result

    def test_right_of_way(self) -> None:
        from mp_parse.normalizer import expand_abbreviations

        result = expand_abbreviations("along the R/W of Route 30")
        assert "right-of-way" in result

    def test_pk_nail(self) -> None:
        from mp_parse.normalizer import expand_abbreviations

        result = expand_abbreviations("to a PK in the curb")
        assert "pk nail" in result

    def test_concrete_monument(self) -> None:
        from mp_parse.normalizer import expand_abbreviations

        result = expand_abbreviations("Con Mon F at corner")
        assert "concrete monument found" in result


class TestNormalizeDmsSymbols:
    def test_degree_symbol_variants(self) -> None:
        from mp_parse.normalizer import normalize_dms_symbols

        assert "45\u00b0" in normalize_dms_symbols("45\u00ba")  # ordinal to degree
        assert "45\u00b0" in normalize_dms_symbols("45\u00b0")  # already correct

    def test_single_quote_variants(self) -> None:
        from mp_parse.normalizer import normalize_dms_symbols

        result = normalize_dms_symbols("N 45\u00b030\u2018 E")
        assert "'" in result  # left single quote -> straight quote

    def test_double_quote_variants(self) -> None:
        from mp_parse.normalizer import normalize_dms_symbols

        result = normalize_dms_symbols("30\u201c")
        assert '"' in result  # left double quote -> straight quote


class TestMergeLineWrappedCalls:
    def test_merges_continuation_lines(self) -> None:
        from mp_parse.normalizer import merge_line_wrapped_calls

        text = "THENCE North 45 degrees\n30 minutes East\nTHENCE South"
        result = merge_line_wrapped_calls(text)
        lines = result.split("\n")
        assert len(lines) == 2
        assert "North 45 degrees 30 minutes East" in lines[0]

    def test_joins_hyphenated_lines(self) -> None:
        from mp_parse.normalizer import merge_line_wrapped_calls

        text = "along the south-\nerly line"
        result = merge_line_wrapped_calls(text)
        assert "southerly" in result

    def test_skips_empty_lines(self) -> None:
        from mp_parse.normalizer import merge_line_wrapped_calls

        text = "THENCE North\n\n\n100 feet"
        result = merge_line_wrapped_calls(text)
        assert "THENCE North 100 feet" in result


class TestStandardizeCardinalDirections:
    def test_written_out_dms(self) -> None:
        from mp_parse.normalizer import standardize_cardinal_directions

        text = "North 45 degrees 30 minutes 15 seconds East"
        result = standardize_cardinal_directions(text)
        assert "N 45\u00b030'15\"" in result or "N 45\u00b030'15" in result

    def test_written_out_dm(self) -> None:
        from mp_parse.normalizer import standardize_cardinal_directions

        text = "South 67 degrees 42 minutes West"
        result = standardize_cardinal_directions(text)
        assert "S 67\u00b042' W" in result

    def test_symbol_spacing(self) -> None:
        from mp_parse.normalizer import standardize_cardinal_directions

        text = "N45\u00b030'15\"E"
        result = standardize_cardinal_directions(text)
        assert "N 45\u00b030'15\" E" in result


class TestCleanOcrErrors:
    def test_fixes_5_to_s(self) -> None:
        from mp_parse.normalizer import clean_ocr_errors

        result = clean_ocr_errors("5outh 45 degrees")
        assert "South" in result

    def test_fixes_0_to_degree(self) -> None:
        from mp_parse.normalizer import clean_ocr_errors

        result = clean_ocr_errors("N 45 0 30' E")
        assert "\u00b0" in result


class TestNormalizeLegalDescription:
    def test_full_pipeline(self) -> None:
        from mp_parse.normalizer import normalize_legal_description

        text = "5outh 45 degrees 30 minutes East to an IPF"
        result = normalize_legal_description(text)
        assert "iron pin found" in result
        assert "South" not in result or "S 45" in result

    def test_returns_string(self) -> None:
        from mp_parse.normalizer import normalize_legal_description

        result = normalize_legal_description("simple text")
        assert isinstance(result, str)
