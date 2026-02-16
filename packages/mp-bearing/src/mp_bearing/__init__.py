"""Bearing conversion and curve math for metes and bounds parsing."""

from .azimuth import (
    COMPASS_POINTS,
    QUADRANT_PATTERN,
    azimuth_to_quadrant,
    bearing_to_azimuth,
    compass_point_to_azimuth,
    degree_of_curvature_to_radius,
    parse_packed_dms,
    parse_quadrant_bearing,
    quadrant_to_azimuth,
)
from .curves import (
    calculate_chord_bearing,
    calculate_curve_properties,
    calculate_missing_curve_elements,
    compute_curve_endpoint,
)
from .deltas import calculate_deltas

__version__ = "1.0.0"

__all__ = [
    "COMPASS_POINTS",
    "QUADRANT_PATTERN",
    "azimuth_to_quadrant",
    "bearing_to_azimuth",
    "calculate_chord_bearing",
    "calculate_curve_properties",
    "calculate_deltas",
    "calculate_missing_curve_elements",
    "compass_point_to_azimuth",
    "compute_curve_endpoint",
    "degree_of_curvature_to_radius",
    "parse_packed_dms",
    "parse_quadrant_bearing",
    "quadrant_to_azimuth",
]
