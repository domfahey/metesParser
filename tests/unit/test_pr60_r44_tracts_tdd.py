"""PR #60 round 44: the monolith facade keeps strip exceptions and easements off the boundary."""

from __future__ import annotations

import pytest
from mp_models import UNAPPLIED_EXCEPTION_NOTE_PREFIX

from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker

SQUARE = (
    "BEGINNING at a pin; thence N 0° E 100 feet to a pin; thence S 90° E 100 feet to a pin; "
    "thence S 0° W 100 feet to a pin; thence N 90° W 100 feet to the point of beginning."
)
EASEMENT = (
    " Together with an easement 10 feet wide, BEGINNING at a stake; "
    "thence N 5° E 20 feet; thence S 85° E 10 feet."
)


def _boundary(calls):
    return [
        (c.course, c.bearing_azimuth_deg_from_north, c.distance_ft, c.is_exception) for c in calls
    ]


@pytest.mark.parametrize(
    "strip",
    [" EXCEPTING the westerly 10 feet thereof.", " LESS AND EXCEPT the north 10 feet thereof."],
)
def test_monolith_strip_exception_is_noted_not_traversed(strip) -> None:
    square = CallExtractor.extract_calls(SQUARE)
    calls = CallExtractor.extract_calls(SQUARE + strip)
    assert _boundary(calls) == _boundary(square)
    assert calls[-1].notes == UNAPPLIED_EXCEPTION_NOTE_PREFIX + strip.strip().rstrip(".")
    result = ClosureChecker.verify_closure(calls)
    assert result.closure_passed and not result.is_fully_verified()
    assert ClosureChecker.verify_closure(square).is_fully_verified()


def test_monolith_easement_legs_stay_off_the_boundary() -> None:
    square = CallExtractor.extract_calls(SQUARE)
    calls = CallExtractor.extract_calls(SQUARE + EASEMENT)
    assert _boundary(calls) == _boundary(square)
    assert EASEMENT.strip() in (calls[-1].notes or "")
    assert ClosureChecker.verify_closure(calls).closure_passed
