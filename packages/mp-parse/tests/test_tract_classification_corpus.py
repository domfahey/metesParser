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

Round 50 adds:

* A description closes where a course reaches its point of beginning ("thence ...
  to the (true) point of beginning", or the last course of a BEGINNING description
  without THENCE). A point-of-beginning mention inside the BEGINNING clause ("BEGINNING
  at an iron pin marking the point of beginning") closes nothing, and a COMMENCING
  tie reaching the true point of beginning opens the boundary.
* An easement clause without its own courses inside an open description ("..., subject
  to a right of way for ingress and egress; thence ...") is noted, never a tract.
* An EXCEPT lead introducing a described parcel ("the following described parcel:
  PARCEL A: BEGINNING ...") makes that parcel an EXCEPTION tract; the lead is never
  set aside as a note and the boundary keeps its label.
* ';'-separated wording after the closing point of beginning is the closing course's
  own: a passing call is noted, adjoiner wording fails closed.
* A described exception traverse is recognised with the parser's bearing grammar
  (dashed DMS, symbol-less bearings), counting each ';'-separated course; one the
  parser cannot read fails closed, never set aside as a note.

Round 52 adds:

* A generic encumbrance recital ("subject to easements (and restrictions) of record,
  if any") names no easement: it never opens an easement description or clause, so
  the boundary after it is never set aside.
* An easement span never crosses its opener's sentence end into a description.

Round 53 adds:

* A recital is generic only if its sentence names no specific easement ("and to an
  easement for drainage", "including a drainage easement", "a right of way 20 feet
  wide") and introduces no description ("described as follows", "following
  described"; after a closed description also a colon running on into a BEGINNING).
  Otherwise the opener stands and the description it introduces is an easement.
* Document structure (a paragraph break, a heading) ends the opener's sentence like
  a period. Normalization reduces a paragraph break before a BEGINNING to a line
  break, so a line break before a BEGINNING ends it too unless the line runs on
  (a comma, colon, "as follows", a connective word). A grant clause running on to a
  BEGINNING with no such end, ';' or THENCE stays an easement.
* A description introduced as the easement's belongs to it across its grant
  sentence's end: after "The said easement is ... described as follows:" or "Said
  right of way is described as follows:", or, after a closed boundary, directly
  after a grant sentence pointing forward ("described as follows.", "over the
  following described land."). A grant sentence pointing nowhere ("TOGETHER WITH an
  easement for utilities. BEGINNING ...") never takes the description after it.
* Each of these deeds exports a verified CSV for the boundary tract only.
"""

from __future__ import annotations

import csv
import itertools
import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from mp_export.csv_writer import export_verified_csv
from mp_models import (
    PASSING_CALL_NOTE_PREFIX,
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
TRUE_POB = "the true point of beginning"
EXCEPTED_PARCEL = (
    "BEGINNING at the northwest corner; thence S 80° E 10 feet; thence S 10° W 10 feet; "
    "thence N 80° W 10 feet; thence N 10° E 10 feet to the point of beginning."
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
    ``passing`` are the passing calls noted on the closing course; ``tie_ins`` the
    flat calls marked as the commencement tie, when stated.
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
    passing: tuple[str, ...] = ()
    tie_ins: int | None = None


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
    # r50: the easement clause qualifying the open description is noted, never a tract.
    "easement_wording_inside_open_description": Case(
        SQUARE.replace("BEGINNING at a pin;", "BEGINNING at a pin, subject to a right of way,"),
        easements=("subject to a right of way",),
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
    # --- r51: easement grants by benefit or assignment of interest --------------------
    "r51_benefit_of_an_easement": _easement_case(
        "TOGETHER WITH the benefit of an easement for ingress and egress described as follows:",
        "BEGINNING at a stake; thence N 10° E 20 feet; thence N 80° W 10 feet to the point of "
        "beginning.",
    ),
    "r51_benefit_of_the_right_of_way": _easement_case(
        "TOGETHER WITH the benefit of the right of way described as follows:"
    ),
    "r51_all_right_title_interest_easement": _easement_case(
        "TOGETHER WITH all right, title and interest in and to the ingress and egress "
        "easement described as follows:"
    ),
    "r51_grantors_interest_that_certain_easement": _easement_case(
        "TOGETHER WITH all of the grantor's right, title and interest in and to that certain "
        "easement described as follows:"
    ),
    "r51_interest_in_right_of_way": _easement_case(
        "TOGETHER WITH all right, title and interest in and to the right of way described as"
    ),
    "r51_right_privilege_and_easement": _easement_case(
        "TOGETHER WITH the right, privilege and easement of passage described as follows:"
    ),
    "r51_non_exclusive_easement_appurtenant": _easement_case(
        "TOGETHER WITH a non-exclusive easement appurtenant described as follows:"
    ),
    "r51_easement_appurtenant": _easement_case(
        "TOGETHER WITH an easement appurtenant to the premises described as follows:"
    ),
    "r51_also_benefit_of_easement": _easement_case("ALSO the benefit of an easement 10 feet wide,"),
    "r51_addition_interest_in_land_within_easement_area": _addition_case(
        "ALSO all right, title and interest in and to land within the easement area,"
    ),
    "r51_together_with_interest_in_land_within_easement_area": _addition_case(
        "TOGETHER WITH all right, title and interest in and to the land lying within the "
        "easement area, described as",
        MAIN_T,
    ),
    "r51_addition_benefit_of_land_adjoining_easement": _addition_case(
        "ALSO the benefit of the land adjoining the easement, described as"
    ),
    "r51_together_with_interest_in_tract_adjoining_right_of_way": _addition_case(
        "TOGETHER WITH all right, title and interest in and to the tract of land adjoining "
        "the right of way, described as",
        MAIN_T,
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
    # --- r50 #1, #2: a closure is a course reaching the point of beginning ---------
    "r50_commencing_tie_then_easement_clause": Case(
        "COMMENCING at the corner of A Street and B Street; thence N 10° E 100 feet to the "
        "true point of beginning, subject to a right of way for ingress and egress; "
        "thence S 80° E 50 feet; thence S 10° W 100 feet; thence N 80° W 50 feet; "
        "thence N 10° E 100 feet to the true point of beginning.",
        flat=5,
        closing_to=TRUE_POB,
        easements=("subject to a right of way for ingress and egress",),
        tie_ins=1,
    ),
    "r50_commencing_tie_then_easement_clause_comma": Case(
        "COMMENCING at the corner of A Street and B Street; thence N 10° E 100 feet to the "
        "true point of beginning, together with an easement for ingress and egress, "
        "thence S 80° E 50 feet; thence S 10° W 100 feet; thence N 80° W 50 feet; "
        "thence N 10° E 100 feet to the true point of beginning.",
        flat=5,
        closing_to=TRUE_POB,
        easements=("together with an easement for ingress and egress",),
        tie_ins=1,
    ),
    # "the true point of beginning" with a course after it is a tie in a BEGINNING
    # description too; the description stays open.
    "r50_beginning_true_pob_tie_then_easement_clause": Case(
        "BEGINNING at the corner of A Street and B Street; thence N 10° E 100 feet to the "
        "true point of beginning, subject to a right of way for ingress and egress; "
        "thence S 80° E 50 feet; thence S 10° W 100 feet; thence N 80° W 50 feet; "
        "thence N 10° E 100 feet to the true point of beginning.",
        flat=5,
        closing_to=TRUE_POB,
        easements=("subject to a right of way for ingress and egress",),
    ),
    "r50_from_said_pob_easement_clause_running": Case(
        "BEGINNING at a point distant 100 feet from the corner, and from said point of "
        "beginning, together with an easement over the driveway, running thence S 80° E 50 "
        "feet; thence S 10° W 100 feet; thence N 80° W 50 feet; thence N 10° E 100 feet to "
        "the point of beginning.",
        easements=("together with an easement over the driveway",),
    ),
    "r50_beginning_marking_pob_with_easement_clause": Case(
        "BEGINNING at an iron pin marking the point of beginning, together with an easement "
        "for utilities over the same; thence S 80° E 50 feet; thence S 10° W 100 feet; "
        "thence N 80° W 50 feet; thence N 10° E 100 feet to the point of beginning.",
        easements=("together with an easement for utilities over the same",),
    ),
    # A COMMENCING description whose courses return to the point of beginning with no
    # course after it closes there: the stated exception after it is noted.
    "r50_commencing_closing_then_stated_exception": Case(
        "COMMENCING at a pin; thence N 0° E 100 feet; thence S 90° E 100 feet; "
        "thence S 0° W 100 feet; thence N 90° W 100 feet to the point of beginning. "
        "EXCEPT the part conveyed to the State of New Jersey for Route 70.",
        exceptions=("EXCEPT the part conveyed to the State of New Jersey for Route 70",),
    ),
    # --- r50 #3: an EXCEPT lead introducing a described parcel --------------------
    "r50_except_following_described_parcel_heading": Case(
        f"{SQUARE} EXCEPTING THEREFROM the following described parcel: PARCEL A: {EXCEPTED_PARCEL}",
        tracts=((MAIN_T, 4), (EXC, 4)),
        flat=8,
        labels=("Unlabelled tract", "Parcel A"),
    ),
    "r50_less_and_except_part_described_heading": Case(
        f"{SQUARE} LESS AND EXCEPT that part described as follows: Tract 2: {EXCEPTED_PARCEL}",
        tracts=((MAIN_T, 4), (EXC, 4)),
        flat=8,
        labels=("Unlabelled tract", "Tract 2"),
    ),
    "r50_headed_boundary_except_following_described_parcel": Case(
        f"TRACT 1: {SQUARE} EXCEPTING THEREFROM the following described parcel: PARCEL A: "
        f"{EXCEPTED_PARCEL}",
        tracts=((MAIN_T, 4), (EXC, 4)),
        flat=8,
        labels=("Tract 1", "Parcel A"),
    ),
    "r50_except_following_described_parcel_no_heading": Case(
        f"{SQUARE} EXCEPTING THEREFROM the following described parcel: {EXCEPTED_PARCEL}",
        tracts=((MAIN_T, 4), (EXC, 4)),
        flat=8,
    ),
    # A stated exception closed by its sentence is not the lead of the next tract.
    "r50_stated_exception_before_next_tract": Case(
        f"TRACT 1: {SQUARE} EXCEPT the part conveyed to the State for Route 70. TRACT 2: {SMALL}",
        tracts=((MAIN_T, 4), (MAIN_T, 4)),
        flat=8,
        exceptions=("EXCEPT the part conveyed to the State for Route 70",),
        labels=("Tract 1", "Tract 2"),
    ),
    # --- r50 #4: ';'-separated wording after the closing point of beginning --------
    "r50_passing_after_closure": Case(
        f"{SQUARE[:-1]}; passing a monument at 30 feet.",
        passing=("passing a monument at 30 feet",),
    ),
    "r50_and_passing_after_closure_then_area": Case(
        f"{SQUARE[:-1]}; and passing a monument at 30 feet; containing 0.23 acres.",
        passing=("and passing a monument at 30 feet",),
    ),
    "r50_passing_after_closure_then_addition": Case(
        f"{SQUARE[:-1]}; passing a monument at 30 feet. {LOT}",
        tracts=((MAIN_T, 4), (ADD, 4)),
        flat=8,
        passing=("passing a monument at 30 feet",),
    ),
    "r50_adjoiner_after_closure_fails_closed": Case(
        f"{SQUARE[:-1]}; along the line of Smith.", error="not attached"
    ),
    "r50_adjoiner_after_closure_then_addition_fails_closed": Case(
        f"{SQUARE[:-1]}; along the line of Smith. {LOT}", error="not attached"
    ),
    # --- r50 #5: exception traverses in the parser's bearing grammar ---------------
    "r50_exception_traverse_dashed_dms": Case(
        f"{SQUARE} EXCEPTING therefrom: Beginning at the northwest corner; S 80-00-00 E 10 feet; "
        "S 10-00-00 W 10 feet; N 80-00-00 W 10 feet; N 10-00-00 E 10 feet to the point of "
        "beginning.",
        tracts=((MAIN_T, 4), (EXC, 4)),
        flat=8,
    ),
    # The parser does not read a symbol-less "S 80 E": the exception fails closed.
    "r50_exception_traverse_symbolless_fails_closed": Case(
        f"{SQUARE} EXCEPTING therefrom: Beginning at the northwest corner; S 80 E 10 feet; "
        "S 10 W 10 feet; N 80 W 10 feet; N 10 E 10 feet to the point of beginning.",
        error="Malformed course",
    ),
    # --- r52 #1: a generic encumbrance recital never opens an easement --------------
    # "subject to easements (and restrictions) of record" names no easement: it is a
    # deed clause, never an easement description, so the boundary after it is kept.
    "r52_subject_to_easements_of_record_before_description": Case(
        f"SUBJECT to easements of record.\n\n{SQUARE}"
    ),
    "r52_lot_subject_to_easements_and_restrictions_if_any": Case(
        "Being Lot 5, Block 3, subject to easements and restrictions of record, if any.\n\n"
        f"ALL THAT CERTAIN lot of land described as follows: {SQUARE}"
    ),
    "r52_subject_to_zoning_and_easements_of_record_before_description": Case(
        "SUBJECT to zoning ordinances, easements, conditions and restrictions of record, and "
        f"such state of facts as an accurate survey would disclose. {SQUARE}"
    ),
    # The same recital after the closing point of beginning is no note.
    "r52_subject_to_boilerplate_after_closing_pob": Case(
        f"{SQUARE} SUBJECT to zoning ordinances, easements, conditions and restrictions of "
        "record, and such state of facts as an accurate survey would disclose."
    ),
    # 219 Berlin Rd (12799-00118): an OCR table tag read as THENCE leaves no description
    # open, so the recital before the description is never an easement clause note.
    "r52_generic_recital_after_ocr_thence_tag": Case(
        '<tr> <thence colspan="3">Additional Information</thence> </tr> Being the same '
        "premises conveyed to the grantor. SUBJECT to zoning ordinances, easements, "
        f"conditions and restrictions of record. {SQUARE}"
    ),
    # A specific easement whose sentence ends before the BEGINNING never takes the
    # description after it: an easement span never crosses a sentence end into one.
    "r52_specific_easement_sentence_then_description": Case(
        f"SUBJECT to a right of way for ingress and egress over the driveway.\n\n{SQUARE}"
    ),
    "r52_together_with_easement_sentence_then_description": Case(
        f"TOGETHER WITH an easement for utilities. {SQUARE}"
    ),
    # --- r53 #1: a recital naming a specific easement or a description is no generic one
    "r53_easements_of_record_and_specific_easement_described": _easement_case(
        "SUBJECT to the easements of record and to an easement for drainage described as follows:",
        SMALL,
        legs=4,
    ),
    "r53_easements_of_record_including_drainage_easement": _easement_case(
        "SUBJECT to the easements of record, including a drainage easement described as follows:",
        SMALL,
        legs=4,
    ),
    "r53_rights_of_way_of_record_and_right_of_way_over_following": _easement_case(
        "TOGETHER WITH the rights of way of record and a right of way 20 feet wide over the "
        "following:",
        SMALL,
        legs=4,
    ),
    "r53_easements_if_any_over_following_described_land": _easement_case(
        "TOGETHER WITH easements for ingress and egress, if any, over the following described "
        "land:",
        SMALL,
        legs=4,
    ),
    # A colon running on into a description introduces it only after a closed
    # description; before any, "of record:" names no easement and the parcel is kept.
    "r53_generic_recital_colon_before_description": Case(
        f"SUBJECT to easements of record: {SQUARE}"
    ),
    "r53_generic_recital_colon_after_boundary": _easement_case(
        "SUBJECT to the easements of record:", SMALL, legs=4
    ),
    # --- r53 #2: document structure ends the opener's sentence ----------------------
    "r53_specific_easement_paragraph_then_description": Case(
        f"SUBJECT to a right of way for ingress and egress over the driveway\n\n{SQUARE}"
    ),
    "r53_specific_easement_heading_then_description": Case(
        "SUBJECT to a right of way for ingress and egress over the driveway\n\n## Schedule A"
        f"\n\n{SQUARE}"
    ),
    "r53_easement_of_record_paragraph_then_description": Case(
        f"SUBJECT to an easement of record\n\n{SQUARE}"
    ),
    # A grant line running on into its description (a comma) stays the easement's.
    "r53_easement_line_runs_on_to_description": Case(
        f"{SQUARE} TOGETHER WITH an easement 10 feet wide,\n{SMALL}",
        tracts=((MAIN_T, 4), (EAS, 4)),
        easements=(f"TOGETHER WITH an easement 10 feet wide,\n{SMALL}",),
        labels=("Tract 1", "Easement 1"),
    ),
    # --- r53 #3: a description introduced as the easement's belongs to the easement --
    "r53_easement_described_as_follows_paragraph": Case(
        f"{SQUARE} TOGETHER WITH an easement for ingress and egress described as follows\n\n"
        f"{SMALL}",
        tracts=((MAIN_T, 4), (EAS, 4)),
        easements=(
            f"TOGETHER WITH an easement for ingress and egress described as follows\n\n{SMALL}",
        ),
        labels=("Tract 1", "Easement 1"),
    ),
    "r53_easement_described_as_follows_period": _easement_case(
        "TOGETHER WITH an easement for ingress and egress described as follows.", SMALL, legs=4
    ),
    "r53_said_easement_bounded_and_described": _easement_case(
        "SUBJECT TO a drainage easement in favor of the Township. The said easement is bounded "
        "and described as follows:",
        SMALL,
        legs=4,
    ),
    "r53_said_right_of_way_described": _easement_case(
        "RESERVING unto the grantor a right of way 20 feet wide. Said right of way is described "
        "as follows:",
        SMALL,
        legs=4,
    ),
    "r53_also_easement_over_following_described_land_period": _easement_case(
        "ALSO an easement for ingress and egress over the following described land.",
        SMALL,
        legs=4,
    ),
}
# r53: cases whose verified export must write only the boundary tract.
R53_EXPORT_CASES = sorted(name for name in CASES if name.startswith("r53_"))

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


def _check_passing_and_ties(case: Case, calls) -> None:
    # Passing calls are never dropped; only the ones stated are noted.
    assert sorted(_noted(calls, PASSING_CALL_NOTE_PREFIX)) == sorted(case.passing)
    if case.passing:
        first_closing = next(c for c in calls if c.to == case.closing_to)
        assert sorted(_noted([first_closing], PASSING_CALL_NOTE_PREFIX)) == sorted(case.passing)
    if case.tie_ins is not None:
        assert sum(c.is_tie_in for c in calls) == case.tie_ins


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
    _check_passing_and_ties(case, calls)
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
    _check_passing_and_ties(case, calls)


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


# --- r50 #1: the COMMENCING tie reaches the true point of beginning ----------------------


def test_commencing_tie_reaches_true_point_of_beginning() -> None:
    calls, tracts = extract_calls(CASES["r50_commencing_tie_then_easement_clause"].text)
    assert not tracts
    assert calls[0].is_tie_in and calls[0].to == TRUE_POB
    assert [c.distance_ft for c in calls[1:]] == [50.0, 100.0, 50.0, 100.0]
    assert not any(c.is_tie_in for c in calls[1:])


def test_closure_is_a_course_reaching_the_point_of_beginning() -> None:
    from mp_parse.tracts import _index

    marking = CASES["r50_beginning_marking_pob_with_easement_clause"].text
    commencing = CASES["r50_commencing_tie_then_easement_clause"].text
    # Only the closing course's point of beginning closes each description.
    assert [marking[s:e] for s, e in _index(marking).closures] == ["point of beginning"]
    assert _index(marking).closures[0][1] == len(marking) - 1
    assert [e for _, e in _index(commencing).closures] == [len(commencing) - 1]


# --- r53: verified export writes only the boundary tract ----------------------------------


@pytest.mark.parametrize("name", R53_EXPORT_CASES)
def test_verified_export_writes_only_the_boundary(name: str, tmp_path: Path) -> None:
    case = CASES[name]
    calls, tracts = extract_calls(case.text, strict=True)
    output = str(tmp_path / "deed.csv")
    if tracts:
        results = verify_closure([], tracts=tracts)
        written = export_verified_csv(
            [], results[0], output, tract_results=list(zip(tracts, results, strict=True))
        )
        boundaries = [i for i, t in enumerate(tracts) if t.tract_type in (MAIN_T, ADD)]
        assert boundaries == [0]
        assert [p.name for p in written] == ["deed_verified_tract1.csv"]
    else:
        written = export_verified_csv(calls, verify_closure(calls), output)
        assert len(written) == 1
    # The one CSV written is the 100-foot square boundary.
    with written[0].open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [float(row["distance_ft"]) for row in rows] == [100.0] * 4
