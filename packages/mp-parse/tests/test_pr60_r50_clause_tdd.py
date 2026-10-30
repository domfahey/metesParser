"""PR #60 round 50: offset wording stays whole in along; ';' cuts are bracket-aware.

1. An offset length before a qualifier ("10 feet from and parallel to X") is part of
   ``along`` verbatim, not dropped.
2. A ';' inside a bracketed group never cuts the destination or splits a course; a
   bracketed group holding a passing call is noted once, whole, and is not ``to``.
"""

from __future__ import annotations

import pytest
from mp_models import split_notes
from mp_parse import extract_calls, extract_single_call
from mp_parse.metadata import extract_course_clause, split_call_fragments

OFFSETS = [
    "10 feet from and parallel to the line of Smith",
    "10 feet distant from and parallel with the line of Smith",
    "10 feet northerly of and parallel with the line of Smith",
    "10 feet southwesterly of and parallel to the line of Smith",
]


TEMPLATES = [
    "thence N 80° E, {o}, 100 feet to a pin",
    "thence N 80° E 100 feet, {o}, to a pin",
    "thence {o}, N 80° E 100 feet to a pin",
]
# A "distant from" length right after a stated length stays ambiguous (r48).
CASES = [
    (template, offset)
    for template in TEMPLATES
    for offset in OFFSETS
    if not ("distant" in offset and template == TEMPLATES[1])
]


@pytest.mark.parametrize(("template", "offset"), CASES)
def test_offset_before_qualifier_is_kept_whole_in_along(template: str, offset: str) -> None:
    call = extract_single_call(template.format(o=offset), 1)
    assert call is not None
    assert (call.along, call.to, call.notes) == (offset, "a pin", None)
    assert call.distance_ft == 100.0


def test_qualifier_first_offset_unchanged() -> None:
    call = extract_single_call(
        "thence N 80° E parallel to and 10 feet from the line of Smith 100 feet to a pin", 1
    )
    assert call is not None
    assert call.along == "parallel to and 10 feet from the line of Smith"
    assert call.distance_ft == 100.0


def test_plain_qualifier_without_offset_unchanged() -> None:
    call = extract_single_call("thence N 80° E parallel to the line of Smith, 100 feet to a pin", 1)
    assert call is not None
    assert (call.along, call.distance_ft) == ("parallel to the line of Smith", 100.0)


def test_offset_wording_after_semicolon_fails_closed() -> None:
    with pytest.raises(ValueError, match="not attached"):
        extract_single_call(
            "thence N 80° E 100 feet to a pin; 10 feet from and parallel to the line of Smith", 1
        )


# --- 2. bracket-aware ';' cuts -------------------------------------------------------

PASSING_NOTE = "passing call: passing a pipe at 20 feet; see plat"


@pytest.mark.parametrize(("open_", "close"), [("(", ")"), ("[", "]")])
def test_semicolon_in_bracket_does_not_cut_destination(open_: str, close: str) -> None:
    text = f"thence N 80° W 50 feet to a pin {open_}passing a pipe at 20 feet; see plat{close}"
    clause = extract_course_clause(text)
    assert clause.to == "a pin"
    assert clause.passing == ("passing a pipe at 20 feet; see plat",)
    call = extract_single_call(text, 1)
    assert call is not None
    assert (call.to, call.distance_ft) == ("a pin", 50.0)
    assert split_notes(call.notes) == [PASSING_NOTE]


def test_bracket_without_passing_keeps_semicolon_inside_to() -> None:
    call = extract_single_call("thence N 80° W 50 feet to a pin (see plat; sheet 2)", 1)
    assert call is not None
    assert call.to == "a pin (see plat; sheet 2)"


def test_passing_bracket_before_next_thence() -> None:
    text = (
        "BEGINNING at a point; thence N 80° W 50 feet to a pin (passing a pipe at 20 feet; "
        "see plat); thence S 10° E 20 feet to a stake; thence N 1° E 5 feet to the point of "
        "beginning."
    )
    calls, _ = extract_calls(text, strict=False)
    assert [c.to for c in calls] == ["a pin", "a stake", "the point of beginning"]
    assert split_notes(calls[0].notes) == [PASSING_NOTE]


def test_split_call_fragments_does_not_split_inside_brackets() -> None:
    text = (
        "N 80° W 50 feet to a pin (passing a pipe at 20 feet; see plat); S 10° E 20 feet to a stake"
    )
    fragments = [f.text for f in split_call_fragments(text)]
    assert fragments == [
        "N 80° W 50 feet to a pin (passing a pipe at 20 feet; see plat)",
        "S 10° E 20 feet to a stake",
    ]


def test_no_thence_description_keeps_bracketed_wording() -> None:
    text = (
        "BEGINNING at a point; N 80° W 50 feet to a pin (passing a pipe at 20 feet; see plat); "
        "S 10° E 20 feet to a stake; N 1° E 5 feet to the point of beginning."
    )
    calls, _ = extract_calls(text, strict=False)
    assert [c.to for c in calls] == ["a pin", "a stake", "the point of beginning"]
    notes = " ".join(c.notes or "" for c in calls)
    assert notes.count("see plat") == 1


def test_header_led_course_list_keeps_bracket_whole() -> None:
    parts = split_call_fragments(
        "THENCE the following two courses: N 10° E 100 feet (a pipe; see plat); S 80° E 100 feet"
    )
    joined = " | ".join(p.text for p in parts)
    assert "(a pipe; see plat)" in joined


def test_qualifier_before_an_adjoiner_is_kept_with_it() -> None:
    call = extract_single_call(
        "thence parallel to Main Street N 45° E 100 feet along Smith to a pin", 1
    )
    assert call is not None
    assert call.along == "parallel to Main Street along Smith"
    assert call.distance_ft == 100.0


def test_offset_right_after_bearing_is_not_taken_as_the_course_length() -> None:
    call = extract_single_call(
        "thence along Main Street N 45° E 10 feet northerly of and parallel with Smith 100 feet to a pin",
        1,
    )
    assert call is not None
    assert call.along == "Main Street 10 feet northerly of and parallel with Smith"
    assert call.distance_ft == 100.0
