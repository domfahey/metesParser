"""PR #60 round 43: adjoiner scope, mark-before-length record order, per-tract source notes.

- a "by the line of ..." adjoiner counts only in the course part, before the
  destination "to", never inside the destination wording;
- a bearing followed by an (R) mark is a record beside another plain or measured
  bearing of the same kind, whatever follows the mark, in either order;
- a record call's wording is restored from its own place in the source (aligned
  token by token), never found by re-searching the whole text.
"""

from __future__ import annotations

import pytest
from mp_models import DeedCall
from mp_parse.calls import extract_calls, extract_single_call

POB = "BEGINNING at a point; "
CLOSING = " THENCE S 45° W 100 feet to the point of BEGINNING."


# --- 1. adjoiner scope ------------------------------------------------------------------
@pytest.mark.parametrize(
    ("fragment", "along", "to"),
    [
        (
            "thence N 45° W 100 feet to a stake in the corner formed by the line of Smith "
            "and the line of Jones, the point of beginning",
            "",
            "a stake in the corner formed by the line of Smith and the line of Jones, "
            "the point of beginning",
        ),
        (
            "thence N 45° W 100 feet to a stake bounded by lands of Smith, the POB",
            "",
            "a stake bounded by lands of Smith, the POB",
        ),
        (
            "thence N 45° E by the line of Smith 100 feet to a point",
            "the line of Smith",
            "a point",
        ),
        (
            "thence N 45° E 100 feet by the line of Smith to a point",
            "the line of Smith",
            "a point",
        ),
        (
            "thence N 45° E 100 feet by lands now or formerly of Smith to a stake bounded "
            "by lands of Jones",
            "lands now or formerly of Smith",
            "a stake bounded by lands of Jones",
        ),
    ],
)
def test_by_adjoiner_counts_only_before_the_destination(fragment: str, along: str, to: str) -> None:
    call = extract_single_call(fragment, 1)
    assert (call.along or "", call.to or "") == (along, to)


# --- 2. (R) mark before the measured bearing ----------------------------------------------
R_FIRST = "N 45° W (R)"
M_BEARING = "N 45° 10' W (M)"
CASES2 = [
    # (fragment, record wording)
    (f"thence {R_FIRST} {M_BEARING} 100 feet to a pin", R_FIRST),
    (f"thence {R_FIRST}, {M_BEARING} 100 feet to a pin", R_FIRST),
    (f"thence {M_BEARING} {R_FIRST} 100 feet to a pin", R_FIRST),
    (f"thence {M_BEARING}, {R_FIRST} 100 feet to a pin", R_FIRST),
    ("thence N 45° W (R) N 45° 10' W 100 feet to a pin", R_FIRST),
    ("thence N 45° W (R), N 45° 10' W 100 feet to a pin", R_FIRST),
    ("thence N 45° 10' W 100 feet N 45° W (R) to a pin", R_FIRST),
    ("thence N 45° 10' W 100 feet, N 45° W (R) to a pin", R_FIRST),
    (f"thence {R_FIRST} 100.5 feet {M_BEARING} 100 feet to a pin", f"{R_FIRST} 100.5 feet"),
    (f"thence {R_FIRST} 100.5 feet, {M_BEARING} 100 feet to a pin", f"{R_FIRST} 100.5 feet"),
    (f"thence {M_BEARING} 100 feet {R_FIRST} 100.5 feet to a pin", f"{R_FIRST} 100.5 feet"),
    (f"thence {M_BEARING} 100 feet, {R_FIRST} 100.5 feet to a pin", f"{R_FIRST} 100.5 feet"),
    ("thence N 45° W (R) 100.5 feet, N 45° 10' W 100 feet to a pin", f"{R_FIRST} 100.5 feet"),
]


@pytest.mark.parametrize(("fragment", "record"), CASES2)
def test_record_mark_bearing_loses_to_the_measured_bearing(fragment: str, record: str) -> None:
    single = extract_single_call(fragment, 1)
    full = extract_calls(POB + fragment + CLOSING, strict=False)[0][0]
    for call in (single, full):
        assert call.bearing_azimuth_deg_from_north == pytest.approx(360 - 45 - 10 / 60), fragment
        assert call.distance_ft == 100.0, fragment
        assert call.notes == f"record call: {record}", fragment


@pytest.mark.parametrize(
    "fragment",
    [
        "thence N 45° W (R) 100 feet to a pin",
        "thence N 45° W 100 feet (R) to a pin",
    ],
)
def test_lone_marked_pair_is_still_the_course(fragment: str) -> None:
    call = extract_single_call(fragment, 1)
    assert call.bearing_azimuth_deg_from_north == 315.0
    assert call.distance_ft == 100.0
    assert not call.notes


def test_marked_chord_bearing_loses_to_the_measured_chord_bearing() -> None:
    base = "thence along a curve to the right having a radius of 100 feet, an arc length of 50 feet"
    for chord in (
        "chord bearing N 45° E (R) chord bearing N 45° 10' E (M) 49 feet",
        "chord bearing N 45° E (R), chord bearing N 45° 10' E (M) 49 feet",
        "chord bearing N 45° 10' E (M) chord bearing N 45° E (R) 49 feet",
        "chord bearing N 45° E (R) 49.5 feet, chord bearing N 45° 10' E (M) 49 feet",
        "chord bearing N 45° E 49.5 feet (R) chord bearing N 45° 10' E (M) 49 feet",
    ):
        call = extract_single_call(f"{base}, {chord}", 1)
        assert call.chord_bearing == "N 45°10' E", chord
        assert call.notes and "record call: chord bearing N 45° E" in call.notes, chord


# --- 3. record notes come from their own place in the source ------------------------------
def _notes(calls: list[DeedCall]) -> list[str | None]:
    return [call.notes for call in calls]


def test_two_tracts_each_restore_their_own_record_wording() -> None:
    tract1 = (
        "TRACT 1: BEGINNING at a pin; thence N 46° E 100 feet (N 45° 10' E 100 ft, R) to a "
        "pin; thence S 45° W 100 feet to a pin; thence N 46° W 100 feet to the point of "
        "beginning. "
    )
    tract2 = (
        "TRACT 2: BEGINNING at a pin; thence N 46° E 100 feet (N 45°10' E 100 Feet, R) to a "
        "pin; thence S 45° W 100 feet to a pin; thence N 46° W 100 feet to the point of "
        "beginning."
    )
    calls, tracts = extract_calls(tract1 + tract2, strict=False)
    assert len(tracts) == 2
    assert tracts[0].calls[0].notes == "record call: (N 45° 10' E 100 ft, R)"
    assert tracts[1].calls[0].notes == "record call: (N 45°10' E 100 Feet, R)"


def test_rewritten_record_does_not_shift_a_later_record() -> None:
    source = (
        "BEGINNING at a pin; thence N 46° E 100 feet (N 45° 10' E 100 ft, R) to a pin; "
        "thence N 47° E 100 feet (N 45° 10' E 100 feet, R) to a pin; "
        "thence S 10° W 100 feet to the point of beginning."
    )
    calls, _ = extract_calls(source, strict=False)
    assert _notes(calls)[:2] == [
        "record call: (N 45° 10' E 100 ft, R)",
        "record call: (N 45° 10' E 100 feet, R)",
    ]


def test_identical_record_text_twice_maps_in_order() -> None:
    source = (
        "BEGINNING at a pin; thence N 46° E 100 feet (N 45° 10' E 100 ft, R) to a pin; "
        "thence N 47° E 100 feet (N 45° 10' E 100 ft, R) to a pin; "
        "thence S 10° W 100 feet to the point of beginning."
    )
    calls, _ = extract_calls(source, strict=False)
    assert _notes(calls)[:2] == ["record call: (N 45° 10' E 100 ft, R)"] * 2


def test_record_wording_is_not_taken_from_inside_another_word_or_number() -> None:
    source = (
        "BEGINNING at a pin (see 1100  FEET (r) in the earlier deed); "
        "thence N 46° E (M) N 45° E 100 feet (R) 99 feet to a pin; "
        "thence S 10° W 100 feet to the point of beginning."
    )
    calls, _ = extract_calls(source, strict=False)
    notes = calls[0].notes or ""
    assert "1100" not in notes and "FEET" not in notes
