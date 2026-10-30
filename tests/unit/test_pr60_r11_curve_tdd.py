"""PR #60 round 11: verification cross-checks tangent/chord/radius; one curve tolerance.

1. ``check_curve_consistency`` re-checks a curve's stated tangent azimuth against its
   chord bearing: the deflection (chord - tangent, signed by curve direction) must
   lie on the curve's side and, with a radius and chord length, satisfy
   chord = 2R*sin(deflection); a stated delta/arc must equal twice the deflection.
   A hand-built call with inconsistent elements fails the curve check, and a
   chord-only call's warnings/blocks say "stated tangent, chord and radius are
   inconsistent" rather than only "delta/arc not stated".
2. Parser, verification and plotting share one curve-element tolerance, so a chord
   that parses and verifies also plots (and vice versa).
"""

from __future__ import annotations

import math

import mp_models
import pytest
from mp_bearing import curves as bearing_curves
from mp_parse import calls as package_calls
from mp_parse.calls import extract_single_call as package_single_call
from mp_verify import checks as package_checks
from mp_verify import plot as package_plot
from mp_verify.closure import verify_closure as package_verify

from metesparser import call_extractor as monolith_calls
from metesparser import models as monolith_models
from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker

IMPLS = {
    "package": (mp_models, package_verify),
    "monolith": (monolith_models, ClosureChecker.verify_closure),
}

RADIUS = 500.0
DEFLECTION = 6.0  # chord bears 6 degrees right of the east tangent: delta 12
CHORD = 2 * RADIUS * math.sin(math.radians(DEFLECTION))  # 104.528...
ARC = RADIUS * math.radians(2 * DEFLECTION)
INCONSISTENT = "stated tangent, chord and radius are inconsistent"


def _curve(m, *, chord=CHORD, chord_bearing="S 84°00'00\" E", side="right", **extra):
    return m.DeedCall(
        course=1,
        direction_text="N 90°00'00\" E",
        bearing_azimuth_deg_from_north=90.0,
        distance_ft=extra.get("arc_length_ft") or chord,
        curve_dir=side,
        radius_ft=RADIUS,
        chord_bearing=chord_bearing,
        chord_length_ft=chord,
        **extra,
    )


def _curve_check(result):
    return next(check for check in result.checks if check.name == "curve_consistency")


def _passes(impl, call) -> bool:
    if impl == "package":
        return package_checks.check_curve_consistency([call])[0]
    return ClosureChecker.check_curve_consistency([call])


CONSISTENT = {
    "chord-only right": {},
    "chord-only left": {"side": "left", "chord_bearing": "N 84°00'00\" E"},
    "delta and arc stated": {"delta_deg": 2 * DEFLECTION, "arc_length_ft": ARC},
    "arc stated": {"arc_length_ft": ARC},
    "non-tangent ignores tangent": {"non_tangent": True, "chord_bearing": "S 70°00'00\" E"},
}

INCONSISTENT_CASES = {
    "chord length off": {"chord": CHORD + 5.0},
    "wrong side": {"side": "left"},
    "zero deflection": {"chord_bearing": "S 90°00'00\" E"},
    "delta not twice deflection": {
        "delta_deg": 14.0,
        "arc_length_ft": RADIUS * math.radians(14.0),
        "chord": 2 * RADIUS * math.sin(math.radians(7.0)),
    },
    "arc not twice deflection": {
        "arc_length_ft": RADIUS * math.radians(14.0),
        "chord": 2 * RADIUS * math.sin(math.radians(7.0)),
    },
}


@pytest.mark.parametrize("impl", IMPLS)
@pytest.mark.parametrize("case", CONSISTENT)
def test_consistent_tangent_chord_radius_pass_curve_math(impl, case):
    m, _ = IMPLS[impl]
    assert _passes(impl, _curve(m, **CONSISTENT[case]))


@pytest.mark.parametrize("impl", IMPLS)
@pytest.mark.parametrize("case", INCONSISTENT_CASES)
def test_inconsistent_tangent_chord_radius_fail_curve_math(impl, case):
    m, _ = IMPLS[impl]
    assert not _passes(impl, _curve(m, **INCONSISTENT_CASES[case]))


@pytest.mark.parametrize("impl", IMPLS)
@pytest.mark.parametrize("case", INCONSISTENT_CASES)
def test_inconsistent_curve_fails_verification_with_reason(impl, case):
    m, verify = IMPLS[impl]
    result = verify([_curve(m, **INCONSISTENT_CASES[case])])
    check = _curve_check(result)
    assert check.status == "failed"
    assert "Course 1" in check.detail
    assert "tangent" in check.detail and "chord" in check.detail
    assert result.curve_consistency_passed is False
    assert result.geometry_verified is False


@pytest.mark.parametrize("impl", IMPLS)
def test_chord_only_inconsistent_reason_is_distinct_from_delta_not_stated(impl):
    m, verify = IMPLS[impl]
    bad = verify([_curve(m, chord=CHORD + 5.0)])
    assert any(INCONSISTENT in w for w in bad.warnings)
    assert not any("delta/arc not stated" in w for w in bad.warnings)
    assert _curve_check(bad).status == "failed"

    ok = verify([_curve(m)])
    assert not any(INCONSISTENT in w for w in ok.warnings)
    assert any("delta/arc not stated" in w for w in ok.warnings)
    check = _curve_check(ok)
    assert check.status == "blocked"
    assert check.reason == "curve_delta_not_stated"


@pytest.mark.parametrize("impl", IMPLS)
def test_chord_only_without_tangent_is_not_cross_checked(impl):
    m, _ = IMPLS[impl]
    call = _curve(m).model_copy(update={"bearing_azimuth_deg_from_north": None})
    assert _passes(impl, call)


# --- 2. One shared curve-element tolerance ---------------------------------------


def test_one_curve_element_tolerance_is_shared():
    tol = bearing_curves.CURVE_ELEMENT_TOLERANCE_FT
    assert package_checks.CURVE_ELEMENT_TOLERANCE_FT == tol
    assert package_plot.CURVE_ELEMENT_TOLERANCE_FT == tol
    assert package_calls.CURVE_ELEMENT_TOLERANCE_FT == tol
    assert monolith_calls.CURVE_ELEMENT_TOLERANCE_FT == tol
    assert package_plot.TANGENT_CHORD_TOLERANCE_DEG == bearing_curves.TANGENT_CHORD_TOLERANCE_DEG


def _plots(call) -> bool:
    try:
        package_plot._arc(
            call, (0.0, 0.0), {"call_id": "c", "occurrence_id": None, "page_id": None}
        )
    except ValueError:
        return False
    return True


# Chord errors straddling the shared tolerance: below, between 0.01 and 0.1, above.
CHORD_ERRORS = [0.004, 0.009, 0.03, 0.05, 0.09, 0.2]


@pytest.mark.parametrize("error", CHORD_ERRORS)
def test_verification_and_plot_agree_on_stated_chord(error):
    call = _curve(mp_models, chord=CHORD + error, delta_deg=2 * DEFLECTION, chord_bearing=None)
    tol = bearing_curves.CURVE_ELEMENT_TOLERANCE_FT
    assert package_checks.check_curve_consistency([call])[0] is (error <= tol)
    assert _plots(call) is (error <= tol)
    mono = _curve(
        monolith_models, chord=CHORD + error, delta_deg=2 * DEFLECTION, chord_bearing=None
    )
    assert ClosureChecker.check_curve_consistency([mono]) is (error <= tol)


@pytest.mark.parametrize("error", CHORD_ERRORS)
def test_verification_and_plot_agree_on_stated_arc(error):
    call = _curve(
        mp_models, delta_deg=2 * DEFLECTION, arc_length_ft=ARC + error, chord_bearing=None
    )
    tol = bearing_curves.CURVE_ELEMENT_TOLERANCE_FT
    assert package_checks.check_curve_consistency([call])[0] is (error <= tol)
    assert _plots(call) is (error <= tol)


TANGENT_CHORD_TEXT = (
    "thence N 90°00'00\" E along a curve to the right having a radius of 500.00 feet, "
    "the chord of which bears S 84°00'00\" E {chord:.2f} feet to a point"
)


@pytest.mark.parametrize("error", CHORD_ERRORS)
@pytest.mark.parametrize("single", [package_single_call, CallExtractor.extract_single_call])
def test_parser_tangent_chord_derivation_agrees_with_verify_and_plot(single, error):
    chord = round(CHORD, 2) + error
    call = single(TANGENT_CHORD_TEXT.format(chord=chord), 1)
    derived = call.arc_length_ft is not None
    tol = bearing_curves.CURVE_ELEMENT_TOLERANCE_FT
    stated_error = abs(round(chord, 2) - CHORD)
    assert derived is (stated_error <= tol)
    if derived:
        package_call = mp_models.DeedCall.model_validate(call.model_dump())
        assert package_checks.check_curve_consistency([package_call])[0]
        assert _plots(package_call)
