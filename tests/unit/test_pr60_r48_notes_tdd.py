"""PR #60 round 48: the monolith facade keeps notes by prefix and offsets off the length."""

from __future__ import annotations

import pytest
from mp_parse import extract_calls

from metesparser.call_extractor import CallExtractor

POB = "BEGINNING at a point; "
CLOSING = "; thence S 45° E 100 feet to the point of beginning."

# (fragment, distance, along, to, notes) of the first course.
CASES = {
    "record-then-passing": (
        "thence N 45° E (deed N 44° E) 100 feet, passing a pipe at 50 feet, to a pin",
        100.0,
        None,
        "a pin",
        "record call: (deed N 44° E); passing call: passing a pipe at 50 feet",
    ),
    "record-length-after-terminus": (
        "thence N 45° E 100 feet to a pin (deed 99 feet)",
        100.0,
        None,
        "a pin",
        "record call: (deed 99 feet)",
    ),
    "record-bearing-after-terminus": (
        "thence N 45° E 100 feet to a pin (record N 44° E)",
        100.0,
        None,
        "a pin",
        "record call: (record N 44° E)",
    ),
    "parallel-offset": (
        "thence N 45° E along a line parallel to and 10 feet from Main Street 100 feet to a pin",
        100.0,
        "a line parallel to and 10 feet from Main Street",
        "a pin",
        None,
    ),
    "passing-after-semicolon": (
        "thence N 45° E 100 feet to a pin; passing a monument at 30 feet",
        100.0,
        None,
        "a pin",
        "passing call: passing a monument at 30 feet",
    ),
}


def _first(calls):
    return next(call for call in calls if call.course == 1)


@pytest.mark.parametrize("name", sorted(CASES))
def test_facade_matches_package_and_expected(name: str) -> None:
    fragment, distance, along, to, notes = CASES[name]
    text = POB + fragment + CLOSING
    package, _ = extract_calls(text, strict=True)
    monolith = CallExtractor.extract_calls(text, strict=True)
    for call in (_first(package), _first(monolith)):
        assert (call.distance_ft, call.along, call.to, call.notes) == (distance, along, to, notes)
