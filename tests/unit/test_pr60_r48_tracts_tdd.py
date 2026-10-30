"""PR #60 round 48: the monolith facade keeps fee additions, exception wording and bearings."""

from __future__ import annotations

import pytest
from mp_models import UNAPPLIED_EXCEPTION_NOTE_PREFIX, split_notes

from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker

SQUARE = (
    "BEGINNING at a pin; thence N 0° E 100 feet to a pin; thence S 90° E 100 feet to a pin; "
    "thence S 0° W 100 feet to a pin; thence N 90° W 100 feet to the point of beginning."
)
SMALL = (
    "BEGINNING at a stake; thence N 0° E 50 feet; thence S 90° E 50 feet; "
    "thence S 0° W 50 feet; thence N 90° W 50 feet to the point of beginning."
)


@pytest.mark.parametrize(
    "lead",
    [
        "ALSO all that tract of land adjoining the railroad right of way,",
        "ALSO the land within the former easement area, described as",
    ],
)
def test_monolith_fee_addition_mentioning_an_easement_keeps_its_courses(lead) -> None:
    calls = CallExtractor.extract_calls(f"{SQUARE} {lead} {SMALL}")
    assert [c.distance_ft for c in calls] == [100.0] * 4 + [50.0] * 4


@pytest.mark.parametrize(
    "clause",
    [
        "EXCEPT the South 10 feet thereof conveyed to John A. Smith by deed dated May 1, 1950",
        "EXCEPT the part conveyed to the U.S. Government for a post office",
        "ALSO EXCEPTING the part lying north of a line running N 80 degrees E from the pin",
    ],
)
def test_monolith_exception_is_noted_whole_never_a_course(clause) -> None:
    square = CallExtractor.extract_calls(SQUARE)
    calls = CallExtractor.extract_calls(f"{SQUARE} {clause}.")
    assert [(c.bearing_azimuth_deg_from_north, c.distance_ft) for c in calls] == [
        (c.bearing_azimuth_deg_from_north, c.distance_ft) for c in square
    ]
    assert UNAPPLIED_EXCEPTION_NOTE_PREFIX + clause in split_notes(calls[-1].notes)
    result = ClosureChecker.verify_closure(calls)
    assert result.closure_passed and not result.is_fully_verified()
