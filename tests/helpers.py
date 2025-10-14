"""Test helper functions and utilities.

Provides reusable assertion helpers and data generators for tests.
"""

import math

from metesparser.models import ClosureResult, DeedCall, Point


# ============================================================================
# Assertion Helpers
# ============================================================================


def assert_point_near(
    p1: Point, p2: Point, tolerance: float = 0.01, msg: str | None = None
) -> None:
    """Assert two points are within tolerance of each other.

    Args:
        p1: First point
        p2: Second point
        tolerance: Distance tolerance in feet (default: 0.01)
        msg: Optional custom error message

    Raises:
        AssertionError: If points differ by more than tolerance
    """
    distance = math.sqrt((p1.x - p2.x) ** 2 + (p1.y - p2.y) ** 2)
    error_msg = msg or f"Points differ by {distance:.4f} ft (tolerance: {tolerance} ft)"

    assert distance <= tolerance, error_msg


def assert_closure_within_tolerance(
    result: ClosureResult, tolerance: float = 0.01, msg: str | None = None
) -> None:
    """Assert traverse closes within specified tolerance.

    Args:
        result: ClosureResult object
        tolerance: Closure tolerance in feet (default: 0.01)
        msg: Optional custom error message

    Raises:
        AssertionError: If misclosure exceeds tolerance
    """
    error_msg = (
        msg or f"Misclosure {result.misclosure_ft:.4f} ft exceeds tolerance {tolerance} ft"
    )

    assert result.misclosure_ft <= tolerance, error_msg
    assert result.closure_passed is True, error_msg


def assert_angle_near(
    angle1: float, angle2: float, tolerance: float = 0.000001, msg: str | None = None
) -> None:
    """Assert two angles are within tolerance (handles 360° wrap).

    Args:
        angle1: First angle in degrees
        angle2: Second angle in degrees
        tolerance: Angular tolerance in degrees (default: 0.000001)
        msg: Optional custom error message

    Raises:
        AssertionError: If angles differ by more than tolerance
    """
    # Normalize both angles to [0, 360)
    a1 = angle1 % 360.0
    a2 = angle2 % 360.0

    # Calculate minimum angular difference (accounts for wrap around)
    diff = abs(a1 - a2)
    if diff > 180.0:
        diff = 360.0 - diff

    error_msg = msg or f"Angles differ by {diff:.6f}° (tolerance: {tolerance}°)"

    assert diff <= tolerance, error_msg


# ============================================================================
# Data Generators
# ============================================================================


def create_square(
    size: float, start_azimuth: float = 0.0, start_course: int = 1
) -> list[DeedCall]:
    """Generate calls for a square traverse.

    Args:
        size: Side length in feet
        start_azimuth: Azimuth of first side (default: 0° = North)
        start_course: Starting course number (default: 1)

    Returns:
        List of 4 DeedCall objects forming a closed square
    """
    calls = []
    for i in range(4):
        azimuth = (start_azimuth + i * 90.0) % 360.0
        calls.append(
            DeedCall(
                course=start_course + i,
                direction_text=f"Side {i+1}",
                bearing_azimuth_deg_from_north=azimuth,
                distance_ft=size,
            )
        )
    return calls


def create_rectangle(
    width: float, height: float, start_azimuth: float = 0.0, start_course: int = 1
) -> list[DeedCall]:
    """Generate calls for a rectangle traverse.

    Args:
        width: Width in feet (perpendicular to first side)
        height: Height in feet (parallel to first side)
        start_azimuth: Azimuth of first side (default: 0° = North)
        start_course: Starting course number (default: 1)

    Returns:
        List of 4 DeedCall objects forming a closed rectangle
    """
    # Calculate azimuths for 4 sides
    azimuths = [
        start_azimuth,
        (start_azimuth + 90.0) % 360.0,
        (start_azimuth + 180.0) % 360.0,
        (start_azimuth + 270.0) % 360.0,
    ]

    # Distances alternate: height, width, height, width
    distances = [height, width, height, width]

    calls = []
    for i in range(4):
        calls.append(
            DeedCall(
                course=start_course + i,
                direction_text=f"Side {i+1}",
                bearing_azimuth_deg_from_north=azimuths[i],
                distance_ft=distances[i],
            )
        )
    return calls


def create_regular_polygon(
    n_sides: int, side_length: float, start_azimuth: float = 0.0, start_course: int = 1
) -> list[DeedCall]:
    """Generate calls for a regular polygon.

    Args:
        n_sides: Number of sides (must be >= 3)
        side_length: Length of each side in feet
        start_azimuth: Azimuth of first side (default: 0° = North)
        start_course: Starting course number (default: 1)

    Returns:
        List of DeedCall objects forming a closed regular polygon

    Raises:
        ValueError: If n_sides < 3
    """
    if n_sides < 3:
        raise ValueError(f"Polygon must have at least 3 sides, got {n_sides}")

    # Exterior angle = 360° / n
    exterior_angle = 360.0 / n_sides

    calls = []
    current_azimuth = start_azimuth

    for i in range(n_sides):
        calls.append(
            DeedCall(
                course=start_course + i,
                direction_text=f"Side {i+1}",
                bearing_azimuth_deg_from_north=current_azimuth,
                distance_ft=side_length,
            )
        )
        current_azimuth = (current_azimuth + exterior_angle) % 360.0

    return calls


# ============================================================================
# Test Data Constants
# ============================================================================

# Expected deltas for common bearings (for N 33°20' E, 60 ft)
EXPECTED_DX_N33E_60FT = 32.9  # 60 * sin(33.333°) ≈ 32.9 ft
EXPECTED_DY_N33E_60FT = 50.2  # 60 * cos(33.333°) ≈ 50.2 ft

# Expected deltas for S 56°40' W, 125 ft
EXPECTED_DX_S56W_125FT = -104.5  # 125 * sin(236.667°) ≈ -104.5 ft
EXPECTED_DY_S56W_125FT = -68.7  # 125 * cos(236.667°) ≈ -68.7 ft

# Standard tolerance values
TOLERANCE_FT = 0.01  # Closure tolerance (feet)
TOLERANCE_ANGLE = 0.000001  # Angular tolerance (degrees)
TOLERANCE_AREA = 1.0  # Area tolerance (square feet)

# 18 Pennbrook actual area (parallelogram, not rectangle!)
PENNBROOK_18_AREA_SQ_FT = 2970.6  # NOT 60×125=7500 (that assumes 90° angles)
PENNBROOK_18_AREA_ACRES = 0.0682
