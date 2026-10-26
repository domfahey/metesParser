from __future__ import annotations

import pytest
from mp_parse.metadata import extract_area_statement as package_extract_area_statement

from metesparser.call_extractor import CallExtractor
from metesparser.text_parser import TextParser
from tests.fixtures.package_parser import extract_calls as package_extract_calls

PARSERS = (package_extract_calls, CallExtractor.extract_calls)
AREA_PARSERS = (package_extract_area_statement, TextParser.extract_area_statement)


@pytest.mark.parametrize("parse", PARSERS)
def test_witness_distance_cannot_supply_missing_boundary_distance(parse):
    description = "THENCE due North to an iron pin, from which a witness tree bears S 45° W 50 feet"
    with pytest.raises(ValueError, match="Malformed course"):
        parse(description, strict=True)


@pytest.mark.parametrize("parse", PARSERS)
def test_compound_chain_and_link_distance_is_additive(parse):
    call = parse("THENCE due North 1 chain and 25 links to an iron pin")[0]
    assert call.distance_ft == pytest.approx(82.5)


@pytest.mark.parametrize("parse", PARSERS)
def test_compound_poles_and_links_distance_is_additive(parse):
    call = parse("THENCE due North 2 poles and 5 links to an iron pin")[0]
    assert call.distance_ft == pytest.approx(36.3)


@pytest.mark.parametrize("parse", PARSERS)
def test_unhandled_compound_distance_fails_closed(parse):
    with pytest.raises(ValueError, match="Malformed course"):
        parse("THENCE due North 1 chain and 25 cubits to an iron pin", strict=True)


@pytest.mark.parametrize("parse", PARSERS)
def test_three_component_compound_distance_includes_every_component(parse):
    call = parse("THENCE due North 1 chain and 25 links and 10 links to an iron pin")[0]
    assert call.distance_ft == pytest.approx(89.1)


@pytest.mark.parametrize("parse", PARSERS)
def test_unhandled_third_compound_distance_component_fails_closed(parse):
    with pytest.raises(ValueError, match="Malformed course"):
        parse("THENCE due North 1 chain and 25 links and 10 cubits to an iron pin", strict=True)


@pytest.mark.parametrize("parse", PARSERS)
def test_unsupported_compound_cannot_fall_back_to_first_feet_component(parse):
    with pytest.raises(ValueError, match="Malformed course"):
        parse("THENCE due North 10 feet and 25 cubits to an iron pin", strict=True)


@pytest.mark.parametrize("parse", PARSERS)
def test_explicit_total_distance_sums_compound_units(parse):
    call = parse("THENCE due North, for a total distance of 1 chain and 25 links to an iron pin")[0]
    assert call.distance_ft == pytest.approx(82.5)


@pytest.mark.parametrize("parse", PARSERS)
def test_explicit_total_distance_with_unsupported_component_fails_closed(parse):
    with pytest.raises(ValueError, match="Malformed course"):
        parse(
            "THENCE due North, for a total distance of 10 feet and 25 cubits to an iron pin",
            strict=True,
        )


@pytest.mark.parametrize("parse", PARSERS)
def test_explicit_total_distance_beats_intermediate_reference_distance(parse):
    call = parse(
        "THENCE N 45° E, passing an iron pin at 50 feet, "
        "for a total distance of 100 feet to a stone"
    )[0]
    assert call.distance_ft == pytest.approx(100.0)


@pytest.mark.parametrize("extract_area", AREA_PARSERS)
def test_area_statement_prefers_parcel_area_over_parent_tract(extract_area):
    area = extract_area("Being part of a 6 acre tract, containing 2.5 acres.")
    assert area is not None
    assert area["value_sq_ft"] == pytest.approx(2.5 * 43560)


@pytest.mark.parametrize("extract_area", AREA_PARSERS)
def test_parent_tract_area_without_parcel_area_is_not_reported(extract_area):
    text = (
        "Full Legal Description: Part of the SE 1/4 of Section 12, "
        "containing 6 acres in the parent tract."
    )
    assert extract_area(text) is None


@pytest.mark.parametrize("extract_area", AREA_PARSERS)
def test_clear_area_only_inputs_remain_supported(extract_area):
    area = extract_area("0.1722 acres more or less")
    assert area is not None
    assert area["value_sq_ft"] == pytest.approx(0.1722 * 43560)


@pytest.mark.parametrize(
    ("text", "expected_sq_ft"),
    [
        ("7500 square feet", 7500.0),
        ("10000 sq ft", 10000.0),
        ("10000 acres", 10000 * 43560.0),
    ],
)
@pytest.mark.parametrize("extract_area", AREA_PARSERS)
def test_standalone_integer_areas_without_commas_remain_supported(
    extract_area, text, expected_sq_ft
):
    area = extract_area(text)
    assert area is not None
    assert area["value_sq_ft"] == pytest.approx(expected_sq_ft)


@pytest.mark.parametrize("extract_area", AREA_PARSERS)
def test_explicit_area_label_is_parcel_area_context(extract_area):
    area = extract_area("Area: 7,500 square feet")
    assert area is not None
    assert area["value_sq_ft"] == pytest.approx(7500.0)


@pytest.mark.parametrize(
    "text",
    [
        "The parent tract contains 6 acres.",
        "Being part of a parent tract containing 6 acres.",
    ],
)
@pytest.mark.parametrize("extract_area", AREA_PARSERS)
def test_parent_tract_area_context_is_not_parcel_area(extract_area, text):
    assert extract_area(text) is None


@pytest.mark.parametrize("extract_area", AREA_PARSERS)
def test_conveyed_parcel_area_after_parent_tract_clause_is_selected(extract_area):
    area = extract_area(
        "Being part of a 6 acre parent tract; the conveyed parcel contains 2.5 acres."
    )
    assert area is not None
    assert area["value_sq_ft"] == pytest.approx(2.5 * 43560)
