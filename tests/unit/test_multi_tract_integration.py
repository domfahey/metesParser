"""Integration tests for multi-tract support with real deed patterns."""

import pytest
from mp_models import TractType
from mp_parse.calls import extract_calls
from mp_parse.tracts import split_into_tracts
from mp_verify import verify_closure


class TestSplitAndExtract:
    """End-to-end: split_into_tracts -> extract_calls -> verify_closure."""

    def test_except_clause_creates_exception_tract(self):
        """EXCEPT clause creates TractType.EXCEPTION."""
        text = (
            "THENCE North 45 degrees 00 minutes 00 seconds East, a distance of 100.00 feet; "
            "THENCE South 45 degrees 00 minutes 00 seconds East, a distance of 100.00 feet; "
            "THENCE South 45 degrees 00 minutes 00 seconds West, a distance of 100.00 feet; "
            "THENCE North 45 degrees 00 minutes 00 seconds West, a distance of 100.00 feet "
            "to the POINT OF BEGINNING. "
            "EXCEPT BEGINNING at a point "
            "THENCE South 10 degrees 00 minutes 00 seconds East, a distance of 50.00 feet; "
            "THENCE South 10 degrees 00 minutes 00 seconds West, a distance of 50.00 feet; "
            "THENCE North 10 degrees 00 minutes 00 seconds West, a distance of 50.00 feet; "
            "THENCE North 10 degrees 00 minutes 00 seconds East, a distance of 50.00 feet "
            "to the POINT OF BEGINNING."
        )
        calls, tracts = extract_calls(text)
        assert [(t.label, t.tract_type, len(t.calls)) for t in tracts] == [
            ("Tract 1", TractType.MAIN, 4),
            ("Exception 1", TractType.EXCEPTION, 4),
        ]

    def test_tract_markers_split_and_verify(self):
        """TRACT #N markers split into independent tracts that verify independently."""
        text = (
            "TRACT #1: BEGINNING at a point "
            "THENCE North 45 degrees 00 minutes 00 seconds East, a distance of 100.00 feet; "
            "THENCE South 45 degrees 00 minutes 00 seconds East, a distance of 100.00 feet; "
            "THENCE South 45 degrees 00 minutes 00 seconds West, a distance of 100.00 feet; "
            "THENCE North 45 degrees 00 minutes 00 seconds West, a distance of 100.00 feet "
            "to the POINT OF BEGINNING. "
            "TRACT #2: BEGINNING at a point "
            "THENCE South 45 degrees 00 minutes 00 seconds East, a distance of 50.00 feet; "
            "THENCE South 45 degrees 00 minutes 00 seconds West, a distance of 50.00 feet; "
            "THENCE North 45 degrees 00 minutes 00 seconds West, a distance of 50.00 feet; "
            "THENCE North 45 degrees 00 minutes 00 seconds East, a distance of 50.00 feet "
            "to the POINT OF BEGINNING."
        )
        calls, tracts = extract_calls(text)
        assert len(tracts) == 2
        assert tracts[0].label == "Tract 1"
        assert tracts[1].label == "Tract 2"

        # Verify each tract independently
        results = verify_closure(calls, tracts=tracts)
        assert isinstance(results, list)
        assert len(results) == 2
        assert all(result.closure_passed for result in results)
        assert results[0].area_sq_ft == pytest.approx(10000.0, abs=1e-6)
        assert results[1].area_sq_ft == pytest.approx(2500.0, abs=1e-6)

    def test_single_tract_no_tracts_returned(self):
        """Single-tract deed returns empty tracts list and single ClosureResult."""
        text = (
            "BEGINNING at a point "
            "THENCE North 45 degrees 00 minutes 00 seconds East, a distance of 100.00 feet; "
            "THENCE South 45 degrees 00 minutes 00 seconds East, a distance of 100.00 feet; "
            "THENCE South 45 degrees 00 minutes 00 seconds West, a distance of 100.00 feet; "
            "THENCE North 45 degrees 00 minutes 00 seconds West, a distance of 100.00 feet "
            "to the POINT OF BEGINNING."
        )
        calls, tracts = extract_calls(text)
        assert tracts == []
        assert len(calls) == 4

        result = verify_closure(calls)
        assert not isinstance(result, list)
        assert result.closure_passed

    def test_exception_calls_marked(self):
        """Exception tract calls have is_exception=True."""
        text = (
            "THENCE North 45 degrees 00 minutes 00 seconds East, a distance of 100.00 feet; "
            "THENCE South 45 degrees 00 minutes 00 seconds East, a distance of 100.00 feet "
            "EXCEPT THENCE South 10 degrees 00 minutes 00 seconds East, a distance of 50.00 feet"
        )
        calls, tracts = extract_calls(text)
        assert [(t.label, t.tract_type, len(t.calls)) for t in tracts] == [
            ("Tract 1", TractType.MAIN, 2),
            ("Exception 1", TractType.EXCEPTION, 1),
        ]
        assert [c.is_exception for c in tracts[0].calls] == [False, False]
        assert [c.is_exception for c in tracts[1].calls] == [True]

    def test_multiple_beginning_blocks(self):
        """Multiple BEGINNING blocks split into separate tracts."""
        text = (
            "BEGINNING at an iron pin "
            "THENCE North 45 degrees 00 minutes 00 seconds East, a distance of 100.00 feet; "
            "THENCE South 45 degrees 00 minutes 00 seconds East, a distance of 100.00 feet; "
            "THENCE South 45 degrees 00 minutes 00 seconds West, a distance of 100.00 feet; "
            "THENCE North 45 degrees 00 minutes 00 seconds West, a distance of 100.00 feet "
            "to the POINT OF BEGINNING. "
            "ALSO BEGINNING at a concrete monument "
            "THENCE South 45 degrees 00 minutes 00 seconds East, a distance of 200.00 feet; "
            "THENCE South 45 degrees 00 minutes 00 seconds West, a distance of 200.00 feet; "
            "THENCE North 45 degrees 00 minutes 00 seconds West, a distance of 200.00 feet; "
            "THENCE North 45 degrees 00 minutes 00 seconds East, a distance of 200.00 feet "
            "to the POINT OF BEGINNING."
        )
        segments = split_into_tracts(text)
        assert len(segments) == 2
