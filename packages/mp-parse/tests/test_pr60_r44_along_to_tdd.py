"""PR #60 round 44: along/to come from one reading of the course clause.

The destination is the FIRST destination "to" after the course and runs verbatim to
the end of the course clause; "to" inside it ("conveyed to", "opposite to") is part
of it. ``along`` comes only from the course before the destination, from any
adjoiner wording ("by and with", "binding on", "adjoining" ...). A passing call is
kept verbatim in notes. The course's own length is never left in ``to``; a monument
size is.
"""

from __future__ import annotations

import pytest
from mp_models import DeedCall
from mp_parse.calls import extract_calls, extract_single_call
from mp_parse.metadata import extract_along_to_fields

from metesparser.text_parser import TextParser

POB = "BEGINNING at a point; "
CLOSING = " THENCE S 45° W 100 feet to the point of BEGINNING."


def _both(fragment: str) -> list[DeedCall]:
    single = extract_single_call(fragment, 1)
    full = extract_calls(POB + fragment + CLOSING, strict=False)[0]
    assert full, fragment
    return [single, full[0]]


@pytest.mark.parametrize(
    ("fragment", "to"),
    [
        (
            "THENCE N 45° E 100 feet to a point in the line of lands conveyed to Smith",
            "a point in the line of lands conveyed to Smith",
        ),
        (
            "THENCE N 45° E 100 feet to a point opposite to the corner",
            "a point opposite to the corner",
        ),
        (
            "THENCE N 45° E 100 feet to a corner of lands belonging to Jones",
            "a corner of lands belonging to Jones",
        ),
        (
            "THENCE N 45° E 100 feet to a stake adjacent to the barn",
            "a stake adjacent to the barn",
        ),
    ],
)
def test_destination_is_the_first_destination_to(fragment: str, to: str) -> None:
    for call in _both(fragment):
        assert call.to == to
        assert call.along is None
        assert call.distance_ft == pytest.approx(100.0)


@pytest.mark.parametrize(
    "fragment",
    [
        "THENCE N 45° E 100 feet to the beginning, containing 0.23 acres, more or less, "
        "subject to a 10 foot easement along the rear line",
        "THENCE N 45° E 100 feet to the beginning, subject to a 10 foot easement",
        "THENCE N 45° E 100 feet to the beginning, being the same land conveyed to Smith",
    ],
)
def test_destination_stops_at_the_end_of_the_course_clause(fragment: str) -> None:
    assert extract_along_to_fields(fragment) == ("", "the beginning")
    call = extract_single_call(fragment, 1)
    assert call.to == "the beginning"
    assert call.along is None


@pytest.mark.parametrize(
    ("fragment", "along"),
    [
        ("THENCE N 45° E 100 feet by and with the line of Lot 6 to a pin", "the line of Lot 6"),
        ("THENCE N 45° E 100 feet with the line of Lot 6 to a pin", "the line of Lot 6"),
        ("THENCE N 45° E 100 feet binding on Main Street to a pin", "Main Street"),
        ("THENCE N 45° E 100 feet bounding on Main Street to a pin", "Main Street"),
        ("THENCE N 45° E 100 feet adjoining lands of Smith to a pin", "lands of Smith"),
        (
            "THENCE N 45° E 100 feet following the center of the creek to a pin",
            "the center of the creek",
        ),
        ("THENCE by and with the line of Lot 6 N 45° E 100 feet to a pin", "the line of Lot 6"),
    ],
)
def test_adjoiner_wording_is_along(fragment: str, along: str) -> None:
    for call in _both(fragment):
        assert call.along == along
        assert call.to == "a pin"
        assert call.distance_ft == pytest.approx(100.0)


@pytest.mark.parametrize(
    ("fragment", "along"),
    [
        ("THENCE N 45° E passing a pipe at 50 feet, in all 100 feet to a pin", None),
        (
            "THENCE N 45° E 100 feet along Main Street passing a pipe at 50 feet to a pin",
            "Main Street",
        ),
    ],
)
def test_passing_call_is_kept_verbatim_in_notes(fragment: str, along: str | None) -> None:
    for call in _both(fragment):
        assert call.along == along
        assert call.to == "a pin"
        assert "passing call: passing a pipe at 50 feet" in (call.notes or "")
        assert call.distance_ft == pytest.approx(100.0)


def test_along_never_comes_from_after_a_later_thence() -> None:
    fragment = "THENCE N 45° E 100 feet to a stone on the bank of a creek, thence along the creek"
    assert extract_along_to_fields(fragment) == ("", "a stone on the bank of a creek")
    call = extract_single_call(fragment, 1)
    assert call.along is None
    assert call.to == "a stone on the bank of a creek"
    assert "meander" not in (call.notes or "")
    assert call.is_meander is False


def test_along_inside_the_destination_stays_in_to() -> None:
    for call in _both("THENCE N 45° E 100 feet to a pin along Main Street"):
        assert call.along is None
        assert call.to == "a pin along Main Street"


@pytest.mark.parametrize(
    ("fragment", "to"),
    [
        ("THENCE N 45° E to a 2 inch iron pipe 100 feet", "a 2 inch iron pipe"),
        ('THENCE N 45° E to a 5/8" rebar a distance of 100 feet', 'a 5/8" rebar'),
        ("THENCE N 45° E to an iron pipe 100 feet, more or less", "an iron pipe"),
    ],
)
def test_course_length_after_destination_is_not_in_to(fragment: str, to: str) -> None:
    for call in _both(fragment):
        assert call.to == to
        assert call.distance_ft == pytest.approx(100.0)


def test_monolith_facade_matches_package() -> None:
    fragment = "THENCE N 45° E 100 feet to a point in the line of lands conveyed to Smith"
    assert TextParser.extract_along_to_fields(fragment) == extract_along_to_fields(fragment)


@pytest.mark.parametrize(
    "fragment",
    [
        "THENCE along Main Street, N 45° E, a distance of 100 feet to a pin",
        "THENCE along Main Street N 45° E the distance of 100 feet to a pin",
        "THENCE N 45° E along Main Street, passing a pipe at 50 feet, and continuing said "
        "course a total distance of 100 feet to a pin",
    ],
)
def test_course_length_wording_is_not_left_in_along(fragment: str) -> None:
    for call in _both(fragment):
        assert call.along == "Main Street"
        assert call.to == "a pin"
        assert call.distance_ft == pytest.approx(100.0)


@pytest.mark.parametrize(
    "fragment",
    [
        "THENCE N 45° E 100 feet to a point, thence",
        "THENCE N 45° E 100 feet to a point and extends thence",
    ],
)
def test_destination_ends_before_the_next_thence(fragment: str) -> None:
    assert extract_along_to_fields(fragment) == ("", "a point")
