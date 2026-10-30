"""PR #60 round 43: the monolith facade extracts or fails closed on preamble courses."""

from __future__ import annotations

import pytest

from metesparser.call_extractor import CallExtractor
from metesparser.models import SkippedCourse

REST = (
    "thence S 45° E 100 feet to a pin; thence S 45° W 100 feet to a pin; "
    "thence N 45° W 100 feet to the point of beginning."
)


@pytest.mark.parametrize(
    "text",
    [
        "BEGINNING at an iron pin being the northeast corner of Lot 5; N 45° E 100 feet to a "
        "pin; " + REST,
        "BEGINNING at a pin; N 45° E 100 feet along Main Street; " + REST,
        "BEGINNING at a pin, running N 45° E 100 feet along Main Street, " + REST,
    ],
)
def test_monolith_extracts_the_course_before_the_first_thence(text):
    calls = CallExtractor.extract_calls(text)
    assert [c.bearing_azimuth_deg_from_north for c in calls] == [45.0, 135.0, 225.0, 315.0]
    assert [c.course for c in calls] == [1, 2, 3, 4]


def test_monolith_fails_closed_on_inseparable_preamble_course():
    text = "BEGINNING at a pin, N 45° E 100 feet along Main Street; " + REST
    with pytest.raises(ValueError, match="BEGINNING"):
        CallExtractor.extract_calls(text)
    skipped: list[SkippedCourse] = []
    CallExtractor.extract_calls(text, strict=False, skipped_courses=skipped)
    assert [s.error_type for s in skipped] == ["CourseInPreamble"]
