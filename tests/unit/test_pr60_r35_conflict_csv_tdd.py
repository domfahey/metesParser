"""PR #60 round 35: verification derives direction conflicts from persisted fields.

is_indefinite is not a CSV column, so a cardinal/chord conflict (or chord > diameter)
must give identical flags, warnings, confidence and dashboard results from parser
text, the CSV round trip and a DeedCall built without the parser.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import mp_models
import pytest
from mp_bearing import cardinal_conflicts_bearing
from mp_export.csv_writer import calls_to_csv, csv_to_calls
from mp_models.dashboard import DashboardBundle
from mp_parse.calls import extract_calls as package_extract_calls
from mp_verify import verify_closure
from mp_verify.dashboard import calculate_dashboard
from mp_verify.traverse import chord_positioned_flags, is_chord_positioned

import metesparser.models as monolith_models
from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker

FIXTURES = Path(__file__).resolve().parents[2] / "packages/mp-review/tests/fixtures"
CONFLICT = (
    "thence northerly along a curve to the right having a radius of 200 feet, "
    "a chord bearing of S 45° E and a chord length of 100 feet"
)
DEED = (
    "BEGINNING at a pin; thence N 0° E 100 feet; " + CONFLICT + " to a point; "
    "thence S 0° E 100 feet; thence S 90° W 100 feet to the point of beginning."
)


def _roundtrip(calls):
    path = Path(tempfile.mkdtemp()) / "calls.csv"
    calls_to_csv(calls, str(path))
    return csv_to_calls(str(path))


def _summary(calls):
    result = verify_closure(calls)
    return chord_positioned_flags(calls), result.warnings, result.confidence_score


def test_helper_sector_rule():
    assert cardinal_conflicts_bearing("northerly", 135.0)
    assert not cardinal_conflicts_bearing("northerly", 67.5)
    assert not cardinal_conflicts_bearing("SW", 270.0)
    assert cardinal_conflicts_bearing("SW", 270.1)
    assert not cardinal_conflicts_bearing("due north", 135.0)
    assert not cardinal_conflicts_bearing("northerly", None)


def test_text_and_csv_paths_agree_on_conflict():
    calls = package_extract_calls(DEED, strict=False)[0]
    assert calls[1].is_indefinite is True
    trip = _roundtrip(calls)
    assert trip[1].is_indefinite is False
    text_flags, text_warn, text_conf = _summary(calls)
    csv_flags, csv_warn, csv_conf = _summary(trip)
    assert text_flags == csv_flags == [False, False, False, False]
    assert any("indefinite call(s) (courses 2)" in w for w in csv_warn)
    assert csv_warn == text_warn
    assert csv_conf == text_conf


def _bundle(**updates) -> DashboardBundle:
    raw = json.loads((FIXTURES / "dashboard-absolute.json").read_text())
    raw["calls"][1]["call"].update(
        bearing_azimuth_deg_from_north=None,
        bearing_quadrant=None,
        curve_dir="right",
        radius_ft=200.0,
        is_indefinite=False,
        **updates,
    )
    return DashboardBundle.model_validate(raw)


def test_dashboard_blocks_csv_style_conflict():
    bundle = _bundle(direction_text="northerly", chord_bearing="S 45° E", chord_length_ft=100.0)
    assert calculate_dashboard(bundle).calculations[0].geometry_status == "blocked"


def _direct(model=mp_models, **kw):
    base = {
        "course": 1,
        "direction_text": "northerly",
        "curve_dir": "right",
        "radius_ft": 200.0,
        "chord_bearing": "S 45° E",
        "chord_length_ft": 100.0,
        "distance_ft": 100.0,
    }
    base.update(kw)
    return model.DeedCall(**base)


def test_direct_call_conflict_not_chord_positioned():
    assert is_chord_positioned(_direct()) is False


def test_direct_call_chord_longer_than_diameter_not_chord_positioned():
    call = _direct(direction_text="southeasterly", chord_length_ft=500.0)
    assert is_chord_positioned(call) is False


def test_direct_call_nonconflicting_chord_only_unchanged():
    assert is_chord_positioned(_direct(direction_text="southeasterly")) is True
    assert is_chord_positioned(_direct(direction_text="easterly")) is True


def test_direct_conflict_warns_and_monolith_matches():
    mono = ClosureChecker.verify_closure([_direct(monolith_models)])
    pkg = verify_closure([_direct()])
    assert any("indefinite call(s)" in w for w in pkg.warnings)
    assert mono.warnings == pkg.warnings
    assert mono.confidence_score == pkg.confidence_score


@pytest.mark.parametrize("extract", [CallExtractor.extract_calls])
def test_monolith_text_matches_csv(extract):
    calls = extract(DEED, strict=False)
    assert calls[1].is_indefinite is True
    assert _summary(_roundtrip(calls)) == _summary(calls)
