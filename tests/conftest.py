"""Shared pytest fixtures and configuration for test suite."""

from __future__ import annotations

import sys

import pytest

from metesparser.logging_config import configure_logging
from metesparser.models import DeedCall


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line("markers", "integration: marks tests as integration tests")
    config.addinivalue_line("markers", "e2e: marks tests as end-to-end tests")
    config.addinivalue_line("markers", "regression: marks tests as regression tests (bug fixes)")
    config.addinivalue_line("markers", "curve: marks tests related to curve calculations")


@pytest.fixture
def isolate_logging_state() -> None:
    """Reset logging configuration for tests that opt in to logging isolation."""
    yield
    configure_logging(level="INFO", log_format="console", stream=sys.stderr, take_over_root=True)
    configure_logging(level="INFO", log_format="console", stream=sys.stderr, take_over_root=False)


@pytest.fixture
def deed_call_factory():
    """Factory to create DeedCall objects with sensible defaults."""

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
def sample_legal_text() -> str:
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
