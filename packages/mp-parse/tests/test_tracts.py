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


class TestTractMarkerSuffix:
    def test_numbered_tract_with_letter_suffix(self):
        text = (
            "TRACT #2: BEGINNING at a point THENCE N 45°00' E 100 feet to a point. "
            "TRACT #2B: BEGINNING at a point THENCE S 45°00' E 50 feet to a point."
        )
        result = split_into_tracts(text)
        assert [label for _, label, _ in result] == ["Tract 2", "Tract 2B"]

    def test_ordinal_suffix_is_not_a_tract_letter(self):
        text = "TRACT 12th: BEGINNING at a point THENCE N 45°00' E 100 feet to a point."
        assert split_into_tracts(text)[0][1] == "Tract 12"

    def test_tract_no_marker(self):
        text = (
            "TRACT NO. 1\n\nBEGINNING at a point THENCE N 45°00' E 100 feet to a point.\n\n"
            "Tract No. 2\n\nBEGINNING at a point THENCE S 45°00' E 50 feet to a point."
        )
        result = split_into_tracts(text)
        assert [label for _, label, _ in result] == ["Tract 1", "Tract 2"]

    def test_tract_number_reference_is_not_a_marker(self):
        """219 Berlin Rd: "tract number 1" mid-description used to become "Tract n"
        and drop every course before it."""
        text = (
            "BEGINNING at a point; thence N 45°00' E 100 feet to a point; thence "
            "S 45°00' E 50 feet along a line common with tract number 2 herein described; "
            "thence N 10°00' W 35 feet thru tract numbered 1 to the point of beginning."
        )
        calls, tracts = extract_calls(text)
        assert [call.distance_ft for call in calls] == [100, 50, 35]
        assert [tract.label for tract in tracts] == []


class TestExceptionsWithinMarkedTracts:
    def test_except_clause_after_last_tract_becomes_exception_tracts(self):
        text = (
            "TRACT #1: BEGINNING at a point THENCE N 45°00' E 100 feet to a point; "
            "THENCE S 45°00' W 100 feet to the point of beginning. "
            "EXCEPTING THEREOUT that part described as follows: BEGINNING at a stake; "
            "THENCE N 10°00' E 20 feet to beginning. "
            "ALSO EXCEPTING THEREOUT that part described as follows: STARTING at a stake; "
            "THENCE S 10°00' W 30 feet to beginning."
        )
        result = split_into_tracts(text)
        assert [(label, tract_type) for _, label, tract_type in result] == [
            ("Tract 1", TractType.MAIN),
            ("Exception 1", TractType.EXCEPTION),
            ("Exception 2", TractType.EXCEPTION),
        ]
        assert "EXCEPTING" not in result[0][0]

    def test_exception_tract_calls_are_separate_from_main_tract(self):
        text = (
            "TRACT #1: BEGINNING at a point THENCE N 45°00' E 100 feet to a point; "
            "THENCE S 45°00' W 100 feet to the point of beginning. "
            "EXCEPTING THEREOUT that part described as follows: BEGINNING at a stake; "
            "THENCE N 10°00' E 20 feet to beginning."
        )
        calls, tracts = extract_calls(text)
        assert [(t.label, len(t.calls)) for t in tracts] == [("Tract 1", 2), ("Exception 1", 1)]
        assert [c.is_exception for c in calls] == [False, False, True]

    def test_narrative_exception_stays_in_marked_tract(self):
        """A conveyance-only EXCEPT clause has no courses, so it is not an exception tract."""
        text = (
            "SCHEDULE A-3: BEGINNING at a point; THENCE N 45°00' E 100 feet; "
            "THENCE S 45°00' W 100 feet to the point of beginning. "
            "Excepting thereout and therefrom so much as was conveyed to the State of "
            "New Jersey by Deed Book 3903, page 46."
        )
        assert [(label, tract_type) for _, label, tract_type in split_into_tracts(text)] == [
            ("Schedule A-3", TractType.MAIN)
        ]
        calls, _tracts = extract_calls(text)
        assert [c.is_exception for c in calls] == [False, False]


class TestScheduleMarkers:
    """219 Berlin Rd 12799-00118: one property per SCHEDULE A-n."""

    def test_schedules_split_into_tracts(self):
        text = (
            "SCHEDULE A-1\n\nBEGINNING at a point; thence N 45°00' E 100 feet to a point; "
            "thence S 45°00' W 100 feet to point and place of beginning.\n\n"
            "SCHEDULE A-2\n\nBEGINNING at a point; thence\n(1) N 10°00' E 20 feet; thence\n"
            "(2) S 10°00' W 20 feet to the point of beginning."
        )
        calls, tracts = extract_calls(text)
        assert [(t.label, len(t.calls)) for t in tracts] == [
            ("Schedule A-1", 2),
            ("Schedule A-2", 2),
        ]
        assert [c.distance_ft for c in calls] == [100, 100, 20, 20]

    def test_lone_schedule_a_is_not_a_marker(self):
        text = "Schedule A\n\nBEGINNING at a point THENCE N 45°00' E 100 feet to a point."
        assert split_into_tracts(text)[0][1] == "Tract 1"


class TestBeginningBlockClosures:
    def test_said_point_of_beginning_does_not_close_the_block(self):
        text = (
            "BEGINNING at a point, said point of beginning being also distant 24.75 feet "
            "from the center line, and from said point of beginning, proceeding THENCE "
            "N 45°00' E 100 feet; THENCE S 45°00' W 100 feet to the point of beginning. "
            "BEGINNING at a stake; THENCE N 10°00' E 20 feet; THENCE S 10°00' W 20 feet "
            "to the point of beginning."
        )
        assert [label for _, label, _ in split_into_tracts(text)] == ["Tract 1", "Tract 2"]

    def test_easement_block_is_an_easement_tract(self):
        text = (
            "BEGINNING at a point; THENCE N 45°00' E 100 feet; THENCE S 45°00' W 100 feet "
            "to the point of beginning. UNDER AND SUBJECT to an ingress and egress easement "
            "bounded and described as follows: BEGINNING at a stake; THENCE N 10°00' E 20 "
            "feet; THENCE S 10°00' W 20 feet to the point of beginning."
        )
        assert [(label, tract_type) for _, label, tract_type in split_into_tracts(text)] == [
            ("Tract 1", TractType.MAIN),
            ("Easement 1", TractType.EASEMENT),
        ]

    def test_to_said_point_of_beginning_closes_the_block(self):
        text = (
            "BEGINNING at a point; THENCE N 45°00' E 100 feet; THENCE S 45°00' W 100 feet "
            "to said point of beginning. "
            "BEGINNING at a stake; THENCE N 10°00' E 20 feet; THENCE S 10°00' W 20 feet "
            "to said point of beginning."
        )
        assert [label for _, label, _ in split_into_tracts(text)] == ["Tract 1", "Tract 2"]

    def test_parcel_and_tract_references_are_not_markers(self):
        """15 E Redman: "corner of Parcel #69" and "D.R.P.A., Parcel #69" are references."""
        text = (
            "BEGINNING at a point at the Southeasterly corner of Parcel #69, conveyed to the "
            "Port Authority; THENCE N 45°00' E 100 feet to the said stake corner to D.R.P.A., "
            "Parcel #69; THENCE along the boundary line of Tract #1 of Haddonfield Estates "
            "S 45°00' W 100 feet to the point of beginning."
        )
        calls, tracts = extract_calls(text)
        assert [call.distance_ft for call in calls] == [100, 100]
        assert tracts == []
