"""Azimuth conversion utilities for metes and bounds parsing.

Converts between quadrant bearings (e.g., N 56°40' E) and azimuths
(degrees from North, clockwise). Also handles packed DMS and compass points.
"""

import math
import re

QUADRANT_PATTERN = re.compile(
    r"(N|S)\s*([0-8]?[0-9]|90)[°º]\s*(?:([0-5]?[0-9])['′])?\s*(?:([0-5]?[0-9](?:\.\d+)?)[\"″])?\s*(E|W)",
    re.IGNORECASE,
)

COMPASS_POINTS: dict[str, float] = {
    "north": 0.0,
    "north by east": 11.25,
    "north-northeast": 22.5,
    "northeast by north": 33.75,
    "northeast": 45.0,
    "northeast by east": 56.25,
    "east-northeast": 67.5,
    "east by north": 78.75,
    "east": 90.0,
    "east by south": 101.25,
    "east-southeast": 112.5,
    "southeast by east": 123.75,
    "southeast": 135.0,
    "southeast by south": 146.25,
    "south-southeast": 157.5,
    "south by east": 168.75,
    "south": 180.0,
    "south by west": 191.25,
    "south-southwest": 202.5,
    "southwest by south": 213.75,
    "southwest": 225.0,
    "southwest by west": 236.25,
    "west-southwest": 247.5,
    "west by south": 258.75,
    "west": 270.0,
    "west by north": 281.25,
    "west-northwest": 292.5,
    "northwest by west": 303.75,
    "northwest": 315.0,
    "northwest by north": 326.25,
    "north-northwest": 337.5,
    "north by west": 348.75,
}


def compass_point_to_azimuth(compass_point: str) -> float | None:
    """Convert a 32-point compass direction to azimuth.

    Args:
        compass_point: Compass point name (e.g., "North by East", "Northeast")

    Returns:
        Azimuth in degrees or None if not a recognized compass point
    """
    normalized = compass_point.strip().lower()
    return COMPASS_POINTS.get(normalized)


def parse_packed_dms(value: float) -> float:
    """Convert packed DMS value to decimal degrees.

    Packed DMS format: degrees.MMSS where MM=minutes, SS=seconds.
    Example: 46.1631 -> 46 deg 16'31" -> 46.275278 deg

    Args:
        value: Packed DMS value (e.g., 46.1631)

    Returns:
        Decimal degrees

    Raises:
        ValueError: If minutes >= 60 or seconds >= 60
    """
    degrees = int(value)
    frac = value - degrees

    minutes_seconds = frac * 100
    minutes = int(round(minutes_seconds * 100) // 100)
    seconds = round((minutes_seconds - minutes) * 100, 4)

    if minutes >= 60:
        raise ValueError(f"Invalid packed DMS: minutes={minutes} (must be 0-59)")
    if seconds >= 60:
        raise ValueError(f"Invalid packed DMS: seconds={seconds:.0f} (must be 0-59)")

    return degrees + minutes / 60.0 + seconds / 3600.0


def degree_of_curvature_to_radius(degree_of_curve: float) -> float:
    """Convert degree of curvature to radius using arc definition.

    The degree of curvature is the central angle subtended by a 100-ft arc.
    Formula: R = 5729.578 / D

    Args:
        degree_of_curve: Degree of curvature (must be > 0)

    Returns:
        Radius in feet

    Raises:
        ValueError: If degree_of_curve is zero or negative
    """
    if degree_of_curve <= 0:
        raise ValueError(
            f"Degree of curvature must be positive and non-zero, got {degree_of_curve}"
        )
    return 5729.578 / degree_of_curve


def parse_quadrant_bearing(bearing_text: str) -> tuple[str, float, str] | None:
    """Parse a quadrant bearing string.

    Args:
        bearing_text: Bearing string like "S 56 deg 40'30\" W" or "N 45 deg E"

    Returns:
        Tuple of (cardinal1, degrees, cardinal2) or None if not parseable
        Example: ("S", 56.675, "W")
    """
    match = QUADRANT_PATTERN.search(bearing_text)
    if not match:
        return None

    cardinal1 = match.group(1).upper()
    degrees = float(match.group(2))
    minutes = float(match.group(3)) if match.group(3) else 0.0
    seconds = float(match.group(4)) if match.group(4) else 0.0
    cardinal2 = match.group(5).upper()

    if not (0 <= degrees <= 90):
        return None
    if not (0 <= minutes < 60):
        return None
    if not (0 <= seconds < 60):
        return None

    decimal_degrees = degrees + (minutes / 60.0) + (seconds / 3600.0)

    if decimal_degrees > 90.0:
        return None

    return (cardinal1, decimal_degrees, cardinal2)


def quadrant_to_azimuth(cardinal1: str, degrees: float, cardinal2: str) -> float:
    """Convert quadrant bearing to azimuth (degrees clockwise from North).

    Convention:
    - N theta E -> az = theta
    - S theta E -> az = 180 - theta
    - S theta W -> az = 180 + theta
    - N theta W -> az = 360 - theta

    Args:
        cardinal1: First cardinal (N or S)
        degrees: Angle in degrees
        cardinal2: Second cardinal (E or W)

    Returns:
        Azimuth in degrees [0, 360)
    """
    if cardinal1 == "N" and cardinal2 == "E":
        azimuth = degrees
    elif cardinal1 == "S" and cardinal2 == "E":
        azimuth = 180.0 - degrees
    elif cardinal1 == "S" and cardinal2 == "W":
        azimuth = 180.0 + degrees
    elif cardinal1 == "N" and cardinal2 == "W":
        azimuth = 360.0 - degrees
    else:
        valid_combos = "N-E, S-E, S-W, N-W"
        raise ValueError(
            f"Invalid cardinal combination: {cardinal1}-{cardinal2}. "
            f"Valid combinations are: {valid_combos}"
        )

    return azimuth % 360.0


def bearing_to_azimuth(bearing_text: str) -> float | None:
    """Convert a bearing string to azimuth.

    Args:
        bearing_text: Bearing like "S 56 deg 40'30\" W"

    Returns:
        Azimuth in degrees or None if unparseable
    """
    parsed = parse_quadrant_bearing(bearing_text)
    if parsed is None:
        return None

    cardinal1, degrees, cardinal2 = parsed
    return quadrant_to_azimuth(cardinal1, degrees, cardinal2)


def azimuth_to_quadrant(azimuth: float) -> str:
    """Convert azimuth to quadrant bearing string.

    Args:
        azimuth: Azimuth in degrees [0, 360)

    Returns:
        Quadrant bearing string like "N 45 deg 30' E"
    """
    azimuth = azimuth % 360.0

    if 0 <= azimuth <= 90:
        angle = azimuth
        cardinal1, cardinal2 = "N", "E"
    elif 90 < azimuth <= 180:
        angle = 180.0 - azimuth
        cardinal1, cardinal2 = "S", "E"
    elif 180 < azimuth <= 270:
        angle = azimuth - 180.0
        cardinal1, cardinal2 = "S", "W"
    else:
        angle = 360.0 - azimuth
        cardinal1, cardinal2 = "N", "W"

    degrees = int(angle)
    remainder = (angle - degrees) * 60
    minutes = int(remainder)
    seconds = (remainder - minutes) * 60

    if seconds >= 59.95:
        seconds = 0.0
        minutes += 1
        if minutes >= 60:
            minutes = 0
            degrees += 1

    if seconds < 0.5:
        return f"{cardinal1} {degrees}\u00b0{minutes:02d}' {cardinal2}"
    else:
        return f'{cardinal1} {degrees}\u00b0{minutes:02d}\'{seconds:04.1f}" {cardinal2}'
