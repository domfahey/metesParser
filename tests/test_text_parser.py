"""Tests for text_parser.py - Text normalization and OCR fixes."""

import pytest

from metesparser.text_parser import TextParser


class TestNormalizeDMSSymbols:
    """Test DMS symbol normalization."""

    def test_normalize_degree_symbols(self):
        """Normalize various degree symbol variants to °."""
        text = "N 45º30' E"  # Different degree symbol
        result = TextParser.normalize_dms_symbols(text)
        assert "45°30'" in result

    def test_normalize_minute_symbols(self):
        """Normalize various minute symbol variants to '."""
        text = "N 45°30' E"  # Curly apostrophe
        result = TextParser.normalize_dms_symbols(text)
        assert "45°30'" in result

    def test_normalize_second_symbols(self):
        """Normalize various second symbol variants to \"."""
        text = 'N 45°30\'15" E'  # Smart quote
        result = TextParser.normalize_dms_symbols(text)
        assert '45°30\'15"' in result

    def test_mixed_symbols(self):
        """Normalize mixed symbol variants."""
        text = 'N 45º30\'15" E'
        result = TextParser.normalize_dms_symbols(text)
        assert '45°30\'15" E' in result


class TestMergeLineWrappedCalls:
    """Test merging of line-wrapped calls."""

    def test_merge_hyphenated_line_break(self):
        """Merge hyphenated line breaks."""
        text = "THENCE North-\neasterly"
        result = TextParser.merge_line_wrapped_calls(text)
        assert "Northeasterly" in result
        assert "\n" not in result

    def test_merge_continuation_line(self):
        """Merge lines that don't start with THENCE."""
        text = "THENCE N 45° E 100 feet\nalong the south line"
        result = TextParser.merge_line_wrapped_calls(text)
        assert "100 feet along the south line" in result

    def test_dont_merge_new_thence_calls(self):
        """Don't merge lines that start with THENCE."""
        text = "THENCE N 45° E 100 feet\nTHENCE S 45° W 100 feet"
        result = TextParser.merge_line_wrapped_calls(text)
        lines = result.split("\n")
        assert len(lines) == 2
        assert "THENCE N 45° E" in lines[0]
        assert "THENCE S 45° W" in lines[1]

    def test_preserve_beginning_keyword(self):
        """Preserve BEGINNING as a separate line."""
        text = "BEGINNING at a point\nTHENCE N 45° E"
        result = TextParser.merge_line_wrapped_calls(text)
        lines = result.split("\n")
        assert len(lines) == 2
        assert "BEGINNING" in lines[0]


class TestStandardizeCardinalDirections:
    """Test cardinal direction standardization."""

    def test_long_form_to_abbrev(self):
        """Convert 'North 56 degrees 40 minutes West' to 'N 56°40' W'."""
        text = "South 56 degrees 40 minutes West"
        result = TextParser.standardize_cardinal_directions(text)
        assert "S 56°40' W" in result

    def test_degrees_only_long_form(self):
        """Convert 'North 45 degrees East' to 'N 45° E'."""
        text = "North 45 degrees East"
        result = TextParser.standardize_cardinal_directions(text)
        assert "N 45° E" in result

    def test_normalize_spacing_dms(self):
        """Normalize spacing around DMS symbols."""
        text = "N  33 ° 20 ' E"  # Extra spaces
        result = TextParser.standardize_cardinal_directions(text)
        assert "N 33°20' E" in result

    def test_normalize_spacing_with_seconds(self):
        """Normalize spacing with seconds."""
        text = 'S 45 ° 30 \' 15 " W'
        result = TextParser.standardize_cardinal_directions(text)
        # Accept either escaped or unescaped double quote
        assert ('S 45°30\'15" W' in result or 'S 45°30\'15\\" W' in result)


class TestExtractPOB:
    """Test Point of Beginning extraction."""

    def test_extract_beginning_at(self):
        """Extract POB from 'BEGINNING at' pattern."""
        text = "BEGINNING at a point in the center of Main Street. THENCE N 45° E"
        pob = TextParser.extract_pob(text)
        assert "point in the center of Main Street" in pob

    def test_extract_pob_at(self):
        """Extract POB from 'POB at' pattern."""
        text = "POB at the southeast corner of Lot 46. THENCE"
        pob = TextParser.extract_pob(text)
        assert "southeast corner of Lot 46" in pob

    def test_extract_point_of_beginning(self):
        """Extract POB from 'POINT OF BEGINNING at' pattern."""
        text = "POINT OF BEGINNING at a stone monument; THENCE"
        pob = TextParser.extract_pob(text)
        assert "stone monument" in pob

    def test_extract_commencing_at(self):
        """Extract POB from 'commencing at' pattern."""
        text = "commencing at a railroad spike. THENCE"
        pob = TextParser.extract_pob(text)
        assert "railroad spike" in pob

    def test_no_pob_found(self):
        """Return empty string when no POB found."""
        text = "THENCE N 45° E 100 feet"
        pob = TextParser.extract_pob(text)
        assert pob == ""


class TestSplitIntoCalls:
    """Test splitting text into individual calls."""

    def test_split_basic_thence_calls(self):
        """Split multiple THENCE calls."""
        text = "THENCE N 45° E 100 feet THENCE S 45° W 100 feet"
        calls = TextParser.split_into_calls(text)
        assert len(calls) == 2
        assert "N 45° E 100 feet" in calls[0]
        assert "S 45° W 100 feet" in calls[1]

    def test_strip_trailing_punctuation(self):
        """Strip trailing punctuation from calls."""
        text = "THENCE N 45° E 100 feet; THENCE S 45° W 100 feet."
        calls = TextParser.split_into_calls(text)
        assert len(calls) == 2
        assert not calls[0].endswith(";")
        assert not calls[1].endswith(".")

    def test_ignore_empty_calls(self):
        """Ignore empty calls from splitting."""
        text = "THENCE N 45° E 100 feet THENCE  THENCE S 45° W 100 feet"
        calls = TextParser.split_into_calls(text)
        assert len(calls) == 2

    def test_case_insensitive_thence(self):
        """Handle case-insensitive THENCE."""
        text = "thence N 45° E 100 feet THENCE S 45° W 100 feet"
        calls = TextParser.split_into_calls(text)
        assert len(calls) == 2


class TestExtractDistance:
    """Test distance extraction with unit conversion."""

    def test_extract_feet(self):
        """Extract distance in feet."""
        value, unit = TextParser.extract_distance("100.50 feet")
        assert value == 100.50
        assert unit == "feet"

    def test_extract_poles(self):
        """Extract distance in poles."""
        value, unit = TextParser.extract_distance("10 poles")
        assert value == 10.0
        assert unit == "poles"

    def test_extract_rods(self):
        """Extract distance in rods."""
        value, unit = TextParser.extract_distance("15.5 rods")
        assert value == 15.5
        assert unit == "rods"

    def test_extract_chains(self):
        """Extract distance in chains."""
        value, unit = TextParser.extract_distance("5 chains")
        assert value == 5.0
        assert unit == "chains"

    def test_normalize_unit_names(self):
        """Normalize unit names."""
        _, unit = TextParser.extract_distance("100 ft")
        assert unit == "feet"

        _, unit = TextParser.extract_distance("10 pole")
        assert unit == "poles"

    def test_no_distance_found(self):
        """Return (0.0, 'feet') when no distance found."""
        value, unit = TextParser.extract_distance("along the north line")
        assert value == 0.0
        assert unit == "feet"


class TestCleanOCRErrors:
    """Test OCR error correction."""

    def test_fix_degree_symbol_zero(self):
        """Fix '0' mistaken for degree symbol."""
        text = "S 56 0 40' W"  # '0' should be '°'
        result = TextParser.clean_ocr_errors(text)
        assert "S 56°40' W" in result

    def test_fix_5outh_to_south(self):
        """Fix '5outh' to 'South'."""
        text = "5outh 45 degrees West"
        result = TextParser.clean_ocr_errors(text)
        assert "South 45 degrees West" in result

    def test_fix_nOrth_to_north(self):
        """Fix 'NOrth' to 'North'."""
        text = "NOrth 45 degrees East"
        result = TextParser.clean_ocr_errors(text)
        assert "North 45 degrees East" in result

    def test_fix_ea5t_to_east(self):
        """Fix 'Ea5t' to 'East'."""
        text = "N 45° Ea5t"
        result = TextParser.clean_ocr_errors(text)
        assert "East" in result

    def test_fix_we5t_to_west(self):
        """Fix 'We5t' to 'West'."""
        text = "S 45° We5t"
        result = TextParser.clean_ocr_errors(text)
        assert "West" in result


class TestExtractAlongToFields:
    """Test extraction of 'along' and 'to' fields."""

    def test_extract_along_and_to(self):
        """Extract both 'along' and 'to' fields."""
        text = "N 45° E 100 feet along the south line of Lot 46 to a point"
        along, to = TextParser.extract_along_to_fields(text)
        assert "south line of Lot 46" in along
        assert "point" in to

    def test_extract_along_only(self):
        """Extract 'along' field only."""
        text = "N 45° E 100 feet along the division line"
        along, to = TextParser.extract_along_to_fields(text)
        assert "division line" in along
        assert to == ""

    def test_extract_to_only(self):
        """Extract 'to' field only."""
        text = "N 45° E 100 feet to the point of beginning"
        along, to = TextParser.extract_along_to_fields(text)
        assert along == ""
        assert "point of beginning" in to

    def test_no_along_or_to(self):
        """Return empty strings when neither found."""
        text = "N 45° E 100 feet"
        along, to = TextParser.extract_along_to_fields(text)
        assert along == ""
        assert to == ""

    def test_case_insensitive(self):
        """Handle case-insensitive 'along' and 'to'."""
        text = "ALONG the boundary TO a corner"
        along, to = TextParser.extract_along_to_fields(text)
        assert "boundary" in along
        assert "corner" in to

    def test_multi_to_phrases(self):
        """Prefer the final 'to' clause for the endpoint."""
        text = (
            "N 45° E 100 feet along a curve to the right having a radius of 50.00 feet "
            "and an arc length of 78.54 feet to an iron pin"
        )
        along, to = TextParser.extract_along_to_fields(text)
        assert along.startswith("a curve to the right")
        assert to == "an iron pin"


class TestNormalizeLegalDescription:
    """Integration test: full normalization pipeline."""

    def test_full_pipeline(self):
        """Test complete normalization pipeline."""
        text = """
        BEGINNING at a point.
        THENCE 5outh 56 0 40' West
        125 feet along the div-
        ision line;
        THENCE North 45 degrees East 100 feet.
        """
        result = TextParser.normalize_legal_description(text)

        # OCR fixes: "5outh 56 0 40' West" becomes "South 56 degrees 40 minutes West"
        # then gets converted to "S 56°40' W" by standardize_cardinal_directions
        assert "S" in result and "W" in result
        assert "56°40'" in result  # "0" converted to degrees/minutes format

        # Line wrapping
        assert "division line" in result
        assert "div-\n" not in result

        # Cardinal standardization
        assert "N 45° E" in result

    def test_preserves_content(self):
        """Ensure normalization preserves essential content."""
        text = "THENCE N 33°20' E 60 feet to a point"
        result = TextParser.normalize_legal_description(text)

        assert "N 33°20' E" in result
        assert "60 feet" in result
        assert "to a point" in result
