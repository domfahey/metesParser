"""Qualifier phrases stay verbatim in along; to comes only from a destination."""

from __future__ import annotations

import pytest
from mp_parse.calls import extract_single_call

CURVE = "along a curve to the right having a radius of 100 feet, an arc length of 50 feet"


@pytest.mark.parametrize(
    ("text", "along", "to"),
    [
        ("thence N 45° E 100 feet parallel to Main Street", "parallel to Main Street", ""),
        ("thence N 45° E 100 feet parallel with Main Street", "parallel with Main Street", ""),
        (
            "thence N 45° E at right angles to Main Street 100 feet",
            "at right angles to Main Street",
            "",
        ),
        (
            "thence N 45° E 100 feet perpendicular to Main Street to a pin",
            "perpendicular to Main Street",
            "a pin",
        ),
        (
            "thence N 45° E 100 feet parallel with Main Street to the point of beginning",
            "parallel with Main Street",
            "the point of beginning",
        ),
        ("thence N 45° E 100 feet along Main Street to a pin", "Main Street", "a pin"),
        (
            f"thence {CURVE}, tangent to the last course",
            "a curve to the right having a radius of 100 feet, an arc length of 50 feet, "
            "tangent to the last course",
            "",
        ),
    ],
)
def test_qualifier_is_along_not_destination(text: str, along: str, to: str) -> None:
    call = extract_single_call(text, 1)
    assert call.along == along
    assert (call.to or "") == to


def test_spiral_with_stated_length_is_not_called_delta_arc_unstated() -> None:
    call = extract_single_call(
        "thence along a spiral curve having a length of 200 feet, chord bearing N 45° E 199.5 feet",
        1,
    )
    assert call.arc_length_ft == 200.0
    assert "curve delta/arc not stated" not in (call.notes or "")
    assert "spiral positioned by its stated chord only" in (call.notes or "")


def test_circular_chord_only_note_unchanged() -> None:
    call = extract_single_call(
        "thence along a curve to the right having a radius of 100 feet, "
        "chord bearing N 45° E 99.5 feet",
        1,
    )
    assert "curve delta/arc not stated - positioned by chord only" in (call.notes or "")
