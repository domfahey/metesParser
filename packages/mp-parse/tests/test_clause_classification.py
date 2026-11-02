"""Tests for clause classification: main tract vs exception vs together-with.

Regression tests for deed 50306-00349 where "except the South 43.65 feet
of said Lot" (a lot qualifier) was incorrectly treated as a structural EXCEPT
clause, causing main tract metes calls to be classified as exceptions.
"""

from __future__ import annotations

import pytest
from mp_parse.calls import extract_calls
from mp_parse.metadata import split_exception_clauses

# ---------------------------------------------------------------------------
# Realistic legal description fragments
# ---------------------------------------------------------------------------

# The sample deed: lot qualifier "except" + Together-with metes + EXCEPT clause
LOT_EXCEPT_TEXT = (
    "Parcel 1: Lot 12, except the South 43.65 feet of said Lot in even width "
    "and parallel with the South line thereof, and all of Lot 13, ASSESSORS "
    "SAMPLE PLAT NO. 1, as recorded in Liber 290, Pages 73 and 77 of Deeds, "
    "also Lots 108, 109 and 110 of SAMPLE HOMESTEAD SUBDIVISION, as recorded "
    "in Liber 66, Page 90 of Plats, County Records. Together with parts of "
    "Lots 11 and 12 of said ASSESSORS SAMPLE PLAT NO. 1, as recorded in Liber 66, "
    "Page 90 of Plats, County Records, described as beginning at a point "
    "distant North 12 degrees, 14 minutes, 20 seconds East 43.65 and South 73 "
    "degrees, 11 minutes, 00 seconds East 210.92 feet from the Northwest corner of "
    "Lot 11 and proceeding thence South 73 degrees, 11 minutes, 00 seconds East "
    "153.00 feet; thence South 32 degrees, 09 minutes, 58 seconds West 82.96 feet; "
    "thence North 73 degrees, 11 minutes, 00 seconds West 131.04 feet; thence "
    "North 16 degrees, 49 minutes, 00 seconds East 80.00 feet to the point of "
    "beginning. EXCEPT the following: Parts of Lots 12 and 13 of ASSESSORS PLAT "
    "NO. 1, as recorded in Liber 66 of Plats, Page 90, City of Sampleton, Sample "
    "County, Michigan and further described as beginning at a point South 78 "
    "degrees, 15 minutes, 40 seconds East along the Northerly line of said Lot 13, "
    "445.93 feet and South 32 degrees, 01 minute, 15 seconds West, along the "
    "Easterly line of said Lot 13, 144.24 feet; and North 73 degrees, 05 minutes, "
    "24 seconds West, 49.61 feet from the Northwesterly corner of said Lot 13; "
    "thence from said point of beginning South 16 degrees, 54 minutes, 36 seconds "
    "West, 85.33 feet; thence North 73 degrees, 05 minutes, 24 seconds West, "
    "128.0 feet; thence North 16 degrees, 54 minutes, 36 seconds East, 18.67 "
    "feet; thence North 28 degrees, 05 minutes, 24 seconds West, 2.83 feet; "
    "thence North 16 degrees, 54 minutes, 36 seconds East, 18.67 feet; thence "
    "South 73 degrees, 05 minutes, 24 seconds East, 2.00 feet; thence North 16 "
    "degrees, 54 minutes, 36 seconds East, 39.33 feet; thence North 73 degrees, "
    "05 minutes, 24 seconds West, 2.00 feet; thence North 16 degrees, 54 minutes, "
    "36 seconds East, 1.33 feet; thence North 61 degrees, 54 minutes 36 seconds "
    "East, 7.54 feet; thence South 73 degrees, 05 minutes 24 seconds East, "
    "124.67 feet to the point of beginning."
)


class TestSplitExceptionClausesLotQualifier:
    """Test that lot-qualifier 'except' is not treated as structural EXCEPT."""

    def test_lot_qualifier_except_not_split(self) -> None:
        """'except the South 43.65 feet of said Lot' should not cause a split."""
        text = (
            "Lot 12, except the South 43.65 feet of said Lot in even width, "
            "and all of Lot 13. Together with beginning thence S 73 degrees E "
            "153.00 feet to the point of beginning."
        )
        result = split_exception_clauses(text)
        # Should be a single main tract (no exception split)
        assert len(result) == 1
        assert result[0][1] is False

    def test_lot_qualifier_except_north(self) -> None:
        """'except the North 50 feet of the lot' is a lot qualifier."""
        text = (
            "Lot 5, except the North 50 feet of the Lot, Block 3. THENCE N 45 degrees E 100 feet."
        )
        result = split_exception_clauses(text)
        assert len(result) == 1
        assert result[0][1] is False

    def test_lot_qualifier_except_easterly(self) -> None:
        """'except the Easterly 25 feet thereof' is a lot qualifier."""
        text = (
            "Lot 8, except the Easterly 25 feet thereof, in Block 2. "
            "THENCE S 30 degrees W 200 feet."
        )
        result = split_exception_clauses(text)
        assert len(result) == 1
        assert result[0][1] is False

    def test_lot_qualifier_except_westerly(self) -> None:
        """'except the Westerly 10.5 feet of said lot' is a lot qualifier."""
        text = "Lot 3, except the Westerly 10.5 feet of said lot, THENCE N 60 degrees W 150 feet."
        result = split_exception_clauses(text)
        assert len(result) == 1
        assert result[0][1] is False

    def test_structural_except_still_splits(self) -> None:
        """'EXCEPT the following:' is a structural exception and MUST split."""
        text = (
            "THENCE S 73 degrees E 153.00 feet to the point of beginning. "
            "EXCEPT the following: beginning at a point thence S 16 degrees W "
            "85.33 feet to the point of beginning."
        )
        result = split_exception_clauses(text)
        exceptions = [r for r in result if r[1] is True]
        assert len(exceptions) >= 1

    def test_structural_except_parts_of(self) -> None:
        """'EXCEPT parts of Lots...' is structural and should split."""
        text = (
            "THENCE N 45 degrees E 100 feet to the point of beginning. "
            "EXCEPT parts of Lots 12 and 13 described as beginning at a point "
            "thence S 16 degrees W 85 feet to the point of beginning."
        )
        result = split_exception_clauses(text)
        exceptions = [r for r in result if r[1] is True]
        assert len(exceptions) >= 1

    def test_structural_less_and_except(self) -> None:
        """'LESS AND EXCEPT' is always structural."""
        text = "THENCE N 45 degrees E 100 feet. LESS AND EXCEPT a strip 10 feet wide."
        result = split_exception_clauses(text)
        exceptions = [r for r in result if r[1] is True]
        assert len(exceptions) >= 1

    def test_structural_excepting(self) -> None:
        """'EXCEPTING' is always structural."""
        text = (
            "THENCE N 45 degrees E 100 feet. "
            "EXCEPTING therefrom a parcel described as beginning "
            "thence S 30 degrees W 50 feet."
        )
        result = split_exception_clauses(text)
        exceptions = [r for r in result if r[1] is True]
        assert len(exceptions) >= 1


class TestLotExceptClauseClassification:
    """End-to-end clause classification for deed 50306-00349."""

    def test_sample_split_produces_main_and_exception(self) -> None:
        """The sample text should split into main tract + exception, not all-exception."""
        result = split_exception_clauses(LOT_EXCEPT_TEXT)
        main_tracts = [r for r in result if r[1] is False]
        exception_tracts = [r for r in result if r[1] is True]
        assert len(main_tracts) >= 1, "Expected at least one main tract"
        assert len(exception_tracts) >= 1, "Expected at least one exception tract"

    def test_sample_main_tract_has_thence(self) -> None:
        """Main tract text should contain THENCE (the metes calls)."""
        result = split_exception_clauses(LOT_EXCEPT_TEXT)
        main_tracts = [r for r in result if r[1] is False]
        assert any("thence" in t[0].lower() for t in main_tracts), (
            "Main tract should contain metes calls with THENCE"
        )

    def test_sample_extract_calls_main_tract_count(self) -> None:
        """The sample should produce 4 main tract calls (is_exception=False)."""
        calls, _tracts = extract_calls(LOT_EXCEPT_TEXT)
        main_calls = [c for c in calls if not c.is_exception]
        assert len(main_calls) == 4, (
            f"Expected 4 main tract calls, got {len(main_calls)}: "
            f"{[(c.course, c.direction_text, c.distance_ft) for c in main_calls]}"
        )

    def test_sample_extract_calls_exception_count(self) -> None:
        """The sample should produce 11 exception calls (is_exception=True)."""
        calls, _tracts = extract_calls(LOT_EXCEPT_TEXT)
        exception_calls = [c for c in calls if c.is_exception]
        assert len(exception_calls) == 11, (
            f"Expected 11 exception calls, got {len(exception_calls)}: "
            f"{[(c.course, c.direction_text, c.distance_ft) for c in exception_calls]}"
        )

    def test_sample_main_tract_first_call_distance(self) -> None:
        """First main tract call should have distance 153.00 ft."""
        calls, _tracts = extract_calls(LOT_EXCEPT_TEXT)
        main_calls = [c for c in calls if not c.is_exception]
        assert len(main_calls) >= 1
        first = main_calls[0]
        assert first.distance_ft == pytest.approx(153.00, abs=0.01)

    def test_sample_main_tract_last_call_closes(self) -> None:
        """Last main tract call should close to POB."""
        calls, _tracts = extract_calls(LOT_EXCEPT_TEXT)
        main_calls = [c for c in calls if not c.is_exception]
        assert len(main_calls) >= 1
        last = main_calls[-1]
        assert last.to is not None
        assert "point of beginning" in last.to.lower()

    def test_sample_exception_first_call_distance(self) -> None:
        """First exception call should have distance 85.33 ft."""
        calls, _tracts = extract_calls(LOT_EXCEPT_TEXT)
        exception_calls = [c for c in calls if c.is_exception]
        assert len(exception_calls) >= 1
        first = exception_calls[0]
        assert first.distance_ft == pytest.approx(85.33, abs=0.01)

    def test_sample_total_call_count(self) -> None:
        """The sample should produce exactly 15 total calls (4 main + 11 exception)."""
        calls, _tracts = extract_calls(LOT_EXCEPT_TEXT)
        assert len(calls) == 15, f"Expected 15 total calls, got {len(calls)}"


class TestSingleClauseDeedUnchanged:
    """Verify that simple deeds with no exceptions still work correctly."""

    def test_simple_deed_no_exception(self) -> None:
        """A straightforward deed with no EXCEPT should produce all main calls."""
        text = (
            "Beginning at a point thence North 45 degrees East 100.00 feet; "
            "thence South 45 degrees East 100.00 feet; "
            "thence South 45 degrees West 100.00 feet; "
            "thence North 45 degrees West 100.00 feet to the point of beginning."
        )
        calls, _tracts = extract_calls(text)
        assert len(calls) == 4
        assert all(not c.is_exception for c in calls)

    def test_split_no_exception_single_tract(self) -> None:
        """split_exception_clauses with no EXCEPT returns single main tract."""
        text = "THENCE North 45 degrees East 100 feet to the point of beginning."
        result = split_exception_clauses(text)
        assert len(result) == 1
        assert result[0][1] is False


class TestLotQualifierVariants:
    """Test various forms of lot-qualifier 'except' that should NOT split."""

    def test_except_southerly_of_lot(self) -> None:
        """'except the Southerly 30 feet of Lot 5' is a lot qualifier."""
        text = (
            "Lot 5, except the Southerly 30 feet of Lot 5, in Block 2. "
            "THENCE N 45 degrees E 100 feet."
        )
        result = split_exception_clauses(text)
        # Should not split on the lot qualifier
        assert len(result) == 1
        assert result[0][1] is False

    def test_except_with_in_even_width(self) -> None:
        """'except the South 43.65 feet ... in even width' is a lot qualifier."""
        text = (
            "Lot 12, except the South 43.65 feet of said Lot in even width "
            "and parallel with the South line thereof."
        )
        result = split_exception_clauses(text)
        assert len(result) == 1
        assert result[0][1] is False

    def test_except_northerly_thereof(self) -> None:
        """'except the Northerly 20 feet thereof' is a lot qualifier."""
        text = "All of Lot 7, except the Northerly 20 feet thereof."
        result = split_exception_clauses(text)
        assert len(result) == 1
        assert result[0][1] is False

    def test_mixed_qualifier_and_structural(self) -> None:
        """Lot qualifier followed by structural EXCEPT should split on structural only."""
        text = (
            "Lot 12, except the South 43.65 feet of said Lot, and Lot 13. "
            "THENCE N 45 degrees E 100 feet. "
            "EXCEPT the following: THENCE S 30 degrees W 50 feet."
        )
        result = split_exception_clauses(text)
        main_tracts = [r for r in result if r[1] is False]
        exception_tracts = [r for r in result if r[1] is True]
        assert len(main_tracts) >= 1, "Should have main tract"
        assert len(exception_tracts) >= 1, "Should have exception tract"
        # The main tract should contain the lot qualifier text and the THENCE
        main_text = " ".join(t[0] for t in main_tracts)
        assert "thence" in main_text.lower() or "THENCE" in main_text
