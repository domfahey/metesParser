"""Coordinate delta calculations for metes and bounds traversals.

Converts azimuth + distance into dx/dy offsets for traverse computation.
"""

from __future__ import annotations

import math


def calculate_deltas(azimuth_deg: float, distance_ft: float) -> tuple[float, float]:
    """Calculate dx, dy deltas from azimuth and distance.

    Formula:
        dx = distance * sin(azimuth)
        dy = distance * cos(azimuth)

    Args:
        azimuth_deg: Azimuth in degrees (clockwise from North)
        distance_ft: Distance in feet

    Returns:
        Tuple of (dx, dy) in feet
    """
    azimuth_rad = math.radians(azimuth_deg)
    dx = distance_ft * math.sin(azimuth_rad)
    dy = distance_ft * math.cos(azimuth_rad)
    return (dx, dy)
