"""Round 14: strict-mode malformed-course gates use the same curve words as parsing."""

from __future__ import annotations

import pytest

from metesparser.call_extractor import CallExtractor
from tests.fixtures.package_parser import extract_calls as package_extract_calls
from tests.unit.test_pr60_r8_calls_tdd import CLOSING

ENTRY = {
    "package": lambda t, tail="": package_extract_calls(t + tail, strict=True),
    "monolith": lambda t, tail="": CallExtractor.extract_calls(t + tail, strict=True),
}
WORDS = ["curve", "curved", "curving"]


@pytest.mark.parametrize("entry", sorted(ENTRY))
@pytest.mark.parametrize("word", WORDS)
@pytest.mark.parametrize("tail", ["50 feet to a pin", "line 50.00 feet to a pin"])
def test_strict_rejects_malformed_curve_course(entry, word, tail):
    # No radius/arc/bearing: the course parses to None and the strict gate must flag it.
    with pytest.raises(ValueError, match="Malformed course"):
        ENTRY[entry](f"{word} {tail}")


@pytest.mark.parametrize("entry", sorted(ENTRY))
@pytest.mark.parametrize("word", WORDS)
def test_strict_well_formed_curve_parses(entry, word):
    calls = ENTRY[entry](
        f"thence (2) along Euclid Avenue, {word} to the right having a radius of 565.45 feet, "
        "an arc distance of 304.57 feet to a set iron pin",
        CLOSING,
    )
    assert any(c.radius_ft == pytest.approx(565.45) for c in calls)
