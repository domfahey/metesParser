"""A straight course's length is read by role; several course lengths are never guessed.

Each length on a straight course is classified by its context: tie, witness,
record, adjoiner and width lengths and intermediate stations ("passing a pin at
30 feet") are not the course length; a stated total ("in all", "a total distance
of") is the course length; a compound ("2 chains 20 links") is one length. When
two or more course lengths remain, the course is ambiguous: no length is chosen,
the course fails closed and its error names every length as written.
"""

from __future__ import annotations

import pytest
from mp_parse.calls import extract_calls, extract_single_call
from mp_parse.metadata import extract_distance

_AMBIGUOUS = [
    (
        "thence N 10°00' E 50.00 feet and 50.00 feet to a pin",
        "course length ambiguous: 50.00 feet, 50.00 feet",
    ),
    (
        "thence N 10°00' E 30.00 feet to a pin and 70.00 feet to a stone",
        "course length ambiguous: 30.00 feet, 70.00 feet",
    ),
    (
        "thence N 10°00' E passing a pin at 30.00 feet and continuing 70.00 feet more to a stone",
        "course length ambiguous: 70.00 feet",
    ),
    (
        "thence N 10°00' E 2 chains and 3 chains to a stake",
        "course length ambiguous: 2 chains, 3 chains",
    ),
]

_RESOLVED = [
    # A normal single-length course is unchanged.
    ("thence N 10°00' E 100.00 feet to a pin", 100.0),
    # A stated total is the course length; a station on the line is not.
    ("thence N 10°00' E passing a pin at 30.00 feet, in all 100.00 feet to a stone", 100.0),
    ("thence N 10°00' E 30.00 feet to a pin and in all 100.00 feet to a stone", 100.0),
    (
        "thence N 10°00' E passing a stone 40.00 feet from the corner and continuing "
        "a total distance of 100.00 feet to a stake",
        100.0,
    ),
    ("thence N 10°00' E passing a pin at 30.00 feet, 100.00 feet to a stone", 100.0),
    # Witness, tie, record, adjoiner and width lengths are not course lengths.
    (
        "thence N 10°00' E 100.00 feet to a stake, from which a white oak bears "
        "N 30°00' E 5.00 feet",
        100.0,
    ),
    (
        "thence N 10°00' E 100.00 feet to a pin, said pin being N 30°00' E 2.00 feet from a stone",
        100.0,
    ),
    (
        "thence N 10°00' E 100.00 feet to a point distant 50.00 feet from the corner",
        100.0,
    ),
    (
        "thence N 10°00' E 100.00 feet to a stake, said stake being 68 feet "
        "Southeastwardly from lands of Hooten",
        100.0,
    ),
    ("thence N 10°00' E 100.00 feet (N 10°05' E 100.50 feet per deed) to a pin", 100.0),
    (
        "thence N 10°00' E 100.00 feet to a pin in the line of Main Street (50 feet wide)",
        100.0,
    ),
    ("thence N 10°00' E 100.00 feet to a point 3 rods north of the oak", 100.0),
    # Compounds are one length.
    ("thence N 10°00' E 2 chains 20 links to a stake", 145.2),
    ("thence N 10°00' E 1 chain and 25 links and 10 links to a stake", 89.1),
    ("thence N 10°00' E 2 rods and 3 links to a stake", 34.98),
]

_CLOSE = (
    "; thence S 80°00' E 100.00 feet to a pin; thence S 10°00' W 100.00 feet to a pin; "
    "thence N 80°00' W 100.00 feet to the point of beginning."
)


def _description(course: str) -> str:
    return "BEGINNING at a pin; " + course + _CLOSE


@pytest.mark.parametrize(("text", "note"), _AMBIGUOUS)
def test_single_call_with_several_course_lengths_fails_closed(text, note):
    with pytest.raises(ValueError, match=note):
        extract_single_call(text, 1)


@pytest.mark.parametrize(("text", "note"), _AMBIGUOUS)
def test_strict_extraction_rejects_an_ambiguous_course_length(text, note):
    with pytest.raises(ValueError, match=note):
        extract_calls(_description(text), strict=True)


@pytest.mark.parametrize(("text", "note"), _AMBIGUOUS)
def test_non_strict_extraction_skips_an_ambiguous_course_length(text, note):
    skipped: list = []
    calls, _ = extract_calls(_description(text), strict=False, skipped_courses=skipped)
    assert [skip.error for skip in skipped] == [note]
    assert skipped[0].course == 1
    assert [call.course for call in calls] == [2, 3, 4]


@pytest.mark.parametrize(("text", "note"), _AMBIGUOUS)
def test_extract_distance_never_chooses_one_of_several_course_lengths(text, note):
    assert extract_distance(text) == (0.0, "feet")


@pytest.mark.parametrize(("text", "expected_ft"), _RESOLVED)
def test_single_call_reads_the_one_course_length(text, expected_ft):
    call = extract_single_call(text, 1)
    assert call is not None
    assert call.distance_ft == pytest.approx(expected_ft)
    assert "ambiguous" not in (call.notes or "")


@pytest.mark.parametrize(("text", "expected_ft"), _RESOLVED)
def test_strict_extraction_reads_the_one_course_length(text, expected_ft):
    calls, _ = extract_calls(_description(text), strict=True)
    assert calls[0].distance_ft == pytest.approx(expected_ft)
    assert len(calls) == 4


@pytest.mark.parametrize(
    ("text", "expected_ft"),
    [(text, ft) for text, ft in _RESOLVED if "per deed" not in text and "bears" not in text],
)
def test_extract_distance_reads_the_one_course_length(text, expected_ft):
    from mp_models.units import ConversionFactors

    value, unit = extract_distance(text)
    assert ConversionFactors.convert_to_feet(value, unit) == pytest.approx(expected_ft)


# A run of descending different-unit components is one measurement and is summed,
# with or without "and"; inches are a compound component (never the seconds marks
# '' or ″). A run that cannot be summed never keeps only its first part.
_DESCENDING_COMPOUNDS = [
    ("thence N 10°00' E 100 feet 6 inches to a stake", 100.5),
    ("thence N 10°00' E 100 ft. 6 in. to a stake", 100.5),
    ("thence N 10°00' E 100 feet and 6 inches to a stake", 100.5),
    ("thence N 10°00' E 2 rods 3 feet to a stake", 36.0),
    ("thence N 10°00' E 1 mile 20 feet to a stake", 5300.0),
    ("thence N 10°00' E 40 poles 5 feet to a stake", 665.0),
    ("thence N 10°00' E 2 chains 20 links to a stake", 145.2),
]

_UNSUMMABLE = [
    # Ascending or equivalent units do not form one measurement: two lengths.
    ("thence N 10°00' E 5 feet 2 rods to a stake", "course length ambiguous: 5 feet, 2 rods"),
    ("thence N 10°00' E 40 poles 2 rods to a stake", "course length ambiguous: 40 poles, 2 rods"),
]


@pytest.mark.parametrize(("text", "expected_ft"), _DESCENDING_COMPOUNDS)
def test_descending_compound_is_summed(text, expected_ft):
    from mp_models.units import ConversionFactors

    call = extract_single_call(text, 1)
    assert call is not None
    assert call.distance_ft == pytest.approx(expected_ft)
    calls, _ = extract_calls(_description(text), strict=True)
    assert calls[0].distance_ft == pytest.approx(expected_ft)
    value, unit = extract_distance(text)
    assert ConversionFactors.convert_to_feet(value, unit) == pytest.approx(expected_ft)


@pytest.mark.parametrize(("text", "note"), _UNSUMMABLE)
def test_unsummable_adjacent_lengths_fail_closed(text, note):
    with pytest.raises(ValueError, match=note):
        extract_single_call(text, 1)
    assert extract_distance(text) == (0.0, "feet")


def test_seconds_marks_are_never_inches():
    call = extract_single_call("thence N 10°00'30'' E 100 feet to a stake", 1)
    assert call is not None
    assert call.distance_ft == pytest.approx(100.0)
