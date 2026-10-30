"""Round 15: cardinal-only curves with a chord bearing and delta/arc."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from mp_models import AuditContext, RunMetadata
from mp_parse.calls import extract_single_call as package_single_call

from metesparser.call_extractor import CallExtractor
from tests.fixtures.package_parser import extract_calls as package_extract_calls

CLOSING = "; THENCE due South 50 feet; THENCE due West 50 feet to the point of beginning."


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
        return call, ctx.call_audits[0].flags

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


CURVE = (
    "THENCE {word} along a curve to the left having a radius of 100.00 feet, "
    "an arc length of 50.00 feet, the chord of which bears {chord} 49.48 feet"
)


def test_consistent_cardinal_with_chord_keeps_tangent_unstated_with_clear_note(parse):
    call, flags = parse(CURVE.format(word="Northeasterly", chord="N 45°00'00\" E"))
    assert call is not None
    # Round 21: no tangent is derived or stored; the chord and delta position it.
    assert call.bearing_azimuth_deg_from_north is None
    assert call.is_indefinite is False
    assert (
        "tangent bearing not stated - curve positioned by chord and delta in verification"
        in call.notes
    )
    assert "stated direction is cardinal only (northeasterly)" in call.notes
    assert "incomplete bearing" not in call.notes
    if flags is not None:
        assert "incomplete_bearing" not in flags
        assert "cardinal_only_direction" in flags


def test_conflicting_cardinal_and_chord_is_flagged_without_tangent(parse):
    call, flags = parse(CURVE.format(word="Southwesterly", chord="N 45°00'00\" E"))
    assert call is not None
    assert call.bearing_azimuth_deg_from_north is None
    assert "stated direction (southwesterly) conflicts with chord bearing" in call.notes
    assert "tangent bearing derived" not in call.notes
    assert call.chord_bearing is not None
    if flags is not None:
        assert "incomplete_bearing" in flags
        assert "cardinal_chord_conflict" in flags


@pytest.mark.parametrize(
    ("word", "chord", "conflict"),
    [
        ("Northerly", "N 60°00'00\" E", False),
        ("Northerly", "N 80°00'00\" E", True),
        ("Southeasterly", "S 10°00'00\" E", False),
        ("Southeasterly", "S 50°00'00\" W", True),
    ],
)
def test_sector_rule_boundaries(parse, word, chord, conflict):
    call, _ = parse(CURVE.format(word=word, chord=chord))
    assert call is not None
    assert ("conflicts with chord bearing" in call.notes) is conflict
    # No tangent is stored either way (round 21); a conflict leaves it unpositioned.
    assert call.bearing_azimuth_deg_from_north is None
    assert call.is_indefinite is conflict


def test_plain_cardinal_only_line_unchanged(parse):
    call, flags = parse("THENCE southwesterly 100.00 feet")
    assert call is not None
    assert call.bearing_azimuth_deg_from_north is None
    assert call.notes == "incomplete bearing - cardinal only"
    if flags is not None:
        assert "incomplete_bearing" in flags
        assert "cardinal_only_direction" not in flags
