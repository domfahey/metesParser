"""PR #60 round 51: along/to keep stated wording whole; clause scans stay linear.

1. The course's own length leaves ``along`` as the whole span the course-length
   reading selects (compound runs, "a distance of", "more or less", inches), never
   a single token re-matched against the distance.
2. "along with" / "together with" are conveyancing phrases, not adjoiners: such a
   tail is never course wording and never fails a course closed.
3. A course length after the destination ends it: adjoiner wording after that
   length is ``along``. Adjoiner wording right after the destination stays in ``to``.
4. A period after a lot/block/parcel label letter ends a sentence before a
   capitalised word ("Lot B. The line ..."); an initial ("John A. Smith") does not.
5. Clause scans are linear in the description length.
"""

from __future__ import annotations

import time

import pytest
from mp_models import DeedCall
from mp_parse import extract_calls, extract_single_call
from mp_parse.metadata import ends_sentence, extract_deed_clauses

POB = "BEGINNING at a pin; "
CLOSING = "; thence N 45° W 100 feet to the point of beginning."


def _both(fragment: str) -> list[DeedCall]:
    single = extract_single_call(fragment, 1)
    assert single is not None, fragment
    calls = extract_calls(POB + fragment + CLOSING)[0]
    assert len(calls) == 2, fragment
    return [single, calls[0]]


# --- 1. the course length leaves along as one span ------------------------------------


@pytest.mark.parametrize(
    ("fragment", "along", "distance"),
    [
        ("thence along the line of Smith N 45° E 1 chain 50 links to a pin", "the line of Smith", 99.0),
        ("thence along the line of Smith N 45° E 25 feet 6 inches to a pin", "the line of Smith", 25.5),
        ("thence along the line of Jones S 45° E 100 feet more or less to a pin", "the line of Jones", 100.0),
        ("thence along the line of Jones S 45° E 100 feet, more or less, to a pin", "the line of Jones", 100.0),
        ("thence along the line of Jones S 45° E a distance of 100 feet to a pin", "the line of Jones", 100.0),
        ("thence along the line of Jones S 45° E 4 rods 10 links to a pin", "the line of Jones", 72.6),
    ],
)  # fmt: skip
def test_course_length_span_leaves_along_whole(fragment: str, along: str, distance: float) -> None:
    for call in _both(fragment):
        assert (call.along, call.to, call.notes) == (along, "a pin", None)
        assert call.distance_ft == pytest.approx(distance)


def test_offset_length_after_the_bearing_stays_in_along() -> None:
    call = extract_single_call(
        "thence along Main Street (50 feet wide) N 45° E 100 feet to a pin", 1
    )
    assert call is not None
    assert (call.along, call.to, call.distance_ft) == ("Main Street (50 feet wide)", "a pin", 100.0)


# --- 2. conveyancing "along with" / "together with" -----------------------------------


def test_along_with_after_the_closing_course_is_not_course_wording() -> None:
    text = (
        "BEGINNING at a pin; thence N 45° E 100 feet to a pin; thence S 45° E 100 feet to a "
        "pin; thence S 45° W 100 feet to a pin; thence N 45° W 100 feet to the point of "
        "beginning; along with all improvements thereon."
    )
    calls = extract_calls(text)[0]
    assert [(c.along, c.to, c.notes) for c in calls] == [
        (None, "a pin", None),
        (None, "a pin", None),
        (None, "a pin", None),
        (None, "the point of beginning", None),
    ]
    clauses = extract_deed_clauses(text)
    assert [(c.clause_type, c.text) for c in clauses] == [
        ("together_with", "along with all improvements thereon")
    ]


@pytest.mark.parametrize("phrase", ["along with", "together with"])
@pytest.mark.parametrize("separator", ["; ", " ", ", "])
def test_conveyancing_with_mid_traverse_never_fails_closed(phrase: str, separator: str) -> None:
    text = (
        f"BEGINNING at a pin; thence N 45° E 100 feet to a pin{separator}{phrase} the right to "
        "use the driveway; thence S 45° E 100 feet to a pin; thence S 45° W 100 feet to a "
        "pin; thence N 45° W 100 feet to the point of beginning."
    )
    skipped: list[object] = []
    calls = extract_calls(text, strict=False, skipped_courses=skipped)[0]  # type: ignore[arg-type]
    assert skipped == []
    assert (calls[0].along, calls[0].to, calls[0].notes) == (None, "a pin", None)
    assert len(extract_calls(text)[0]) == 4


@pytest.mark.parametrize(
    "fragment",
    [
        "thence N 45° E 100 feet along with the line of Smith to a pin",
        "thence along with the line of Smith N 45° E 100 feet to a pin",
    ],
)
def test_along_with_a_line_is_still_adjoiner_wording(fragment: str) -> None:
    for call in _both(fragment):
        assert (call.along, call.to) == ("the line of Smith", "a pin")


def test_adjoiner_after_semicolon_still_fails_closed() -> None:
    with pytest.raises(ValueError, match="not attached"):
        extract_single_call("thence N 45° E 100 feet to a pin; along the line of Smith", 1)


# --- 3. a course length after the destination ends it ---------------------------------


@pytest.mark.parametrize(
    "fragment",
    [
        "thence S 45° E to a pin 100 feet more or less along the line of Jones",
        "thence S 45° E to a pin 100 feet along the line of Jones",
        "thence S 45° E to a pin, a distance of 100 feet, along the line of Jones",
    ],
)
def test_adjoiner_after_a_trailing_course_length_is_along(fragment: str) -> None:
    for call in _both(fragment):
        assert (call.along, call.to, call.notes) == ("the line of Jones", "a pin", None)
        assert call.distance_ft == pytest.approx(100.0)


def test_adjoiner_right_after_the_destination_stays_destination_wording() -> None:
    for call in _both("thence S 45° E 100 feet to a pin along Main Street"):
        assert (call.along, call.to) == (None, "a pin along Main Street")


# --- 4. label letters end sentences ---------------------------------------------------


def test_period_after_a_label_letter_ends_the_along_sentence() -> None:
    text = (
        "BEGINNING at a pin; thence N 45° E 100 feet along Lot B. The line continues; thence "
        "S 45° E 100 feet to a pin; thence S 45° W 100 feet to a pin; thence N 45° W 100 feet "
        "to the point of beginning."
    )
    calls = extract_calls(text)[0]
    assert (calls[0].along, calls[0].to) == ("Lot B", None)


@pytest.mark.parametrize(
    ("fragment", "along"),
    [
        ("thence N 45° E 100 feet along Lot B. Subject to a right of way", "Lot B"),
        ("thence N 45° E 100 feet along Block C. The line continues", "Block C"),
        ("thence N 45° E 100 feet along land of John A. Smith to a pin", "land of John A. Smith"),
    ],
)
def test_along_ends_at_a_sentence_end_not_an_initial(fragment: str, along: str) -> None:
    call = extract_single_call(fragment, 1)
    assert call is not None
    assert call.along == along


@pytest.mark.parametrize(
    ("text", "ends"),
    [
        ("along Lot B. The line", True),
        ("along Tract C. Smith", True),
        ("land of John A. Smith", False),
        ("along Lot B. the line", False),
        ("Main St. Subject to", True),
        ("Main St. Smith", False),
        ("1.5 acres", False),
    ],
)
def test_ends_sentence_label_letters(text: str, ends: bool) -> None:
    assert ends_sentence(text, text.index(".")) is ends


def test_deed_clause_does_not_stop_at_an_initial() -> None:
    clauses = extract_deed_clauses("SUBJECT TO a right of way to John A. Smith. Next sentence.")
    assert [c.text for c in clauses] == ["SUBJECT TO a right of way to John A. Smith"]


# --- 5. linear clause scans -----------------------------------------------------------

_BEARINGS = ("N 45° E", "S 45° E", "S 45° W", "N 45° W")


def _description(courses: int) -> str:
    parts = [
        f"thence {_BEARINGS[i % 4]} 100 feet along the line of Lot {i} "
        "(passing a pipe at 50 feet) to a pin"
        for i in range(courses - 1)
    ]
    parts.append(f"thence {_BEARINGS[(courses - 1) % 4]} 100 feet to the point of beginning")
    return POB + "; ".join(parts) + "."


def _best_time(text: str) -> float:
    times = []
    for _ in range(3):
        started = time.perf_counter()
        extract_calls(text)
        times.append(time.perf_counter() - started)
    return min(times)


@pytest.mark.parametrize("normalized", [False, True])
def test_long_description_extraction_scales_linearly(normalized: bool) -> None:
    def text(courses: int) -> str:
        source = _description(courses)
        # Wording normalization rewrites in every course ("ft." -> "feet").
        return source.replace("°", " degrees").replace("feet", "ft.") if normalized else source

    small, large = text(100), text(400)
    assert len(extract_calls(large)[0]) == 400
    small_time, large_time = _best_time(small), _best_time(large)
    # Four times the courses: linear work takes ~4x; a per-character rescan ~16x.
    assert large_time < 8 * small_time, (small_time, large_time)
