"""PR #60 round 12: derived curve values are never stored as stated deed values.

1. A curve stating its tangent, chord bearing, chord length and radius (no delta or
   arc) keeps only those stated values: ``arc_length_ft`` and ``delta_deg`` stay None,
   ``bearing_azimuth_deg_from_north`` is the stated tangent (not indefinite) and
   ``distance_ft`` is the stated chord. The curve is positioned by its chord; the
   tangent/chord/radius cross-check is left to verification, which evaluates the
   stated values only (consistent: chord-positioned and blocked, never a derived
   pass; inconsistent: failed).
2. Curve info is extracted once per call, and a BEGINNING/POB clause returns
   before any bearing normalization runs.
"""

from __future__ import annotations

import math

import pytest
from mp_parse import calls as package_calls
from mp_parse.calls import extract_single_call as package_single_call
from mp_verify.closure import verify_closure as package_verify

from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker
from tests.fixtures.package_parser import extract_calls as package_extract_calls

CLOSING = "; THENCE due South 50 feet; THENCE due West 50 feet to the point of beginning."


def _via_calls(extract):
    return lambda text: extract(text + CLOSING, strict=True)[0]


def _via_single(extract):
    return lambda text: extract(text, 1)


ENTRY_POINTS = {
    "package-calls": _via_calls(package_extract_calls),
    "monolith-calls": _via_calls(CallExtractor.extract_calls),
    "package-single": _via_single(package_single_call),
    "monolith-single": _via_single(CallExtractor.extract_single_call),
}


@pytest.fixture(params=sorted(ENTRY_POINTS))
def parse(request):
    return ENTRY_POINTS[request.param]


TANGENT_CHORD = (
    "thence N 10°00'00\" E along a curve to the {side} having a radius of 500.00 feet, "
    "the chord of which bears N {chord_deg}°00'00\" E {chord} feet to a point"
)
POSITIONED_NOTE = "curve positioned by stated tangent and chord; arc not stated"


@pytest.mark.parametrize(
    "side,chord_deg,chord",
    [
        ("right", 45, "573.58"),  # consistent: delta 70
        ("right", 45, "99.93"),  # inconsistent chord length
        ("left", 45, "573.58"),  # chord on the wrong side
    ],
)
def test_tangent_chord_curve_stores_only_stated_values(parse, side, chord_deg, chord):
    call = parse(TANGENT_CHORD.format(side=side, chord_deg=chord_deg, chord=chord))
    assert call is not None
    assert call.bearing_azimuth_deg_from_north == pytest.approx(10.0)
    assert call.is_indefinite is False
    assert call.arc_length_ft is None
    assert call.delta_deg is None
    assert call.radius_ft == pytest.approx(500.0)
    assert call.chord_length_ft == pytest.approx(float(chord))
    assert call.distance_ft == pytest.approx(float(chord))
    assert call.is_chord_only_curve()
    notes = call.notes or ""
    assert POSITIONED_NOTE in notes
    assert "derived" not in notes


PARSE_VERIFY = {
    "package": (package_single_call, package_verify),
    "monolith": (CallExtractor.extract_single_call, ClosureChecker.verify_closure),
}


def _triangle(impl, chord):
    single, verify = PARSE_VERIFY[impl]
    curve = single(TANGENT_CHORD.format(side="right", chord_deg=45, chord=chord), 1)
    leg = float(chord) * math.sqrt(0.5)
    south = single(f"THENCE due South {leg:.2f} feet to a point", 2)
    west = single(f"THENCE due West {leg:.2f} feet to the point of beginning", 3)
    return verify([curve, south, west])


def _curve_check(result):
    return next(check for check in result.checks if check.name == "curve_consistency")


@pytest.mark.parametrize("impl", PARSE_VERIFY)
def test_consistent_tangent_chord_curve_is_chord_positioned_not_derived(impl):
    result = _triangle(impl, "573.58")
    assert result.misclosure_ft == pytest.approx(0.0, abs=0.01)
    check = _curve_check(result)
    assert check.status == "blocked"
    assert check.reason == "curve_delta_not_stated"
    assert any("positioned by chord only" in w for w in result.warnings)
    assert not any("inconsistent" in w for w in result.warnings)
    assert result.area_available is False
    assert result.perimeter_available is False
    assert result.geometry_verified is False


@pytest.mark.parametrize("impl", PARSE_VERIFY)
def test_inconsistent_tangent_chord_curve_fails_on_stated_values(impl):
    result = _triangle(impl, "99.93")
    check = _curve_check(result)
    assert check.status == "failed"
    assert "stated tangent, chord and radius are inconsistent" in check.detail
    assert result.curve_consistency_passed is False
    assert result.geometry_verified is False


# --- 2. One curve-info extraction per call; BEGINNING returns early -------------


def _spy(monkeypatch, impl):
    """Count extract_curve_info and bearing-normalization calls in one implementation."""
    seen: dict[str, list[str]] = {"curve": [], "normalize": []}
    # The monolith CallExtractor delegates to mp_parse.calls, so both are spied there.
    original_normalize = package_calls._normalize_bearing_segments

    def normalize(segments):
        seen["normalize"].append(segments[0])
        return original_normalize(segments)

    monkeypatch.setattr(package_calls, "_normalize_bearing_segments", normalize)
    original_curve = package_calls.extract_curve_info

    def curve(text, *args, **kwargs):
        seen["curve"].append(text)
        return original_curve(text, *args, **kwargs)

    monkeypatch.setattr(package_calls, "extract_curve_info", curve)
    return seen


EXTRACT_CALLS = {"package": package_extract_calls, "monolith": CallExtractor.extract_calls}
EXTRACT_SINGLE = {"package": package_single_call, "monolith": CallExtractor.extract_single_call}
CURVE_TEXT = TANGENT_CHORD.format(side="right", chord_deg=45, chord="573.58")


@pytest.mark.parametrize("impl", ["package", "monolith"])
def test_extract_calls_extracts_curve_info_once_per_call(monkeypatch, impl):
    seen = _spy(monkeypatch, impl)
    calls = EXTRACT_CALLS[impl](CURVE_TEXT + CLOSING, strict=True)
    assert len(calls) == 3
    assert len(seen["curve"]) == 3
    assert len(set(seen["curve"])) == 3


@pytest.mark.parametrize("impl", ["package", "monolith"])
def test_extract_single_call_extracts_curve_info_once(monkeypatch, impl):
    seen = _spy(monkeypatch, impl)
    assert EXTRACT_SINGLE[impl](CURVE_TEXT, 1) is not None
    assert len(seen["curve"]) == 1


BEGINNING = "BEGINNING at a point N 10° E 50 feet from a stake on a curve to the right"


@pytest.mark.parametrize("impl", ["package", "monolith"])
def test_beginning_clause_single_skips_bearing_work(monkeypatch, impl):
    seen = _spy(monkeypatch, impl)
    assert EXTRACT_SINGLE[impl](BEGINNING, 1) is None
    assert seen == {"curve": [], "normalize": []}


@pytest.mark.parametrize("impl", ["package", "monolith"])
def test_beginning_clause_calls_skips_bearing_work(monkeypatch, impl):
    # split_into_calls normally drops BEGINNING clauses; force one through so the
    # per-call loop must reach extract_single_call's early return.
    pieces = [BEGINNING, CURVE_TEXT]
    # The monolith delegates call splitting to the package.
    monkeypatch.setattr(package_calls, "split_into_calls", lambda text, **_: list(pieces))
    seen = _spy(monkeypatch, impl)
    skipped: list = []
    calls = EXTRACT_CALLS[impl]("THENCE " + CURVE_TEXT, strict=False, skipped_courses=skipped)
    assert len(calls) == 1
    # The forced BEGINNING piece is not a course and is recorded as skipped, not dropped.
    assert [s.source_excerpt for s in skipped] == [BEGINNING]
    assert seen["curve"] == [CURVE_TEXT]
    assert not any("BEGINNING" in segment for segment in seen["normalize"])
