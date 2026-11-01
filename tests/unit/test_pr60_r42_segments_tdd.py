"""PR #60 round 42: the monolith facade never silently loses courses either."""

from __future__ import annotations

import pytest

from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker
from metesparser.models import SkippedCourse

AND_JOINED = (
    "BEGINNING at a pin and running N 45° E 100 feet to a pin and S 45° E 100 feet to a pin "
    "and S 45° W 100 feet to a pin and N 45° W 100 feet to the beginning."
)
HIDDEN_IN_BEGINNING = (
    "BEGINNING at a pin, N 45° E 100 feet to a pin; S 45° E 100 feet to a pin; "
    "S 45° W 100 feet to a pin; N 45° W 100 feet to the beginning."
)
COMMENCING = (
    "COMMENCING at the corner of X and Y; thence N 45° E 50 feet to the point of beginning; "
    "thence N 45° E 100 feet to a pin; thence S 45° E 100 feet to a pin; thence S 45° W 100 "
    "feet to a pin; thence N 45° W 100 feet to the point of beginning."
)


def test_monolith_extracts_every_and_joined_course():
    calls = CallExtractor.extract_calls(AND_JOINED)
    assert [c.bearing_azimuth_deg_from_north for c in calls] == [45.0, 135.0, 225.0, 315.0]
    assert ClosureChecker.verify_closure(calls).misclosure_ft < 0.01


def test_monolith_raises_for_course_in_beginning_clause():
    with pytest.raises(ValueError, match="BEGINNING"):
        CallExtractor.extract_calls(HIDDEN_IN_BEGINNING)


def test_monolith_records_course_in_beginning_clause_when_not_strict():
    skipped: list[SkippedCourse] = []
    CallExtractor.extract_calls(HIDDEN_IN_BEGINNING, strict=False, skipped_courses=skipped)
    assert [s.error_type for s in skipped] == ["CourseInPreamble"]


def test_monolith_marks_commencing_tie_in():
    calls = CallExtractor.extract_calls(COMMENCING)
    assert [c.is_tie_in for c in calls] == [True, False, False, False, False]
    assert ClosureChecker.verify_closure(calls).misclosure_ft < 0.01
