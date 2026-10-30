"""A curve stated by radius and chord alone is a valid, ambiguous DeedCall."""

import pytest
from mp_models import DeedCall
from pydantic import ValidationError


def _curve(**overrides):
    data = {
        "course": 1,
        "direction_text": "curve",
        "distance_ft": 100.0,
        "curve_dir": "right",
        "radius_ft": 500.0,
    }
    data.update(overrides)
    return DeedCall(**data)


def test_radius_with_chord_bearing_and_length_is_accepted_without_delta_or_arc():
    call = _curve(chord_bearing="N 45° E", chord_length_ft=100.0, is_indefinite=True)
    assert call.delta_deg is None
    assert call.arc_length_ft is None
    assert call.bearing_azimuth_deg_from_north is None


@pytest.mark.parametrize(
    "overrides",
    [{}, {"chord_length_ft": 100.0}, {"chord_bearing": "N 45° E"}],
    ids=["radius-only", "chord-length-only", "chord-bearing-only"],
)
def test_curve_without_delta_arc_or_complete_chord_is_rejected(overrides):
    with pytest.raises(ValidationError, match="Curve geometry requires"):
        _curve(**overrides)
