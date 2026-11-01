from __future__ import annotations

import json
from pathlib import Path

import pytest
from mp_parse import extract_calls as package_extract_with_tracts

from metesparser.call_extractor import CallExtractor
from tests.fixtures.package_parser import extract_calls as package_extract_calls

PARSERS = (package_extract_calls, CallExtractor.extract_calls)

SAMPLE_DEEDS = Path(__file__).resolve().parents[2] / "sample_deeds"
# Both recorded deeds carry the same legal-description rider.
KINGS_HIGHWAY_GTS = (
    SAMPLE_DEEDS / "101-111 Kings Highway E - Deed Image (7683 - 1295).ground_truth.json",
    SAMPLE_DEEDS / "101-111 Kings Highway E - Deed Image (11030 - 763).ground_truth.json",
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


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _printed_azimuth(course: dict) -> float | None:
    """The azimuth as the deed prints it; parsers read the print, not a corrected misprint."""
    azimuth = course.get(
        "printed_bearing_azimuth_deg_from_north", course["bearing_azimuth_deg_from_north"]
    )
    return None if azimuth is None else round(azimuth, 4)


def _course_fields(call) -> tuple:
    azimuth = call.bearing_azimuth_deg_from_north
    return (
        round(call.distance_ft, 2),
        None if azimuth is None else round(azimuth, 4),
        call.is_tie_in,
        call.is_exception,
    )


@pytest.mark.parametrize("gt_path", KINGS_HIGHWAY_GTS, ids=lambda p: p.stem)
@pytest.mark.parametrize("parse", PARSERS)
def test_kings_highway_multi_tract_courses_match_ground_truth(parse, gt_path):
    gt = _load(gt_path)
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


@pytest.mark.parametrize("gt_path", KINGS_HIGHWAY_GTS, ids=lambda p: p.stem)
def test_kings_highway_tracts_and_exceptions_match_ground_truth(gt_path):
    gt = _load(gt_path)
    calls, tracts = package_extract_with_tracts(gt["expected_legal_description"], strict=True)
    # Exceptions described inside a marked tract are that tract's flagged courses.
    boundary = [t for t in gt["expected_tracts"] if t["tract_type"] != "exception"]
    excepted = [t for t in gt["expected_tracts"] if t["tract_type"] == "exception"]
    assert [(t.label, t.tract_type.value) for t in tracts] == [
        (t["label"], t["tract_type"]) for t in boundary
    ]
    assert [sum(not c.is_exception for c in t.calls) for t in tracts] == [
        len(t["courses"]) for t in boundary
    ]
    assert sum(c.is_exception for c in calls) == sum(len(t["courses"]) for t in excepted)


_LETTERED_THEN_EASEMENT = (
    "BEGINNING at a point, proceeding thence\n\n"
    "(a) North 50 degrees 45 minutes 00 seconds East, a distance of 416.57 feet; thence\n\n"
    "(b) South 32 degrees 36 minutes 00 seconds East, a distance of 300.07 feet to the "
    "point and place of BEGINNING.\n\n"
    "UNDER AND SUBJECT to an easement bounded and described as follows:\n\n"
    "BEGINNING at a point, proceeding thence\n\n"
    "(1) North 56 degrees 44 minutes 05 seconds East, a distance of 140.00 feet; thence\n\n"
    "(2) North 32 degrees 36 minutes 00 seconds West, a distance of 35.00 feet to the "
    "point and place of BEGINNING."
)


@pytest.mark.parametrize("parse", PARSERS)
def test_lettered_courses_split_before_numbered_courses(parse):
    # The easement's own courses are never boundary courses.
    calls = parse(_LETTERED_THEN_EASEMENT)
    assert [call.distance_ft for call in calls] == [416.57, 300.07]


def test_lettered_courses_and_numbered_easement_courses_are_both_read():
    _calls, tracts = package_extract_with_tracts(_LETTERED_THEN_EASEMENT)
    assert [(t.tract_type.value, [c.distance_ft for c in t.calls]) for t in tracts] == [
        ("main", [416.57, 300.07]),
        ("easement", [140.00, 35.00]),
    ]


@pytest.mark.parametrize("parse", PARSERS)
def test_schedules_split_thence_courses_from_numbered_courses(parse):
    calls = parse(
        "SCHEDULE A-1\n\nBeginning at a point; thence "
        "North 40 Degrees 41 Minutes 31 Seconds East a distance of 223.65 feet to a point "
        "and extending thence;\n\n"
        "South 59 Degrees 29 Minutes 19 Seconds East a distance of 250.44 feet to point and "
        "place of beginning.\n\n"
        "SCHEDULE A-2\n\nBEGINNING at a point, proceeding thence\n\n"
        "(1) North 56 degrees 44 minutes 05 seconds East, a distance of 140.00 feet; thence\n\n"
        "(2) North 32 degrees 36 minutes 00 seconds West, a distance of 35.00 feet to the "
        "point and place of BEGINNING."
    )
    assert [call.distance_ft for call in calls] == [223.65, 250.44, 140.00, 35.00]


BERLIN_12799_GT = SAMPLE_DEEDS / "219 Berlin Rd - Deed Image (12799 - 00118).ground_truth.json"


@pytest.mark.parametrize("key", ["expected_legal_description", "expected_normalized_text"])
@pytest.mark.parametrize("parse", PARSERS)
def test_berlin_schedules_match_ground_truth(parse, key):
    gt = _load(BERLIN_12799_GT)
    calls = parse(gt[key], strict=True)
    expected = [
        (round(c["distance_ft"], 2), _printed_azimuth(c), c["is_tie_in"])
        for c in gt["expected_calls"]
    ]
    assert [_course_fields(call)[:3] for call in calls] == expected


def test_berlin_schedules_are_tracts():
    gt = _load(BERLIN_12799_GT)
    _calls, tracts = package_extract_with_tracts(gt["expected_legal_description"], strict=True)
    assert [(t.label, len(t.calls)) for t in tracts] == [
        ("Schedule A-1", 6),
        ("Schedule A-2", 16),
        ("Schedule A-3", 4),
        ("Schedule A-4", 4),
    ]


@pytest.mark.parametrize("parse", PARSERS)
def test_course_ending_in_thence_after_preamble_is_kept_and_counted_tie_courses_flagged(parse):
    calls = parse(
        "Beginning at a point in the Northwesterly Line of White Horse Road said point being "
        "the following two courses and distances from the intersection of White Horse Road "
        "with Burnt Mill Road.\n\n"
        "North 40 Degrees 41 Minutes 31 Seconds East a distance of 483.13 feet to a point "
        "thence;\n\n"
        "North 59 Degrees 29 Minutes 19 Seconds West a distance of 17.78 feet to a point "
        "thence;\n\n"
        "North 40 Degrees 41 Minutes 31 Seconds East a distance of 223.65 feet to a point and "
        "extending thence;\n\n"
        "South 59 Degrees 29 Minutes 19 Seconds East a distance of 250.44 feet to point and "
        "place of beginning."
    )
    assert [(call.distance_ft, call.is_tie_in) for call in calls] == [
        (483.13, True),
        (17.78, True),
        (223.65, False),
        (250.44, False),
    ]


@pytest.mark.parametrize("parse", PARSERS)
def test_preamble_offset_is_not_a_course(parse):
    calls = parse(
        "BEGINNING at a point in the Northerly line of Main Street distant 100 feet "
        "Westerly from Elm Street; thence North 10 degrees East 50 feet; thence South 10 "
        "degrees West 50 feet to the place of beginning."
    )
    assert [call.distance_ft for call in calls] == [50, 50]


BERLIN_12941_GT = SAMPLE_DEEDS / "219 Berlin Rd - Deed Image (12941 - 00156).ground_truth.json"


@pytest.mark.parametrize("key", ["expected_legal_description", "expected_normalized_text"])
@pytest.mark.parametrize("parse", PARSERS)
def test_berlin_exhibit_a_matches_ground_truth(parse, key):
    """12941-00156: two lots whose preambles end "proceeding thence:"."""
    gt = _load(BERLIN_12941_GT)
    calls = parse(gt[key], strict=True)
    expected = [(round(c["distance_ft"], 2), _printed_azimuth(c)) for c in gt["expected_calls"]]
    assert [_course_fields(call)[:2] for call in calls] == expected


def test_berlin_exhibit_a_lots_are_tracts():
    gt = _load(BERLIN_12941_GT)
    _calls, tracts = package_extract_with_tracts(gt["expected_legal_description"], strict=True)
    assert [len(t.calls) for t in tracts] == [
        sum(c["tract"] == lot for c in gt["expected_calls"]) for lot in ("Lot 17", "Lot 22")
    ]


@pytest.mark.parametrize("parse", PARSERS)
def test_curve_turning_towards_the_left_is_a_curve(parse):
    call = parse(
        "BEGINNING at a stake; thence Northwestwardly an arc distance of 182.19 feet along a "
        "curve of radius 4173.79 feet turning towards the left, to a point",
        strict=True,
    )[0]
    assert str(getattr(call.curve_dir, "value", call.curve_dir)) == "left"
    assert call.radius_ft == pytest.approx(4173.79)
    assert call.arc_length_ft == pytest.approx(182.19)


@pytest.mark.parametrize("parse", PARSERS)
def test_thence_from_the_beginning_point_before_numbered_courses(parse):
    calls = parse(
        "BEGINNING at a point in the northerly line of Redman Avenue; thence from the "
        "beginning point;\n\n(1) South 49 degrees 14 minutes West, 7.44 feet; thence\n\n"
        "(2) North 49 degrees 13 minutes 55 seconds East, 5.49 feet to the point of beginning.",
        strict=True,
    )
    assert [call.distance_ft for call in calls] == [7.44, 5.49]


REDMAN_GT = SAMPLE_DEEDS / "15 E Redman Ave - Deed Image (04462 - 00144).ground_truth.json"


@pytest.mark.parametrize("key", ["expected_legal_description", "expected_normalized_text"])
@pytest.mark.parametrize("parse", PARSERS)
def test_redman_main_tract_and_exception_match_ground_truth(parse, key):
    gt = _load(REDMAN_GT)
    calls = parse(gt[key], strict=True)
    expected = [
        (
            # The deed prints "7144 feet" and "33191 feet"; parsers read the printed value
            c.get("printed_distance_ft", c["distance_ft"]),
            None
            if c["bearing_azimuth_deg_from_north"] is None
            else round(c["bearing_azimuth_deg_from_north"], 4),
            c["radius_ft"],
            c["is_exception"],
        )
        for c in gt["expected_calls"]
    ]
    assert [
        (round(c.distance_ft, 2), _course_fields(c)[1], c.radius_ft, c.is_exception) for c in calls
    ] == expected


@pytest.mark.parametrize("parse", PARSERS)
@pytest.mark.parametrize(
    "curve_text",
    [
        "curving to the right having a radius of 565.45 feet, an arc distance of 304.57 feet",
        "curving to the right with a radius of 565.45 feet, an arc distance of 304.57 feet",
    ],
)
def test_curving_to_the_right_is_a_curve_not_a_radius_length(parse, curve_text):
    call = parse(
        "BEGINNING at a point; thence in a Northeastwardly direction along the curved line of "
        f"Euclid Avenue, {curve_text} to a set iron pin",
        strict=True,
    )[0]
    assert str(getattr(call.curve_dir, "value", call.curve_dir)) == "right"
    assert call.radius_ft == pytest.approx(565.45)
    assert call.distance_ft == pytest.approx(304.57)
    assert call.bearing_azimuth_deg_from_north is None


def _curve_fields(call) -> tuple:
    return (
        round(call.distance_ft, 2),
        _course_fields(call)[1],
        getattr(call.curve_dir, "value", call.curve_dir),
        call.radius_ft,
        call.arc_length_ft,
    )


def _expected_curve_fields(gt: dict) -> list[tuple]:
    # Parsers read a misprinted course as printed ("printed_distance_ft").
    return [
        (
            c.get("printed_distance_ft", c["distance_ft"]),
            None
            if c["bearing_azimuth_deg_from_north"] is None
            else round(c["bearing_azimuth_deg_from_north"], 4),
            c["curve_dir"],
            c["radius_ft"],
            c["arc_length_ft"],
        )
        for c in gt["expected_calls"]
    ]


@pytest.mark.parametrize(
    "deed",
    [
        "One Centennial Square - Deed Image (9528 - 156)",
        "89 Haddon Ave - Deed Image (4732 - 544)",
    ],
)
@pytest.mark.parametrize("key", ["expected_legal_description", "expected_normalized_text"])
@pytest.mark.parametrize("parse", PARSERS)
def test_curving_deeds_match_ground_truth(parse, key, deed):
    gt = _load(SAMPLE_DEEDS / f"{deed}.ground_truth.json")
    calls = parse(gt[key], strict=True)
    assert [_curve_fields(call) for call in calls] == _expected_curve_fields(gt)


@pytest.mark.parametrize("parse", PARSERS)
def test_following_courses_introduction_is_not_a_course(parse):
    calls = parse(
        "BEGINNING at a point; thence (1) South 19 degrees 58 minutes 30 seconds West, a "
        "distance of 146.44 feet to a found field stone; thence along the line of lands now or "
        "formerly of Oscar Hinski and wife, the following two courses and distances; thence "
        "(2) North 34 degrees 42 minutes 30 seconds West, a distance of 53.75 feet to a point; "
        "thence (3) South 53 degrees 41 minutes 15 seconds West, a distance of 310.45 feet to "
        "the point of beginning.",
        strict=True,
    )
    assert [call.distance_ft for call in calls] == [146.44, 53.75, 310.45]


KRESSON_EXCEPTION = (
    "BEGINNING at a point along a line common with Lot 13A, said point being the following "
    "courses and distances from the intersection of Willard Avenue with Kresson Road\n\n"
    "(A) Along the said row line of Kresson Road North 73 degrees 30 minutes 00 seconds West a "
    "distance of 509.1 feet to a point common to said Lots 13 and 13B, thence;\n\n"
    "(B) Along line common to said Lots 13 and 13A South 16 degrees 30 minutes 00 seconds West a "
    "distance of 27.00 feet to a point and place of beginning, thence;\n\n"
    "(1) South 73 degrees 30 minutes 00 seconds East a distance of 10.00 feet to a point, thence;\n\n"
    "(2) North 16 degrees 30 minutes 00 seconds East a distance of 47.00 feet to a point and "
    "place of BEGINNING."
)


@pytest.mark.parametrize("parse", PARSERS)
def test_uncounted_lettered_tie_courses_are_kept_and_flagged(parse):
    calls = parse(KRESSON_EXCEPTION, strict=True)
    assert [(call.distance_ft, call.is_tie_in) for call in calls] == [
        (509.1, True),
        (27.0, True),
        (10.0, False),
        (47.0, False),
    ]


KRESSON_GT = SAMPLE_DEEDS / "36 Kresson Rd - Deed Image (9476 - 462).ground_truth.json"
KRESSON_GTS = (
    KRESSON_GT,
    SAMPLE_DEEDS / "36 Kresson Rd - Deed Image (9888 - 954).ground_truth.json",
    SAMPLE_DEEDS / "36 Kresson Rd - Deed Image (12006 - 01795).ground_truth.json",
)


@pytest.mark.parametrize("gt_path", KRESSON_GTS, ids=lambda p: p.stem)
@pytest.mark.parametrize("key", ["expected_legal_description", "expected_normalized_text"])
@pytest.mark.parametrize("parse", PARSERS)
def test_kresson_exception_with_tie_courses_matches_ground_truth(parse, key, gt_path):
    gt = _load(gt_path)
    calls = parse(gt[key], strict=True)
    expected = [
        (
            # Tract 1 course 1 is printed 217.14 ft (recorded as 317.14); parsers read the print
            round(c.get("printed_distance_ft", c["distance_ft"]), 2),
            round(c["bearing_azimuth_deg_from_north"], 4),
            c["is_tie_in"],
            c.get("is_exception", False),
        )
        for c in gt["expected_calls"]
    ]
    assert [_course_fields(call) for call in calls] == expected


def test_kresson_exception_is_one_tract():
    gt = _load(KRESSON_GT)
    _calls, tracts = package_extract_with_tracts(gt["expected_legal_description"], strict=True)
    assert [(t.label, len(t.calls)) for t in tracts] == [("Tract 1", 4), ("Exception 1", 6)]


CHEWS_LANDING_GTS = tuple(
    SAMPLE_DEEDS / f"26 Chews Landing Rd - Deed Image ({deed}).ground_truth.json"
    for deed in (
        "5056 - 813",
        "7797 - 967",
        "7797 - 972",
        "8566 - 200",
        "8566 - 209",
        "9701 - 296",
        "10965 - 1948",
    )
)


@pytest.mark.parametrize("gt_path", CHEWS_LANDING_GTS, ids=lambda p: p.stem)
@pytest.mark.parametrize("key", ["expected_legal_description", "expected_normalized_text"])
@pytest.mark.parametrize("parse", PARSERS)
def test_chews_landing_parsers_read_printed_values(parse, key, gt_path):
    """Misprinted courses record intended values; parsers read what the deed prints."""
    gt = _load(gt_path)
    calls = parse(gt[key], strict=True)
    expected = [
        (
            c.get("printed_distance_ft", c["distance_ft"]),
            round(
                c.get(
                    "printed_bearing_azimuth_deg_from_north", c["bearing_azimuth_deg_from_north"]
                ),
                4,
            ),
        )
        for c in gt["expected_calls"]
    ]
    assert [_course_fields(call)[:2] for call in calls] == expected


@pytest.mark.parametrize("parse", PARSERS)
def test_preamble_before_numbered_courses_without_thence_is_not_a_course(parse):
    calls = parse(
        "BEGINNING at a point in the northeasterly line of Pennbrook Drive, 50' wide, a distance "
        "of 310.00 feet southeastwardly from a point in the southeasterly line of Greenmount "
        "Road, bounded and described as follows:\n\n"
        "1. S 71°53'10\" E along Pennbrook Drive, a distance of 23.67 feet to an angle point;\n\n"
        "2. N 87°07'30\" E along Pennbrook Drive, a distance of 125.26 feet to the point and "
        "place of beginning.",
        strict=True,
    )
    assert [call.distance_ft for call in calls] == [23.67, 125.26]


PENNBROOK_NORMALIZED_GTS = tuple(
    SAMPLE_DEEDS / f"{deed}.ground_truth.json"
    for deed in (
        "31 Pennbrook Dr - Deed Image (10989 - 916)",
        "31 Pennbrook Dr - Deed Image (11191 - 01716)",
        "24 Pennbrook Dr - Deed Image (11793 - 00217)",
    )
)


@pytest.mark.parametrize("gt_path", PENNBROOK_NORMALIZED_GTS, ids=lambda p: p.stem)
@pytest.mark.parametrize("parse", PARSERS)
def test_pennbrook_normalized_text_has_no_preamble_course(parse, gt_path):
    gt = _load(gt_path)
    calls = parse(gt["expected_normalized_text"], strict=False)
    assert [call.distance_ft for call in calls] == [c["distance_ft"] for c in gt["expected_calls"]]


@pytest.mark.parametrize("parse", PARSERS)
def test_two_digit_decimal_comma_is_a_decimal_point(parse):
    """219 Berlin 12799-00118 prints "a distance of 300,07 feet"; it is not 30,007 feet."""
    calls = parse(
        "BEGINNING at a point; thence (a) North 50 degrees 45 minutes 00 seconds East, a distance "
        "of 416.57 feet; thence\n\n(b) South 32 degrees 36 minutes 00 seconds East, a distance of "
        "300,07 feet to a point; thence\n\n(c) North 32 degrees 36 minutes 00 seconds West, a "
        "distance of 1,200.50 feet to the point of beginning.",
        strict=True,
    )
    assert [call.distance_ft for call in calls] == [416.57, 300.07, 1200.5]


@pytest.mark.parametrize("parse", PARSERS)
def test_numbered_courses_before_the_first_thence_are_kept(parse):
    """8 Kings Highway W 7489-772: course (1) ends with ";" and "thence" first follows (2)."""
    calls = parse(
        "BEGINNING at a point in the Northeasterly line of Lot 10, Block 76 and running;\n\n"
        "(1) Along said Northeasterly line of Lot 10, Block 76, North 32 degrees 22 minutes "
        "34 seconds West, 41.23 feet to a point in same;\n\n"
        "(2) Along the common line of Lots 12.12 and 12.13, Block 76, North 61 degrees 11 "
        "minutes 34 seconds East, 82.47 feet to a point; thence\n\n"
        "(3) Along said Southeasterly line of Lot 12.07, South 28 degrees 36 minutes 51 seconds "
        "East, 36.73 feet to a point; thence\n\n"
        "(4) Along said Northerly line of Lot 13, South 58 degrees 01 minutes 30 seconds West, "
        "79.90 feet, to the point and place of BEGINNING.",
        strict=True,
    )
    assert [call.distance_ft for call in calls] == pytest.approx([41.23, 82.47, 36.73, 79.90])


@pytest.mark.parametrize("parse", PARSERS)
@pytest.mark.parametrize(
    ("heading", "second"), [("Tract #1", "Tract #2"), ("PARCEL A:", "PARCEL B:")]
)
def test_tract_heading_ends_the_previous_tracts_courses(parse, heading, second):
    """15 E Euclid: Tract 1's last course is not merged into Tract 2's numbered courses."""
    calls = parse(
        f"{heading}\n\nBeginning in the Northwesterly line of Euclid Avenue; thence Southwestwardly "
        "along the Northwesterly line of Euclid Avenue 80 feet in width or breadth; thence "
        "Northwestwardly between parallel lines, parallel with Turnley Avenue 142 feet in length "
        f"or depth.\n\n{second}\n\nBeginning at a point on the Northerly line of Euclid Avenue; "
        "and extends thence\n\n1.  Westwardly along said Northerly line of Euclid Avenue the "
        "distance of 10 feet to a point; and extends thence\n\n2.  Northwardly the distance of "
        "142 feet to a point; and extends thence\n\n3.  Eastwardly the distance of 10 feet to a "
        "point; and extends thence\n\n4.  Southwardly the distance of 142 feet to the place of "
        "beginning."
    )
    assert [call.distance_ft for call in calls] == pytest.approx([80, 142, 10, 142, 10, 142])


@pytest.mark.parametrize("parse", PARSERS)
def test_lot_reference_without_courses_has_no_calls_in_strict_mode(parse):
    """101-111 Kings Highway E 11353-01989: "Kings Highway East" is not a course."""
    calls = parse(
        "BEING Lot 1.01, Block 21 on the tax map of the Borough of Haddonfield.\n\n"
        "BEING commonly known as 101-111 Kings Highway East, Haddonfield, New Jersey 08033.",
        strict=True,
    )
    assert calls == []


@pytest.mark.parametrize("parse", PARSERS)
def test_bearing_without_distance_is_still_malformed_in_strict_mode(parse):
    with pytest.raises(ValueError, match="Malformed course"):
        parse("North 45 degrees 30 minutes East to the corner of Lot 7", strict=True)


@pytest.mark.parametrize("parse", PARSERS)
def test_two_tie_courses_in_one_sentence_pair_before_numbered_courses(parse):
    """1 Walnut St 12420-00902 Tract No. 3: "...122.55 feet to a point. South 18 degrees..."."""
    calls = parse(
        "BEGINNING at a point which is located at the following two courses and distances from "
        "the intersection of the Southwesterly line of Ellis Street with the Southeasterly line of "
        "Walnut Street; thence\n\nSouth 71 degrees 54 minutes 50 seconds East along the "
        "Southwesterly line of Ellis Street 122.55 feet to a point. South 18 degrees 05 minutes 10 "
        "seconds West 123.00 feet to the point and place of beginning; thence\n\n(1) South 18 "
        "degrees 05 minutes 10 seconds West 82.00 feet to a point; thence\n\n(2) North 71 degrees "
        "54 minutes 50 seconds West 53.36 feet to a point; thence\n\n(3) North 18 degrees 17 "
        "minutes 22 seconds East 82.00 feet to a point; thence\n\n(4) South 71 degrees 54 minutes "
        "50 seconds East 53.19 feet to the point and place of beginning.",
        strict=True,
    )
    assert [call.distance_ft for call in calls] == pytest.approx(
        [122.55, 123.0, 82.0, 53.36, 82.0, 53.19]
    )
    assert [call.is_tie_in for call in calls] == [True, True, False, False, False, False]
