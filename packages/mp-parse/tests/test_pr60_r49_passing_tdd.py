"""PR #60 round 49: a passing call never swallows the course's own bearing or length."""

from __future__ import annotations

import pytest
from mp_models import FIXED_NOTE_PREFIXES, FIXED_NOTES, split_notes
from mp_parse import calls as calls_module
from mp_parse import extract_single_call
from mp_parse import metadata as metadata_module
from mp_parse.metadata import bracket_groups, extract_course_clause

WALL = "passing over a stone wall"


@pytest.mark.parametrize(
    ("text", "passing"),
    [
        (f"thence {WALL} S 45° E 100 feet to a stake", WALL),
        (f"thence S 45° E {WALL} 100 feet to a stake", WALL),
        (f"thence S 45° E 100 feet {WALL} to a stake", WALL),
        (f"thence S 45° E 100 feet to a stake; {WALL}", WALL),
        (f"thence along Smith Road {WALL} S 45° E 100 feet to a stake", WALL),
    ],
)
def test_passing_call_excludes_course_bearing_and_length(text: str, passing: str) -> None:
    assert extract_course_clause(text).passing == (passing,)
    call = extract_single_call(text, 1)
    assert call is not None
    assert call.notes == f"passing call: {passing}"
    assert call.distance_ft == pytest.approx(100.0)
    assert call.bearing_quadrant is not None
    assert "wall" not in (call.to or "")


def test_passing_after_destination_is_not_course_wording() -> None:
    clause = extract_course_clause("thence S 45° E 100 feet to a stake; passing a pipe at 30 feet")
    assert clause.passing == ("passing a pipe at 30 feet",)
    assert clause.to == "a stake"


def test_one_passing_rule_and_one_bracket_scanner() -> None:
    assert not hasattr(calls_module, "_PASSING_SEGMENT")
    assert not hasattr(calls_module, "_bracket_groups")
    assert calls_module.PASSING_PIECE is metadata_module.PASSING_PIECE
    assert calls_module.bracket_groups is bracket_groups
    assert bracket_groups("a (b [c] d) e (f") == [(2, 11, True), (14, 16, False)]


def test_fixed_note_constants_are_registered() -> None:
    for note in (
        calls_module.AMBIGUOUS_DECIMAL_DEGREES_NOTE,
        calls_module.ARC_COMPUTED_NOTE,
        calls_module.TANGENT_NOT_STATED_NOTE,
        calls_module.LENGTH_NOT_DETERMINED_NOTE,
    ):
        assert note in FIXED_NOTES
    for template in (
        calls_module.CURVE_LENGTH_AMBIGUOUS_NOTE,
        calls_module.RADIUS_CONFLICT_NOTE,
        metadata_module.COURSE_LENGTH_AMBIGUOUS_NOTE,
    ):
        assert any(template.startswith(prefix) for prefix in FIXED_NOTE_PREFIXES)
    assert split_notes(f"{calls_module.ARC_COMPUTED_NOTE}; x") == [
        calls_module.ARC_COMPUTED_NOTE,
        "x",
    ]
