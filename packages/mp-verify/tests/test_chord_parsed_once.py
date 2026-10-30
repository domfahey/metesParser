"""verify_closure parses each distinct chord bearing string once, not per consumer."""

import mp_verify.checks as checks_mod
import mp_verify.tangents as tangents
import mp_verify.traverse as traverse_mod
from mp_models import DeedCall
from mp_verify.closure import verify_closure


def _line(course, azimuth, distance=100.0):
    return DeedCall(
        course=course,
        direction_text="recorded",
        bearing_azimuth_deg_from_north=azimuth,
        distance_ft=distance,
    )


def test_verify_closure_parses_chord_bearing_once(monkeypatch):
    chord = "N 12°34'56\" E"  # unique to this test so no other test warms the cache
    curve = DeedCall(
        course=2,
        direction_text="recorded",
        bearing_azimuth_deg_from_north=None,
        distance_ft=100.0,
        curve_dir="right",
        radius_ft=500.0,
        delta_deg=11.5,
        chord_bearing=chord,
        chord_length_ft=100.0,
        is_indefinite=True,
    )
    calls = [_line(1, 0.0), curve, _line(3, 180.0), _line(4, 270.0)]
    if hasattr(tangents, "_chord_azimuth"):
        tangents._chord_azimuth.cache_clear()
    seen: list[str] = []
    real = tangents.bearing_to_azimuth

    def spy(text):
        seen.append(text)
        return real(text)

    for mod in (tangents, checks_mod, traverse_mod):
        if hasattr(mod, "bearing_to_azimuth"):
            monkeypatch.setattr(mod, "bearing_to_azimuth", spy)
    verify_closure(calls)
    assert seen.count(chord) == 1
