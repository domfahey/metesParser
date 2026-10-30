"""Tests for tract splitting logic."""

import pytest
from mp_models import TractType
from mp_parse.calls import extract_calls
from mp_parse.tracts import find_tract_markers, split_into_tracts


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


class TestNeighbourReferencesAreNotMarkers:
    """Bug #69: references to adjoining parcels/tracts must not split a parcel."""

    def test_neighbour_parcel_references_stay_one_tract(self):
        text = (
            "BEGINNING at the northeast corner of Parcel 2; "
            "THENCE S 0° W 100 ft along the line of Parcel 3; "
            "THENCE W 100 ft; THENCE N 100 ft; "
            "THENCE E 100 ft to the POINT OF BEGINNING."
        )
        assert [label for _t, label, _k in split_into_tracts(text)] == ["Tract 1"]
        calls, tracts = extract_calls(text)
        assert tracts == []
        assert len(calls) == 4

    def test_lot_of_tract_references_do_not_split(self):
        text = (
            "BEGINNING at the corner of Lot 5 of Tract 4567; "
            "THENCE N 100 ft along Lot 6 of Tract 4567; THENCE E 100 ft; "
            "THENCE S 100 ft; THENCE W 100 ft to the POINT OF BEGINNING."
        )
        _calls, tracts = extract_calls(text)
        assert tracts == []

    def test_heading_markers_after_sentence_or_newline_still_split(self):
        text = (
            "PARCEL A BEGINNING at a point THENCE N 100 ft to the POINT OF BEGINNING.\n"
            "PARCEL B BEGINNING at a point THENCE S 100 ft to the POINT OF BEGINNING."
        )
        assert [label for _t, label, _k in split_into_tracts(text)] == ["Parcel A", "Parcel B"]


class TestHeadingDetectionAfterColonAndMergedText:
    """PR #60 review: headings after ':'/';' or merged by the normalizer."""

    @pytest.mark.parametrize(
        "text",
        [
            "A tract of land described as follows: TRACT 1 BEGINNING at a point "
            "THENCE N 100 ft to the POINT OF BEGINNING. "
            "TRACT 2 BEGINNING at a point THENCE S 100 ft to the POINT OF BEGINNING.",
            "TRACT 1 BEGINNING at a point THENCE N 100 ft to the POINT OF BEGINNING, "
            "containing 1 acre more or less PARCEL 2 BEGINNING at a point "
            "THENCE S 100 ft to the POINT OF BEGINNING.",
            "PARCEL 1: BEGINNING at a point THENCE N 100 ft to the POINT OF BEGINNING; "
            "PARCEL 2 BEGINNING at a point THENCE S 100 ft to the POINT OF BEGINNING.",
        ],
    )
    def test_colon_semicolon_and_merged_headings_split(self, text):
        assert len(find_tract_markers(text)) == 2

    def test_ocr_wrapped_reference_is_not_a_heading(self):
        text = (
            "BEGINNING at the northeast corner of\nParcel 2; "
            "THENCE S 0° W 100 ft along the line of\nParcel 3; "
            "THENCE W 100 ft to the POINT OF BEGINNING."
        )
        assert find_tract_markers(text) == []


class TestReferencePrecedenceRound2:
    """PR #60 round 2: reference words beat dash/newline heading heuristics."""

    def test_hyphenated_id_after_reference_word_is_not_a_marker(self):
        text = "PARCEL 1: BEGINNING at a corner of Parcel A-1, thence N 10 ft"
        assert [m[1] for m in find_tract_markers(text)] == ["Parcel 1"]

    @pytest.mark.parametrize("word", ["in", "within", "being"])
    def test_in_within_being_references_are_not_markers(self, word):
        text = f"TRACT 1: BEGINNING at a point {word} Tract 4567\nBEGINNING at a stake"
        assert [m[1] for m in find_tract_markers(text)] == ["Tract 1"]

    def test_reference_word_across_line_break(self):
        text = "TRACT 1: BEGINNING at a point lying in\nTract 4567\nBEGINNING at a stake"
        assert [m[1] for m in find_tract_markers(text)] == ["Tract 1"]


class TestStandaloneHeadingAfterReferenceWord:
    """PR #60 round 3: a standalone heading line is not a reference."""

    @pytest.mark.parametrize(
        ("text", "label"),
        [
            ("Schedule A description of\nPARCEL 1\nBEGINNING at a point", "Parcel 1"),
            ("land being\nTRACT 2\nBEGINNING at a point", "Tract 2"),
            ("lands in\nTract 3\nBeginning at a point", "Tract 3"),
            ("TOGETHER WITH\nPARCEL 2\nBEGINNING at a point", "Parcel 2"),
        ],
    )
    def test_standalone_heading_line_is_a_marker(self, text, label):
        assert [m[1] for m in find_tract_markers(text)] == [label]

    def test_inline_reference_after_closed_description_is_not_a_marker(self):
        text = "of Parcel 2 then N 10 ft"
        assert find_tract_markers(text) == []
