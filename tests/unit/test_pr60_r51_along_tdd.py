"""PR #60 round 51: the monolith facade keeps along/to wording whole like the package."""

from __future__ import annotations

import pytest
from mp_parse import extract_calls

from metesparser.call_extractor import CallExtractor
from metesparser.text_parser import TextParser

POB = "BEGINNING at a pin; "
CLOSING = "; thence N 45° W 100 feet to the point of beginning; along with all improvements."

# (fragment, distance, along, to) of the first course.
CASES = {
    "compound-length": (
        "thence along the line of Smith N 45° E 1 chain 50 links to a pin",
        99.0,
        "the line of Smith",
        "a pin",
    ),
    "more-or-less": (
        "thence along the line of Jones S 45° E 100 feet, more or less, to a pin",
        100.0,
        "the line of Jones",
        "a pin",
    ),
    "length-after-destination": (
        "thence S 45° E to a pin 100 feet more or less along the line of Jones",
        100.0,
        "the line of Jones",
        "a pin",
    ),
    "along-with-conveyance": (
        "thence N 45° E 100 feet to a pin; along with the right to use the driveway",
        100.0,
        None,
        "a pin",
    ),
    "label-letter-sentence": (
        "thence N 45° E 100 feet along Lot B. The line continues",
        100.0,
        "Lot B",
        None,
    ),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_facade_matches_package_and_expected(name: str) -> None:
    fragment, distance, along, to = CASES[name]
    text = POB + fragment + CLOSING
    package, _ = extract_calls(text, strict=True)
    monolith = CallExtractor.extract_calls(text, strict=True)
    assert len(package) == len(monolith) == 2
    for call in (package[0], monolith[0]):
        assert (call.distance_ft, call.along, call.to, call.notes) == (distance, along, to, None)
    for call in (package[1], monolith[1]):
        assert (call.along, call.to) == (None, "the point of beginning")


def test_facade_deed_clauses_record_along_with() -> None:
    clauses = TextParser.extract_deed_clauses(POB + "thence N 45° E 100 feet to a pin" + CLOSING)
    assert [(c.clause_type, c.text) for c in clauses] == [
        ("together_with", "along with all improvements")
    ]
