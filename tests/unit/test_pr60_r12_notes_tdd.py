"""Round 12: the cardinal-only marker survives every other note branch."""

from __future__ import annotations

import pytest
from mp_parse.calls import extract_single_call as package_single_call

from metesparser.call_extractor import CallExtractor
from tests.fixtures.package_parser import extract_calls as package_extract_calls

CLOSING = "; THENCE due South 50 feet; THENCE due West 50 feet to the point of beginning."
MARKER = "incomplete bearing - cardinal only"

ENTRY_POINTS = {
    "package-calls": lambda t: package_extract_calls(t + CLOSING, strict=True)[0],
    "monolith-calls": lambda t: CallExtractor.extract_calls(t + CLOSING, strict=True)[0],
    "package-single": lambda t: package_single_call(t, 1),
    "monolith-single": lambda t: CallExtractor.extract_single_call(t, 1),
}


@pytest.fixture(params=sorted(ENTRY_POINTS))
def parse(request):
    return ENTRY_POINTS[request.param]


CURVE = "along a curve to the right having a radius of 100.00 feet, "
CASES = {
    "meander": (
        "Thence southerly along the meanders of the creek 100 feet",
        ["meander / approximate"],
    ),
    "approximate": ("Thence southerly approximately 100 feet", ["meander / approximate"]),
    "meander-chord": (
        "Thence southwesterly along the meanders of a creek, a curve to the right having a "
        "radius of 100.00 feet, the chord of which bears S 40°00'00\" W, 50.00 feet",
        ["meander / approximate", "positioned by chord only"],
    ),
    "chord-only": (
        f"Thence southwesterly {CURVE}the chord of which bears S 40°00'00\" W, 50.00 feet",
        ["positioned by chord only"],
    ),
    "derived-tangent": (
        f"Thence southwesterly {CURVE}a delta of 20°00'00\", "
        "the chord of which bears S 40°00'00\" W, 34.73 feet",
        ["tangent bearing derived from chord bearing and delta"],
    ),
    "plain": ("Thence southerly 100 feet", []),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_cardinal_marker_kept_with_other_notes(parse, name):
    text, others = CASES[name]
    call = parse(text)
    assert call is not None
    assert call.notes is not None and MARKER in call.notes
    for other in others:
        assert other in call.notes


def test_tangent_and_chord_note_needs_stated_bearing_so_no_cardinal_marker(parse):
    # A stated tangent bearing is a real bearing: that branch cannot be cardinal-only.
    call = parse(
        f"Thence southwesterly {CURVE}tangent bearing S 30°00'00\" W, "
        "the chord of which bears S 40°00'00\" W, 50.00 feet"
    )
    assert "positioned by stated tangent and chord" in call.notes
    assert MARKER not in call.notes
