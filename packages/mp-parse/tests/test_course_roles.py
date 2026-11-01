"""Round 26: chord phrasings and the role of every bearing + distance pair.

A chord stated in any supported phrasing is recorded as the chord, never as the
tangent. Before complete courses are counted, each bearing + distance pair in a
call fragment is classified: a TIE to a point ("... N 30 E 2 feet from a stone"),
a RECORD call (in parentheses or labelled "per deed"/"(R)") and an ADJOINER line
("which line bears ...") are not boundary courses, so they never make a valid
course fail closed and never replace the measured course. Their wording is never
stripped from the call's along/to fields.
"""

from __future__ import annotations

import pytest
from mp_bearing.azimuth import bearing_to_azimuth
from mp_parse import extract_calls, extract_single_call
from mp_parse.metadata import extract_along_to_fields

POB = "BEGINNING at a point; "
CLOSING = "; THENCE S 45° W 100 feet to the point of beginning."
STRICT = pytest.mark.parametrize("strict", [True, False], ids=["strict", "non-strict"])

# Radius 500, arc 87.27 -> delta 10 deg; chord 87.16 = 2 R sin 5.
CURVE = (
    "THENCE along a curve to the left, having a radius of 500.00 feet, an arc distance "
    "of 87.27 feet {clause} to a point"
)
CHORD_CLAUSES = [
    "and a long chord of N 40° E 87.16 feet",
    "and a chord of N 40° E 87.16 feet",
    ", chord: N 40° E 87.16 feet",
    "(chord = N 40° E 87.16 feet)",
    ", with a chord direction of N 40° E and a chord length of 87.16 feet",
    ", chord direction N 40° E 87.16 feet",
    ", chord brg. N 40° E 87.16 feet",
    ", chord brg N 40° E 87.16 feet",
    ", C.B. N 40° E 87.16 feet",
    ", C. B. N 40° E, 87.16 feet",
    ", a chord which runs N 40° E 87.16 feet",
    ", the chord runs N 40° E 87.16 feet",
]


@STRICT
@pytest.mark.parametrize("clause", CHORD_CLAUSES)
def test_chord_phrasing_records_chord_not_tangent(clause: str, strict: bool) -> None:
    calls, _ = extract_calls(POB + CURVE.format(clause=clause) + CLOSING, strict=strict)
    call = calls[0]
    assert call.chord_bearing is not None, clause
    assert bearing_to_azimuth(call.chord_bearing) == pytest.approx(40.0)
    assert call.chord_length_ft == pytest.approx(87.16)
    # A stated chord is never the tangent.
    assert call.bearing_azimuth_deg_from_north is None
    assert call.arc_length_ft == pytest.approx(87.27)


@pytest.mark.parametrize(
    "text",
    [
        # Words resembling the new chord links, on straight courses.
        "THENCE N 45° E 100 feet along the chord of the old fence",
        "THENCE N 45° E 100 feet to the C.B. Smith line",
        "THENCE N 45° E 100 feet; chord: none stated",
    ],
)
def test_chord_like_wording_on_straight_course_keeps_course(text: str) -> None:
    call = extract_single_call(text.split(";")[0], 1)
    assert call is not None
    assert call.bearing_azimuth_deg_from_north == pytest.approx(45.0)
    assert call.chord_bearing is None


# (fragment, measured azimuth, measured distance, wording kept in along/to). A
# record call between the course and its "to" lies outside both fields (None).
ONE_COURSE_ROWS = {
    "tie-said-pin-being-from": (
        "THENCE S 45° E 100 feet to an iron pin, said pin being N 30° E 2 feet from a stone",
        135.0,
        100.0,
        "N 30° E 2 feet from a stone",
    ),
    "tie-which-is-from-centerline": (
        "THENCE S 45° E 100 feet to a point which is S 89° W 10 feet from the centerline",
        135.0,
        100.0,
        "S 89° W 10 feet from the centerline",
    ),
    "tie-distant-from-monument": (
        "THENCE S 45° E 100 feet to a point distant S 10° W 50 feet from a monument",
        135.0,
        100.0,
        "distant S 10° W 50 feet from a monument",
    ),
    "tie-being-also-from-corner": (
        "THENCE S 45° E 100 feet to a point, being also N 45° W 100 feet from the corner of Lot 7",
        135.0,
        100.0,
        "being also N 45° W 100 feet from the corner of Lot 7",
    ),
    "tie-which-is-stone-existing-case": (
        "THENCE S 45° E 100 feet to a point which is S 10° E 25 feet from a stone",
        135.0,
        100.0,
        "S 10° E 25 feet from a stone",
    ),
    "record-parenthetical-per-deed": (
        "THENCE N 45° E 100 feet (N 45°10' E 100.5 feet per deed) to a point",
        45.0,
        100.0,
        None,
    ),
    "record-parenthetical-deed-label": (
        "THENCE N 45° E 100 feet (deed N 45° 10' E 100.5 feet) to a point",
        45.0,
        100.0,
        None,
    ),
    "record-parenthetical-before-measured": (
        "THENCE (deed N 45° 10' E 100.5 feet) N 45° E 100 feet to a point",
        45.0,
        100.0,
        None,
    ),
    "record-labelled-R": (
        "THENCE N 45° E 100 feet, N 45°10' E 100.5 feet (R), to a point",
        45.0,
        100.0,
        None,
    ),
    "record-labelled-of-record": (
        "THENCE N 45° E 100 feet, being N 45°10' E 100.5 feet of record, to a point",
        45.0,
        100.0,
        None,
    ),
    "adjoiner-which-line-bears": (
        "THENCE N 45° E 100 feet to a point in the line of lands of Smith, which line "
        "bears S 45° E 300 feet",
        45.0,
        100.0,
        "which line bears S 45° E 300 feet",
    ),
    "adjoiner-said-line-bears": (
        "THENCE N 45° E 100 feet to a point in the line of Jones, said line bears S 45° E 300 feet",
        45.0,
        100.0,
        "said line bears S 45° E 300 feet",
    ),
}


@STRICT
@pytest.mark.parametrize("name", sorted(ONE_COURSE_ROWS))
def test_non_boundary_pair_leaves_one_measured_course(name: str, strict: bool) -> None:
    fragment, azimuth, distance, verbatim = ONE_COURSE_ROWS[name]
    calls, _ = extract_calls(POB + fragment + CLOSING, strict=strict)
    assert [c.bearing_azimuth_deg_from_north for c in calls] == [azimuth, 225.0]
    first = calls[0]
    assert first.distance_ft == pytest.approx(distance)
    # along/to are read from the verbatim fragment: tie/record/adjoiner wording is
    # never stripped from them.
    assert (first.along or "", first.to or "") == extract_along_to_fields(fragment)
    if verbatim is not None:
        assert verbatim in f"{first.along} {first.to}", (first.along, first.to, verbatim)


@pytest.mark.parametrize("name", sorted(ONE_COURSE_ROWS))
def test_single_call_keeps_measured_course(name: str) -> None:
    fragment, azimuth, distance, _ = ONE_COURSE_ROWS[name]
    call = extract_single_call(fragment, 1)
    assert call is not None
    assert call.bearing_azimuth_deg_from_north == pytest.approx(azimuth)
    assert call.distance_ft == pytest.approx(distance)


MULTI_COURSE_ROWS = {
    "comma-courses": "THENCE N 45° E 100 feet, S 45° E 100 feet to a pin",
    # 101-111 Kings Highway E (7683-1295): a tie length then a real 158-foot course.
    "kings-highway-parallel-course": (
        "THENCE N 61°5' E partly along said lot 10 feet, more or less, to a point distant "
        "10 feet Northeastwardly from land square measured at right angles and distant 10 "
        "feet S 27°15' E running parallel with the first course and distant 10 feet "
        "Northeastwardly therefrom measured at right angles thereto 158 feet 8 inches to a "
        "point in the aforesaid line"
    ),
    "course-after-from-word": ("THENCE N 45° E 100 feet from the road, S 45° E 100 feet to a pin"),
    "second-course-after-being-word-not-adjacent": (
        "THENCE N 45° E 100 feet to a point being in the line of Smith, S 45° E 100 feet"
    ),
}


@pytest.mark.parametrize("name", sorted(MULTI_COURSE_ROWS))
def test_genuine_multi_course_fragment_fails_closed(name: str) -> None:
    with pytest.raises(ValueError, match="fragment contains multiple courses"):
        extract_calls(POB + MULTI_COURSE_ROWS[name] + CLOSING, strict=True)
