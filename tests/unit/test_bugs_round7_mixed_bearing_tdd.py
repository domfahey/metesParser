"""Round 7: bearings mixing degree/minute/second markers (word degrees + symbol minutes)."""

from __future__ import annotations

import itertools

import pytest
from mp_parse.calls import extract_single_call as package_single_call

from metesparser.call_extractor import CallExtractor
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


def _az(quad: str, d: int, m: int = 0, s: float = 0.0) -> float:
    v = d + m / 60 + s / 3600
    return {"NE": v, "SE": 180 - v, "SW": 180 + v, "NW": 360 - v}[quad]


# Forms found in sample_deeds (100 Haddon 4317-236).
SAMPLE_FORMS = {
    "North 34 degrees 02' 00\" West": _az("NW", 34, 2),
    "South 34 degrees 02' 00\" East": _az("SE", 34, 2),
    "North 55 degrees 58' 00\" East": _az("NE", 55, 58),
    "South 55 degrees 58' 00\" West": _az("SW", 55, 58),
}

# Synthetic combinations of degree x minute x second markers.
DEG = ["°", " degrees ", " degree ", " deg ", " deg. ", "d"]
MIN = ["'", "’", " minutes ", " min ", " min. ", "m"]
SEC = ['"', "″", "”", " seconds ", " sec ", " sec. ", "s"]
SYNTHETIC: dict[str, float] = {}
for _d, _m, _s in itertools.product(DEG, MIN, SEC):
    SYNTHETIC[" ".join(f"North 34{_d}02{_m}15{_s} West".split())] = _az("NW", 34, 2, 15)
for _d, _m in itertools.product(DEG, MIN):
    SYNTHETIC[" ".join(f"S 61{_d}05{_m} E".split())] = _az("SE", 61, 5)
SYNTHETIC["S 56 degrees 40' 30\" W"] = _az("SW", 56, 40, 30)
SYNTHETIC["N 12° 30 minutes 20 seconds E"] = _az("NE", 12, 30, 20)
SYNTHETIC["N 12 degrees 30' E"] = _az("NE", 12, 30)
SYNTHETIC["North 12 deg 30' 05.5\" East"] = _az("NE", 12, 30, 5.5)
SYNTHETIC["N 12° 30′ 05″ W"] = _az("NW", 12, 30, 5)

ALL_FORMS = {**SAMPLE_FORMS, **SYNTHETIC}


@pytest.mark.parametrize("entry", ENTRY_POINTS)
@pytest.mark.parametrize("form", ALL_FORMS)
def test_mixed_marker_bearings_parse(entry, form):
    call = ENTRY_POINTS[entry](f"THENCE {form} 100 feet to a point")
    assert call is not None
    assert call.bearing_azimuth_deg_from_north == pytest.approx(ALL_FORMS[form], abs=1e-9)
    assert not call.is_indefinite


# A number with no unit marker is ambiguous: no minutes/seconds may be invented.
@pytest.mark.parametrize("entry", ENTRY_POINTS)
@pytest.mark.parametrize(
    "form", ["North 34 degrees 02 West", "N 34° 02 W", "North 34 degrees 02 00 West"]
)
def test_unmarked_numbers_are_not_guessed(entry, form):
    call = ENTRY_POINTS[entry](f"THENCE {form} 100 feet to a point")
    if call is not None and call.bearing_azimuth_deg_from_north is not None:
        # only the whole-degree reading is acceptable; never 34 deg 02 min/sec
        assert call.bearing_azimuth_deg_from_north == pytest.approx(_az("NW", 34), abs=1e-9)
