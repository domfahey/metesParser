"""verify_closure derives indefinite flags from its single boundary analysis.

Each boundary call's indefinite state is decided once in analyze_courses. The warning
and confidence scoring reuse those records instead of re-deriving effective_indefinite
per call. effective_indefinite is the only path that re-parses a chord, so counting
parse_chord calls in the traverse module covers every re-derivation.
"""

import mp_verify.confidence as confidence_mod
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


def _four_course_parcel() -> list[DeedCall]:
    chord_curve = DeedCall(
        course=2,
        direction_text="recorded",
        distance_ft=100.0,
        curve_dir="right",
        radius_ft=500.0,
        chord_bearing="S 90° E",
        chord_length_ft=100.0,
    )
    return [_line(1, 0.0), chord_curve, _line(3, 180.0), _line(4, 270.0)]


def test_all_boundary_parcel_does_not_rederive_indefinite(monkeypatch):
    calls = _four_course_parcel()
    real_effective = traverse_mod.effective_indefinite
    seen: list[int] = []

    def spy_effective(call: DeedCall) -> bool:
        seen.append(call.course)
        return real_effective(call)

    monkeypatch.setattr(confidence_mod, "effective_indefinite", spy_effective)
    verify_closure(calls)
    assert seen == []


def test_all_boundary_parcel_parses_each_chord_once(monkeypatch):
    calls = _four_course_parcel()
    real_parse = traverse_mod.parse_chord
    parsed: list[str | None] = []

    def spy_parse(call: DeedCall):
        parsed.append(call.chord_bearing)
        return real_parse(call)

    monkeypatch.setattr(traverse_mod, "parse_chord", spy_parse)
    verify_closure(calls)
    assert len(parsed) == len(calls)
