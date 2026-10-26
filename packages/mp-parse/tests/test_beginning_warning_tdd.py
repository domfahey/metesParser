"""Closing POB wording is not a second tract-start clause."""

import pytest
from mp_parse.tracts import split_into_tracts
from structlog.testing import capture_logs


@pytest.mark.parametrize(
    "closing",
    [
        "place of beginning",
        "POINT OF BEGINNING",
        "point and place of beginning",
        "point of beginning at said pin",
        "place of beginning in said road",
    ],
)
def test_single_boundary_closing_phrase_does_not_warn_about_multiple_beginnings(closing):
    text = (
        "BEGINNING at an iron pin; THENCE due North 100 feet; "
        "THENCE due East 100 feet; THENCE due South 100 feet; "
        f"THENCE due West 100 feet to the {closing}."
    )
    with capture_logs() as logs:
        tracts = split_into_tracts(text)
    assert len(tracts) == 1
    assert tracts[0][0] == text
    assert not any("multiple BEGINNING" in event["event"] for event in logs)
    assert not any("BEGINNING block without" in event["event"] for event in logs)


def test_two_real_unmatched_start_clauses_keep_the_warning():
    text = (
        "BEGINNING at pin; THENCE due North 100 feet. BEGINNING in road; THENCE due East 100 feet."
    )
    with capture_logs() as logs:
        tracts = split_into_tracts(text)
    assert len(tracts) == 1
    event = next(event for event in logs if "multiple BEGINNING" in event["event"])
    assert event["beginning_count"] == 2


def test_two_complete_descriptions_still_produce_two_tracts():
    text = (
        "BEGINNING at pin; THENCE due North 100 feet to the place of beginning. "
        "BEGINNING in road; THENCE due East 100 feet to the point of beginning."
    )
    assert len(split_into_tracts(text)) == 2


def square(opening, size):
    return (
        f"{opening}; THENCE due North {size} feet; THENCE due East {size} feet; "
        f"THENCE due South {size} feet; THENCE due West {size} feet to the point of beginning. "
    )


@pytest.mark.parametrize(
    "opening", ["POINT OF BEGINNING at", "PLACE OF BEGINNING in", "Point and Place of Beginning at"]
)
def test_point_of_beginning_openings_are_preserved_as_distinct_tracts(opening):
    from mp_parse import extract_calls

    text = square(f"{opening} pin A", 100) + square(f"{opening} pin B", 200)
    segments = split_into_tracts(text)
    assert len(segments) == 2
    assert segments[0][0].startswith(f"{opening} pin A")
    assert segments[1][0].startswith(f"{opening} pin B")
    calls, tracts = extract_calls(text)
    assert len(calls) == 8
    assert [len(tract.calls) for tract in tracts] == [4, 4]


def test_point_of_beginning_opening_is_not_lost_when_two_ordinary_tracts_follow():
    from mp_parse import extract_calls

    text = (
        square("POINT OF BEGINNING at pin A", 100)
        + square("BEGINNING at pin B", 200)
        + square("BEGINNING at pin C", 300)
    )
    segments = split_into_tracts(text)
    assert len(segments) == 3
    assert all(f"pin {label}" in segment[0] for label, segment in zip("ABC", segments, strict=True))
    calls, tracts = extract_calls(text)
    assert len(calls) == 12
    assert [tract.calls[0].distance_ft for tract in tracts] == [100, 200, 300]
