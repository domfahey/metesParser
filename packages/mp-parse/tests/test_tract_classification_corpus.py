"""One corpus for tract, exception, easement and strip classification (PR #60 round 49).

Rounds 43-48 moved this logic back and forth: widening easement detection swallowed
fee additions, narrowing it missed real easement grants. Every case asserted by the
round 44, 47 and 48 tract tests (package and monolith) is collected here with the
round 49 cases, and the whole corpus must pass at once.

Each case states the tract types and per-tract course counts, the flat boundary
call count, the closing course's ``to`` and the verbatim notes. The rules:

* A boundary course is never dropped or invented. Wording that is not a course
  (a strip, a stated exception, an easement described by its own courses) is set
  aside and noted verbatim on the boundary's closing course.
* An easement grant is an EASEMENT tract (or a note), never a fee parcel. A grant
  names an easement or right of way as the clause's object: "an easement", "a right
  of way", "the use of an easement / a 10 foot wide right of way", "the right to
  use ...", "the free and uninterrupted use of ...", "a right of ingress and egress",
  with an optional grantee ("unto the grantor, its successors and assigns,",
  "to the grantor") with or without commas.
* A fee parcel that mentions an easement is never an easement: "ALSO all that tract
  of land adjoining the railroad right of way", "ALSO the land within the former
  easement area". "ALSO a strip of land for a right of way" conveys a strip of land
  (a fee) for a purpose: it stays an addition (round 48's choice, kept).
* A strip never extends over a course's destination: "..., except the North 10
  feet thereof, to the point of beginning" keeps "the point of beginning" as the
  closing course's ``to``.
* An EXCEPT after the point-of-beginning closure, with only non-course wording
  between ("containing 0.23 acres, more or less, being Lot 5"), is a stated
  exception. Unless it describes a traverse it is noted "exception not applied".
* A described exception traverse needs courses: two or more, or one closing to a
  point of beginning. A single bearing and distance locating a dividing line
  ("lying North of a line running N 80° E 100 feet from the pin") is no traverse;
  it is noted, never a one-course exception tract.
"""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from mp_models import (
    SEPARATE_EASEMENT_NOTE_PREFIX,
    TractType,
    split_notes,
    unapplied_exceptions,
)
from mp_parse.calls import _extract_calls_from_text, extract_calls
from mp_parse.metadata import detect_strip_exceptions
from mp_verify import verify_closure

from metesparser.call_extractor import CallExtractor

MAIN_T = TractType.MAIN
EXC = TractType.EXCEPTION
ADD = TractType.ADDITION
EAS = TractType.EASEMENT
POB = "the point of beginning"

SQUARE = (
    "BEGINNING at a pin; thence N 0° E 100 feet to a pin; thence S 90° E 100 feet to a pin; "
    "thence S 0° W 100 feet to a pin; thence N 90° W 100 feet to the point of beginning."
)
SMALL = (
    "BEGINNING at a stake; thence N 0° E 50 feet; thence S 90° E 50 feet; "
    "thence S 0° W 50 feet; thence N 90° W 50 feet to the point of beginning."
)
MAIN = (
    "BEGINNING at an iron pin; thence North 10 degrees East 100 feet; "
    "thence South 80 degrees East 100 feet; thence South 10 degrees West 100 feet; "
    "thence North 80 degrees West 100 feet to the point of beginning."
)
LOT = (
    "ALSO all that lot BEGINNING at a stake; thence North 10 degrees East 50 feet; "
    "thence South 80 degrees East 50 feet; thence South 10 degrees West 50 feet; "
    "thence North 80 degrees West 50 feet to the point of beginning."
)
EASEMENT_COURSES = "BEGINNING at a stake; thence N 5° E 20 feet; thence S 85° E 10 feet."
DRAINAGE_EASEMENT = (
    "ALSO an easement for drainage: BEGINNING at said pin; "
    "thence North 80 degrees West 20 feet; thence North 10 degrees East 50 feet."
)
MIWAYN = (
    "Beginning at a point distant North 2 degrees 56 minutes 20 seconds West 955.85 feet "
    "from the East 1/4 corner of Section 16, and proceeding thence South 87 degrees 03 "
    "minutes 40 seconds West 138.0 feet; thence North 2 degrees 56 minutes 20 seconds West "
    "324.0 feet; thence North 87 degrees 03 minutes 40 seconds East 138.0 feet; thence "
    "South 2 degrees 56 minutes 20 seconds East 324.0 feet to the Point of Beginning, "
    "except the South 30 feet thereof."
)
COMMENCING_ALSO_BEING = (
    "Commencing at the Northwest corner of Lot 15, also being the Southerly right of way "
    "of Mack Avenue; Thence S 26° E 120.00 feet for the point of beginning; "
    "Thence N 58° E 100 feet; Thence S 32° E 50 feet; Thence S 58° W 100 feet; "
    "Thence N 32° W 50 feet to the point of beginning."
)


@dataclass(frozen=True)
class Case:
    """Expected classification of one deed text.

    ``tracts`` is empty for a single-tract deed. ``flat`` counts the calls
    ``extract_calls`` returns (exception tracts included, easement legs never);
    ``flat_text`` counts the one-description extraction when it differs.
    ``exceptions`` and ``easements`` are the verbatim wordings noted on the flat
    calls. ``ordered`` False compares tracts as a multiset (generated deeds).
    ``error`` is the strict failure expected when no reading is safe (fail closed).
    """

    text: str
    tracts: tuple[tuple[TractType, int], ...] = ()
    flat: int = 4
    closing_to: str | None = POB
    exceptions: tuple[str, ...] = ()
    easements: tuple[str, ...] = ()
    flat_text: int | None = None
    labels: tuple[str, ...] | None = None
    ordered: bool = True
    error: str | None = None


def _strip_case(base: str, wording: str, closing_to: str = POB) -> Case:
    return Case(f"{base} {wording}.", closing_to=closing_to, exceptions=(wording,))


def _easement_case(lead: str, courses: str = EASEMENT_COURSES, legs: int = 2) -> Case:
    wording = f"{lead} {courses}"
    return Case(
        f"{SQUARE} {wording}",
        tracts=((MAIN_T, 4), (EAS, legs)),
        easements=(wording,),
        labels=("Tract 1", "Easement 1"),
    )


def _addition_case(lead: str, tract_type: TractType = ADD) -> Case:
    return Case(f"{SQUARE} {lead} {SMALL}", tracts=((MAIN_T, 4), (tract_type, 4)), flat=8)


CASES: dict[str, Case] = {
    # --- plain descriptions -----------------------------------------------------------
    "square": Case(SQUARE),
    "main": Case(MAIN),
    "commencing_also_being_right_of_way": Case(COMMENCING_ALSO_BEING, flat=5),
    "easement_wording_inside_open_description": Case(
        SQUARE.replace("BEGINNING at a pin;", "BEGINNING at a pin, subject to a right of way,")
    ),
    "easement_clause_without_courses": Case(
        f"{SQUARE} Together with an easement of record for utilities."
    ),
    # --- strips after the closure (r44, r47) ----------------------------------------
    "r44_strip_westerly": _strip_case(SQUARE, "EXCEPTING the westerly 10 feet thereof"),
    "r44_strip_less_and_except": _strip_case(SQUARE, "LESS AND EXCEPT the north 10 feet thereof"),
    "r44_miwayn_strip_after_comma": Case(
        MIWAYN,
        closing_to="the Point of Beginning",
        exceptions=("except the South 30 feet thereof",),
    ),
    **{
        f"r47_strip_{i}": _strip_case(MAIN, wording)
        for i, wording in enumerate(
            [
                "LESS AND EXCEPT the North 10 feet of said lot conveyed for road purposes",
                "EXCEPTING THEREFROM the Northerly 10 feet of the above described premises "
                "for road purposes",
                "SAVE AND EXCEPT the westerly 10 feet thereof",
                "EXCEPTING AND RESERVING the South 5 feet thereof",
                "EXCEPT the East 20 feet of said tract taken for highway purposes",
                "LESS AND EXCEPT the West 15 feet of the above described land deeded for "
                "street purposes",
            ]
        )
    },
    "r47_strip_semicolon_continuation": Case(
        f"{MAIN} EXCEPTING the westerly 10 feet thereof; conveyed to the County.",
        exceptions=("EXCEPTING the westerly 10 feet thereof; conveyed to the County",),
    ),
    "r47_strip_comma_continuation": Case(
        f"{MAIN} EXCEPT the North 10 feet thereof, conveyed to X by deed recorded in Book 12, "
        "page 4. Subject to easements of record.",
        exceptions=(
            "EXCEPT the North 10 feet thereof, conveyed to X by deed recorded in Book 12, page 4",
        ),
    ),
    # --- strips inside a course (r49 #1) --------------------------------------------
    "r49_strip_inside_closing_course": Case(
        SQUARE.replace(
            "thence N 90° W 100 feet to the point",
            "thence N 90° W 100 feet, except the North 10 feet thereof, to the point",
        ),
        exceptions=("except the North 10 feet thereof",),
    ),
    "r49_strip_inside_closing_course_to_pob": Case(
        SQUARE.replace(
            "thence N 90° W 100 feet to the point of beginning.",
            "thence N 90° W 100 feet, except the North 10 feet thereof, to the POB.",
        ),
        # Normalization reads "POB" as "point of beginning" (as without the strip).
        exceptions=("except the North 10 feet thereof",),
    ),
    "r49_strip_with_purpose_inside_closing_course": Case(
        SQUARE.replace(
            "thence N 90° W 100 feet to the point",
            "thence N 90° W 100 feet, except the North 10 feet thereof taken for road purposes, "
            "to the point",
        ),
        exceptions=("except the North 10 feet thereof taken for road purposes",),
    ),
    # A strip followed in its sentence by a THENCE is not read as a strip
    # (``strip_exception_spans``): the course keeps both lengths and fails closed.
    "r49_strip_inside_middle_course_fails_closed": Case(
        SQUARE.replace(
            "thence S 90° E 100 feet to a pin;",
            "thence S 90° E 100 feet, except the North 10 feet thereof, to a pin;",
        ),
        error="ambiguous",
    ),
    # --- stated exceptions without a traverse (r47, r48) ---------------------------
    "r47_non_strip_lot_in_even_width": _strip_case(
        MAIN, "EXCEPT the South 43.65 feet of said Lot in even width conveyed to Jones"
    ),
    "r47_non_strip_lying_along": _strip_case(
        MAIN, "LESS AND EXCEPT the North 10 feet lying along Main Street"
    ),
    **{
        f"r48_exception_with_periods_{i}": Case(
            f"{SQUARE} {wording}. Subject to easements of record.", exceptions=(wording,)
        )
        for i, wording in enumerate(
            [
                "EXCEPT the South 10 feet thereof conveyed to John A. Smith by deed dated "
                "May 1, 1950",
                "EXCEPT the part conveyed to the U.S. Government for a post office",
                "EXCEPT the part conveyed to Acme Co. by deed recorded in Deed Bk. 12, Pg. 4",
                "EXCEPT the part conveyed to Mr. Jones and Wm. R. Brown, Jr. for road purposes",
            ]
        )
    },
    "r48_bearing_only_line_running": _strip_case(
        SQUARE, "ALSO EXCEPTING the part lying north of a line running N 80 degrees E from the pin"
    ),
    "r48_bearing_only_line_bearing": _strip_case(
        SQUARE, "EXCEPT that part lying southerly of a line bearing S 45° E through said pin"
    ),
    # --- r49 #3: EXCEPT after the closure behind non-course wording -----------------
    "r49_except_after_containing_acres": Case(
        SQUARE[:-1] + ", containing 0.23 acres, EXCEPT that portion conveyed to the State of "
        "New Jersey for Route 70.",
        exceptions=("EXCEPT that portion conveyed to the State of New Jersey for Route 70",),
    ),
    "r49_except_after_more_or_less_being": Case(
        SQUARE[:-1] + ", containing 0.23 acres, more or less, being Lot 5, EXCEPT that portion "
        "conveyed to the State of New Jersey for Route 70.",
        exceptions=("EXCEPT that portion conveyed to the State of New Jersey for Route 70",),
    ),
    "r49_except_after_square_feet": Case(
        SQUARE[:-1] + ", containing 10,000 square feet, EXCEPT the part taken for Route 70.",
        exceptions=("EXCEPT the part taken for Route 70",),
    ),
    # --- r49 #4: a dividing line is no traverse ------------------------------------
    "r49_dividing_line_bearing_and_distance": _strip_case(
        SQUARE, "EXCEPT that part lying North of a line running N 80° E 100 feet from the pin"
    ),
    "r49_dividing_line_one_thence": _strip_case(
        SQUARE,
        "EXCEPT that part lying north of a line running thence N 80° E 100 feet to the river",
    ),
    # --- described exception traverses stay exception tracts (r44, r48) -----------
    "r44_geometric_exception": Case(
        SQUARE + " EXCEPTING THEREFROM: BEGINNING at a pin; thence N 0° E 10 feet; "
        "thence S 90° E 10 feet; thence S 0° W 10 feet; thence N 90° W 10 feet to the point of "
        "beginning.",
        tracts=((MAIN_T, 4), (EXC, 4)),
        flat=8,
    ),
    "r44_excepted_right_of_way": Case(
        SQUARE + " ALSO EXCEPTING therefrom a right of way described as follows: BEGINNING at a "
        "pin; thence N 0° E 10 feet; thence S 90° E 10 feet; thence S 0° W 10 feet; "
        "thence N 90° W 10 feet to the point of beginning.",
        tracts=((MAIN_T, 4), (EXC, 4)),
        flat=8,
    ),
    "r48_exception_traverse": Case(
        f"{SQUARE} EXCEPTING therefrom: {SMALL}", tracts=((MAIN_T, 4), (EXC, 4)), flat=8
    ),
    "r49_exception_traverse_after_containing": Case(
        f"{SQUARE[:-1]}, containing 0.23 acres, EXCEPTING therefrom: {SMALL}",
        tracts=((MAIN_T, 4), (EXC, 4)),
        flat=8,
    ),
    # --- easement grants (r44, r47, r48, r49 #2) ------------------------------------
    "r44_together_with_easement": _easement_case(
        "Together with an easement 10 feet wide,",
        "BEGINNING at a stake; thence N 5° E 20 feet; thence S 85° E 10 feet.",
    ),
    "r44_also_easement": _easement_case(
        "ALSO an easement for ingress and egress described as follows:"
    ),
    "r44_subject_to_right_of_way": _easement_case(
        "Subject to a right of way described as follows:"
    ),
    "r48_together_with_right_of_way": _easement_case("TOGETHER WITH a right of way 20 feet wide,"),
    "r48_subject_to_easement": _easement_case("SUBJECT TO an easement for drainage described as"),
    "r48_reserving_grantee_commas": _easement_case(
        "RESERVING unto the grantor, its successors and assigns, a perpetual easement,"
    ),
    "r48_together_with_modifiers": _easement_case(
        "TOGETHER WITH a perpetual, non-exclusive easement for utilities:"
    ),
    "r49_use_of_an_easement": _easement_case("TOGETHER WITH the use of an easement as follows:"),
    "r49_right_to_use": _easement_case("TOGETHER WITH the right to use an easement 10 feet wide,"),
    "r49_use_of_right_of_way": _easement_case(
        "TOGETHER WITH the use of a 10 foot wide right of way,"
    ),
    "r49_reserving_right_of_way_no_comma": _easement_case(
        "RESERVING to the grantor the right of way"
    ),
    "r49_right_of_ingress_and_egress": _easement_case(
        "TOGETHER WITH a right of ingress and egress over the following:"
    ),
    "r49_free_and_uninterrupted_use": _easement_case(
        "TOGETHER WITH the free and uninterrupted use of a driveway described as follows:"
    ),
    "r49_grantee_heirs_no_commas": _easement_case(
        "RESERVING unto the grantors and their heirs and assigns an easement"
    ),
    "r49_long_grantee_closed_easement": _easement_case(
        "RESERVING unto the grantor, its successors and assigns, a perpetual non-exclusive "
        "easement for ingress and egress described as follows:",
        SMALL,
        legs=4,
    ),
    "r47_easement_between_descriptions": Case(
        f"{MAIN} {DRAINAGE_EASEMENT} {LOT}",
        tracts=((MAIN_T, 4), (EAS, 2), (ADD, 4)),
        flat=8,
        easements=(DRAINAGE_EASEMENT,),
        labels=("Tract 1", "Easement 1", "Addition 1"),
    ),
    # --- fee parcels mentioning an easement stay parcels (r48, r49) ---------------
    "r48_addition_adjoining_right_of_way": _addition_case(
        "ALSO all that tract of land adjoining the railroad right of way,"
    ),
    "r48_addition_former_easement_area": _addition_case(
        "ALSO the land within the former easement area, described as"
    ),
    "r48_addition_subject_to_right_of_way": _addition_case(
        "ALSO all that tract of land subject to a right of way, described as"
    ),
    "r48_together_with_lot_along_right_of_way": _addition_case(
        "TOGETHER WITH all that lot of land lying along the right of way of Route 9,", MAIN_T
    ),
    "r49_strip_of_land_for_right_of_way": _addition_case(
        "ALSO a strip of land for a right of way, described as"
    ),
}

# --- generated deeds (r48 invariant, r49 clauses) ------------------------------------

_GENERATED = {
    "addition": f"ALSO all that tract of land adjoining the railroad right of way, {SMALL}",
    "easement": f"TOGETHER WITH an easement 10 feet wide, {EASEMENT_COURSES}",
    "use_easement": f"TOGETHER WITH the use of an easement as follows: {EASEMENT_COURSES}",
    "strip": "EXCEPTING the westerly 10 feet thereof.",
    "non_traverse": (
        "EXCEPT the South 10 feet thereof conveyed to John A. Smith by deed dated May 1, 1950."
    ),
    "bearing_only": (
        "ALSO EXCEPTING the part lying north of a line running N 80 degrees E from the pin."
    ),
    "dividing_line": "EXCEPT that part lying North of a line running N 80° E 100 feet from the pin.",
}
_GENERATED_EXCEPTIONS = ("strip", "non_traverse", "bearing_only", "dividing_line")
_GENERATED_EASEMENTS = ("easement", "use_easement")


def _generated_orders() -> list[tuple[str, ...]]:
    names = list(_GENERATED)
    orders: list[tuple[str, ...]] = [(name,) for name in names]
    orders += list(itertools.permutations(names, 2))
    orders += [tuple(names[i:] + names[:i]) for i in range(len(names))]
    return orders


def _generated_case(order: tuple[str, ...]) -> Case:
    tracts: list[tuple[TractType, int]] = []
    if "addition" in order:
        tracts.append((ADD, 4))
    tracts += [(EAS, 2) for name in order if name in _GENERATED_EASEMENTS]
    return Case(
        " ".join([SQUARE, *(_GENERATED[name] for name in order)]),
        tracts=((MAIN_T, 4), *tracts) if tracts else (),
        flat=8 if "addition" in order else 4,
        exceptions=tuple(
            _GENERATED[name].rstrip(".") for name in order if name in _GENERATED_EXCEPTIONS
        ),
        easements=tuple(_GENERATED[name] for name in order if name in _GENERATED_EASEMENTS),
        ordered=False,
    )


CASES.update({"gen:" + "+".join(order): _generated_case(order) for order in _generated_orders()})


def _kresson_case() -> Case | None:
    sample = Path(__file__).resolve().parents[3] / (
        "sample_deeds/36 Kresson Rd - Deed Image (9888 - 954).ground_truth.json"
    )
    if not sample.exists():
        return None
    truth = json.loads(sample.read_text())
    return Case(
        truth["expected_legal_description"],
        tracts=((MAIN_T, 4), (EXC, 5)),
        flat=9,
        closing_to=None,
    )


_KRESSON = _kresson_case()
if _KRESSON is not None:
    CASES["r44_kresson_tie_to_pob_then_courses"] = _KRESSON


# --- helpers ---------------------------------------------------------------------------


def _noted(calls, prefix: str) -> list[str]:
    return [
        part[len(prefix) :]
        for call in calls
        for part in split_notes(call.notes)
        if part.startswith(prefix)
    ]


def _exceptions(calls) -> list[str]:
    return [wording for call in calls for wording in unapplied_exceptions(call.notes)]


def _closing(calls):
    return next(c for c in reversed(calls) if not c.is_exception)


def _check_closing_to(case: Case, calls) -> None:
    if case.closing_to is not None:
        assert _closing(calls).to == case.closing_to


# --- the corpus ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", list(CASES))
def test_extract_calls_classifies(name: str) -> None:
    case = CASES[name]
    if case.error is not None:
        with pytest.raises(ValueError, match=case.error):
            extract_calls(case.text, strict=True)
        return
    calls, tracts = extract_calls(case.text, strict=True)
    got = [(t.tract_type, len(t.calls)) for t in tracts]
    if case.ordered:
        assert got == list(case.tracts)
    else:
        assert sorted(got) == sorted(case.tracts)
    if case.labels is not None:
        assert tuple(t.label for t in tracts) == case.labels
    assert len(calls) == case.flat
    assert all(c.bearing_azimuth_deg_from_north is not None for c in calls)
    _check_closing_to(case, calls)
    assert sorted(_exceptions(calls)) == sorted(case.exceptions)
    assert sorted(_noted(calls, SEPARATE_EASEMENT_NOTE_PREFIX)) == sorted(case.easements)
    # An easement's legs never join a boundary; exception legs only on exception tracts.
    for tract in tracts:
        assert all(c.is_exception == (tract.tract_type == EXC) for c in tract.calls)
    boundary = tracts[0].calls if tracts else calls
    assert boundary and not any(c.is_exception for c in boundary)


@pytest.mark.parametrize("name", list(CASES))
def test_one_description_extraction_matches(name: str) -> None:
    case = CASES[name]
    if case.error is not None:
        with pytest.raises(ValueError, match=case.error):
            _extract_calls_from_text(case.text, strict=True)
        return
    calls = _extract_calls_from_text(case.text, strict=True)
    assert len(calls) == (case.flat if case.flat_text is None else case.flat_text)
    _check_closing_to(case, calls)
    assert sorted(_exceptions(calls)) == sorted(case.exceptions)
    assert sorted(_noted(calls, SEPARATE_EASEMENT_NOTE_PREFIX)) == sorted(case.easements)


@pytest.mark.parametrize("name", list(CASES))
def test_monolith_facade_matches_package(name: str) -> None:
    text = CASES[name].text

    def row(c):
        return (c.course, c.bearing_azimuth_deg_from_north, c.distance_ft, c.to, c.notes)

    skips: list = []
    package = _extract_calls_from_text(text, strict=False, skipped_courses=skips)
    monolith = CallExtractor.extract_calls(text, strict=False, skipped_courses=[])
    assert bool(skips) == (CASES[name].error is not None)
    assert [row(c) + (c.is_exception,) for c in monolith] == [
        row(c) + (c.is_exception,) for c in package
    ]


@pytest.mark.parametrize("name", [n for n, c in CASES.items() if c.exceptions])
def test_unapplied_exception_blocks_eligibility_but_keeps_closure(name: str) -> None:
    case = CASES[name]
    calls, tracts = extract_calls(case.text)
    # Each boundary (the single description, or every tract carrying a note) closes
    # yet is blocked by the exceptions it notes.
    boundaries = [t.calls for t in tracts if _exceptions(t.calls)] if tracts else [calls]
    warned: list[str] = []
    for boundary in boundaries:
        result = verify_closure(boundary)
        assert result.misclosure_available and result.closure_passed
        assert not result.is_fully_verified()
        warned += result.warnings
    for wording in case.exceptions:
        assert any(wording in warning for warning in warned), wording


def test_course_wording_except_inside_an_open_course_is_kept() -> None:
    # r47: wording within a course is the course's own; the course fails closed.
    text = MAIN.replace(
        "thence South 80 degrees East 100 feet;",
        "thence South 80 degrees East along Lot 5 except the North 10 feet of said Lot 100 feet;",
    )
    with pytest.raises(ValueError, match="ambiguous"):
        _extract_calls_from_text(text)
    skips: list = []
    calls = _extract_calls_from_text(text, strict=False, skipped_courses=skips)
    assert [skip.course for skip in skips] == [2]
    assert not _exceptions(calls)


# --- strip detection (r44, r47) ------------------------------------------------------------

STRIP_DETECTIONS = [
    (
        "to the POB. EXCEPTING the westerly 10 feet thereof.",
        ["EXCEPTING the westerly 10 feet thereof"],
    ),
    (
        "to the POB. LESS AND EXCEPT the north 10 feet thereof.",
        ["LESS AND EXCEPT the north 10 feet thereof"],
    ),
    (
        "to the point of beginning, except the North 60.00 feet thereof taken for road purposes.",
        ["except the North 60.00 feet thereof taken for road purposes"],
    ),
    (
        "to the point of beginning, except the South 30 feet thereof. TRACT 2: BEGINNING at a "
        "pin; thence N 10° E 5 feet",
        ["except the South 30 feet thereof"],
    ),
    ("Lot 12, except the South 43.65 feet of said Lot in even width", []),
    *(
        (f"to the point of beginning. {wording}.", [wording])
        for wording in (
            "SAVE AND EXCEPT the westerly 10 feet thereof",
            "EXCEPTING AND RESERVING the South 5 feet thereof",
            "EXCEPT the East 20 feet of said tract taken for highway purposes",
        )
    ),
]


@pytest.mark.parametrize(("text", "expected"), STRIP_DETECTIONS)
def test_strip_detection(text: str, expected: list[str]) -> None:
    assert [s["original_text"] for s in detect_strip_exceptions(text)] == expected


# --- r49 #5: clause structure is computed once per text ----------------------------------


def test_clause_structure_is_computed_once_per_text() -> None:
    from mp_parse.tracts import _index, easement_description_spans, stated_exception_spans

    text = " ".join([SQUARE, *(_GENERATED[name] for name in _GENERATED)])
    _index.cache_clear()
    stated = stated_exception_spans(text)
    easements = easement_description_spans(text)
    assert len(stated) == len(_GENERATED_EXCEPTIONS)
    assert len(easements) == len(_GENERATED_EASEMENTS)
    # Every EXCEPT lead and easement opener bisects one precomputed structure.
    assert _index.cache_info().misses == 1
