"""PR #60 round 47: the monolith facade keeps easements, strips and stated exceptions off courses."""

from __future__ import annotations

import pytest
from mp_models import DESCRIPTION_ROLES_NOTE, UNAPPLIED_EXCEPTION_NOTE_PREFIX, split_notes

from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker

MAIN = (
    "BEGINNING at an iron pin; thence North 10 degrees East 100 feet; "
    "thence South 80 degrees East 100 feet; thence South 10 degrees West 100 feet; "
    "thence North 80 degrees West 100 feet to the point of beginning."
)
EASEMENT = (
    "ALSO an easement for drainage: BEGINNING at said pin; "
    "thence North 80 degrees West 20 feet; thence North 10 degrees East 50 feet."
)
LOT = (
    "ALSO all that lot BEGINNING at a stake; thence North 10 degrees East 50 feet; "
    "thence South 80 degrees East 50 feet; thence South 10 degrees West 50 feet; "
    "thence North 80 degrees West 50 feet to the point of beginning."
)


def test_monolith_easement_between_descriptions_is_strict_and_verbatim() -> None:
    calls = CallExtractor.extract_calls(f"{MAIN} {EASEMENT} {LOT}")
    assert [c.distance_ft for c in calls] == [100.0] * 4 + [50.0] * 4
    # Round 58: the facade's default extraction is the split one, whose roles (a parcel,
    # an ALSO addition) were inferred: every call carries the role-review mark.
    notes = [split_notes(c.notes) for c in calls]
    assert all(DESCRIPTION_ROLES_NOTE in parts for parts in notes)
    assert [n for parts in notes for n in parts if n != DESCRIPTION_ROLES_NOTE] == [
        "easement, not part of the boundary: " + EASEMENT
    ]


@pytest.mark.parametrize(
    "clause",
    [
        "LESS AND EXCEPT the North 10 feet of said lot conveyed for road purposes",
        "EXCEPTING THEREFROM the Northerly 10 feet of the above described premises for road purposes",
        "SAVE AND EXCEPT the westerly 10 feet thereof",
        "EXCEPT the South 43.65 feet of said Lot in even width conveyed to Jones",
    ],
)
def test_monolith_stated_exception_is_noted_whole_not_a_course(clause) -> None:
    square = CallExtractor.extract_calls(MAIN)
    calls = CallExtractor.extract_calls(f"{MAIN} {clause}.")
    assert [(c.bearing_azimuth_deg_from_north, c.distance_ft, c.is_exception) for c in calls] == [
        (c.bearing_azimuth_deg_from_north, c.distance_ft, c.is_exception) for c in square
    ]
    assert calls[-1].notes == UNAPPLIED_EXCEPTION_NOTE_PREFIX + clause
    result = ClosureChecker.verify_closure(calls)
    assert result.closure_passed and not result.is_fully_verified()
