"""PR #60 round 48: easement openers, exception sentence ends, non-traverse exceptions.

- An easement opener grants, reserves or subjects an easement or right of way as
  its object ("ALSO an easement", "RESERVING unto the grantor a right of way").
  A fee parcel that merely mentions one ("ALSO all that tract of land adjoining the
  railroad right of way") stays an addition: its courses are never taken off the
  boundary.
- A stated exception's sentence does not end at an initial, an abbreviation or an
  acronym ("John A. Smith", "the U.S. Government", "Acme Co. by deed").
- An EXCEPT clause after a closed description that names a bearing but states no
  course ("lying north of a line running N 80 degrees E from the pin") is noted
  as an unapplied exception, never parsed as a course.
- Invariant over generated deeds: the boundary keeps exactly its courses, every
  exception is kept verbatim (in notes or as its own tract) and strict parsing
  never raises.
"""

from __future__ import annotations

import itertools

import pytest
from mp_models import (
    SEPARATE_EASEMENT_NOTE_PREFIX,
    UNAPPLIED_EXCEPTION_NOTE_PREFIX,
    TractType,
    split_notes,
)
from mp_parse.calls import _extract_calls_from_text, extract_calls
from mp_parse.metadata import ends_sentence
from mp_parse.tracts import easement_description_spans, split_into_tracts
from mp_verify import verify_closure

SQUARE = (
    "BEGINNING at a pin; thence N 0° E 100 feet to a pin; thence S 90° E 100 feet to a pin; "
    "thence S 0° W 100 feet to a pin; thence N 90° W 100 feet to the point of beginning."
)
SMALL = (
    "BEGINNING at a stake; thence N 0° E 50 feet; thence S 90° E 50 feet; "
    "thence S 0° W 50 feet; thence N 90° W 50 feet to the point of beginning."
)
EASEMENT_COURSES = "BEGINNING at a stake; thence N 5° E 20 feet; thence S 85° E 10 feet."


def _boundary(calls):
    return [(c.bearing_azimuth_deg_from_north, c.distance_ft, c.is_exception) for c in calls]


@pytest.fixture(scope="module")
def square_calls():
    calls, tracts = extract_calls(SQUARE)
    assert tracts == []
    return calls


# --- 1. an easement opener grants an easement; a mention is not one -------------------

MENTION_LEADS = [
    "ALSO all that tract of land adjoining the railroad right of way,",
    "ALSO the land within the former easement area, described as",
    "ALSO all that tract of land subject to a right of way, described as",
    "TOGETHER WITH all that lot of land lying along the right of way of Route 9,",
]


@pytest.mark.parametrize("lead", MENTION_LEADS)
def test_fee_parcel_mentioning_an_easement_stays_an_addition(lead, square_calls) -> None:
    text = f"{SQUARE} {lead} {SMALL}"
    assert easement_description_spans(text) == []
    kinds = [kind for _, _, kind in split_into_tracts(text)]
    assert TractType.EASEMENT not in kinds
    calls, tracts = extract_calls(text)
    assert [len(t.calls) for t in tracts] == [4, 4]
    assert _boundary(calls[:4]) == _boundary(square_calls)
    assert [c.distance_ft for c in calls[4:]] == [50.0] * 4
    assert not any(SEPARATE_EASEMENT_NOTE_PREFIX in (c.notes or "") for c in calls)


GRANT_LEADS = [
    "ALSO an easement for ingress and egress described as follows:",
    "TOGETHER WITH a right of way 20 feet wide,",
    "SUBJECT TO an easement for drainage described as",
    "RESERVING unto the grantor, its successors and assigns, a perpetual easement,",
    "TOGETHER WITH a perpetual, non-exclusive easement for utilities:",
]


@pytest.mark.parametrize("lead", GRANT_LEADS)
def test_easement_grant_is_an_easement_tract(lead, square_calls) -> None:
    text = f"{SQUARE} {lead} {EASEMENT_COURSES}"
    segments = split_into_tracts(text)
    assert [(label, kind) for _, label, kind in segments] == [
        ("Tract 1", TractType.MAIN),
        ("Easement 1", TractType.EASEMENT),
    ]
    calls, tracts = extract_calls(text)
    assert [(t.label, t.tract_type) for t in tracts] == [
        ("Tract 1", TractType.MAIN),
        ("Easement 1", TractType.EASEMENT),
    ]
    assert _boundary(tracts[0].calls) == _boundary(square_calls)
    assert _boundary(calls[:4]) == _boundary(square_calls)


# --- 2. sentence ends skip initials, abbreviations and acronyms -------------------------

EXCEPTIONS_WITH_PERIODS = [
    "EXCEPT the South 10 feet thereof conveyed to John A. Smith by deed dated May 1, 1950",
    "EXCEPT the part conveyed to the U.S. Government for a post office",
    "EXCEPT the part conveyed to Acme Co. by deed recorded in Deed Bk. 12, Pg. 4",
    "EXCEPT the part conveyed to Mr. Jones and Wm. R. Brown, Jr. for road purposes",
]


@pytest.mark.parametrize("clause", EXCEPTIONS_WITH_PERIODS)
def test_exception_note_keeps_initials_and_abbreviations(clause, square_calls) -> None:
    text = f"{SQUARE} {clause}. Subject to easements of record."
    for calls in (extract_calls(text)[0], _extract_calls_from_text(text)):
        assert _boundary(calls) == _boundary(square_calls)
        assert calls[-1].notes is not None
        assert UNAPPLIED_EXCEPTION_NOTE_PREFIX + clause in split_notes(calls[-1].notes)


@pytest.mark.parametrize(
    ("text", "index", "expected"),
    [
        ("to John A. Smith", 9, False),
        ("the U.S. Government", 5, False),
        ("the U.S. Government", 7, False),
        ("Acme Co. by deed", 7, False),
        ("a 1.5 foot strip", 3, False),
        ("thereof. Subject", 7, True),
        ("Book 12, page 4. Subject", 15, True),
        ("feet thereof.", 12, True),
    ],
)
def test_ends_sentence(text, index, expected) -> None:
    assert text[index] == "."
    assert ends_sentence(text, index) is expected


# --- 3. an exception naming a bearing but describing no course --------------------------

BEARING_ONLY_EXCEPTIONS = [
    "ALSO EXCEPTING the part lying north of a line running N 80 degrees E from the pin",
    "EXCEPT that part lying southerly of a line bearing S 45° E through said pin",
]


@pytest.mark.parametrize("clause", BEARING_ONLY_EXCEPTIONS)
def test_exception_with_bearing_but_no_course_is_noted(clause, square_calls) -> None:
    text = f"{SQUARE} {clause}."
    for calls in (extract_calls(text)[0], _extract_calls_from_text(text)):
        assert _boundary(calls) == _boundary(square_calls)
        assert UNAPPLIED_EXCEPTION_NOTE_PREFIX + clause in split_notes(calls[-1].notes)
    assert extract_calls(text)[1] == []
    result = verify_closure(extract_calls(text)[0])
    assert result.closure_passed and not result.is_fully_verified()


def test_exception_traverse_with_courses_is_still_an_exception_tract() -> None:
    # A described exception (courses with lengths) is still parsed as a traverse.
    text = f"{SQUARE} EXCEPTING therefrom: {SMALL}"
    _, tracts = extract_calls(text)
    assert [(t.tract_type, len(t.calls)) for t in tracts] == [
        (TractType.MAIN, 4),
        (TractType.EXCEPTION, 4),
    ]


# --- 4. invariant over generated deeds ------------------------------------------------

ADDITION = "ALSO all that tract of land adjoining the railroad right of way, " + SMALL
EASEMENT = "TOGETHER WITH an easement 10 feet wide, " + EASEMENT_COURSES
STRIP = "EXCEPTING the westerly 10 feet thereof."
NON_TRAVERSE = (
    "EXCEPT the South 10 feet thereof conveyed to John A. Smith by deed dated May 1, 1950."
)
BEARING_ONLY = "ALSO EXCEPTING the part lying north of a line running N 80 degrees E from the pin."
CLAUSES = {
    "addition": ADDITION,
    "easement": EASEMENT,
    "strip": STRIP,
    "non_traverse": NON_TRAVERSE,
    "bearing_only": BEARING_ONLY,
}
EXCEPTION_CLAUSES = ("strip", "non_traverse", "bearing_only")


def _orders() -> list[tuple[str, ...]]:
    names = list(CLAUSES)
    orders: list[tuple[str, ...]] = [(name,) for name in names]
    orders += list(itertools.permutations(names, 2))
    orders += [tuple(names[i:] + names[:i]) for i in range(len(names))]
    return orders


@pytest.mark.parametrize("order", _orders(), ids=lambda order: "+".join(order))
def test_generated_deed_invariant(order, square_calls) -> None:
    text = " ".join([SQUARE, *(CLAUSES[name] for name in order)])
    calls, tracts = extract_calls(text, strict=True)
    flat = _extract_calls_from_text(text, strict=True)
    every = [*calls, *(c for t in tracts for c in t.calls), *flat]
    notes = [part for c in every for part in split_notes(c.notes)]

    boundary = tracts[0].calls if tracts else calls
    assert tracts == [] or tracts[0].tract_type == TractType.MAIN
    assert _boundary(boundary) == _boundary(square_calls)
    for name in EXCEPTION_CLAUSES:
        if name in order:
            wording = CLAUSES[name].rstrip(".")
            assert UNAPPLIED_EXCEPTION_NOTE_PREFIX + wording in notes, (name, notes)
    by_type = {t.tract_type: t for t in tracts}
    if "addition" in order:
        assert [c.distance_ft for c in by_type[TractType.ADDITION].calls] == [50.0] * 4
    if "easement" in order:
        assert [c.distance_ft for c in by_type[TractType.EASEMENT].calls] == [20.0, 10.0]
    assert TractType.EXCEPTION not in by_type
