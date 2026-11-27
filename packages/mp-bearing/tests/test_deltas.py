"""Behavioral tests for delta (dx, dy) coordinate offset calculations."""

from __future__ import annotations

import math

import pytest
from mp_bearing import calculate_deltas


@pytest.mark.parametrize(
    ("azimuth_deg", "distance_ft", "expected_dx", "expected_dy"),
    [
        (0.0, 100.0, 0.0, 100.0),
        (90.0, 100.0, 100.0, 0.0),
        (180.0, 100.0, 0.0, -100.0),
        (270.0, 100.0, -100.0, 0.0),
        (360.0, 100.0, 0.0, 100.0),
        (45.0, 100.0, 50.0 * math.sqrt(2.0), 50.0 * math.sqrt(2.0)),
        (135.0, 100.0, 50.0 * math.sqrt(2.0), -50.0 * math.sqrt(2.0)),
        (225.0, 100.0, -50.0 * math.sqrt(2.0), -50.0 * math.sqrt(2.0)),
        (315.0, 100.0, -50.0 * math.sqrt(2.0), 50.0 * math.sqrt(2.0)),
        (
            236.675,
            150.0,
            150.0 * math.sin(math.radians(236.675)),
            150.0 * math.cos(math.radians(236.675)),
        ),
        (60.0, 0.0, 0.0, 0.0),
    ],
)
def test_calculate_deltas_all_quadrants_and_boundaries(
    azimuth_deg: float, distance_ft: float, expected_dx: float, expected_dy: float
) -> None:
    dx, dy = calculate_deltas(azimuth_deg, distance_ft)
    assert dx == pytest.approx(expected_dx, abs=1e-12)
    assert dy == pytest.approx(expected_dy, abs=1e-12)
