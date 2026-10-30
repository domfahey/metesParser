"""PR #60 round 40: record calls never steal the course length (monolith facade).

The monolith ``CallExtractor`` delegates to ``mp_parse``; a parenthetical or
bracketed record call, a lone labelled pair and (R)/(M) pairs read exactly as in
the package, with record wording kept verbatim in notes.
"""

from __future__ import annotations

import pytest

from metesparser.call_extractor import CallExtractor

CASES = [
    ("thence N 45° E (deed N 44° E) 100 feet", 45.0, 100.0, "record call: (deed N 44° E)"),
    ("thence N 45° E 100 feet (R) to a pin", 45.0, 100.0, None),
    (
        "thence N 45°10' E 100.00 feet (R), N 45°05' E 100.05 feet (M) to a pin",
        45.0 + 5.0 / 60.0,
        100.05,
        "record call: N 45°10' E 100.00 feet (R)",
    ),
    (
        "thence N 45° E 100.00 feet (deed 99.5 feet) to a pin",
        45.0,
        100.0,
        "record call: (deed 99.5 feet)",
    ),
]


@pytest.mark.parametrize(("fragment", "azimuth", "distance", "notes"), CASES)
def test_monolith_record_call_course(
    fragment: str, azimuth: float, distance: float, notes: str | None
) -> None:
    call = CallExtractor.extract_single_call(fragment, 1)
    assert call is not None
    assert call.bearing_azimuth_deg_from_north == pytest.approx(azimuth)
    assert call.distance_ft == pytest.approx(distance)
    assert call.notes == notes
