"""PR #60 round 6: the curve tangent comes only from boundary course text.

Chord, radial, radius-point and center-point bearings are removed before the
course bearing is extracted, so the chord bearing can only ever reach
``chord_bearing`` (or derive a disclosed tangent). Each case runs through the
package and monolith, both via ``extract_calls`` (normalized) and directly via
``extract_single_call`` (raw text).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pytest
from mp_parse.calls import extract_single_call as package_single_call
from mp_parse.normalizer import normalize_legal_description as package_normalize

from metesparser.call_extractor import CallExtractor
from metesparser.text_parser import TextParser
from tests.fixtures.package_parser import extract_calls as package_extract_calls

CLOSING = "; THENCE due South 50 feet; THENCE due West 50 feet to the point of beginning."


def _via_calls(extract):
    def parse(text: str):
        return extract(text + CLOSING, strict=True)[0]

    return parse


def _via_single(extract):
    def parse(text: str):
        return extract(text, 1)

    return parse


ENTRY_POINTS = {
    "package-calls": _via_calls(package_extract_calls),
    "monolith-calls": _via_calls(CallExtractor.extract_calls),
    "package-single": _via_single(package_single_call),
    "monolith-single": _via_single(CallExtractor.extract_single_call),
}

DERIVED = "tangent bearing derived from chord bearing and delta"
FROM_ARC = "delta computed from arc length and radius"
FROM_CHORD = "delta computed from chord length and radius"
ARC_FROM_CHORD = "arc length computed from chord length and radius"
CHORD_ONLY = "tangent bearing not stated - chord bearing only"


@dataclass(frozen=True)
class Case:
    text: str
    azimuth: float | None = None
    quadrant: str | None = None
    chord_bearing: str | None = None
    delta_deg: float | None = None
    arc_length_ft: float | None = None
    notes_in: tuple[str, ...] = ()
    notes_out: tuple[str, ...] = ()
    raises: bool = False
    tol: float = 1e-6
    extra: dict = field(default_factory=dict)


# Shared geometry -----------------------------------------------------------
ARC_CHORD = (
    "THENCE along a curve to the right having a radius of 100.00 feet, an arc length of "
    "50.00 feet, the chord of which bears N 45°00'00\" E 49.00 feet{along} to a point"
)
ARC_TANGENT_AZ = 45.0 - math.degrees(0.5) / 2.0
RADIAL_TANGENT_AZ = 80.0 + math.degrees(0.1) / 2.0
# Finding 1/2: radius 500, arc 100, chord N 51°13'46" E; stated tangent N 45°30' E.
STATED_TANGENT_CURVE = (
    "thence {tangent} along a curve to the right having a radius of 500.00 feet, an arc "
    "length of 100.00 feet, the chord of which bears N 51°13'46\" E 99.83 feet to a point"
)
# Finding 3: radius and chord length only; delta = 2 asin(c / 2R).
CHORD_DELTA = math.degrees(2.0 * math.asin(100.0 / (2.0 * 500.0)))
CHORD_ARC = 500.0 * math.radians(CHORD_DELTA)


def _radial(clause: str) -> Case:
    return Case(
        text=(
            f"THENCE along a non-tangent curve to the left {clause} having a radius of 500 feet, "
            "an arc length of 50 feet, chord bears N 80° E 49.9 feet to a point"
        ),
        azimuth=RADIAL_TANGENT_AZ,
        notes_in=(DERIVED,),
    )


def _stated(tangent: str) -> Case:
    return Case(
        text=STATED_TANGENT_CURVE.format(tangent=tangent),
        azimuth=45.5,
        quadrant="N 45°30' E",
        chord_bearing="N 51°13'46\" E",
        tol=1e-9,
        notes_out=(DERIVED, CHORD_ONLY),
    )


CASES: dict[str, Case] = {
    # --- round 3 ---------------------------------------------------------
    "r3-chord-only-delta-90": Case(
        text=(
            "THENCE along a curve to the right, radius of 100 feet, delta angle of 90 degrees, "
            "arc length of 157.0796327 feet, the chord of which bears N 45° E, 141.421356 feet"
        ),
        azimuth=0.0,
        chord_bearing="N 45° E",
        delta_deg=90.0,
        notes_in=(DERIVED,),
    ),
    "r3-chord-bearing-word-form": Case(
        text=(
            "THENCE a curve to the right, radius of 50 feet, delta angle of 90°, "
            "chord bearing North 45° East 70.71 feet"
        ),
        delta_deg=90.0,
        azimuth=0.0,
        notes_in=(DERIVED,),
    ),
    # --- round 4 ---------------------------------------------------------
    "r4-approximate-keeps-derived-note": Case(
        text=(
            "THENCE a curve to the right, approximately radius of 50 feet, delta angle of 90°, "
            "chord bearing North 45° East 70.71 feet"
        ),
        delta_deg=90.0,
        azimuth=0.0,
        notes_in=(DERIVED, "meander / approximate"),
    ),
    "r4-abbreviated-chord": Case(
        text=(
            "THENCE a curve to the right, radius of 100 feet, delta angle of 90°, "
            "chord bears N 45°00'00\" E 141.42 feet"
        ),
        delta_deg=90.0,
        azimuth=0.0,
        notes_in=(DERIVED,),
    ),
    "r4-spelled-chord": Case(
        text=(
            "THENCE a curve to the right, radius of 100 feet, delta angle of 90°, "
            "chord bears North 45°00'00\" East 141.42 feet"
        ),
        delta_deg=90.0,
        azimuth=0.0,
        notes_in=(DERIVED,),
    ),
    "r4-separate-tangent-kept": Case(
        text=(
            "THENCE N 10°00'00\" E along a curve to the right, radius of 100 feet, "
            "delta angle of 90°, chord bears N 55°00'00\" E 141.42 feet"
        ),
        delta_deg=90.0,
        azimuth=10.0,
        quadrant="N 10°00' E",
        notes_out=(DERIVED, CHORD_ONLY),
    ),
    # --- round 5 ---------------------------------------------------------
    "r5-arc-radius-delta": Case(
        text=ARC_CHORD.format(along=""),
        azimuth=ARC_TANGENT_AZ,
        notes_in=(DERIVED, FROM_ARC),
    ),
    "r5-arc-radius-delta-with-along": Case(
        text=ARC_CHORD.format(along=" along the Northerly line of Pennbrook Drive"),
        azimuth=ARC_TANGENT_AZ,
        notes_in=(DERIVED, FROM_ARC),
    ),
    "r5-radial-radius-point": _radial("whose radius point bears S 10° W,"),
    "r5-radial-bearing-of": _radial("radial bearing of S 10° W,"),
    "r5-radial-line": _radial("radial line bears S 10° W,"),
    "r5-center-point": _radial("to the center point which bears S 10° W,"),
    "r5-centre-point": _radial("to the centre point which bears S 10° W,"),
    # --- round 6, finding 1 and 2: stated tangent in any accepted form ----
    "r6-tangent-words-deg-min": _stated("North 45 degrees 30 minutes East"),
    "r6-tangent-word-symbol": _stated("North 45°30' East"),
    "r6-tangent-abbrev-symbol": _stated("N 45°30' E"),
    "r6-tangent-dashed": _stated("N 45-30-00 E"),
    "r6-tangent-d-m": _stated("N 45d30m E"),
    "r6-tangent-deg-min-abbrev": _stated("N 45 deg 30 min E"),
    "r6-tangent-bearing-label-dashed": Case(
        text=(
            "thence along a curve to the right having a tangent bearing N 45-30-00 E, a radius "
            "of 500.00 feet, an arc length of 100.00 feet, the chord of which bears "
            "N 51°13'46\" E 99.83 feet to a point"
        ),
        azimuth=45.5,
        quadrant="N 45°30' E",
        tol=1e-9,
        notes_out=(DERIVED, CHORD_ONLY),
    ),
    "r6-tangent-after-chord": Case(
        text=(
            "thence along a curve to the right, the chord of which bears N 51°13'46\" E "
            "99.83 feet, having a radius of 500.00 feet, an arc length of 100.00 feet, "
            "and an initial tangent bearing of N 45°30' E to a point"
        ),
        azimuth=45.5,
        quadrant="N 45°30' E",
        tol=1e-9,
        notes_out=(DERIVED, CHORD_ONLY),
    ),
    "r6-dashed-chord-derives-tangent": Case(
        text=(
            "thence along a curve to the right having a radius of 500.00 feet, an arc length "
            "of 100.00 feet, the chord of which bears N 51-13-46 E 99.83 feet to a point"
        ),
        azimuth=51.0 + 13.0 / 60 + 46.0 / 3600 - math.degrees(0.2) / 2.0,
        chord_bearing="N 51°13'46\" E",
        notes_in=(DERIVED, FROM_ARC),
    ),
    # --- round 6, finding 3: radius + chord length only -----------------
    "r6-radius-chord-only": Case(
        text=(
            "thence along a curve to the right with a radius of 500 feet, chord bears "
            "N 45° E, 100 feet to a point"
        ),
        azimuth=45.0 - CHORD_DELTA / 2.0,
        chord_bearing="N 45° E",
        arc_length_ft=CHORD_ARC,
        notes_in=(DERIVED, FROM_CHORD, ARC_FROM_CHORD),
        extra={"distance_ft": CHORD_ARC},
    ),
    "r6-radius-chord-with-stated-tangent": Case(
        text=(
            "thence N 40° E along a curve to the right with a radius of 500 feet, chord bears "
            "N 45° E, 100 feet to a point"
        ),
        azimuth=40.0,
        quadrant="N 40°00' E",
        arc_length_ft=CHORD_ARC,
        notes_in=(ARC_FROM_CHORD,),
        notes_out=(DERIVED, CHORD_ONLY),
    ),
    "r6-chord-longer-than-diameter-is-invalid": Case(
        text=(
            "thence along a curve to the right with a radius of 500 feet, chord bears "
            "N 45° E, 1001 feet to a point"
        ),
        raises=True,
    ),
}


@pytest.mark.parametrize("entry", ENTRY_POINTS)
@pytest.mark.parametrize("case_id", CASES)
def test_curve_tangent_comes_only_from_course_text(entry, case_id):
    case = CASES[case_id]
    parse = ENTRY_POINTS[entry]
    if case.raises:
        with pytest.raises(ValueError):
            parse(case.text)
        return

    call = parse(case.text)
    assert call is not None
    notes = call.notes or ""
    if case.azimuth is None:
        assert call.bearing_azimuth_deg_from_north is None
    else:
        assert call.bearing_azimuth_deg_from_north == pytest.approx(case.azimuth, abs=case.tol)
    assert call.bearing_quadrant == case.quadrant
    if case.chord_bearing is not None:
        assert call.chord_bearing == case.chord_bearing
    # delta_deg is stored only when stated; derived deltas are disclosed in notes.
    if case.delta_deg is None:
        assert call.delta_deg is None
    else:
        assert call.delta_deg == pytest.approx(case.delta_deg)
    if case.arc_length_ft is not None:
        assert call.arc_length_ft == pytest.approx(case.arc_length_ft)
    for fragment in case.notes_in:
        assert fragment in notes
    for fragment in case.notes_out:
        assert fragment not in notes
    for name, expected in case.extra.items():
        assert getattr(call, name) == pytest.approx(expected)
    assert call.is_indefinite is False


NORMALIZERS = {
    "package": package_normalize,
    "monolith": TextParser.normalize_legal_description,
}


@pytest.mark.parametrize("normalize", NORMALIZERS.values(), ids=NORMALIZERS)
@pytest.mark.parametrize(
    "bearing", ["N 45-30-00 E", "N 45d30m E", "N 45 30 00 E", "N 45 deg 30 min E"]
)
def test_normalizer_does_not_turn_a_quadrant_bearing_into_due_north(normalize, bearing):
    # The bare-cardinal rewrite ("thence N 100 feet" -> "due North") fabricated
    # a 0 degree course from bearings in forms it did not recognise.
    assert "due" not in normalize(f"thence {bearing} 100 feet to a point")


@pytest.mark.parametrize("normalize", NORMALIZERS.values(), ids=NORMALIZERS)
def test_normalizer_still_expands_bare_cardinal_distance(normalize):
    assert "due South 289.81 feet" in normalize("thence S 289.81 feet along the East line")


@pytest.mark.parametrize("entry", ["package-calls", "monolith-calls"])
def test_spaced_bearing_fails_closed_instead_of_due_north(entry):
    # Previously normalized to "due North 45 30 00 E" and parsed as azimuth 0.
    with pytest.raises(ValueError, match="Malformed course"):
        ENTRY_POINTS[entry]("THENCE N 45 30 00 E 100 feet to a point")
