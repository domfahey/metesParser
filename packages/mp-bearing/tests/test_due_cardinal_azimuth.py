"""Tests for due cardinal bearing to azimuth conversion.

'Due North', 'due South', 'due East', 'due West' are precise bearings
meaning exactly 0, 180, 90, 270 degrees azimuth respectively.  The 'due'
prefix indicates surveyor certainty, NOT incompleteness.
"""

from __future__ import annotations

import pytest
from mp_bearing.azimuth import due_cardinal_to_azimuth


class TestDueCardinalToAzimuth:
    """Test due_cardinal_to_azimuth() conversion function."""

    # --- Core four directions (full words) ---

    def test_due_north(self) -> None:
        assert due_cardinal_to_azimuth("due North") == 0.0

    def test_due_south(self) -> None:
        assert due_cardinal_to_azimuth("due South") == 180.0

    def test_due_east(self) -> None:
        assert due_cardinal_to_azimuth("due East") == 90.0

    def test_due_west(self) -> None:
        assert due_cardinal_to_azimuth("due West") == 270.0

    # --- Case insensitivity ---

    def test_lowercase(self) -> None:
        assert due_cardinal_to_azimuth("due north") == 0.0

    def test_uppercase(self) -> None:
        assert due_cardinal_to_azimuth("DUE SOUTH") == 180.0

    def test_mixed_case(self) -> None:
        assert due_cardinal_to_azimuth("Due east") == 90.0

    # --- Abbreviated cardinals (N, S, E, W) ---

    def test_due_n(self) -> None:
        assert due_cardinal_to_azimuth("due N") == 0.0

    def test_due_s(self) -> None:
        assert due_cardinal_to_azimuth("due S") == 180.0

    def test_due_e(self) -> None:
        assert due_cardinal_to_azimuth("due E") == 90.0

    def test_due_w(self) -> None:
        assert due_cardinal_to_azimuth("due W") == 270.0

    # --- Whitespace handling ---

    def test_extra_spaces(self) -> None:
        assert due_cardinal_to_azimuth("due   North") == 0.0

    def test_leading_trailing_whitespace(self) -> None:
        assert due_cardinal_to_azimuth("  due South  ") == 180.0

    # --- Returns None for non-due-cardinal ---

    def test_no_due_prefix(self) -> None:
        """Bare 'North' without 'due' should return None."""
        assert due_cardinal_to_azimuth("North") is None

    def test_quadrant_bearing(self) -> None:
        """Standard quadrant bearing should return None."""
        assert due_cardinal_to_azimuth("N 45 E") is None

    def test_empty_string(self) -> None:
        assert due_cardinal_to_azimuth("") is None

    def test_due_only(self) -> None:
        """'due' without a direction should return None."""
        assert due_cardinal_to_azimuth("due") is None

    def test_due_northeast(self) -> None:
        """'due Northeast' is not a standard due-cardinal; should return None."""
        assert due_cardinal_to_azimuth("due Northeast") is None

    def test_due_with_degrees(self) -> None:
        """'due North 45 degrees' is not a pure due-cardinal; should return None."""
        assert due_cardinal_to_azimuth("due North 45 degrees") is None


class TestDueCardinalEdgeCases:
    """Edge cases and integration-style checks."""

    @pytest.mark.parametrize(
        "direction,expected",
        [
            ("due North", 0.0),
            ("due South", 180.0),
            ("due East", 90.0),
            ("due West", 270.0),
            ("due N", 0.0),
            ("due S", 180.0),
            ("due E", 90.0),
            ("due W", 270.0),
            ("Due North", 0.0),
            ("DUE WEST", 270.0),
        ],
    )
    def test_parametrized_conversions(self, direction: str, expected: float) -> None:
        assert due_cardinal_to_azimuth(direction) == expected
