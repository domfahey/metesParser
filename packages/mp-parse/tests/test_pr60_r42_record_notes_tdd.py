"""PR #60 round 42: record-labelled wording is never lost, and stays verbatim.

Every record-labelled statement or bracketed group excluded from the course is kept
verbatim in notes (both ``extract_calls`` and ``extract_single_call``); adjoiner
wording "by the line of ..." is captured in ``along``.
"""

from __future__ import annotations

import re

import pytest
from mp_models import DeedCall
from mp_parse.calls import extract_calls, extract_single_call

POB = "BEGINNING at a point; "
CLOSING = " THENCE S 45° W 100 feet to the point of BEGINNING."


def _both(fragment: str) -> list[DeedCall]:
    single = extract_single_call(fragment, 1)
    full = extract_calls(POB + fragment + CLOSING, strict=False)[0]
    assert full, fragment
    return [single, full[0]]


# (fragment, azimuth, distance, record wording that must appear verbatim in notes)
RECORD_CASES = [
    ("THENCE N 46° E (M) N 45° E (R) 100 feet to a point", 46.0, 100.0, "N 45° E (R)"),
    ("THENCE N 46° E (M), N 45° E (R) 100 feet to a point", 46.0, 100.0, "N 45° E (R)"),
    ("THENCE N 45° E (Rec. 99.5') 100 feet to a point", 45.0, 100.0, "(Rec. 99.5')"),
    ("THENCE N 45° E (99.5' Rec.) 100 feet to a point", 45.0, 100.0, "(99.5' Rec.)"),
    ("THENCE N 45° E 100.2 feet (100 feet plan) to a point", 45.0, 100.2, "(100 feet plan)"),
    ("THENCE N 45° E 100 feet (100.5 feet, plat) to a point", 45.0, 100.0, "(100.5 feet, plat)"),
    ("THENCE N 45° E 100 feet (plat: 100.5 feet) to a point", 45.0, 100.0, "(plat: 100.5 feet)"),
    ("THENCE N 45° E 100 feet (100.5 feet P) to a point", 45.0, 100.0, "(100.5 feet P)"),
    ("THENCE N 45° E 99.9 feet (M) (100 feet D) to a point", 45.0, 99.9, "(100 feet D)"),
    ("THENCE N 45° E 100 feet (100.5 feet survey) to a point", 45.0, 100.0, "(100.5 feet survey)"),
    (
        "THENCE N 45° E 100 feet (N 45° 10' E 100.5 feet, R) to a pin",
        45.0,
        100.0,
        "(N 45° 10' E 100.5 feet, R)",
    ),
    (
        "THENCE N 45° E 100 feet in prior deed N 44° E 100.5 feet to a pin",
        45.0,
        100.0,
        "in prior deed N 44° E 100.5 feet",
    ),
]

# Groups that are not record calls: never noted as a record call.
NON_RECORD_CASES = [
    "THENCE N 45° E 100 feet (50 feet wide) to a point",
    "THENCE N 45° E 100 feet (100) to a point",
    "THENCE N 45° E 100 feet (R=100.00') to a point",
    "THENCE N 45° E 100 feet (see plan 12 feet) to a point",
]


@pytest.mark.parametrize(("fragment", "azimuth", "distance", "wording"), RECORD_CASES)
def test_record_wording_kept_verbatim_in_both_paths(
    fragment: str, azimuth: float, distance: float, wording: str
) -> None:
    for call in _both(fragment):
        assert call.bearing_azimuth_deg_from_north == pytest.approx(azimuth)
        assert call.distance_ft == pytest.approx(distance)
        assert call.notes is not None, fragment
        assert wording in call.notes, (fragment, call.notes)


@pytest.mark.parametrize("fragment", NON_RECORD_CASES)
def test_non_record_groups_are_not_record_calls(fragment: str) -> None:
    for call in _both(fragment):
        assert call.distance_ft == pytest.approx(100.0)
        assert "record call" not in (call.notes or "")


@pytest.mark.parametrize("fragment", [case[0] for case in RECORD_CASES])
def test_every_excluded_record_group_is_noted(fragment: str) -> None:
    """Invariant: a bracket group holding a length or bearing absent from the course is noted."""
    for call in _both(fragment):
        for group in re.findall(r"\([^()]*\)", fragment):
            if not re.search(r"\d", group) or re.fullmatch(r"\((?:M|R)\)", group):
                continue
            assert group in (call.notes or ""), (fragment, group, call.notes)


def test_label_words_stay_with_the_record_wording() -> None:
    for call in _both("THENCE N 45° E 100 feet in prior deed N 44° E 100.5 feet to a pin"):
        assert call.notes == "record call: in prior deed N 44° E 100.5 feet"


@pytest.mark.parametrize(
    "fragment",
    [
        "THENCE N 45° E by the line of Smith 100 feet to a point",
        "THENCE N 45° E 100 feet by the line of Smith to a point",
    ],
)
def test_by_the_line_of_is_adjoiner_wording(fragment: str) -> None:
    for call in _both(fragment):
        assert call.along == "the line of Smith"
        assert call.to == "a point"
        assert call.distance_ft == pytest.approx(100.0)


def test_by_land_now_or_formerly_of_is_adjoiner_wording() -> None:
    for call in _both("THENCE N 45° E 100 feet by land now or formerly of Smith to a point"):
        assert call.along == "land now or formerly of Smith"


@pytest.mark.parametrize(
    "fragment",
    [
        "THENCE N 45° E 100 feet by deed to a point",
        "THENCE N 45° E 100 feet by plan to a point",
        "THENCE N 45° E 100 feet, bounded by an iron pin to a point",
    ],
)
def test_other_senses_of_by_are_not_along(fragment: str) -> None:
    for call in _both(fragment):
        assert call.along is None
