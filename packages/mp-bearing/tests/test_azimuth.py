"""Verify azimuth conversions."""


def test_quadrant_to_azimuth_ne():
    from mp_bearing import quadrant_to_azimuth

    assert quadrant_to_azimuth("N", 45.0, "E") == 45.0


def test_quadrant_to_azimuth_sw():
    from mp_bearing import quadrant_to_azimuth

    assert quadrant_to_azimuth("S", 45.0, "W") == 225.0


def test_parse_quadrant_bearing():
    from mp_bearing import parse_quadrant_bearing

    result = parse_quadrant_bearing("S 56\u00b040' W")
    assert result is not None
    assert result[0] == "S"


def test_bearing_to_azimuth():
    from mp_bearing import bearing_to_azimuth

    az = bearing_to_azimuth("N 45\u00b000' E")
    assert az is not None
    assert abs(az - 45.0) < 0.01


def test_azimuth_to_quadrant():
    from mp_bearing import azimuth_to_quadrant

    result = azimuth_to_quadrant(225.0)
    assert result.startswith("S")
    assert "W" in result


def test_parse_packed_dms():
    from mp_bearing import parse_packed_dms

    result = parse_packed_dms(46.1631)
    assert abs(result - 46.2753) < 0.001


def test_compass_point_to_azimuth():
    from mp_bearing import compass_point_to_azimuth

    assert compass_point_to_azimuth("northeast") == 45.0
    assert compass_point_to_azimuth("south") == 180.0
