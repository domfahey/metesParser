"""PR #60 round 13: a radius-and-delta curve stores only its stated elements.

A curve stating only its radius and delta has its arc and chord fixed by them, but
neither is a deed-stated value: ``arc_length_ft`` and ``chord_length_ft`` stay None.
``distance_ft`` (the required course length) is the arc computed from the stated
radius and delta, disclosed in the notes and the audit trail. Verification and
plotting compute the geometry from radius and delta (closure, perimeter and plot are
numerically unchanged), and with no redundant stated element there is nothing to
cross-check: ``curve_consistency`` is ``not_applicable``, never a derived pass.
Curves that state their arc (with or without a delta) are unchanged.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest
from mp_models import AuditContext, RunMetadata
from mp_models.plot_request import PlotCall, PlotRequest
from mp_parse.calls import extract_single_call as package_single_call
from mp_verify.closure import verify_closure as package_verify
from mp_verify.plot import prepare_plot

from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker
from tests.fixtures.package_parser import extract_calls as package_extract_calls

RADIUS = 200.0
DELTA = 14 + 21 / 60 + 36 / 3600
ARC = RADIUS * math.radians(DELTA)
CHORD = 2 * RADIUS * math.sin(math.radians(DELTA) / 2)

CLOSING = (
    "; THENCE due East 100 feet; THENCE due South 150 feet; "
    "THENCE due West 120 feet to the point of beginning."
)
R_DELTA = (
    "thence N 10°00'00\" E along a curve to the right having a radius of 200.00 feet "
    "and a delta of 14°21'36\" to a point"
)
# The first degree value after the radius is the chord bearing, so the labelled
# central angle is parsed by the secondary (non-CURVE_PATTERN) branch.
R_DELTA_CHORD_BEARING = (
    "thence N 10°00'00\" E along a curve to the right, having a radius of 200.00 feet, "
    "the chord of which bears N 17°10'48\" E, and a central angle of 14°21'36\" to a point"
)
R_ARC = (
    "thence N 10°00'00\" E along a curve to the right having a radius of 200.00 feet "
    f"and an arc length of {ARC:.4f} feet to a point"
)
R_DELTA_ARC = (
    "thence N 10°00'00\" E along a curve to the right having a radius of 200.00 feet "
    f"and a delta of 14°21'36\" and an arc length of {ARC:.4f} feet to a point"
)
COMPUTED_NOTE = "arc length not stated - course distance computed from radius and delta"


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


@pytest.mark.parametrize("text", [R_DELTA, R_DELTA_CHORD_BEARING])
def test_radius_delta_curve_stores_no_derived_arc_or_chord(parse, text):
    call = parse(text)
    assert call is not None
    assert call.radius_ft == pytest.approx(RADIUS)
    assert call.delta_deg == pytest.approx(DELTA)
    assert call.arc_length_ft is None
    assert call.chord_length_ft is None
    # The required course length is the computed arc, disclosed as computed.
    assert call.distance_ft == pytest.approx(ARC)
    assert COMPUTED_NOTE in (call.notes or "")


def test_radius_delta_note_keeps_incomplete_bearing_flag():
    text = (
        "thence northeasterly along a curve to the right having a radius of 200.00 feet "
        "and a delta of 14°21'36\" to a point"
    )
    for extract in (package_single_call, CallExtractor.extract_single_call):
        call = extract(text, 1)
        assert call is not None
        notes = call.notes or ""
        assert COMPUTED_NOTE in notes
        assert "incomplete bearing - cardinal only" in notes


@pytest.mark.parametrize("text", [R_ARC, R_DELTA_ARC])
def test_curves_stating_their_arc_are_unchanged(parse, text):
    call = parse(text)
    assert call is not None
    assert call.arc_length_ft == pytest.approx(float(f"{ARC:.4f}"))
    assert call.distance_ft == pytest.approx(float(f"{ARC:.4f}"))
    assert call.chord_length_ft is None
    assert COMPUTED_NOTE not in (call.notes or "")
    if text is R_DELTA_ARC:
        assert call.delta_deg == pytest.approx(DELTA)
    else:
        assert call.delta_deg is None


VERIFIERS = {
    "package": package_verify,
    "monolith": ClosureChecker.verify_closure,
}


@pytest.mark.parametrize("verifier", sorted(VERIFIERS))
@pytest.mark.parametrize(
    "extract", [package_extract_calls, CallExtractor.extract_calls], ids=["package", "monolith"]
)
def test_radius_delta_geometry_matches_stated_arc_and_is_not_cross_checked(extract, verifier):
    verify = VERIFIERS[verifier]
    r_delta = extract(R_DELTA + CLOSING, strict=True)
    r_arc = extract(R_ARC + CLOSING, strict=True)
    result = verify(r_delta)
    reference = verify(r_arc)
    assert result.misclosure_ft == pytest.approx(reference.misclosure_ft, abs=1e-3)
    assert result.perimeter_ft == pytest.approx(reference.perimeter_ft, abs=1e-3)
    assert result.perimeter_ft == pytest.approx(ARC + 370.0, abs=1e-6)
    consistency = {c.name: c for c in result.checks}["curve_consistency"]
    assert consistency.status == "not_applicable"
    assert consistency.passed is False


def test_radius_delta_curve_plots_from_radius_and_delta():
    calls = package_extract_calls(R_DELTA + CLOSING, strict=True)
    geometry = prepare_plot(
        PlotRequest(title="t", calls=tuple(PlotCall(id=f"c{c.course}", call=c) for c in calls))
    ).geometry
    arc = next(p for p in geometry.primitives if p.kind == "arc")
    assert arc.length_ft == pytest.approx(ARC)
    assert arc.sweep_deg == pytest.approx(DELTA)
    assert math.dist(arc.start, arc.end) == pytest.approx(CHORD)


def test_radius_delta_distance_audit_discloses_computation():
    audit = AuditContext(
        run_metadata=RunMetadata(
            parser_version="t",
            llm_provider="t",
            llm_model="t",
            prompt_hash="t",
            timestamp_utc=datetime.now(UTC),
            source_pdf="t.pdf",
            cache_enabled=False,
        )
    )
    package_extract_calls(R_DELTA + CLOSING, audit_context=audit, strict=True)
    curve_audit = audit.call_audits[0]
    distance = next(t for t in curve_audit.transformations if t.step == "extract_distance")
    assert distance.output == str(ARC)
    assert distance.rule is not None and "radius and delta" in distance.rule
