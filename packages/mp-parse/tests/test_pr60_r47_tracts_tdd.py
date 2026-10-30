"""PR #60 round 47: tract splitting and stated exceptions fail closed, never invent courses.

- An easement described by its own courses between two closed descriptions becomes
  an EASEMENT tract; the lead-in wording left behind ("ALSO all that lot") attaches
  to the following description and never becomes a tract of its own.
- A strip exception is recognised with its whole lead ("SAVE AND EXCEPT",
  "EXCEPTING THEREFROM", ...), its object ("of said lot", "of the above described
  premises") and a trailing purpose ("for road purposes", "conveyed for ...").
- An EXCEPT clause that is neither a strip nor a described traverse is noted as an
  unapplied exception, never read as a cardinal-only course.
- Exception wording holding "; " is kept whole by note parsing.
"""

from __future__ import annotations

import pytest
from mp_models import UNAPPLIED_EXCEPTION_NOTE_PREFIX, TractType, unapplied_exceptions
from mp_parse.calls import _extract_calls_from_text, extract_calls
from mp_parse.metadata import detect_strip_exceptions
from mp_parse.tracts import UNLABELLED_TRACT_LABEL, split_into_tracts
from mp_verify import verify_closure

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
TWO_PARCELS_WITH_EASEMENT = f"{MAIN} {EASEMENT} {LOT}"


def _boundary(calls):
    return [
        (c.course, c.bearing_azimuth_deg_from_north, c.distance_ft, c.to, c.is_exception)
        for c in calls
    ]


@pytest.fixture(scope="module")
def main_calls():
    calls, tracts = extract_calls(MAIN)
    assert tracts == []
    return calls


# --- 1. easement between two descriptions --------------------------------------------


def test_easement_between_descriptions_leaves_no_fragment_tract() -> None:
    segments = split_into_tracts(TWO_PARCELS_WITH_EASEMENT)
    assert [(label, kind) for _, label, kind in segments] == [
        ("Tract 1", TractType.MAIN),
        ("Easement 1", TractType.EASEMENT),
        ("Addition 1", TractType.ADDITION),
    ]
    assert not any(label.startswith(UNLABELLED_TRACT_LABEL) for _, label, _ in segments)
    # The lead-in left behind by the easement attaches to the following description.
    assert segments[2][0].startswith("ALSO all that lot BEGINNING at a stake")
    assert segments[1][0] == EASEMENT


def test_easement_between_descriptions_extracts_strictly(main_calls) -> None:
    calls, tracts = extract_calls(TWO_PARCELS_WITH_EASEMENT)
    assert [(t.label, t.tract_type, len(t.calls)) for t in tracts] == [
        ("Tract 1", TractType.MAIN, 4),
        ("Easement 1", TractType.EASEMENT, 2),
        ("Addition 1", TractType.ADDITION, 4),
    ]
    # The flat list is the eight boundary courses (Tract 1 + Addition 1), as on main.
    assert [c.distance_ft for c in calls] == [100.0] * 4 + [50.0] * 4
    assert _boundary(tracts[0].calls)[:3] == _boundary(main_calls)[:3]
    assert verify_closure(tracts[0].calls).closure_passed
    assert verify_closure(tracts[2].calls).closure_passed
    # The easement is noted verbatim on the boundary that precedes it.
    assert tracts[0].calls[-1].notes == "easement, not part of the boundary: " + EASEMENT


def test_flat_extraction_notes_easement_verbatim() -> None:
    calls = _extract_calls_from_text(TWO_PARCELS_WITH_EASEMENT)
    assert [c.distance_ft for c in calls] == [100.0] * 4 + [50.0] * 4
    noted = [c.notes for c in calls if c.notes]
    assert noted == ["easement, not part of the boundary: " + EASEMENT]


# --- 2./3. strip exception wording ------------------------------------------------------

STRIPS = [
    "LESS AND EXCEPT the North 10 feet of said lot conveyed for road purposes",
    "EXCEPTING THEREFROM the Northerly 10 feet of the above described premises for road purposes",
    "SAVE AND EXCEPT the westerly 10 feet thereof",
    "EXCEPTING AND RESERVING the South 5 feet thereof",
    "EXCEPT the East 20 feet of said tract taken for highway purposes",
    "LESS AND EXCEPT the West 15 feet of the above described land deeded for street purposes",
]


@pytest.mark.parametrize("strip", STRIPS)
def test_strip_wording_is_noted_whole_not_traversed(strip, main_calls) -> None:
    text = f"{MAIN} {strip}."
    for calls in (extract_calls(text)[0], _extract_calls_from_text(text)):
        assert _boundary(calls) == _boundary(main_calls)
        assert calls[-1].notes == UNAPPLIED_EXCEPTION_NOTE_PREFIX + strip
        assert all(not c.notes for c in calls[:-1])
    assert extract_calls(text)[1] == []
    result = verify_closure(extract_calls(text)[0])
    assert result.closure_passed and not result.is_fully_verified()
    assert any(strip in warning for warning in result.warnings)


@pytest.mark.parametrize("strip", STRIPS)
def test_strip_detection_reads_whole_lead_and_purpose(strip) -> None:
    (found,) = detect_strip_exceptions(f"to the point of beginning. {strip}.")
    assert found["original_text"] == strip
    assert found["width_ft"] in (5.0, 10.0, 15.0, 20.0)


def test_partial_lot_strip_is_still_not_a_strip() -> None:
    assert (
        detect_strip_exceptions("Lot 12, except the South 43.65 feet of said Lot in even width")
        == []
    )


NON_STRIP_EXCEPTIONS = [
    "EXCEPT the South 43.65 feet of said Lot in even width conveyed to Jones",
    "LESS AND EXCEPT the North 10 feet lying along Main Street",
]


@pytest.mark.parametrize("clause", NON_STRIP_EXCEPTIONS)
def test_exception_without_traverse_is_noted_never_a_cardinal_course(clause, main_calls) -> None:
    text = f"{MAIN} {clause}."
    for calls in (extract_calls(text)[0], _extract_calls_from_text(text)):
        assert _boundary(calls) == _boundary(main_calls)
        assert all(c.bearing_azimuth_deg_from_north is not None for c in calls)
        assert calls[-1].notes == UNAPPLIED_EXCEPTION_NOTE_PREFIX + clause
    assert extract_calls(text)[1] == []
    result = verify_closure(extract_calls(text)[0])
    assert result.closure_passed and not result.is_fully_verified()


def test_exception_inside_an_open_course_is_not_set_aside() -> None:
    # Wording within a course (before its closure) is the course's own, never an exception.
    text = MAIN.replace(
        "thence South 80 degrees East 100 feet;",
        "thence South 80 degrees East along Lot 5 except the North 10 feet of said Lot 100 feet;",
    )
    # The course keeps its wording (both lengths), so it fails closed as ambiguous.
    with pytest.raises(ValueError, match="ambiguous"):
        _extract_calls_from_text(text)
    skips: list = []
    calls = _extract_calls_from_text(text, strict=False, skipped_courses=skips)
    assert [skip.course for skip in skips] == [2]
    assert not any(unapplied_exceptions(c.notes) for c in calls)


# --- 4. exception wording holding "; " -------------------------------------------------


def test_exception_wording_with_semicolon_is_kept_whole() -> None:
    text = f"{MAIN} EXCEPTING the westerly 10 feet thereof; conveyed to the County."
    calls, _ = extract_calls(text)
    wording = "EXCEPTING the westerly 10 feet thereof; conveyed to the County"
    assert unapplied_exceptions(calls[-1].notes) == [wording]
    assert any(repr(wording) in w for w in verify_closure(calls).warnings)


def test_strip_clause_continued_after_a_comma_is_noted_to_its_sentence_end(main_calls) -> None:
    wording = "EXCEPT the North 10 feet thereof, conveyed to X by deed recorded in Book 12, page 4"
    calls, tracts = extract_calls(f"{MAIN} {wording}. Subject to easements of record.")
    assert tracts == []
    assert _boundary(calls) == _boundary(main_calls)
    assert unapplied_exceptions(calls[-1].notes) == [wording]
