"""Round 13: curve wording variants ('curving to the right', 'arc distance', no 'of').

The 89 Haddon Ave course 2 ("... curving to the right having a radius of 565.45 feet,
an arc distance of 304.57 feet ...") used to parse as a cardinal-only straight call whose
distance was the radius. Stated radius/arc/direction are recorded; with no stated tangent,
chord or delta the bearing stays None (never fabricated).
"""

from __future__ import annotations

import pytest
from mp_parse.calls import extract_single_call as package_single_call

from metesparser.call_extractor import CallExtractor
from tests.fixtures.package_parser import extract_calls as package_extract_calls
from tests.unit.test_pr60_r8_calls_tdd import CLOSING

SAMPLE = (
    "thence (2) in a Northeastwardly direction along the Southeasterly and southerly curved line "
    "of Euclid Avenue, curving to the right having a radius of 565.45 feet, an arc distance "
    "of 304.57 feet to a set iron pin"
)

DIRECTION = [
    "curving to the right",
    "curving to the left",
    "curve to the right",
    "curved to the left",
]
RADIUS = ["having a radius of 565.45 feet", "radius of 565.45 feet", "a radius 565.45 feet"]
ARC = [
    "an arc distance of 304.57 feet",
    "an arc distance 304.57 feet",
    "an arc length of 304.57 feet",
    "an arc of 304.57 feet",
    "a distance along the arc of 304.57 feet",
]

CASES = [(SAMPLE, "right")]
for _d in DIRECTION:
    for _r in RADIUS:
        for _a in ARC:
            for _sep in (", ", " "):
                text = f"thence (2) along Euclid Avenue, {_d} {_r}{_sep}{_a} to a set iron pin"
                CASES.append((text, "left" if "left" in _d else "right"))

ENTRY = {
    "package-calls": lambda t: package_extract_calls(t + CLOSING, strict=True)[0],
    "monolith-calls": lambda t: CallExtractor.extract_calls(t + CLOSING, strict=True)[0],
    "package-single": lambda t: package_single_call(t, 1),
    "monolith-single": lambda t: CallExtractor.extract_single_call(t, 1),
}


@pytest.mark.parametrize("entry", sorted(ENTRY))
@pytest.mark.parametrize(("text", "side"), CASES)
def test_curving_phrasings_record_radius_arc_and_direction(entry, text, side):
    call = ENTRY[entry](text)
    assert call is not None
    assert call.radius_ft == pytest.approx(565.45)
    assert call.arc_length_ft == pytest.approx(304.57)
    assert call.curve_dir == side
    assert call.distance_ft == pytest.approx(304.57)
    assert call.bearing_azimuth_deg_from_north is None


@pytest.mark.parametrize("entry", sorted(ENTRY))
def test_plain_curved_line_without_radius_stays_straight(entry):
    call = ENTRY[entry](
        "thence (2) N 10° E along the curved line of Euclid Avenue, 50.00 feet to a pin"
    )
    assert call is not None
    assert call.radius_ft is None
    assert call.arc_length_ft is None
