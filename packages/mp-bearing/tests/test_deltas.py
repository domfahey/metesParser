"""Verify delta (dx, dy) calculation functions."""

import math


def test_calculate_deltas():
    from mp_bearing import calculate_deltas

    dx, dy = calculate_deltas(90.0, 100.0)
    assert abs(dx - 100.0) < 0.01
    assert abs(dy) < 0.01


def test_calculate_deltas_north():
    from mp_bearing import calculate_deltas

    dx, dy = calculate_deltas(0.0, 100.0)
    assert abs(dx) < 0.01
    assert abs(dy - 100.0) < 0.01
