"""Out-of-range bearings become incomplete calls; unreadable chord/radial bearings are recorded."""

from __future__ import annotations

import pytest
from mp_parse.calls import extract_calls, extract_single_call
from mp_verify.closure import verify_closure

CURVE = "along a curve to the right having a radius of 100 feet, an arc length of 50 feet"


@pytest.mark.parametrize(
    "bearing",
    [
        "N 45° 61' E",
        "North 45° 61' East",
        "North 91° East",
        "South 45° 30' 75\" West",
        "North 89° 59' 61\" East",
        "N 45 degrees 61 minutes E",
        "North 95-30' East",
        "South 91 degrees West",
    ],
)
def test_out_of_range_bearing_is_incomplete_call_in_both_paths(bearing: str) -> None:
    text = f"THENCE {bearing} 100 feet"
    single = extract_single_call(text, 1)
    assert single is not None
    (listed,), _ = extract_calls(text, strict=False)
    for call in (single, listed):
        assert call.bearing_azimuth_deg_from_north is None
        assert (call.notes or "").startswith("incomplete bearing")
        assert call.distance_ft == 100.0


def test_out_of_range_bearing_in_multi_course_text_is_not_skipped() -> None:
    calls, _ = extract_calls("THENCE North 91° East 100 feet; THENCE S 10° W 50 feet", strict=False)
    assert [c.distance_ft for c in calls] == [100.0, 50.0]
    assert calls[0].bearing_azimuth_deg_from_north is None
    assert calls[1].bearing_azimuth_deg_from_north == pytest.approx(190.0)


@pytest.mark.parametrize(
    "text",
    [
        "THENCE Lot N 12-3 E 100 feet",
        "THENCE Lot N 12-70 E 100 feet",
        "THENCE Block S 5 E 100 feet",
    ],
)
def test_identifiers_are_not_bearings(text: str) -> None:
    with pytest.raises(ValueError):
        extract_single_call(text, 1)


def test_cardinal_with_number_is_not_a_bearing_shape() -> None:
    call = extract_single_call("THENCE North 91 feet", 1)
    assert call is not None
    assert call.notes == "incomplete bearing - cardinal only"


def test_unreadable_chord_bearing_is_recorded_and_not_chord_positioned() -> None:
    text = f"THENCE {CURVE} and a chord bearing of N 45 E and chord of 49.79 feet"
    single = extract_single_call(text, 1)
    (listed,), _ = extract_calls(text, strict=False)
    for call in (single, listed):
        assert call is not None
        assert call.chord_bearing is None
        assert "chord bearing not read: 'N 45 E'" in (call.notes or "")
        assert call.is_indefinite is True
    result = verify_closure([single])
    assert any("indefinite" in w.lower() for w in result.warnings)


def test_unreadable_chord_bearing_next_to_stated_tangent_is_recorded() -> None:
    text = f"THENCE N 10° E {CURVE}, a chord bearing of N 45 E and chord of 49.79 feet"
    call = extract_single_call(text, 1)
    assert call is not None
    assert call.bearing_azimuth_deg_from_north == 10.0
    assert call.chord_bearing is None
    assert "chord bearing not read: 'N 45 E'" in (call.notes or "")
    assert call.is_indefinite is True


def test_readable_chord_bearing_has_no_unread_note() -> None:
    call = extract_single_call(
        f"THENCE {CURVE} and a chord bearing of N 45° E and chord of 49.79 feet", 1
    )
    assert call is not None
    assert call.chord_bearing == "N 45° E"
    assert "not read" not in (call.notes or "")
    assert call.is_indefinite is False


def test_unreadable_radial_bearing_is_recorded() -> None:
    call = extract_single_call(f"THENCE {CURVE}, a radial bearing of N 45 E", 1)
    assert call is not None
    assert call.radial_bearing is None
    assert "radial bearing not read: 'N 45 E'" in (call.notes or "")
