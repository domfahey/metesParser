"""PR #60 round 21: a curve's tangent is never derived into a stated field.

A curve stating a chord bearing and a delta (or arc and radius) but no tangent
keeps ``bearing_azimuth_deg_from_north=None``. Verification positions such a
curve by its chord and delta and computes tangents internally, so closure, area,
perimeter and topology are unchanged and geometry eligibility stays reachable.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from mp_models import AuditContext, RunMetadata
from mp_parse.calls import extract_single_call as package_single_call
from mp_verify.closure import verify_closure as package_verify

from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker
from tests.fixtures.package_parser import extract_calls as package_extract_calls

NOT_STATED = "tangent bearing not stated - curve positioned by chord and delta in verification"
DERIVED = "tangent bearing derived"
CLOSING = "; THENCE due South 50 feet; THENCE due West 50 feet to the point of beginning."

REPRO = (
    "THENCE along a curve to the left having a radius of 100.00 feet, an arc length of "
    "157.08 feet, a chord bearing of N 45°00'00\" E to a point"
)


def _ctx() -> AuditContext:
    return AuditContext(
        run_metadata=RunMetadata(
            parser_version="0.0.0",
            llm_provider="none",
            llm_model="none",
            prompt_hash="x",
            timestamp_utc=datetime(2026, 1, 1, tzinfo=UTC),
            source_pdf="t.pdf",
            cache_enabled=False,
        )
    )


def _via_calls(extract):
    def run(text):
        ctx = _ctx()
        call = extract(text + CLOSING, audit_context=ctx, strict=True)[0]
        return call, ctx.call_audits[0]

    return run


def _via_single(extract):
    return lambda text: (extract(text, 1), None)


ENTRY_POINTS = {
    "package-calls": _via_calls(package_extract_calls),
    "monolith-calls": _via_calls(CallExtractor.extract_calls),
    "package-single": _via_single(package_single_call),
    "monolith-single": _via_single(CallExtractor.extract_single_call),
}


@pytest.fixture(params=sorted(ENTRY_POINTS))
def parse(request):
    return ENTRY_POINTS[request.param]


def test_tangentless_curve_keeps_bearing_unset_and_stated_elements(parse):
    call, audit = parse(REPRO)
    assert call.bearing_azimuth_deg_from_north is None
    assert call.bearing_quadrant is None
    assert not call.is_complete_bearing()
    assert call.chord_bearing is not None and "45" in call.chord_bearing
    assert call.curve_dir == "left"
    assert call.radius_ft == pytest.approx(100.0)
    assert call.arc_length_ft == pytest.approx(157.08)
    assert call.delta_deg is None
    assert NOT_STATED in (call.notes or "")
    assert DERIVED not in (call.notes or "")
    # Positioned by chord and delta in verification, so not indefinite.
    assert call.is_indefinite is False
    if audit is not None:
        steps = {t.step for t in audit.transformations}
        assert "derive_tangent_azimuth" not in steps
        bearing = [d for d in audit.decisions if d.field == "bearing_azimuth_deg_from_north"]
        assert len(bearing) == 1
        assert bearing[0].value == "none"
        assert "not stated" in bearing[0].reason


def test_tangentless_curve_with_stated_delta_keeps_bearing_unset(parse):
    call, _ = parse(
        "THENCE along a curve to the right, radius of 100 feet, delta angle of 90 degrees, "
        "the chord of which bears N 45° E, 141.42 feet to a point"
    )
    assert call.bearing_azimuth_deg_from_north is None
    assert call.delta_deg == pytest.approx(90.0)
    assert call.chord_length_ft == pytest.approx(141.42)
    assert NOT_STATED in (call.notes or "")


def test_cardinal_only_tangentless_curve_keeps_cardinal_disclosure(parse):
    call, audit = parse(REPRO.replace("THENCE along", "THENCE northeasterly along"))
    assert call.bearing_azimuth_deg_from_north is None
    assert NOT_STATED in call.notes
    assert "stated direction is cardinal only (northeasterly)" in call.notes
    if audit is not None:
        assert "cardinal_only_direction" in audit.flags


def test_cardinal_chord_conflict_stays_flagged(parse):
    call, audit = parse(REPRO.replace("THENCE along", "THENCE southwesterly along"))
    assert call.bearing_azimuth_deg_from_north is None
    assert "stated direction (southwesterly) conflicts with chord bearing" in call.notes
    assert NOT_STATED not in call.notes
    assert call.is_indefinite is True
    if audit is not None:
        assert "cardinal_chord_conflict" in audit.flags


def test_stated_tangent_curve_is_unchanged(parse):
    call, _ = parse(REPRO.replace("THENCE along", "THENCE N 90° E along"))
    assert call.bearing_azimuth_deg_from_north == pytest.approx(90.0)
    assert NOT_STATED not in (call.notes or "")


# --- verification is numerically unchanged ----------------------------------
# Recorded before the change (azimuth then stored as chord +/- delta/2).
PARCELS = {
    "left-arc": (
        "BEGINNING at a point; " + REPRO + "; THENCE N 90° W 100 feet to a point; "
        "THENCE S 0° E 100 feet to the point of beginning.",
        0.00025973458523239186,
        7854.000000033732,
        357.08000000000004,
    ),
    "right-delta": (
        "BEGINNING at a point; THENCE N 0° E 100 feet to a point; THENCE along a curve to the "
        "right, radius of 100 feet, delta angle of 90 degrees, the chord of which bears N 45° E, "
        "141.42 feet to a point; THENCE S 0° E 200 feet to a point; THENCE N 90° W 100 feet to "
        "the point of beginning.",
        1.8369701987210297e-14,
        17853.981633974483,
        557.0796326794897,
    ),
}

BASELINE_CHECKS = {
    "traverse_closure": "passed",
    "interior_angles": "not_applicable",
    "parallelism": "not_applicable",
    "boundary_intersections": "passed",
    "area_reasonableness": "not_applicable",
    "double_entry": "not_applicable",
    "bearing_reversals": "passed",
    "distance_reasonableness": "passed",
}
EXTRACTORS = {"package": package_extract_calls, "monolith": CallExtractor.extract_calls}
VERIFIERS = {"package": package_verify, "monolith": ClosureChecker.verify_closure}


@pytest.mark.parametrize("verifier", VERIFIERS)
@pytest.mark.parametrize("extractor", EXTRACTORS)
@pytest.mark.parametrize("parcel", PARCELS)
def test_verification_of_tangentless_curve_is_numerically_unchanged(parcel, extractor, verifier):
    text, misclosure, area, perimeter = PARCELS[parcel]
    calls = EXTRACTORS[extractor](text, strict=True)
    assert all(c.bearing_azimuth_deg_from_north is None for c in calls if c.curve_dir is not None)
    result = VERIFIERS[verifier](calls)
    assert result.misclosure_ft == pytest.approx(misclosure, abs=1e-9)
    assert result.area_sq_ft == pytest.approx(area, abs=1e-9)
    assert result.perimeter_ft == pytest.approx(perimeter, abs=1e-9)
    checks = {c.name: c.status for c in result.checks}
    # The stated chord length (right-delta) is still cross-checked against R and delta.
    assert checks == {
        **BASELINE_CHECKS,
        "curve_consistency": "passed" if parcel == "right-delta" else "not_applicable",
    }
    assert result.geometry_verified is True
