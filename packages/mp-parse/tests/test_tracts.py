"""Tests for tract splitting logic."""

from mp_models import TractType
from mp_parse.calls import extract_calls
from mp_parse.tracts import split_into_tracts


class TestExplicitTractMarkers:
    """Priority 1: TRACT #N, TRACT A, PARCEL N markers."""

    def test_tract_numbered(self):
        text = (
            "TRACT #1: BEGINNING at a point... THENCE N 45\u00b000' E 100 feet "
            "to the POINT OF BEGINNING. "
            "TRACT #2: BEGINNING at a point... THENCE S 45\u00b000' E 200 feet "
            "to the POINT OF BEGINNING."
        )
        result = split_into_tracts(text)
        assert len(result) == 2
        assert result[0][1] == "Tract 1"
        assert result[0][2] == TractType.MAIN
        assert result[1][1] == "Tract 2"
        assert result[1][2] == TractType.MAIN

    def test_tract_lettered(self):
        text = (
            "TRACT A: BEGINNING at a point... THENCE N 45\u00b000' E 100 feet "
            "to the POINT OF BEGINNING. "
            "TRACT B: BEGINNING at a point... THENCE S 45\u00b000' E 200 feet "
            "to the POINT OF BEGINNING."
        )
        result = split_into_tracts(text)
        assert len(result) == 2
        assert result[0][1] == "Tract A"
        assert result[1][1] == "Tract B"

    def test_parcel_numbered(self):
        text = (
            "PARCEL 1: BEGINNING at a point... THENCE N 45\u00b000' E 100 feet "
            "to the POINT OF BEGINNING. "
            "PARCEL 2: BEGINNING at a point... THENCE S 45\u00b000' E 200 feet "
            "to the POINT OF BEGINNING."
        )
        result = split_into_tracts(text)
        assert len(result) == 2
        assert result[0][1] == "Parcel 1"
        assert result[1][1] == "Parcel 2"

    def test_tract_roman_numerals(self):
        text = (
            "TRACT III: BEGINNING at a point... THENCE N 45\u00b000' E 100 feet "
            "to the POINT OF BEGINNING. "
            "TRACT IV: BEGINNING at a point... THENCE S 45\u00b000' E 200 feet "
            "to the POINT OF BEGINNING."
        )
        result = split_into_tracts(text)
        assert len(result) == 2
        assert result[0][1] == "Tract III"
        assert result[1][1] == "Tract IV"

    def test_tract_without_hash(self):
        text = (
            "TRACT 1 BEGINNING at a point... THENCE N 45\u00b000' E 100 feet "
            "to the POINT OF BEGINNING. "
            "TRACT 2 BEGINNING at a point... THENCE S 45\u00b000' E 200 feet "
            "to the POINT OF BEGINNING."
        )
        result = split_into_tracts(text)
        assert len(result) == 2


class TestMultipleBeginningBlocks:
    """Priority 2: Multiple BEGINNING blocks."""

    def test_two_beginning_blocks(self):
        text = (
            "BEGINNING at an iron pin THENCE N 45\u00b000' E 100 feet; "
            "THENCE S 45\u00b000' E 100 feet; "
            "THENCE S 45\u00b000' W 100 feet; "
            "THENCE N 45\u00b000' W 100 feet to the POINT OF BEGINNING. "
            "ALSO BEGINNING at a concrete monument THENCE S 45\u00b000' E 200 feet; "
            "THENCE S 45\u00b000' W 200 feet; "
            "THENCE N 45\u00b000' W 200 feet; "
            "THENCE N 45\u00b000' E 200 feet to the POINT OF BEGINNING."
        )
        result = split_into_tracts(text)
        assert len(result) == 2

    def test_single_beginning_block_no_split(self):
        text = "BEGINNING at a point THENCE N 45\u00b000' E 100 feet to the POINT OF BEGINNING."
        result = split_into_tracts(text)
        assert len(result) == 1

    def test_except_beginning_block(self):
        text = (
            "BEGINNING at an iron pin THENCE N 45\u00b000' E 100 feet; "
            "THENCE S 45\u00b000' E 100 feet to the POINT OF BEGINNING. "
            "EXCEPT BEGINNING at another pin THENCE S 10\u00b000' E 50 feet; "
            "THENCE S 10\u00b000' W 50 feet to the POINT OF BEGINNING."
        )
        result = split_into_tracts(text)
        assert len(result) == 2
        types = [r[2] for r in result]
        assert TractType.EXCEPTION in types


class TestExceptAlsoFallback:
    """Priority 3: EXCEPT/ALSO fallback (no BEGINNING blocks)."""

    def test_except_clause_without_beginning(self):
        text = (
            "THENCE N 45\u00b000' E 100 feet; THENCE S 45\u00b000' E 100 feet "
            "EXCEPT THENCE S 10\u00b000' E 50 feet"
        )
        result = split_into_tracts(text)
        assert len(result) == 2
        types = [r[2] for r in result]
        assert TractType.MAIN in types
        assert TractType.EXCEPTION in types


class TestSingleTract:
    """Single-tract deeds pass through unchanged."""

    def test_simple_single_tract(self):
        text = "THENCE N 45\u00b000' E 100 feet to the POINT OF BEGINNING."
        result = split_into_tracts(text)
        assert len(result) == 1
        assert result[0][1] == "Tract 1"
        assert result[0][2] == TractType.MAIN

    def test_return_type(self):
        text = "THENCE N 45\u00b000' E 100 feet."
        result = split_into_tracts(text)
        assert isinstance(result, list)
        text_val, label, tract_type = result[0]
        assert isinstance(text_val, str)
        assert isinstance(label, str)
        assert isinstance(tract_type, TractType)

    def test_tract_or_parcel_of_land_no_false_split(self):
        """Common preamble 'TRACT OR PARCEL OF LAND' must NOT trigger splitting."""
        text = (
            "ALL THAT CERTAIN TRACT OR PARCEL OF LAND SITUATE IN THE TOWNSHIP "
            "BEGINNING at an iron pin THENCE N 45\u00b000' E 100 feet; "
            "THENCE S 45\u00b000' E 100 feet; "
            "THENCE S 45\u00b000' W 100 feet; "
            "THENCE N 45\u00b000' W 100 feet to the POINT OF BEGINNING."
        )
        result = split_into_tracts(text)
        assert len(result) == 1

    def test_being_all_that_tract_no_false_split(self):
        """Preamble 'BEING ALL THAT TRACT' must NOT trigger splitting."""
        text = (
            "BEING ALL THAT TRACT IN THE TOWNSHIP "
            "THENCE N 45\u00b000' E 100 feet to the POINT OF BEGINNING."
        )
        result = split_into_tracts(text)
        assert len(result) == 1

    def test_tract_situate_no_false_split(self):
        """'TRACT SITUATE IN THE TOWNSHIP' must NOT trigger splitting."""
        text = (
            "ALL THAT CERTAIN TRACT SITUATE IN THE TOWNSHIP OF HADDONFIELD "
            "BEGINNING at an iron pin THENCE N 45\u00b000' E 100 feet; "
            "THENCE S 45\u00b000' E 100 feet to the POINT OF BEGINNING."
        )
        result = split_into_tracts(text)
        assert len(result) == 1

    def test_tract_is_described_no_false_split(self):
        """'TRACT IS DESCRIBED AS' must NOT trigger splitting."""
        text = (
            "SAID TRACT IS DESCRIBED AS FOLLOWS "
            "THENCE N 45\u00b000' E 100 feet to the POINT OF BEGINNING."
        )
        result = split_into_tracts(text)
        assert len(result) == 1

    def test_parcel_of_land_no_false_split(self):
        """'PARCEL OF LAND SITUATE' must NOT trigger splitting."""
        text = (
            "ALL THAT CERTAIN PARCEL OF LAND SITUATE IN THE COUNTY "
            "THENCE N 45\u00b000' E 100 feet to the POINT OF BEGINNING."
        )
        result = split_into_tracts(text)
        assert len(result) == 1

    def test_tract_conveyed_no_false_split(self):
        """'TRACT CONVEYED BY' must NOT trigger splitting."""
        text = (
            "THE TRACT CONVEYED BY DEED BOOK 1234 PAGE 567 "
            "THENCE N 45\u00b000' E 100 feet to the POINT OF BEGINNING."
        )
        result = split_into_tracts(text)
        assert len(result) == 1


class TestSplitOnMarkersExceptDetection:
    """split_on_markers assigns correct TractType from preceding text."""

    def test_except_preceding_marker_gets_exception_type(self):
        text = (
            "TRACT 1: BEGINNING at a point... THENCE N 45\u00b000' E 100 feet "
            "to the POINT OF BEGINNING. "
            "EXCEPT TRACT 2: BEGINNING at a point... THENCE S 45\u00b000' E 200 feet "
            "to the POINT OF BEGINNING."
        )
        result = split_into_tracts(text)
        assert len(result) == 2
        assert result[1][2] == TractType.EXCEPTION


class TestExtractCallsMultiTract:
    """extract_calls returns Tract objects when multi-tract patterns detected."""

    def test_returns_tracts_for_tract_markers(self):
        text = (
            "TRACT #1: BEGINNING at a point THENCE North 45 degrees 00 minutes 00 seconds East, "
            "a distance of 100.00 feet to a point; THENCE South 45 degrees 00 minutes 00 seconds East, "
            "a distance of 100.00 feet to a point; THENCE South 45 degrees 00 minutes 00 seconds West, "
            "a distance of 100.00 feet to a point; THENCE North 45 degrees 00 minutes 00 seconds West, "
            "a distance of 100.00 feet to the POINT OF BEGINNING. "
            "TRACT #2: BEGINNING at a point THENCE South 45 degrees 00 minutes 00 seconds East, "
            "a distance of 50.00 feet to a point; THENCE South 45 degrees 00 minutes 00 seconds West, "
            "a distance of 50.00 feet to a point; THENCE North 45 degrees 00 minutes 00 seconds West, "
            "a distance of 50.00 feet to a point; THENCE North 45 degrees 00 minutes 00 seconds East, "
            "a distance of 50.00 feet to the POINT OF BEGINNING."
        )
        calls, tracts = extract_calls(text)
        assert len(tracts) == 2
        assert tracts[0].label == "Tract 1"
        assert tracts[1].label == "Tract 2"
        # Course numbering resets per tract
        assert tracts[0].calls[0].course == 1
        assert tracts[1].calls[0].course == 1

    def test_single_tract_returns_empty_tracts(self):
        text = (
            "THENCE North 45 degrees 00 minutes 00 seconds East, "
            "a distance of 100.00 feet to a point; THENCE South 45 degrees 00 minutes 00 seconds East, "
            "a distance of 100.00 feet to the POINT OF BEGINNING."
        )
        calls, tracts = extract_calls(text)
        assert tracts == []
        assert len(calls) == 2

    def test_except_clause_returns_tracts(self):
        text = (
            "THENCE North 45 degrees 00 minutes 00 seconds East, a distance of 100.00 feet; "
            "THENCE South 45 degrees 00 minutes 00 seconds East, a distance of 100.00 feet; "
            "THENCE South 45 degrees 00 minutes 00 seconds West, a distance of 100.00 feet; "
            "THENCE North 45 degrees 00 minutes 00 seconds West, a distance of 100.00 feet "
            "EXCEPT THENCE South 10 degrees 00 minutes 00 seconds East, a distance of 50.00 feet; "
            "THENCE South 10 degrees 00 minutes 00 seconds West, a distance of 50.00 feet"
        )
        calls, tracts = extract_calls(text)
        assert len(tracts) >= 2
        types = [t.tract_type for t in tracts]
        assert TractType.MAIN in types
        assert TractType.EXCEPTION in types

    def test_exception_calls_marked(self):
        """Exception tract calls should have is_exception=True."""
        text = (
            "THENCE North 45 degrees 00 minutes 00 seconds East, a distance of 100.00 feet; "
            "THENCE South 45 degrees 00 minutes 00 seconds East, a distance of 100.00 feet "
            "EXCEPT THENCE South 10 degrees 00 minutes 00 seconds East, a distance of 50.00 feet"
        )
        calls, tracts = extract_calls(text)
        exception_tracts = [t for t in tracts if t.tract_type == TractType.EXCEPTION]
        assert len(exception_tracts) >= 1
        for exc_tract in exception_tracts:
            for call in exc_tract.calls:
                assert call.is_exception is True
