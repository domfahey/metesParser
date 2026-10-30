"""PR #60 round 6: the curve tangent comes only from boundary course text.

Chord, radial, radius-point and center-point bearings are removed before the
course bearing is extracted, so the chord bearing can only ever reach
``chord_bearing`` (or derive a disclosed tangent). Each case runs through the
package and monolith, both via ``extract_calls`` (normalized) and directly via
``extract_single_call`` (raw text).
"""

from __future__ import annotations

import importlib
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime

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
# Radius + chord without a stated delta or arc is ambiguous (minor or major arc):
# nothing is derived; the course is positioned by its chord only.
BY_CHORD = "curve delta/arc not stated - positioned by chord only"
CHORD_TOO_LONG = "chord length exceeds twice the radius"


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
    no_arc: bool = False
    indefinite: bool = False
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
    # Ambiguous (minor vs major arc): no delta, arc or tangent is derived. The
    # course is kept and positioned by its chord; it carries no azimuth.
    "r6-radius-chord-only": Case(
        text=(
            "thence along a curve to the right with a radius of 500 feet, chord bears "
            "N 45° E, 100 feet to a point"
        ),
        chord_bearing="N 45° E",
        no_arc=True,
        indefinite=True,
        notes_in=(BY_CHORD,),
        notes_out=(DERIVED, FROM_CHORD, ARC_FROM_CHORD),
        extra={"chord_length_ft": 100.0, "radius_ft": 500.0},
    ),
    "r6-radius-chord-with-stated-tangent": Case(
        text=(
            "thence N 40° E along a curve to the right with a radius of 500 feet, chord bears "
            "N 45° E, 100 feet to a point"
        ),
        azimuth=40.0,
        quadrant="N 40°00' E",
        chord_bearing="N 45° E",
        no_arc=True,
        notes_in=(BY_CHORD,),
        notes_out=(DERIVED, CHORD_ONLY, ARC_FROM_CHORD),
        extra={"chord_length_ft": 100.0},
    ),
    "r6-chord-longer-than-diameter-is-kept-and-flagged": Case(
        text=(
            "thence along a curve to the right with a radius of 500 feet, chord bears "
            "N 45° E, 1001 feet to a point"
        ),
        chord_bearing="N 45° E",
        no_arc=True,
        indefinite=True,
        notes_in=(BY_CHORD, CHORD_TOO_LONG),
        notes_out=(DERIVED,),
        extra={"chord_length_ft": 1001.0},
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
    if case.no_arc:
        assert call.arc_length_ft is None
    for fragment in case.notes_in:
        assert fragment in notes
    for fragment in case.notes_out:
        assert fragment not in notes
    for name, expected in case.extra.items():
        assert getattr(call, name) == pytest.approx(expected)
    assert call.is_indefinite is case.indefinite


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


# --- round 6 follow-up: dashed and d/m bearings ------------------------------
# A two-part dashed bearing is degrees-minutes; a three-part one is
# degrees-minutes-seconds. An explicit seconds marker is always seconds.
DASHED_BEARINGS = {
    "N 45-30 E": 45.5,
    "S 44-30 E": 135.5,
    "N 45-30-15 E": 45.0 + 30.0 / 60 + 15.0 / 3600,
    "S 44-30-30 W": 180.0 + 44.0 + 30.0 / 60 + 30.0 / 3600,
    "N 45d30m E": 45.5,
    "N 45d30m15s E": 45.0 + 30.0 / 60 + 15.0 / 3600,
    "S 44d30m E": 135.5,
    "N 45d E": 45.0,
    "N 45d 30s E": 45.0 + 30.0 / 3600,
}


@pytest.mark.parametrize("entry", ENTRY_POINTS)
@pytest.mark.parametrize("bearing", DASHED_BEARINGS)
def test_dashed_and_dm_bearings_read_minutes_before_seconds(entry, bearing):
    call = ENTRY_POINTS[entry](f"THENCE {bearing} 100 feet to a point")
    assert call is not None
    assert call.bearing_azimuth_deg_from_north == pytest.approx(DASHED_BEARINGS[bearing], abs=1e-9)


# direction_text keeps the deed's own wording; normalization is for parsing only.
VERBATIM_FORMS = {
    "North 45° East": 45.0,
    "North 45°30' East": 45.5,
    "North 45 degrees 30 minutes East": 45.5,
    "N 45-30 E": 45.5,
    "N 45-30-00 E": 45.5,
    "N 45d30m E": 45.5,
    "N 45 deg 30 min E": 45.5,
    "S 10°15'30\" W": 190.0 + 15.0 / 60 + 30.0 / 3600,
}


@pytest.mark.parametrize("entry", ENTRY_POINTS)
@pytest.mark.parametrize("form", VERBATIM_FORMS)
def test_direction_text_is_a_verbatim_substring_of_the_call(entry, form):
    text = f"THENCE {form} 100 feet to a point"
    call = ENTRY_POINTS[entry](text)
    assert call is not None
    assert call.bearing_azimuth_deg_from_north == pytest.approx(VERBATIM_FORMS[form], abs=1e-9)
    # extract_calls parses the normalized description, so its call text is the
    # normalized source; extract_single_call receives the deed text as-is.
    normalize = NORMALIZERS["package" if entry.startswith("package") else "monolith"]
    source = text if entry.endswith("single") else normalize(text + CLOSING)
    assert call.direction_text in source
    if entry.endswith("single"):
        assert call.direction_text == form


@pytest.mark.parametrize("entry", ENTRY_POINTS)
def test_curve_direction_text_skips_the_chord_bearing_verbatim(entry):
    text = (
        "THENCE North 45 degrees 30 minutes East along a curve to the right having a radius "
        "of 500.00 feet, an arc length of 100.00 feet, the chord of which bears "
        "N 51-13-46 E 99.83 feet to a point"
    )
    call = ENTRY_POINTS[entry](text)
    assert call.bearing_azimuth_deg_from_north == pytest.approx(45.5)
    if entry.endswith("single"):
        assert call.direction_text == "North 45 degrees 30 minutes East"


@pytest.mark.parametrize("entry", ["package-single", "monolith-single"])
def test_unparsed_bearing_keeps_its_cardinal_direction_text(entry):
    # A mixed form the parser does not read ("degrees" with a minute symbol) stays
    # an incomplete cardinal-only course; the verbatim lookup must not dress it up
    # as a bearing or clear its indefinite flag.
    call = ENTRY_POINTS[entry]("THENCE North 34 degrees 02' 00\" West 129 feet to a point")
    assert call.bearing_azimuth_deg_from_north is None
    assert call.direction_text == "north"
    assert call.is_indefinite is True


# --- round 6 follow-up: audit of a derived tangent ---------------------------
def _audit_ctx(models):
    return models.AuditContext(
        run_metadata=models.RunMetadata(
            parser_version="t",
            llm_provider="t",
            llm_model="t",
            prompt_hash="t",
            timestamp_utc=datetime.now(UTC),
            source_pdf="t.pdf",
            cache_enabled=False,
        )
    )


AUDIT_ENTRY_POINTS = {
    "package": (package_extract_calls, "mp_models"),
    "monolith": (CallExtractor.extract_calls, "metesparser.models"),
}


@pytest.mark.parametrize(
    ("text", "delta_source"),
    [
        (
            "THENCE along a curve to the right, radius of 100 feet, delta angle of 90 degrees, "
            "arc length of 157.0796327 feet, the chord of which bears N 45° E, 141.421356 feet",
            "stated delta",
        ),
        (ARC_CHORD.format(along=""), "arc length and radius"),
    ],
    ids=["stated-delta", "arc-delta"],
)
@pytest.mark.parametrize("impl", AUDIT_ENTRY_POINTS)
def test_derived_tangent_records_an_audit_step(impl, text, delta_source):
    extract, models_name = AUDIT_ENTRY_POINTS[impl]
    ctx = _audit_ctx(importlib.import_module(models_name))
    call = extract(text + CLOSING, audit_context=ctx, strict=True)[0]
    assert call.bearing_quadrant is None
    steps = {t.step: t for t in ctx.call_audits[0].transformations}
    step = steps["derive_tangent_azimuth"]
    assert call.chord_bearing in step.input
    assert delta_source in step.input
    assert step.output == str(call.bearing_azimuth_deg_from_north)
    assert step.rule is not None and "chord" in step.rule


# --- round 6 follow-up: verification of chord-positioned curves --------------
SQUARE_WITH_CHORD = (
    "BEGINNING at a point; THENCE N 0° E 100 feet; "
    "THENCE along a curve to the right with a radius of 500 feet, chord bears "
    "S 90° E, 100 feet to a point; THENCE S 0° E 100 feet; THENCE N 90° W 100 feet."
)


def _monolith_verify(calls):
    from metesparser.closure_checker import ClosureChecker

    return ClosureChecker.verify_closure(calls)


def _package_verify(calls):
    from mp_verify.closure import verify_closure

    return verify_closure(calls)


VERIFY_PAIRS = pytest.mark.parametrize(
    ("extract", "verify"),
    [(package_extract_calls, _package_verify), (CallExtractor.extract_calls, _monolith_verify)],
    ids=["package", "monolith"],
)


@VERIFY_PAIRS
def test_chord_only_curve_is_positioned_by_its_chord_but_not_verified(extract, verify):
    calls = extract(SQUARE_WITH_CHORD, strict=True)
    assert len(calls) == 4
    curve = calls[1]
    assert curve.bearing_azimuth_deg_from_north is None
    assert curve.is_indefinite is True
    result = verify(calls)
    # The chord fixes the endpoint exactly, so the traverse still returns home ...
    assert result.misclosure_ft == pytest.approx(0.0, abs=1e-9)
    # ... but the arc is ambiguous: the curve check is blocked and nothing is eligible.
    checks = {c.name: c.status for c in result.checks}
    assert checks["curve_consistency"] == "blocked"
    assert result.geometry_verified is False


@VERIFY_PAIRS
def test_chord_longer_than_diameter_fails_curve_check(extract, verify):
    calls = extract(SQUARE_WITH_CHORD.replace("100 feet to a point", "1001 feet to a point"))
    curve = calls[1]
    assert CHORD_TOO_LONG in (curve.notes or "")
    result = verify(calls)
    checks = {c.name: c.status for c in result.checks}
    assert checks["curve_consistency"] == "failed"
    assert result.curve_consistency_passed is False
    assert result.geometry_verified is False


@pytest.mark.parametrize("entry", ["package-calls", "monolith-calls"])
def test_chord_longer_than_diameter_is_kept_in_non_strict_mode(entry):
    extract = package_extract_calls if entry.startswith("package") else CallExtractor.extract_calls
    calls = extract(
        "thence along a curve to the right with a radius of 500 feet, chord bears "
        "N 45° E, 1001 feet to a point" + CLOSING,
        strict=False,
    )
    assert len(calls) == 3
    assert CHORD_TOO_LONG in (calls[0].notes or "")
