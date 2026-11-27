"""Tests for due cardinal bearing to azimuth conversion.

'Due North', 'due South', 'due East', 'due West' are precise bearings
meaning exactly 0, 180, 90, 270 degrees azimuth respectively.  The 'due'
prefix indicates surveyor certainty, NOT incompleteness.
"""

from __future__ import annotations

import pytest
from mp_bearing.azimuth import due_cardinal_to_azimuth


@pytest.mark.parametrize(
    ("direction", "expected"),
    [
        ("due North", 0.0),
        ("due South", 180.0),
        ("due East", 90.0),
        ("due West", 270.0),
        ("due north", 0.0),
        ("DUE SOUTH", 180.0),
        ("Due east", 90.0),
        ("DUE WEST", 270.0),
        ("due N", 0.0),
        ("due S", 180.0),
        ("due E", 90.0),
        ("due W", 270.0),
        ("due   North", 0.0),
        ("  due South  ", 180.0),
    ],
)
def test_due_cardinal_to_azimuth_valid_forms(direction: str, expected: float) -> None:
    assert due_cardinal_to_azimuth(direction) == expected


@pytest.mark.parametrize(
    "direction",
    [
        "North",
        "N 45 E",
        "",
        "due",
        "due Northeast",
        "due North 45 degrees",
    ],
)
def test_due_cardinal_to_azimuth_rejects_non_due_cardinal(direction: str) -> None:
    assert due_cardinal_to_azimuth(direction) is None
