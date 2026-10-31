from __future__ import annotations

import json
from pathlib import Path

import pytest
from mp_parse import extract_calls as package_extract_with_tracts

from metesparser.call_extractor import CallExtractor
from tests.fixtures.package_parser import extract_calls as package_extract_calls

PARSERS = (package_extract_calls, CallExtractor.extract_calls)

KINGS_HIGHWAY_GT = (
    Path(__file__).resolve().parents[2]
    / "sample_deeds"
    / "101-111 Kings Highway E - Deed Image (7683 - 1295).ground_truth.json"
)


@pytest.mark.parametrize("parse", PARSERS)
def test_comma_separated_dms_bearing_is_parsed(parse):
    call = parse(
        "BEGINNING at a point; thence North 29 degrees, 23 minutes, 50 seconds West "
        "along the Northeasterly line of Tanner Street, 72.64 feet to a point"
    )[0]
    assert call.bearing_azimuth_deg_from_north == pytest.approx(330.602778)
    assert call.distance_ft == pytest.approx(72.64)


@pytest.mark.parametrize("parse", PARSERS)
@pytest.mark.parametrize(
    ("distance_text", "expected_ft"),
    [("158 feet 8 inches", 158 + 8 / 12), ("92 feet, 4 inches", 92 + 4 / 12)],
)
def test_feet_and_inches_distance_includes_inches(parse, distance_text, expected_ft):
    call = parse(f"thence North 27 degrees 15 minutes West {distance_text} to a point")[0]
    assert call.distance_ft == pytest.approx(expected_ft)


@pytest.mark.parametrize("parse", PARSERS)
def test_interior_angle_is_not_a_compound_distance(parse):
    call = parse(
        "thence in a Northwesterly direction and forming an interior angle of 90 degrees "
        "15 minutes and 40 seconds and along the division line a distance of 15.60 feet "
        "to a point",
        strict=True,
    )[0]
    assert call.distance_ft == pytest.approx(15.60)
    assert call.bearing_azimuth_deg_from_north is None


@pytest.mark.parametrize("parse", PARSERS)
def test_offset_distance_is_not_the_course_length(parse):
    call = parse(
        "thence South 27 degrees 15 minutes East running parallel with the first course and "
        "distant 10 feet Northeastwardly therefrom measured at right angles thereto 158 feet, "
        "more or less, to a point"
    )[0]
    assert call.distance_ft == pytest.approx(158.0)


@pytest.mark.parametrize("parse", PARSERS)
def test_width_is_not_the_course_length(parse):
    call = parse(
        "thence in a Northwesterly direction along the Northeasterly line of the aforesaid "
        "10 feet wide alley, a distance of 148.10 feet to a point"
    )[0]
    assert call.distance_ft == pytest.approx(148.10)


@pytest.mark.parametrize("parse", PARSERS)
def test_course_ending_at_restated_place_of_beginning_is_a_tie_line(parse):
    calls = parse(
        "STARTING at a point in the line of Kings Highway; thence in a Northwesterly direction "
        "a distance of 148.10 feet to a point corner to lands of Glassman which last mentioned "
        "point is the place of beginning on the lands hereby being described; and continuing "
        "thence in a Northwesterly direction a distance of 12 feet to a point; thence in a "
        "Northeasterly direction a distance of 50 feet to the place of beginning."
    )
    assert [call.is_tie_in for call in calls] == [True, False, False]


@pytest.mark.parametrize("parse", PARSERS)
def test_closing_course_to_place_of_beginning_is_not_a_tie_line(parse):
    calls = parse(
        "BEGINNING at a point; thence North 10 degrees East 100 feet to a point; "
        "thence South 10 degrees West 100 feet to the place of beginning, the last mentioned "
        "point is the place of beginning."
    )
    assert [call.is_tie_in for call in calls] == [False, False]


def _kings_highway() -> dict:
    return json.loads(KINGS_HIGHWAY_GT.read_text(encoding="utf-8"))


def _course_fields(call) -> tuple:
    azimuth = call.bearing_azimuth_deg_from_north
    return (
        round(call.distance_ft, 2),
        None if azimuth is None else round(azimuth, 4),
        call.is_tie_in,
        call.is_exception,
    )


@pytest.mark.parametrize("parse", PARSERS)
def test_kings_highway_multi_tract_courses_match_ground_truth(parse):
    gt = _kings_highway()
    calls = parse(gt["expected_legal_description"], strict=True)
    expected = [
        (
            round(c["distance_ft"], 2),
            None
            if c["bearing_azimuth_deg_from_north"] is None
            else round(c["bearing_azimuth_deg_from_north"], 4),
            c["is_tie_in"],
            c["is_exception"],
        )
        for c in gt["expected_calls"]
    ]
    assert [_course_fields(call) for call in calls] == expected


def test_kings_highway_tracts_and_exceptions_match_ground_truth():
    gt = _kings_highway()
    _calls, tracts = package_extract_with_tracts(gt["expected_legal_description"], strict=True)
    assert [(t.label, t.tract_type.value) for t in tracts] == [
        (t["label"], t["tract_type"]) for t in gt["expected_tracts"]
    ]
    assert [len(t.calls) for t in tracts] == [len(t["courses"]) for t in gt["expected_tracts"]]
