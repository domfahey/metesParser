"""Hyphenated DMS with explicit minute/second marks parses as a bearing."""

from __future__ import annotations

import pytest
from mp_parse.calls import extract_calls, extract_single_call
from mp_parse.metadata import read_course_length

_CLOSE = (
    "; thence S 80°00' E 100.00 feet to a pin; thence S 10°00' W 100.00 feet to a pin; "
    "thence N 80°00' W 100.00 feet to the point of beginning."
)

# (bearing as written, azimuth)
_FORMS = [
    ("N 45-30' 15\" E", 45 + 30 / 60 + 15 / 3600),
    ("N 45-30'-15\" E", 45 + 30 / 60 + 15 / 3600),
    ("N 45-30'15\" E", 45 + 30 / 60 + 15 / 3600),
    ("N 45-30′ 15″ E", 45 + 30 / 60 + 15 / 3600),
    ("N 45-30' E", 45.5),
    ("S 10-15' W", 180 + 10.25),
    ("S 10 - 15' W", 180 + 10.25),
    ("N 45-30 E", 45.5),
    ("N 45-30-15 E", 45 + 30 / 60 + 15 / 3600),
]


@pytest.mark.parametrize("bearing,azimuth", _FORMS)
@pytest.mark.parametrize("length", ["100 feet", "100'"])
def test_hyphen_marked_dms(bearing, azimuth, length):
    text = f"thence {bearing} {length} to a pin"
    call = extract_single_call(text, 1)
    assert call is not None
    assert call.bearing_azimuth_deg_from_north == pytest.approx(azimuth)
    assert call.distance_ft == pytest.approx(100.0)
    assert bearing in call.direction_text
    assert read_course_length(text).value == 100.0
    calls, _ = extract_calls("BEGINNING at a pin; " + text + _CLOSE, strict=True)
    assert calls[0].bearing_azimuth_deg_from_north == pytest.approx(azimuth)
    assert round(calls[0].distance_ft, 6) == 100.0


@pytest.mark.parametrize(
    "text",
    [
        "Lot N 12-3 E 100 feet",
        "thence along Lot N 12-3' E 100 feet to a pin",
        "Parcel A N 12-3' E 100 feet",
    ],
)
def test_identifier_not_a_bearing(text):
    call = extract_single_call("thence " + text if not text.startswith("thence") else text, 1)
    assert call is None or call.bearing_azimuth_deg_from_north is None
