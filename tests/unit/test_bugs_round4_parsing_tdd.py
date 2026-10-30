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


@pytest.mark.parametrize("parse", PARSERS)
@pytest.mark.parametrize(
    ("course", "expected_ft"),
    [
        ("THENCE N 10° E 2 chains 20 links to an iron pin", 145.2),
        ("THENCE N 10° E 2 chains, 20 links to an iron pin", 145.2),
    ],
)
def test_compound_distance_without_and_sums_every_component(parse, course, expected_ft):
    # Bug #70: only the first component was kept when "and" was absent.
    assert parse(course)[0].distance_ft == pytest.approx(expected_ft)


@pytest.mark.parametrize("parse", PARSERS)
@pytest.mark.parametrize(
    ("course", "expected_ft"),
    [
        ("THENCE N 10° E 150 feet, 3 rods north of the oak to an iron pin", 150.0),
        ("THENCE N 10° E 40 poles 2 rods to an iron pin", 660.0),
        ("THENCE N 10° E 40 poles 5 feet to an iron pin", 660.0),
        ("THENCE N 10° E 40 poles and 5 feet to an iron pin", 665.0),
        ("THENCE N 10° E 3 poles 4 links to an iron pin", 52.14),
    ],
)
def test_unrelated_adjacent_units_are_not_summed_without_and(parse, course, expected_ft):
    # PR #60 review: only genuine descending sub-unit pairs join without "and".
    assert parse(course)[0].distance_ft == pytest.approx(expected_ft)


@pytest.mark.parametrize("parse", PARSERS)
def test_repeated_same_unit_measurements_are_not_summed_without_and(parse):
    call = parse("THENCE N 10° E 100 feet, 50 feet from the corner to an iron pin")[0]
    assert call.distance_ft == pytest.approx(100.0)


@pytest.mark.parametrize("parse", PARSERS)
@pytest.mark.parametrize("qualifier", ["approximately ", ""])
def test_derived_tangent_note_survives_meander_or_approximate_note(parse, qualifier):
    # PR #60 review: the derivation disclosure was replaced by the meander note.
    call = parse(
        f"THENCE a curve to the right, {qualifier}radius of 50 feet, delta angle of 90°, "
        "chord bearing North 45° East 70.71 feet; THENCE due South 50 feet; "
        "THENCE due West 50 feet to the point of beginning."
    )[0]
    assert call.bearing_azimuth_deg_from_north == pytest.approx(0.0, abs=1e-6)
    assert call.bearing_quadrant is None
    assert "tangent bearing derived from chord bearing and delta" in (call.notes or "")
    if qualifier:
        assert "meander / approximate" in call.notes


@pytest.mark.parametrize("parse", PARSERS)
def test_abbreviated_chord_bearing_is_not_used_as_tangent(parse):
    text = (
        "THENCE a curve to the right, radius of 100 feet, delta angle of 90°, "
        "chord bears {chord} 141.42 feet; THENCE due South 50 feet; "
        "THENCE due West 50 feet to the point of beginning."
    )
    a = parse(text.format(chord="N 45°00'00\" E"))[0]
    b = parse(text.format(chord="North 45°00'00\" East"))[0]
    assert a.bearing_azimuth_deg_from_north == pytest.approx(0.0, abs=1e-6)
    assert a.bearing_azimuth_deg_from_north == b.bearing_azimuth_deg_from_north
    assert a.bearing_quadrant is None
    assert "tangent bearing derived from chord bearing and delta" in (a.notes or "")


@pytest.mark.parametrize("parse", PARSERS)
def test_separately_stated_tangent_bearing_is_kept_with_chord(parse):
    text = (
        "THENCE N 10°00'00\" E along a curve to the right, radius of 100 feet, delta angle of 90°, "
        "chord bears N 55°00'00\" E 141.42 feet; THENCE due South 50 feet; "
        "THENCE due West 50 feet to the point of beginning."
    )
    assert parse(text)[0].bearing_azimuth_deg_from_north == pytest.approx(10.0)
