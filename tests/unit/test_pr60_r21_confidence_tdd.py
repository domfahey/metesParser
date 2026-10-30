"""Round 21: a curve fixed by chord and delta scores like one with its tangent stated."""

from __future__ import annotations

from mp_models import DeedCall
from mp_verify.confidence import score_call_quality


def _curve(**overrides: object) -> DeedCall:
    fields: dict[str, object] = {
        "course": 2,
        "direction_text": "along a curve to the left",
        "distance_ft": 157.08,
        "curve_dir": "left",
        "radius_ft": 100.0,
        "arc_length_ft": 157.08,
        "chord_bearing": "N 45°00'00\" E",
    }
    fields.update(overrides)
    return DeedCall(**fields)  # type: ignore[arg-type]


def test_chord_and_delta_curve_is_not_scored_as_missing_bearing() -> None:
    unstated = _curve()
    stated = _curve(bearing_azimuth_deg_from_north=90.0)

    assert unstated.bearing_azimuth_deg_from_north is None
    assert score_call_quality(unstated) == score_call_quality(stated) == "high"


def test_chord_only_curve_still_scores_low() -> None:
    chord_only = _curve(arc_length_ft=None, chord_length_ft=100.0, distance_ft=100.0)

    assert score_call_quality(chord_only) == "low"
