"""A feature's dimension is not a course length; excluded parentheticals are noted (round 44).

Dimension rule: a length directly followed by a dimension word ("high", "tall",
"thick", "long", "deep", "square", "radius", "in diameter", "in height", ...)
describes a feature (a fence, wall, stone, ditch, radius), not the course. It can
be the course length only when it is the sole course-capable length and the word
plausibly describes the course itself ("150 feet deep" as a lot depth, "100 feet
long"); a length used as an adjective before a noun ("a 6 foot high fence", "a 150
foot deep lot") describes that noun and never is. Otherwise a sole dimension length
fails closed (no course length). "In length" / "in depth" ("142 feet in length or
depth") are the deed's course-length idiom: always course lengths, so beside another
course length they stay ambiguous.

Parentheticals: a bracketed length that is not a record or measured call is never
read as the course length. An alternative length ("(calculated 101 feet)", "(see
plan 12 feet)") is always kept verbatim in notes as "parenthetical: (...)"; a
description ("(50 feet wide)", "(crossing a 10 foot easement)") is noted only when
the call's along/to wording does not already keep it verbatim.
"""

from __future__ import annotations

import pytest
from mp_parse import extract_calls, extract_single_call
from mp_parse.metadata import extract_area_statement, read_course_length

from metesparser.call_extractor import CallExtractor
from metesparser.text_parser import TextParser

SINGLE = pytest.mark.parametrize(
    "single", [extract_single_call, CallExtractor.extract_single_call], ids=["pkg", "mono"]
)
AREA = pytest.mark.parametrize(
    "area", [extract_area_statement, TextParser.extract_area_statement], ids=["pkg", "mono"]
)
POB = "BEGINNING at a point; THENCE S 45° W 100 feet to a point; "
B = "thence N 45° E 100 feet "
MISSING = "Missing boundary course distance"

# origin/main read 100 feet and kept along/to verbatim; each is (text, along, to).
DIMENSION_REGRESSIONS = {
    "fence-high": (
        B + "to a corner of a fence 4 feet high",
        None,
        "a corner of a fence 4 feet high",
    ),
    "adjective-high": (B + "to a 6 foot high fence", None, "a 6 foot high fence"),
    "stone-long": (B + "to a stone 2 feet long", None, "a stone 2 feet long"),
    "wall-thick": (B + "to a wall 3 feet thick", None, "a wall 3 feet thick"),
    "ditch-deep": (B + "to a ditch 5 feet deep", None, "a ditch 5 feet deep"),
    "radius": (B + "to a point on a 20 foot radius", None, "a point on a 20 foot radius"),
    "along-high": (B + "along a fence 3 feet high to a stone", "a fence 3 feet high", "a stone"),
    "post-tall": (B + "to a post 6 feet tall", None, "a post 6 feet tall"),
    "stone-square": (B + "to a stone 2 feet square", None, "a stone 2 feet square"),
    "tree-diameter": (B + "to a tree 3 feet in diameter", None, "a tree 3 feet in diameter"),
    "wall-thick-and-long": (
        B + "to a wall 3 feet thick and 100 feet long",
        None,
        "a wall 3 feet thick and 100 feet long",
    ),
}
# The sole length, with a word that describes the course itself: the course length.
SOLE_COURSE = {
    "back-to-beginning": ("thence N 45° E 100 feet back to the place of beginning", 100.0),
    "lot-depth": ("thence N 45° E 150 feet deep to a stake", 150.0),
    "in-depth": ("thence N 45° E 150 feet in depth to a stake", 150.0),
    "long": ("thence N 45° E 100 feet long to a stake", 100.0),
    "in-length": ("thence N 45° E 100 feet in length to a stake", 100.0),
    "offset-then-deep": ("thence N 45° E, 3 feet off the fence, 150 feet deep to a stake", 150.0),
}
# The sole length describes a feature (or is an adjective): no course length.
SOLE_DIMENSION = {
    "set-below-grade": "thence N 45° E to an iron pin set 0.5 feet below grade",
    "high": "thence N 45° E 4 feet high to a stone",
    "adjective-high": "thence N 45° E to a 6 foot high fence",
    "along-high": "thence N 45° E along a fence 3 feet high",
    "radius": "thence N 45° E 20 foot radius to a stone",
    "adjective-deep": "thence N 45° E along a 150 foot deep lot to a stake",
    "thick": "thence N 45° E to a wall 3 feet thick",
}


@SINGLE
@pytest.mark.parametrize("name", sorted(DIMENSION_REGRESSIONS))
def test_dimension_beside_course_length_is_not_the_course(single, name: str) -> None:
    text, along, to = DIMENSION_REGRESSIONS[name]
    call = single(text, 1)
    assert call is not None
    assert (call.distance_ft, call.along, call.to) == (100.0, along, to)


@pytest.mark.parametrize("name", sorted(DIMENSION_REGRESSIONS))
def test_description_reads_course_beside_dimension(name: str) -> None:
    text = DIMENSION_REGRESSIONS[name][0]
    calls, _ = extract_calls(POB + text + ".", strict=True)
    assert [c.distance_ft for c in calls] == [100.0, 100.0]


@SINGLE
@pytest.mark.parametrize("name", sorted(SOLE_COURSE))
def test_sole_course_describing_dimension_is_the_course(single, name: str) -> None:
    text, expected = SOLE_COURSE[name]
    call = single(text, 1)
    assert call is not None
    assert call.distance_ft == expected
    assert read_course_length(text)[:1] == (expected,)


@SINGLE
@pytest.mark.parametrize("name", sorted(SOLE_DIMENSION))
def test_sole_feature_dimension_fails_closed(single, name: str) -> None:
    with pytest.raises(ValueError, match=MISSING):
        single(SOLE_DIMENSION[name], 1)


@pytest.mark.parametrize(
    ("text", "values"),
    [
        ("thence N 45° E 150 feet deep to a ditch 5 feet deep", ("150 feet", "5 feet")),
        ("thence N 45° E 100 feet to a ditch 5 feet in depth", ("100 feet", "5 feet")),
        # Two lot-dimension courses merged into one fragment (15 E Euclid Ave).
        (
            "thence Southwestwardly along the Northwesterly line of Euclid Avenue 80 feet in "
            "width or breadth; thence Northwestwardly parallel with Turnley Avenue 142 feet "
            "in length or depth",
            ("80 feet", "142 feet"),
        ),
    ],
)
def test_course_length_idioms_beside_a_course_stay_ambiguous(text: str, values) -> None:
    reading = read_course_length(text)
    assert (reading.value, reading.ambiguous) == (0.0, values)


# --- parentheticals ------------------------------------------------------------------
PARENTHETICAL_NOTES = {
    "calculated": (B + "(calculated 101 feet) to a stone", "parenthetical: (calculated 101 feet)"),
    "see-plan": (B + "(see plan 12 feet) to a stone", "parenthetical: (see plan 12 feet)"),
    "easement": (
        B + "(crossing a 10 foot easement) to a stone",
        "parenthetical: (crossing a 10 foot easement)",
    ),
    "width-dropped": (B + "(50 feet wide) to a stone", "parenthetical: (50 feet wide)"),
    # An alternative length is noted even where the destination keeps it.
    "calculated-in-to": (
        B + "to a stone (calculated 101 feet)",
        "parenthetical: (calculated 101 feet)",
    ),
    "with-record": (
        B + "(100.5 feet per deed) (calc. 101 feet) to a stone",
        "parenthetical: (calc. 101 feet); record call: (100.5 feet per deed)",
    ),
}
# A description kept verbatim in along/to, or a parenthetical without a length.
PARENTHETICAL_UNNOTED = {
    "width-in-along": B + "along Main Street (50 feet wide) to a stone",
    "width-before-length": "thence N 45° E along Main Street (50 feet wide) 100 feet to a stone",
    "more-or-less": B + "(more or less) to a stone",
}


@SINGLE
@pytest.mark.parametrize("name", sorted(PARENTHETICAL_NOTES))
def test_excluded_parenthetical_is_noted_verbatim(single, name: str) -> None:
    text, notes = PARENTHETICAL_NOTES[name]
    call = single(text, 1)
    assert call is not None
    assert (call.distance_ft, call.notes) == (100.0, notes)


@SINGLE
@pytest.mark.parametrize("name", sorted(PARENTHETICAL_UNNOTED))
def test_kept_or_lengthless_parenthetical_is_not_noted(single, name: str) -> None:
    call = single(PARENTHETICAL_UNNOTED[name], 1)
    assert call is not None
    assert (call.distance_ft, call.notes) == (100.0, None)


def test_record_call_notes_still_read_after_parenthetical() -> None:
    from mp_parse.calls import _noted_record_calls

    call = extract_single_call(PARENTHETICAL_NOTES["with-record"][0], 1)
    assert call is not None
    assert _noted_record_calls(call.notes) == ["(100.5 feet per deed)"]


# --- area statements -----------------------------------------------------------------
ACRE = 43560.0
AREAS = {
    "leading-decimal": ("containing .5 acres", 0.5 * ACRE),
    "decimal": ("containing 0.5 acres", 0.5 * ACRE),
    "mixed-fraction": ("containing 2 1/2 acres", 2.5 * ACRE),
    "fraction": ("containing 1/2 acre", 0.5 * ACRE),
    "comma-sq-ft": ("containing 1,234.5 square feet", 1234.5),
    "acres-and-perches": ("containing 2 acres and 50 perches", 2 * ACRE + 50 * 272.25),
    "acres-perches-no-joiner": ("containing 2 acres 50 perches", 2 * ACRE + 50 * 272.25),
    "acres-roods-perches": (
        "containing 2 acres, 3 roods and 10 perches",
        2 * ACRE + 3 * ACRE / 4 + 10 * 272.25,
    ),
    "acres-and-sq-ft": ("containing 10 acres and 2,000 square feet", 10 * ACRE + 2000),
    "acres-square-rods": ("containing 1 acre and 20 square rods", ACRE + 20 * 272.25),
}
# A partial area is never reported: an unread component makes the area unavailable.
UNREAD_AREAS = {
    "and-feet": "containing 2 acres and 50 feet",
    "and-unknown": "containing 2 acres and 50 hectares",
}


@AREA
@pytest.mark.parametrize("name", sorted(AREAS))
def test_area_reads_shared_number_grammar_and_compounds(area, name: str) -> None:
    text, expected = AREAS[name]
    result = area(text)
    assert result is not None
    assert result["value_sq_ft"] == pytest.approx(expected)


@AREA
@pytest.mark.parametrize("name", sorted(UNREAD_AREAS))
def test_area_with_unread_component_is_unavailable(area, name: str) -> None:
    assert area(UNREAD_AREAS[name]) is None


@AREA
def test_area_more_or_less_still_approximate(area) -> None:
    result = area("containing 2 acres and 50 perches, more or less")
    assert result is not None
    assert result["approximate"] is True
    assert result["value_sq_ft"] == pytest.approx(2 * ACRE + 50 * 272.25)
