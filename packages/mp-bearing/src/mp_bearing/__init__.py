"""Bearing conversion and curve math for metes and bounds parsing."""

from .azimuth import (
    azimuth_to_quadrant,
    bearing_to_azimuth,
    compass_point_to_azimuth,
    degree_of_curvature_to_radius,
    parse_packed_dms,
    parse_quadrant_bearing,
    quadrant_to_azimuth,
)

__version__ = "1.0.0"

__all__ = [
    "azimuth_to_quadrant",
    "bearing_to_azimuth",
    "compass_point_to_azimuth",
    "degree_of_curvature_to_radius",
    "parse_packed_dms",
    "parse_quadrant_bearing",
    "quadrant_to_azimuth",
]
