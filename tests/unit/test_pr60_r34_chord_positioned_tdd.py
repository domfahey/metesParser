"""PR #60 round 34: a conflicting-direction course is not chord-positioned.

A cardinal word that conflicts with the stated chord bearing leaves the course
indefinite; it must not count as a stated direction in the dashboard or confidence.
"""

from __future__ import annotations

import json
from pathlib import Path

import mp_models
import mp_verify.closure as closure
import mp_verify.dashboard as pkg_dashboard
import mp_verify.traverse as traverse
import pytest
from mp_models.dashboard import DashboardBundle
from mp_parse.calls import extract_calls as package_extract_calls
from mp_verify import verify_closure
from mp_verify.confidence import calculate_confidence_score, score_call_quality
from mp_verify.dashboard import calculate_dashboard
from mp_verify.traverse import is_chord_positioned

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
EXTRACT = {
    "package": lambda text: package_extract_calls(text, strict=False)[0],
    "monolith": lambda text: CallExtractor.extract_calls(text, strict=False),
}


def _conflict_call(model=mp_models):
    return model.DeedCall(
        course=1,
        direction_text="northerly",
        curve_dir="right",
        radius_ft=200.0,
        chord_bearing="S 45° E",
        chord_length_ft=100.0,
        distance_ft=100.0,
        is_indefinite=True,
        notes="incomplete bearing - cardinal only",
    )


@pytest.mark.parametrize("impl", EXTRACT)
def test_parser_marks_conflict_indefinite(impl):
    assert EXTRACT[impl](DEED)[1].is_indefinite is True


def test_conflicting_course_is_not_chord_positioned():
    assert is_chord_positioned(_conflict_call()) is False


def test_confidence_does_not_count_conflicting_course_as_stated():
    call = _conflict_call()
    assert score_call_quality(call) == "low"
    clear = call.model_copy(update={"is_indefinite": False, "notes": None})
    result = verify_closure([call])
    assert calculate_confidence_score(result, [call]) < calculate_confidence_score(
        verify_closure([clear]), [clear]
    )


def test_monolith_confidence_matches_package():
    mono = ClosureChecker.verify_closure([_conflict_call(monolith_models)])
    assert mono.confidence_score == verify_closure([_conflict_call()]).confidence_score


def _bundle() -> DashboardBundle:
    raw = json.loads((FIXTURES / "dashboard-absolute.json").read_text())
    raw["calls"][1]["call"].update(
        bearing_azimuth_deg_from_north=None,
        bearing_quadrant=None,
        direction_text="northerly",
        curve_dir="right",
        radius_ft=200.0,
        chord_bearing="S 45° E",
        chord_length_ft=100.0,
        is_indefinite=True,
        notes="incomplete bearing - cardinal only",
    )
    return DashboardBundle.model_validate(raw)


def test_dashboard_blocks_conflicting_direction():
    # The monolith dashboard is a facade over mp_review/mp_verify: one implementation.
    result = calculate_dashboard(_bundle()).calculations[0]
    assert result.geometry_status == "blocked"
    assert any("Incomplete recorded bearings" in w for w in result.warnings)


def test_dashboard_analyzes_courses_once_beyond_verification(monkeypatch):
    raw = json.loads((FIXTURES / "dashboard-absolute.json").read_text())
    bundle = DashboardBundle.model_validate(raw)
    count = 0
    real = traverse.analyze_courses

    def spy(*args, **kwargs):
        nonlocal count
        count += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(traverse, "analyze_courses", spy)
    monkeypatch.setattr(closure, "analyze_courses", spy)
    monkeypatch.setattr(pkg_dashboard, "analyze_courses", spy, raising=False)
    calculate_dashboard(bundle)
    # one pass inside verify_closure plus at most one shared pass for the dashboard
    assert count <= 2
