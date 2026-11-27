"""Behavioral tests for mp_bearing.azimuth conversions, parsing, and cardinal sectors."""

from __future__ import annotations

import math

import pytest
from mp_bearing import (
    azimuth_to_quadrant,
    bearing_to_azimuth,
    compass_point_to_azimuth,
    degree_of_curvature_to_radius,
    parse_packed_dms,
    parse_quadrant_bearing,
    quadrant_to_azimuth,
)
from mp_bearing.azimuth import cardinal_conflicts_bearing, normalize_cardinal_word


@pytest.mark.parametrize(
    ("c1", "deg", "c2", "expected"),
    [
        ("N", 0.0, "E", 0.0),
        ("N", 45.0, "E", 45.0),
        ("N", 90.0, "E", 90.0),
        ("S", 45.0, "E", 135.0),
        ("S", 0.0, "E", 180.0),
        ("S", 45.0, "W", 225.0),
        ("S", 90.0, "W", 270.0),
        ("N", 45.0, "W", 315.0),
        ("N", 0.0, "W", 0.0),
        (" n ", 30.5, " w ", 329.5),
    ],
)
def test_quadrant_to_azimuth_all_quadrants_and_boundaries(
    c1: str, deg: float, c2: str, expected: float
) -> None:
    assert quadrant_to_azimuth(c1, deg, c2) == pytest.approx(expected)


@pytest.mark.parametrize("bad_deg", [-0.1, 90.01, math.nan, math.inf, -math.inf, True, False])
def test_quadrant_to_azimuth_rejects_invalid_degrees(bad_deg: float) -> None:
    with pytest.raises(ValueError, match="Degrees must be finite"):
        quadrant_to_azimuth("N", bad_deg, "E")


@pytest.mark.parametrize(("c1", "c2"), [("E", "N"), ("N", "S"), ("E", "W"), ("X", "Y")])
def test_quadrant_to_azimuth_rejects_invalid_cardinals(c1: str, c2: str) -> None:
    with pytest.raises(ValueError, match="Invalid cardinal combination"):
        quadrant_to_azimuth(c1, 45.0, c2)


def test_parse_quadrant_bearing_formats_and_rejection() -> None:
    parsed = parse_quadrant_bearing("S 56\u00b040' W")
    assert parsed is not None
    assert parsed[0] == "S"
    assert parsed[1] == pytest.approx(56.0 + 40.0 / 60.0)
    assert parsed[2] == "W"

    with_secs = parse_quadrant_bearing("North 12\u00ba05\u203230.5\u2033 East")
    assert with_secs is not None
    assert with_secs[0] == "N"
    assert with_secs[1] == pytest.approx(12.0 + 5.0 / 60.0 + 30.5 / 3600.0)
    assert with_secs[2] == "E"

    deg_only = parse_quadrant_bearing("N 90\u00b0 E")
    assert deg_only == ("N", 90.0, "E")

    # Exceeding 90 degrees via minutes/seconds or unparseable text must return None.
    assert parse_quadrant_bearing("N 90\u00b001' E") is None
    assert parse_quadrant_bearing("S 90\u00b000'01\" W") is None
    assert parse_quadrant_bearing("southeasterly along the creek") is None


def test_bearing_to_azimuth_valid_and_invalid() -> None:
    assert bearing_to_azimuth("N 45\u00b000' E") == pytest.approx(45.0)
    assert bearing_to_azimuth("S 56\u00b040'30\" W") == pytest.approx(236.675)
    assert bearing_to_azimuth("northerly") is None


@pytest.mark.parametrize(
    ("az", "expected"),
    [
        (0.0, "N 0\u00b000' E"),
        (360.0, "N 0\u00b000' E"),
        (45.0, "N 45\u00b000' E"),
        (90.0, "N 90\u00b000' E"),
        (135.0, "S 45\u00b000' E"),
        (180.0, "S 0\u00b000' E"),
        (225.0, "S 45\u00b000' W"),
        (270.0, "S 90\u00b000' W"),
        (315.0, "N 45\u00b000' W"),
        (-45.0, "N 45\u00b000' W"),
        (45.0 + 30.0 / 60.0 + 15.0 / 3600.0, "N 45\u00b030'15.0\" E"),
        # Seconds >= 59.95 carry into minutes, and minutes == 60 carry into degrees.
        (45.0 + 29.0 / 60.0 + 59.98 / 3600.0, "N 45\u00b030' E"),
        (44.0 + 59.0 / 60.0 + 59.98 / 3600.0, "N 45\u00b000' E"),
    ],
)
def test_azimuth_to_quadrant_all_quadrants_rounding_and_wrap(az: float, expected: str) -> None:
    assert azimuth_to_quadrant(az) == expected


@pytest.mark.parametrize("bad_az", [math.nan, math.inf, -math.inf, True, False])
def test_azimuth_to_quadrant_rejects_non_finite_and_bool(bad_az: float) -> None:
    with pytest.raises(ValueError, match="Azimuth must be finite"):
        azimuth_to_quadrant(bad_az)


def test_parse_packed_dms_valid_and_errors() -> None:
    assert parse_packed_dms(0.0) == pytest.approx(0.0)
    assert parse_packed_dms(46.1631) == pytest.approx(46.0 + 16.0 / 60.0 + 31.0 / 3600.0)
    assert parse_packed_dms(89.5959) == pytest.approx(89.0 + 59.0 / 60.0 + 59.0 / 3600.0)

    for bad in (True, False, math.nan, math.inf, -math.inf):
        with pytest.raises(ValueError, match="Invalid packed DMS value"):
            parse_packed_dms(bad)

    with pytest.raises(ValueError, match="non-negative"):
        parse_packed_dms(-1.0)
    with pytest.raises(ValueError, match="minutes=60"):
        parse_packed_dms(45.6000)
    with pytest.raises(ValueError, match="seconds=60"):
        parse_packed_dms(45.1060)


def test_degree_of_curvature_to_radius_valid_and_errors() -> None:
    assert degree_of_curvature_to_radius(1.0) == pytest.approx(5729.578)
    assert degree_of_curvature_to_radius(5.0) == pytest.approx(5729.578 / 5.0)

    for bad in (0.0, -2.5, math.nan, math.inf, True, False):
        with pytest.raises(ValueError, match="Degree of curvature"):
            degree_of_curvature_to_radius(bad)


def test_compass_point_to_azimuth() -> None:
    assert compass_point_to_azimuth("northeast") == 45.0
    assert compass_point_to_azimuth("  South by West ") == 191.25
    assert compass_point_to_azimuth("North-Northwest") == 337.5
    assert compass_point_to_azimuth("south") == 180.0
    assert compass_point_to_azimuth("invalid point") is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("North", "north"),
        ("northerly", "north"),
        ("northwardly", "north"),
        ("  SOUTHWESTERLY ", "southwest"),
        ("southwardly", "south"),
        ("NE", "northeast"),
        ("nw", "northwest"),
        ("SE", "southeast"),
        ("SW", "southwest"),
        ("N 45 E", None),
        ("", None),
    ],
)
def test_normalize_cardinal_word(raw: str, expected: str | None) -> None:
    assert normalize_cardinal_word(raw) == expected


def test_cardinal_conflicts_bearing_sector_rules_and_wraparound() -> None:
    # Primary cardinals accept within +-67.5 deg of center (inclusive), wrapping across 0/360.
    assert cardinal_conflicts_bearing("northerly", 0.0) is False
    assert cardinal_conflicts_bearing("northerly", 67.5) is False
    assert cardinal_conflicts_bearing("northerly", 292.5) is False
    assert cardinal_conflicts_bearing("northerly", 350.0) is False
    assert cardinal_conflicts_bearing("northerly", 68.0) is True
    assert cardinal_conflicts_bearing("northerly", 180.0) is True

    # Intercardinals accept within +-45 deg of center (inclusive).
    assert cardinal_conflicts_bearing("NE", 0.0) is False
    assert cardinal_conflicts_bearing("NE", 90.0) is False
    assert cardinal_conflicts_bearing("NE", 91.0) is True
    assert cardinal_conflicts_bearing("southwesterly", 225.0) is False
    assert cardinal_conflicts_bearing("southwesterly", 45.0) is True

    # Non-cardinal text or absent azimuth never reports a conflict.
    assert cardinal_conflicts_bearing("N 45 E", 180.0) is False
    assert cardinal_conflicts_bearing("northerly", None) is False


class TestCommaInDMS:
    """GPT-5 sometimes inserts a comma between minutes and seconds."""

    def test_parse_bearing_with_comma_between_min_sec(self) -> None:
        result = parse_quadrant_bearing("S 56\u00b040', 00\" W")
        assert result is not None
        assert result[0] == "S"
        assert result[1] == pytest.approx(56.0 + 40.0 / 60.0)
        assert result[2] == "W"

    def test_parse_bearing_with_comma_no_space(self) -> None:
        result = parse_quadrant_bearing("N 33\u00b020',00\" W")
        assert result is not None
        assert result[0] == "N"
        assert result[1] == pytest.approx(33.0 + 20.0 / 60.0)
        assert result[2] == "W"

    def test_azimuth_with_comma_in_dms(self) -> None:
        assert bearing_to_azimuth("S 56\u00b040', 00\" W") == pytest.approx(236.0 + 40.0 / 60.0)

    def test_azimuth_with_comma_n_w(self) -> None:
        assert bearing_to_azimuth("N 33\u00b020', 00\" W") == pytest.approx(
            360.0 - (33.0 + 20.0 / 60.0)
        )
