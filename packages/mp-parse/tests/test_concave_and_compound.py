"""Concavity wording is not travel direction; 'and' sums only unit-descending pairs."""

import pytest
from mp_parse.calls import extract_single_call
from mp_parse.metadata import extract_distance

_CURVE = (
    "thence along a curve to the right, {concave}having a radius of 300.00 feet "
    "and an arc length of 50.00 feet, the chord of which bears "
    "N 40°00'00\" E 49.94 feet"
)


@pytest.mark.parametrize(
    "concave",
    [
        "",
        "concave to the southeast, ",
        "concave southeasterly, ",
        "concaved to the north, ",
        "concave to the SW, ",
        "whose concave side faces the northwest, ",
        "concave to the south-west, ",
    ],
)
def test_concavity_clause_is_not_a_travel_direction(concave):
    call = extract_single_call(_CURVE.format(concave=concave), 1)
    assert call is not None
    assert call.is_indefinite is False
    assert "conflicts" not in (call.notes or "")
    assert "cardinal only" not in (call.notes or "")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("100.00 feet and 50.00 feet from the line of Smith", (100.0, "feet")),
        # Two same-unit course lengths are ambiguous: neither is chosen (0.0).
        ("North 45 degrees East a distance of 100.00 feet and 50.00 feet", (0.0, "feet")),
        ("2 rods and 3 poles", (0.0, "feet")),
        ("2 chains and 3 chains", (0.0, "feet")),
        ("2 chains and 3 links", (None, "feet")),
        ("2 rods and 3 links", (34.98, "feet")),
        ("2 poles and 3 links", (None, "feet")),
    ],
)
def test_and_compound_sums_only_different_units(text, expected):
    value, unit = extract_distance(text)
    if expected[0] is None:
        assert value > 0 and unit == expected[1]
    else:
        assert value == pytest.approx(expected[0])
        assert unit == expected[1]


def test_links_extend_an_established_chain_run():
    assert extract_distance("1 chain and 25 links and 10 links")[0] == pytest.approx(89.1)
