"""Round 20: every length in a curve call is classified by its own label.

A length is stored only under the role the deed labels it with: radius, chord,
tangent (never stored), arc, or the course length (the stated arc when it is the
only one). Several unlabelled course lengths are ambiguous and none is chosen.
Numbered-course headers ("THENCE the following four courses and distances:") are
markers, not courses.
"""

from __future__ import annotations

import pytest
from mp_parse.calls import extract_curve_info as package_curve_info
from mp_parse.calls import extract_single_call as package_single_call

from metesparser.call_extractor import CallExtractor
from tests.fixtures.package_parser import extract_calls as package_extract_calls

CLOSING = "; THENCE due South 50 feet; THENCE due West 50 feet to the point of beginning."


def _via_calls(extract):
    return lambda text: extract(text + CLOSING, strict=True)[0]


def _via_single(extract):
    def parse(text):
        call = extract(text, 1)
        if call is None:
            raise ValueError("no call parsed")
        return call

    return parse


ENTRY_POINTS = {
    "package-calls": _via_calls(package_extract_calls),
    "monolith-calls": _via_calls(CallExtractor.extract_calls),
    "package-single": _via_single(package_single_call),
    "monolith-single": _via_single(CallExtractor.extract_single_call),
}

P = "thence N 80° E along a curve to the right"
RD = " having a radius of 500.00 feet and a central angle of 10°00'00\""
TO = " to a point"
COMPUTED = "computed from radius and delta"
R_DELTA_ARC = 87.2665  # 500 ft * 10 degrees in radians
UNDETERMINED_SPIRAL = "spiral length not stated - course distance not determined"
RAISES = "raises"
REPRO3 = (
    "thence along a curve to the left, the radius point bearing N 10°00'00\" E, "
    "a distance of 87.27 feet" + TO
)

# (id, text, expected). Expected keys: radius, arc, chord, distance (None = not
# stored), notes (substrings required), absent (substrings forbidden).
CASES = [
    # --- arc role -------------------------------------------------------------
    (
        "arc-length-of",
        P + RD + " an arc length of 87.27 feet" + TO,
        {"radius": 500.0, "arc": 87.27, "chord": None, "distance": 87.27, "absent": [COMPUTED]},
    ),
    (
        "arc-distance-of",
        P + RD + ", an arc distance of 87.27 feet" + TO,
        {"radius": 500.0, "arc": 87.27, "chord": None, "distance": 87.27},
    ),
    ("arc-of", P + RD + " and an arc of 87.27 feet" + TO, {"arc": 87.27, "distance": 87.27}),
    (
        "length-of-arc",
        P + RD + ", a length of arc of 87.27 feet" + TO,
        {"arc": 87.27, "distance": 87.27},
    ),
    (
        "distance-along-the-arc",
        P + RD + ", a distance along the arc of 87.27 feet" + TO,
        {"arc": 87.27, "distance": 87.27},
    ),
    ("curve-length", P + RD + ", curve length 87.27 feet" + TO, {"arc": 87.27, "distance": 87.27}),
    (
        "arc-apostrophe-feet",
        P
        + " having a radius of 500.00' and a central angle of 10°00'00\" an arc length of 87.27'"
        + TO,
        {"radius": 500.0, "arc": 87.27, "distance": 87.27},
    ),
    (
        "arc-no-delta",
        P + " having a radius of 500.00 feet, an arc length of 87.27 feet" + TO,
        {"radius": 500.0, "arc": 87.27, "chord": None, "distance": 87.27},
    ),
    (
        "arc-wins-over-extra-unlabelled",
        P + RD + ", an arc length of 87.27 feet, 90.00 feet" + TO,
        {"arc": 87.27, "distance": 87.27},
    ),
    # --- course length (fc75587: a single course length is the stated arc) -----
    (
        "course-distance-of",
        P + RD + " a distance of 87.30 feet" + TO,
        {"radius": 500.0, "arc": 87.30, "chord": None, "distance": 87.30, "absent": [COMPUTED]},
    ),
    ("course-bare", P + RD + ", 87.27 feet" + TO, {"arc": 87.27, "distance": 87.27}),
    (
        "course-word-bearing",
        "thence North 80 degrees 00 minutes East along a curve to the right"
        + RD
        + ", 87.27 feet"
        + TO,
        {"radius": 500.0, "arc": 87.27, "distance": 87.27},
    ),
    (
        "course-compound-units",
        P + RD + " a distance of 1 chain and 21 links" + TO,
        {"arc": 79.86, "distance": 79.86},
    ),
    (
        "no-length-computed",
        P + RD + TO,
        {"radius": 500.0, "arc": None, "chord": None, "distance": R_DELTA_ARC, "notes": [COMPUTED]},
    ),
    # --- chord role -----------------------------------------------------------
    (
        "repro1-chord-distance",
        P + RD + " a chord distance of 87.16 feet" + TO,
        {
            "radius": 500.0,
            "arc": None,
            "chord": 87.16,
            "distance": R_DELTA_ARC,
            "notes": [COMPUTED],
        },
    ),
    (
        "chord-length-and-course",
        P + RD + ", a chord length of 87.16 feet and a distance of 87.27 feet" + TO,
        {"arc": 87.27, "chord": 87.16, "distance": 87.27},
    ),
    (
        "long-chord",
        P + RD + ", a long chord of 87.16 feet" + TO,
        {"arc": None, "chord": 87.16, "distance": R_DELTA_ARC, "notes": [COMPUTED]},
    ),
    (
        "chord-bearing-then-length",
        P + RD + ", a chord bearing N 85° E 87.16 feet, an arc length of 87.27 feet" + TO,
        {"arc": 87.27, "chord": 87.16, "distance": 87.27},
    ),
    (
        "chord-bears-distance-of",
        P + RD + ", a chord which bears N 85° E, a distance of 87.16 feet" + TO,
        {"arc": None, "chord": 87.16, "distance": R_DELTA_ARC, "notes": [COMPUTED]},
    ),
    (
        "chord-lead-length",
        P + RD + ", a chord of 87.16 feet bearing N 85° E, and an arc length of 87.27 feet" + TO,
        {"arc": 87.27, "chord": 87.16, "distance": 87.27},
    ),
    (
        "chord-only-positioned (5d3711f)",
        "thence along a curve to the right with a radius of 500.00 feet, a chord bearing "
        "N 85° E 87.16 feet" + TO,
        {"radius": 500.0, "arc": None, "chord": 87.16, "distance": 87.16},
    ),
    # --- tangent role (never stored) -------------------------------------------
    (
        "repro2-tangent-bare",
        P + ", radius 500.00 feet, delta 10°00'00\", tangent 43.74 feet, 87.27 feet" + TO,
        {"radius": 500.0, "arc": 87.27, "chord": None, "distance": 87.27},
    ),
    (
        "tangent-length-of",
        P + RD + ", a tangent length of 43.74 feet and an arc length of 87.27 feet" + TO,
        {"arc": 87.27, "chord": None, "distance": 87.27},
    ),
    (
        "tangent-only",
        P + RD + ", tangent 43.74 feet" + TO,
        {"arc": None, "chord": None, "distance": R_DELTA_ARC, "notes": [COMPUTED]},
    ),
    (
        "tangent-distance-then-bare",
        P + RD + ", tangent distance of 43.74 feet, 87.27 feet" + TO,
        {"arc": 87.27, "distance": 87.27},
    ),
    # --- radius role / radial clauses ------------------------------------------
    # No radius is stated, so the curve is not computable (never radius = 87.27).
    ("repro3-radial-distance-of-no-radius", REPRO3, RAISES),
    (
        "repro3-radial-distance-of-stated-radius",
        "thence along a curve to the left having a radius of 500.00 feet, the radius point "
        "bearing N 10°00'00\" E, a distance of 87.27 feet" + TO,
        {"radius": 500.0, "arc": 87.27, "distance": 87.27, "absent": ["conflict"]},
    ),
    (
        "radial-distance-of-no-comma",
        P + RD + ", radius point bears N 10° E a distance of 87.27 feet" + TO,
        {"radius": 500.0, "arc": 87.27, "distance": 87.27, "absent": ["conflict"]},
    ),
    (
        "radial-comma-bare-is-course",
        P + RD + ", radius point bears N 10° E, 87.27 feet" + TO,
        {"radius": 500.0, "arc": 87.27, "distance": 87.27, "absent": ["conflict"]},
    ),
    (
        "radial-length-is-radius (de08631)",
        "thence along a non-tangent curve to the right, radius point bears N 10° E 500.00 feet, "
        "an arc length of 100.00 feet" + TO,
        {"radius": 500.0, "arc": 100.0, "distance": 100.0},
    ),
    (
        "radial-conflict (de08631)",
        "thence along a non-tangent curve to the right with a radius of 400.00 feet, radius point "
        "bears N 10° E 500.00 feet, an arc length of 100.00 feet" + TO,
        {"radius": 400.0, "arc": 100.0, "distance": 100.0, "notes": ["radius conflict"]},
    ),
    (
        "center-point-element (fc75587)",
        P + RD + " the center point being 500.00 feet away a distance of 100.00 feet" + TO,
        {"radius": 500.0, "arc": 100.0, "distance": 100.0},
    ),
    (
        "center-of-curve-bearing (fc75587)",
        P
        + RD
        + " the center of said curve bearing N 10° E 500.00 feet a distance of 100.00 feet"
        + TO,
        {"radius": 500.0, "arc": 100.0, "distance": 100.0},
    ),
    # --- ambiguous course lengths ----------------------------------------------
    (
        "ambiguous-two-bare",
        P + RD + ", 87.27 feet, 90.00 feet" + TO,
        {
            "radius": 500.0,
            "arc": None,
            "chord": None,
            "distance": R_DELTA_ARC,
            "notes": [COMPUTED, "curve length ambiguous: 87.27 feet, 90.00 feet"],
        },
    ),
    (
        "ambiguous-distance-of-and-bare",
        P + RD + ", a distance of 87.27 feet, 90.00 feet" + TO,
        {
            "arc": None,
            "distance": R_DELTA_ARC,
            "notes": [COMPUTED, "curve length ambiguous: 87.27 feet, 90.00 feet"],
        },
    ),
    ("ambiguous-without-radius-delta", P + ", 87.27 feet, 90.00 feet" + TO, RAISES),
    # --- spiral (5d3711f) ------------------------------------------------------
    (
        "spiral-without-length",
        "thence N 80° E along a spiral curve to the right having a radius of 1000.00 feet and a "
        "delta angle of 10°00'00\"" + TO,
        {"radius": 1000.0, "arc": None, "distance": None, "notes": [UNDETERMINED_SPIRAL]},
    ),
]


def _approx(value):
    return None if value is None else pytest.approx(value, abs=1e-3)


@pytest.mark.parametrize("entry", sorted(ENTRY_POINTS))
@pytest.mark.parametrize(("text", "expected"), [c[1:] for c in CASES], ids=[c[0] for c in CASES])
def test_curve_length_roles(entry, text, expected):
    parse = ENTRY_POINTS[entry]
    if expected == RAISES:
        with pytest.raises(ValueError):
            parse(text)
        return
    call = parse(text)
    fields = {
        "radius": call.radius_ft,
        "arc": call.arc_length_ft,
        "chord": call.chord_length_ft,
        "distance": call.distance_ft,
    }
    for key, actual in fields.items():
        if key in expected:
            assert actual == _approx(expected[key]), key
    notes = call.notes or ""
    for fragment in expected.get("notes", []):
        assert fragment in notes
    for fragment in expected.get("absent", []):
        assert fragment not in notes


@pytest.mark.parametrize(
    "curve_info",
    [package_curve_info, CallExtractor.extract_curve_info],
    ids=["package", "monolith"],
)
def test_radial_distance_of_is_never_the_radius(curve_info):
    info = curve_info(REPRO3)
    assert info.get("radius_ft") is None
    assert info["radial_bearing"] == "N 10°00'00\" E"
    assert info.get("arc_length_ft") is None


def test_case_table_is_large_enough():
    assert len(CASES) >= 30


# --- numbered-course headers ----------------------------------------------------

COURSES = (
    "(1) North 10 degrees East 100.00 feet to a point;\n"
    "(2) South 80 degrees East 50.00 feet to a point;\n"
    "(3) South 10 degrees West 100.00 feet to a point;\n"
    "(4) North 80 degrees West 50.00 feet to the point and place of BEGINNING."
)
HEADERS = [
    "THENCE the following four courses and distances:",
    "THENCE the following 4 courses and distances:",
    "THENCE the following four (4) courses and distances:",
    "THENCE the following courses and distances:",
    "THENCE by the following courses and distances:",
    "THENCE by the following four courses and distances;",
    "THENCE the following four courses:",
    "THENCE along the line of lands now or formerly of Smith, the following four courses "
    "and distances;",
    "THENCE:",
]
EXTRACTORS = {
    "package": package_extract_calls,
    "monolith": CallExtractor.extract_calls,
}


@pytest.mark.parametrize("impl", sorted(EXTRACTORS))
@pytest.mark.parametrize("strict", [True, False], ids=["strict", "non-strict"])
@pytest.mark.parametrize("header", HEADERS)
def test_following_courses_header_is_a_marker(impl, strict, header):
    text = "BEGINNING at a point in the Northerly line of Main Street;\n" + header + "\n" + COURSES
    skipped: list = []
    calls = EXTRACTORS[impl](text, strict=strict, skipped_courses=skipped)
    assert [c.course for c in calls] == [1, 2, 3, 4]
    assert [c.distance_ft for c in calls] == [100.0, 50.0, 100.0, 50.0]
    assert skipped == []


@pytest.mark.parametrize("impl", sorted(EXTRACTORS))
def test_skipped_course_after_header_keeps_deed_numbering(impl):
    text = (
        "BEGINNING at a point;\nTHENCE the following four courses and distances:\n"
        + COURSES.replace("South 80 degrees East 50.00 feet", "along the fence to a stake")
    )
    skipped: list = []
    calls = EXTRACTORS[impl](text, strict=False, skipped_courses=skipped)
    assert [c.course for c in calls] == [1, 3, 4]
    assert [(s.course, s.source_course) for s in skipped] == [(2, 2)]


@pytest.mark.parametrize("impl", sorted(EXTRACTORS))
def test_course_mentioning_following_is_still_a_course(impl):
    text = (
        "BEGINNING at a point;\nTHENCE the following two courses and distances:\n"
        "(1) North 10 degrees East 100.00 feet following the fence to a point;\n"
        "(2) South 10 degrees West 100.00 feet to the point of BEGINNING."
    )
    calls = EXTRACTORS[impl](text, strict=True)
    assert [c.course for c in calls] == [1, 2]
