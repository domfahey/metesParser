"""PR #60 round 52: the monolith facade reads adjoiner "along with" and structural
sentence ends like the package, and keeps the boundary after a generic recital."""

from __future__ import annotations

import pytest
from mp_models import unapplied_exceptions
from mp_parse import extract_calls

from metesparser.call_extractor import CallExtractor
from metesparser.text_parser import TextParser

SQUARE = (
    "BEGINNING at a pin; thence N 0° E 100 feet to a pin; thence S 90° E 100 feet to a pin; "
    "thence S 0° W 100 feet to a pin; thence N 90° W 100 feet to the point of beginning."
)
CASES = {
    "along-with-adjoiner": (
        "BEGINNING at a pin; THENCE along with the Northerly side of Main Street "
        "N 0°00'00\" E 100 feet to a pin; THENCE S 90° E 100 feet along with said road to a "
        "pin; THENCE S 0° W 100 feet to a pin; THENCE N 90° W 100 feet to the point of "
        "beginning."
    ),
    "subject-to-easements-of-record": f"SUBJECT to easements of record.\n\n{SQUARE}",
    "lot-subject-to-easements-if-any": (
        "Being Lot 5, Block 3, subject to easements and restrictions of record, if any.\n\n"
        f"ALL THAT CERTAIN lot of land described as follows: {SQUARE}"
    ),
    "exception-before-form": (
        f"{SQUARE} No fee is due except in the case of a spouse.\n\n### B. BLIND\n\n"
        "- [ ] Grantor(s) legally blind."
    ),
}


def _row(call):
    return (call.course, call.bearing_azimuth_deg_from_north, call.distance_ft, call.along)


@pytest.mark.parametrize("name", sorted(CASES))
def test_facade_matches_package(name: str) -> None:
    text = CASES[name]
    package, tracts = extract_calls(text, strict=True)
    monolith = CallExtractor.extract_calls(text, strict=True)
    assert not tracts
    assert len(package) == 4
    assert [_row(c) + (c.to, c.notes) for c in monolith] == [
        _row(c) + (c.to, c.notes) for c in package
    ]


def test_facade_along_with_adjoiner() -> None:
    calls = CallExtractor.extract_calls(CASES["along-with-adjoiner"], strict=True)
    assert [c.along for c in calls] == [
        "the Northerly side of Main Street",
        "said road",
        None,
        None,
    ]
    assert TextParser.extract_deed_clauses(CASES["along-with-adjoiner"]) == []


def test_facade_exception_note_stops_before_the_form() -> None:
    calls = CallExtractor.extract_calls(CASES["exception-before-form"], strict=True)
    assert [w for c in calls for w in unapplied_exceptions(c.notes)] == [
        "except in the case of a spouse"
    ]
