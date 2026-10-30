from __future__ import annotations

import json
from pathlib import Path

import pytest
from mp_parse.calls import extract_curve_info
from mp_parse.metadata import extract_plss_metadata
from mp_verify import verify_closure

from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker
from metesparser.text_parser import TextParser
from tests.fixtures.package_parser import extract_calls


def _apis():
    return (
        (extract_calls, verify_closure),
        (CallExtractor.extract_calls, ClosureChecker.verify_closure),
    )


@pytest.mark.parametrize("parse,verify", list(_apis()))
def test_witness_reference_bearing_does_not_replace_course_bearing(parse, verify):
    description = (
        "THENCE due North 100 feet to an iron pin, from which a witness tree bears S 45° W 50 feet"
    )
    call = parse(description)[0]
    assert call.direction_text.lower() == "due north"
    assert call.bearing_azimuth_deg_from_north == 0.0
    assert call.to == "an iron pin, from which a witness tree bears S 45° W 50 feet"
    assert call.distance_ft == pytest.approx(100.0)


@pytest.mark.parametrize("parse,_verify", list(_apis()))
def test_cardinal_only_boundary_bearing_stays_incomplete_despite_witness_bearing(parse, _verify):
    call = parse(
        "THENCE northerly 100 feet to an iron pin; from which an oak bears S 45° W 50 feet"
    )[0]
    assert call.bearing_azimuth_deg_from_north is None
    assert call.notes == "incomplete bearing - cardinal only"


@pytest.mark.parametrize("parse,_verify", list(_apis()))
@pytest.mark.parametrize("tree", ["hickory", "sycamore", "cottonwood"])
def test_tree_reference_bearing_is_removed_using_witness_metadata_patterns(parse, _verify, tree):
    call = parse(f"THENCE northerly 100 feet to an iron pin; a large {tree} bears S 45° W 50 feet")[
        0
    ]
    assert call.bearing_azimuth_deg_from_north is None
    assert call.notes == "incomplete bearing - cardinal only"


@pytest.mark.parametrize("parse,verify", list(_apis()))
def test_witness_bearings_do_not_make_square_traverse_appear_closed(parse, verify):
    description = (
        "THENCE easterly 100 feet to iron pin, from which oak bears N 0° E 20 feet; "
        "THENCE southerly 100 feet to iron pin, from which pine bears N 90° E 20 feet; "
        "THENCE westerly 100 feet to iron pin, from which elm bears S 0° E 20 feet; "
        "THENCE northerly 100 feet to iron pin, from which maple bears N 90° W 20 feet"
    )
    calls = parse(description)
    assert [call.bearing_azimuth_deg_from_north for call in calls] == [None, None, None, None]
    result = verify(calls)
    assert result.is_fully_verified() is False
    assert any("4 call(s) have incomplete bearings" in warning for warning in result.warnings)


@pytest.mark.parametrize("parse,verify", list(_apis()))
def test_curve_without_initial_tangent_keeps_chord_bearing_for_closure(parse, verify):
    calls = parse(
        "THENCE along a curve to the right, radius of 100 feet, delta angle of 90 degrees, "
        "arc length of 157.0796327 feet, the chord of which bears N 45° E, "
        "141.421356 feet; THENCE due South 100 feet; "
        "THENCE due West 100 feet to the point of beginning."
    )
    # Chord-only bearing is not the tangent: derived tangent = 45 - 90/2 = 0.
    assert calls[0].bearing_azimuth_deg_from_north == pytest.approx(0.0, abs=1e-6)
    assert calls[0].chord_bearing == "N 45° E"
    result = verify(calls)
    assert result.is_fully_verified()
    assert result.misclosure_ft == pytest.approx(0.0, abs=0.01)


@pytest.mark.parametrize("parse,_verify", list(_apis()))
@pytest.mark.parametrize(
    ("text", "expected_ft"),
    [
        ("THENCE N 45° E 10 engineer chains to pin", 1000.0),
        ("THENCE N 45° E 10 engineer links to pin", 10.0),
        (
            "THENCE N 45° E 1 US survey foot to pin",
            0.30480061 / 0.3048,
        ),
        (
            "THENCE N 45° E 100 US survey feet to pin",
            100.0 * (0.30480061 / 0.3048),
        ),
    ],
)
def test_straight_engineer_and_us_survey_units_are_converted(parse, _verify, text, expected_ft):
    call = parse(text)[0]
    assert call.distance_ft == pytest.approx(expected_ft)


@pytest.mark.parametrize("extract", [extract_curve_info, CallExtractor.extract_curve_info])
def test_curve_radius_accepts_singular_us_survey_foot(extract):
    curve = extract(
        "curve to the right with radius of 1 US survey foot and delta angle of 90 degrees"
    )
    assert curve["radius_ft"] == pytest.approx(0.30480061 / 0.3048)


@pytest.mark.parametrize(
    "extract",
    [extract_plss_metadata, TextParser.extract_plss_metadata],
)
def test_town_alias_extracts_township_in_plss(extract):
    metadata = extract("That part of the Southwest 1/4 of Section 34, Town 4 South, Range 9 East")
    assert metadata["section"] == "34"
    assert metadata["township"] == "4 S"
    assert metadata["range"] == "9 E"


def test_saved_miwayn_ground_truth_township_is_extracted():
    ground_truth = json.loads(Path("sample_deeds/MIWAYN-50745-01268.ground_truth.json").read_text())
    description = ground_truth["Full_Legal_Description"]
    assert extract_plss_metadata(description)["township"] == "4 S"
    assert TextParser.extract_plss_metadata(description)["township"] == "4 S"


@pytest.mark.parametrize("parse,verify", list(_apis()))
def test_chord_bearing_phrasing_populates_chord_bearing_and_closes(parse, verify):
    # Bug #62: "chord bearing ..." was stored as the tangent bearing.
    calls = parse(
        "THENCE a curve to the right, radius of 50 feet, delta angle of 90°, "
        "chord bearing North 45° East 70.71 feet; THENCE due South 50 feet; "
        "THENCE due West 50 feet to the point of beginning."
    )
    assert calls[0].chord_bearing is not None
    assert calls[0].chord_bearing.replace("°", " ").split()[0] == "N"
    assert calls[0].chord_length_ft == pytest.approx(70.71)
    # right curve, delta 90: tangent = chord (45) - delta/2 = 0
    assert calls[0].bearing_azimuth_deg_from_north == pytest.approx(0.0, abs=1e-6)
    assert calls[0].bearing_quadrant is None
    result = verify(calls)
    assert result.misclosure_ft < 0.1


def test_extract_curve_info_chord_bearing_phrasing():
    info = extract_curve_info(
        "a curve to the right, radius of 50 feet, delta angle of 90°, "
        "chord bearing North 45° East 70.71 feet"
    )
    assert info["chord_bearing"] == "N 45° E"
    assert info["chord_length_ft"] == pytest.approx(70.71)
