"""Dotted P.O.B. closes the course region; word-form bearings keep a foot-mark length."""

import re

import pytest
from mp_parse.calls import _COURSE_DISTANCE, extract_calls, extract_single_call
from mp_parse.units import LENGTH_NUMBER_GUARD, LENGTH_UNIT

PRE = (
    "BEGINNING at a point; THENCE N 10°00'00\" E 100 feet; THENCE S 80°00'00\" E 100 feet; "
    "THENCE S 10°00'00\" W 100 feet; THENCE N 80° W 100 feet to the {pob} "
)
TAIL = "Being the same premises as recorded; N 5 E 20 feet."


@pytest.mark.parametrize(
    "pob", ["point of beginning.", "P.O.B.", "POB.", "T.P.O.B.", "R.P.O.B.", "TPOB.", "RPOB."]
)
@pytest.mark.parametrize("strict", [True, False])
def test_dotted_pob_closes_course_region(pob, strict):
    skips = []
    calls, _ = extract_calls(PRE.format(pob=pob) + TAIL, strict=strict, skipped_courses=skips)
    assert len(calls) == 4
    assert skips == []


def test_pob_trailing_recital_in_single_call_text():
    text = "thence N 80\u00b0 W 100 feet to the P.O.B. " + TAIL
    calls, _ = extract_calls(text)
    assert len(calls) == 1
    assert extract_single_call(text, 1) is not None


_LENGTH = re.compile(rf"{LENGTH_NUMBER_GUARD}\d[\d,.]*\s*{LENGTH_UNIT}", re.IGNORECASE)


@pytest.mark.parametrize(
    "text",
    [
        "100' North 45 degrees 30 minutes East",
        "100' N 45 deg. 30' E",
        "100' South 45 Degree West",
        "100' N 45 º E",
    ],
)
def test_foot_mark_before_word_bearing_is_a_length(text):
    assert _LENGTH.search(text)
    assert _COURSE_DISTANCE.search(text)


@pytest.mark.parametrize("text", ["N 45 30' E", "S 5 20' West"])
def test_minutes_still_not_lengths(text):
    assert not _LENGTH.search(text)
