"""PR #60 round 33: a course positioned by a stated chord is not a missing bearing.

has_determined_direction keeps meaning "tangent direction known". The dashboard,
confidence and parser decide on whether the course is positioned/stated instead:
chord-only curves and spirals with a stated chord bearing and length are drawn as
their chord (arc not drawn), score as stated direction at medium quality, and are
not marked indefinite (is_indefinite is not a CSV field, so text and CSV must agree).
"""

from __future__ import annotations

import json
from pathlib import Path

import mp_models
import pytest
from mp_export.csv_writer import calls_to_csv, csv_to_calls
from mp_models.dashboard import DashboardBundle
from mp_parse.calls import extract_calls as package_extract_calls
from mp_verify import verify_closure
from mp_verify.confidence import calculate_confidence_score, score_call_quality
from mp_verify.dashboard import calculate_dashboard
from mp_verify.tangents import has_determined_direction

import metesparser.models as monolith_models
from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker

FIXTURES = Path(__file__).resolve().parents[2] / "packages/mp-review/tests/fixtures"
SPIRAL = "along a spiral curve to the right, chord bearing N 20° E, chord distance of 100.00 feet"
CHORD_CURVE = (
    "along a curve to the right having a radius of 50 feet, "
    "chord bearing S 45° E, chord distance of 70.71 feet"
)
EXTRACT = {
    "package": lambda text: package_extract_calls(text, strict=False)[0],
    "monolith": lambda text: CallExtractor.extract_calls(text, strict=False),
}


def _deed(course: str) -> str:
    return (
        "BEGINNING at a pin; thence N 0° E 100 feet; thence "
        + course
        + " to a point; thence S 0° E 100 feet; thence S 90° W 100 feet "
        "to the point of beginning."
    )


def _chord_call(model=mp_models):
    return model.DeedCall(
        course=1,
        direction_text="curve",
        curve_dir="right",
        radius_ft=50.0,
        chord_bearing="S 45° E",
        chord_length_ft=70.71,
        distance_ft=70.71,
    )


def _bundle(**curve) -> DashboardBundle:
    raw = json.loads((FIXTURES / "dashboard-absolute.json").read_text())
    call = raw["calls"][1]["call"]
    call.update(bearing_azimuth_deg_from_north=None, bearing_quadrant=None)
    call.update(curve_dir="right", radius_ft=50.0, chord_bearing="N 90°00'00\" E", **curve)
    return DashboardBundle.model_validate(raw)


def test_has_determined_direction_keeps_tangent_meaning():
    assert has_determined_direction(_chord_call()) is False


def test_dashboard_chord_only_curve_is_analyzed_with_chord_drawn():
    bundle = _bundle(chord_length_ft=50.0)
    result = calculate_dashboard(bundle).calculations[0]
    assert result.geometry_status == "analyzed"
    assert not any("Incomplete recorded bearings" in w for w in result.warnings)
    assert any("arc not determined" in w.lower() and "chord only" in w for w in result.warnings)
    assert len(result.courses) == len([c for c in bundle.calls if c.call is not None])
    course = result.courses[1]
    assert course.local_azimuth_deg == pytest.approx(90.0)
    assert (course.delta_x_ft, course.delta_y_ft) == pytest.approx((50.0, 0.0), abs=1e-9)
    assert result.engine_verified is False
    assert result.verified_export_eligible is False


def test_dashboard_unpositioned_course_still_blocked_as_incomplete():
    raw = json.loads((FIXTURES / "dashboard-absolute.json").read_text())
    raw["calls"][1]["call"].update(
        bearing_azimuth_deg_from_north=None, bearing_quadrant=None, direction_text="northerly"
    )
    result = calculate_dashboard(DashboardBundle.model_validate(raw)).calculations[0]
    assert result.geometry_status == "blocked"
    assert any("Incomplete recorded bearings" in w for w in result.warnings)


def test_chord_positioned_course_counts_as_stated_but_lower_quality():
    call = _chord_call()
    assert score_call_quality(call) == "medium"
    straight = mp_models.DeedCall(
        course=1, direction_text="N 0° E", bearing_azimuth_deg_from_north=0.0, distance_ft=10.0
    )
    assert score_call_quality(straight) == "high"
    unpositioned = call.model_copy(update={"chord_bearing": None, "chord_length_ft": None})
    assert score_call_quality(unpositioned) == "low"
    result = verify_closure([call])
    assert calculate_confidence_score(result, [call]) > calculate_confidence_score(
        result, [unpositioned]
    )


def test_monolith_confidence_matches_package():
    mono = ClosureChecker.verify_closure([_chord_call(monolith_models)])
    assert mono.confidence_score == verify_closure([_chord_call()]).confidence_score


@pytest.mark.parametrize("course", [SPIRAL, CHORD_CURVE], ids=["spiral", "chord-curve"])
@pytest.mark.parametrize("impl", EXTRACT)
def test_chord_stated_course_is_not_indefinite_and_csv_roundtrips(impl, course, tmp_path):
    calls = EXTRACT[impl](_deed(course))
    assert calls[1].is_indefinite is False
    result = verify_closure(calls)
    assert not any("indefinite" in w for w in result.warnings)
    path = tmp_path / "calls.csv"
    calls_to_csv(calls, str(path))
    again = csv_to_calls(str(path))
    assert [c.is_indefinite for c in again] == [c.is_indefinite for c in calls]
    assert verify_closure(again).warnings == result.warnings


def test_unpositioned_chord_curve_stays_indefinite():
    calls = EXTRACT["package"](
        _deed(
            "along a curve to the right having a radius of 10 feet, "
            "chord bearing S 45° E, chord distance of 70.71 feet"
        )
    )
    assert calls[1].is_indefinite is True
