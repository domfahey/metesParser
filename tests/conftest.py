"""Shared pytest fixtures and configuration for test suite.

Provides reusable fixtures for common test scenarios and test data.
"""

import math

import pytest

from metesparser.models import DeedCall, Point

# Test tolerance constants
TOLERANCE_FT = 0.01  # Standard closure tolerance
TOLERANCE_ANGLE = 0.000001  # Angle comparison tolerance


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line("markers", "integration: marks tests as integration tests (end-to-end)")
    config.addinivalue_line("markers", "regression: marks tests as regression tests (bug fixes)")
    config.addinivalue_line("markers", "curve: marks tests related to curve calculations")
    config.addinivalue_line("markers", "validation: marks tests related to input validation")


# ============================================================================
# Factory Fixtures
# ============================================================================


@pytest.fixture
def deed_call_factory():
    """Factory to create DeedCall objects with sensible defaults.

    Usage:
        def test_something(deed_call_factory):
            call = deed_call_factory(course=5, distance_ft=200.0)
    """

    def _create(
        course: int = 1,
        direction_text: str = "North",
        bearing_quadrant: str | None = None,
        bearing_azimuth_deg_from_north: float | None = 0.0,
        distance_ft: float = 100.0,
        **kwargs,
    ) -> DeedCall:
        return DeedCall(
            course=course,
            direction_text=direction_text,
            bearing_quadrant=bearing_quadrant,
            bearing_azimuth_deg_from_north=bearing_azimuth_deg_from_north,
            distance_ft=distance_ft,
            **kwargs,
        )

    return _create


@pytest.fixture
def point_factory():
    """Factory to create Point objects.

    Usage:
        def test_something(point_factory):
            p = point_factory(x=100.0, y=200.0)
    """

    def _create(x: float = 0.0, y: float = 0.0) -> Point:
        return Point(x=x, y=y)

    return _create


# ============================================================================
# Common Shape Fixtures
# ============================================================================


@pytest.fixture
def origin():
    """The origin point (0, 0)."""
    return Point(x=0.0, y=0.0)


@pytest.fixture
def square_100ft(deed_call_factory):
    """Perfect 100x100 ft square that closes.

    Returns 4 calls forming a square with:
    - Area: 10,000 sq ft
    - Perimeter: 400 ft
    - Perfect closure (misclosure < 0.01 ft)
    """
    return [
        deed_call_factory(
            course=1,
            direction_text="North",
            bearing_quadrant="N 0°00' E",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=100.0,
        ),
        deed_call_factory(
            course=2,
            direction_text="East",
            bearing_quadrant="N 90°00' E",
            bearing_azimuth_deg_from_north=90.0,
            distance_ft=100.0,
        ),
        deed_call_factory(
            course=3,
            direction_text="South",
            bearing_quadrant="S 0°00' E",
            bearing_azimuth_deg_from_north=180.0,
            distance_ft=100.0,
        ),
        deed_call_factory(
            course=4,
            direction_text="West",
            bearing_quadrant="S 90°00' W",
            bearing_azimuth_deg_from_north=270.0,
            distance_ft=100.0,
        ),
    ]


@pytest.fixture
def pennbrook_18_rectangle(deed_call_factory):
    """18 Pennbrook parcel (parallelogram).

    This is NOT a rectangle - it's a parallelogram with:
    - Opposite sides parallel
    - Not perpendicular (angles ≠ 90°)
    - Area: ~2,971 sq ft (NOT 60×125=7,500)
    - Perfect closure (misclosure < 0.01 ft)
    """
    return [
        # N 33°20' E, 60.00 feet
        deed_call_factory(
            course=1,
            direction_text="N 33°20' E",
            bearing_quadrant="N 33°20' E",
            bearing_azimuth_deg_from_north=33.333333,
            distance_ft=60.0,
        ),
        # S 56°40' W, 125.00 feet
        deed_call_factory(
            course=2,
            direction_text="S 56°40' W",
            bearing_quadrant="S 56°40' W",
            bearing_azimuth_deg_from_north=236.666667,
            distance_ft=125.0,
        ),
        # S 33°20' W, 60.00 feet
        deed_call_factory(
            course=3,
            direction_text="S 33°20' W",
            bearing_quadrant="S 33°20' W",
            bearing_azimuth_deg_from_north=213.333333,
            distance_ft=60.0,
        ),
        # N 56°40' E, 125.00 feet
        deed_call_factory(
            course=4,
            direction_text="N 56°40' E",
            bearing_quadrant="N 56°40' E",
            bearing_azimuth_deg_from_north=56.666667,
            distance_ft=125.0,
        ),
    ]


@pytest.fixture
def right_triangle(deed_call_factory):
    """Right triangle: 100 ft base × 100 ft height.

    Returns 3 calls forming a right triangle with:
    - Area: 5,000 sq ft
    - Closes via hypotenuse
    """
    return [
        deed_call_factory(
            course=1,
            direction_text="East",
            bearing_azimuth_deg_from_north=90.0,
            distance_ft=100.0,
        ),
        deed_call_factory(
            course=2,
            direction_text="South",
            bearing_azimuth_deg_from_north=180.0,
            distance_ft=100.0,
        ),
        deed_call_factory(
            course=3,
            direction_text="N 45° W",
            bearing_azimuth_deg_from_north=315.0,
            distance_ft=math.sqrt(100**2 + 100**2),  # ~141.42 ft
        ),
    ]


# ============================================================================
# Curve Fixtures
# ============================================================================


@pytest.fixture
def curve_90deg_right(deed_call_factory):
    """90° right curve with radius 100 ft.

    Properties:
    - Arc length: ~157.08 ft
    - Chord length: ~141.42 ft
    """
    delta_rad = math.radians(90.0)
    arc_length = 100.0 * delta_rad
    chord_length = 2 * 100.0 * math.sin(delta_rad / 2)

    return deed_call_factory(
        course=1,
        direction_text="Curve to the right",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=arc_length,
        curve_dir="right",
        radius_ft=100.0,
        delta_deg=90.0,
        arc_length_ft=arc_length,
        chord_length_ft=chord_length,
    )


# ============================================================================
# Invalid/Edge Case Fixtures
# ============================================================================


@pytest.fixture
def incomplete_bearing_call(deed_call_factory):
    """Call with incomplete bearing (meander/cardinal-only)."""
    return deed_call_factory(
        course=1,
        direction_text="southwesterly",
        bearing_quadrant=None,
        bearing_azimuth_deg_from_north=None,
        distance_ft=150.0,
        notes="incomplete bearing - cardinal only",
    )


@pytest.fixture
def open_traverse(deed_call_factory):
    """Open traverse that doesn't close (for testing failure cases)."""
    return [
        deed_call_factory(course=1, bearing_azimuth_deg_from_north=0.0, distance_ft=100.0),
        deed_call_factory(course=2, bearing_azimuth_deg_from_north=90.0, distance_ft=100.0),
        # Missing closing calls - will not close
    ]


# ============================================================================
# File/Path Fixtures
# ============================================================================


@pytest.fixture
def tmp_csv_path(tmp_path):
    """Temporary CSV file path for export tests."""
    return tmp_path / "test_output.csv"


@pytest.fixture
def sample_legal_text():
    """Sample legal description text for parsing tests."""
    return """
    BEGINNING at a point in the division line between Lots 46 and 47;
    THENCE South 33 degrees 20 minutes East 60.00 feet along said
    southwesterly line of Concord Drive to a point;
    THENCE South 56 degrees 40 minutes West 125.00 feet along the
    division line to the corner;
    THENCE North 33 degrees 20 minutes West 60.00 feet along the
    division line;
    THENCE North 56 degrees 40 minutes East 125.00 feet to the
    POINT OF BEGINNING.
    """
