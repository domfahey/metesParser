"""PR #60 round 23: a spiral stated only by chord bearing and chord length is representable.

Its radius and direction are not required (never invented); the course is positioned by
the stated chord, area/perimeter are not determined and the arc check stays blocked.
Circular curves without a radius are still rejected.
"""

from __future__ import annotations

import mp_models
import pytest
from mp_models.plot_request import PlotCall, PlotRequest
from mp_parse.calls import extract_calls as package_extract_calls
from mp_parse.calls import extract_single_call as package_extract_single_call
from mp_verify.closure import verify_closure as package_verify
from mp_verify.plot import prepare_plot
from pydantic import ValidationError

from metesparser import models as monolith_models
from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker

COURSE = "along a spiral curve to the right, chord bearing N 20° E, chord distance of 100.00 feet"
DEED = (
    "BEGINNING at a pin; thence N 0° E 100 feet; thence "
    + COURSE
    + " to a point; thence S 0° E 100 feet; thence S 90° W 100 feet to the point of beginning."
)
NOTE = "spiral positioned by its stated chord only; radius not stated"

MODELS = {"package": mp_models, "monolith": monolith_models}
EXTRACT_SINGLE = {
    "package": package_extract_single_call,
    "monolith": CallExtractor.extract_single_call,
}
EXTRACT_CALLS = {
    "package": lambda text, strict: package_extract_calls(text, strict=strict)[0],
    "monolith": lambda text, strict: CallExtractor.extract_calls(text, strict=strict),
}
VERIFY = {"package": package_verify, "monolith": ClosureChecker.verify_closure}


@pytest.mark.parametrize("with_dir", [False, True], ids=["no-dir", "dir"])
@pytest.mark.parametrize("impl", MODELS)
def test_chord_only_spiral_constructs(impl, with_dir):
    extra = {"curve_dir": "right"} if with_dir else {}
    call = MODELS[impl].DeedCall(
        course=1,
        direction_text="spiral",
        curve_type="spiral",
        chord_bearing="N 20° E",
        chord_length_ft=100.0,
        distance_ft=100.0,
        **extra,
    )
    assert call.radius_ft is None
    assert call.distance_ft == 100.0


@pytest.mark.parametrize(
    "overrides",
    [
        {"curve_type": "spiral", "chord_length_ft": 100.0},
        {"curve_type": "spiral", "curve_dir": "right", "delta_deg": 5.0},
        {"chord_bearing": "N 20° E", "chord_length_ft": 100.0},
        {"curve_dir": "right", "chord_bearing": "N 20° E", "chord_length_ft": 100.0},
        {"curve_type": "circular", "chord_bearing": "N 20° E", "chord_length_ft": 100.0},
    ],
    ids=[
        "spiral-length-only",
        "spiral-delta-no-radius",
        "untyped-chord",
        "untyped-chord-dir",
        "circular-chord",
    ],
)
@pytest.mark.parametrize("impl", MODELS)
def test_other_curves_without_radius_stay_rejected(impl, overrides):
    with pytest.raises(ValidationError):
        MODELS[impl].DeedCall(course=1, direction_text="x", distance_ft=100.0, **overrides)


@pytest.mark.parametrize("impl", EXTRACT_SINGLE)
def test_single_call_parses_chord_only_spiral(impl):
    call = EXTRACT_SINGLE[impl](COURSE, 1)
    assert call is not None
    assert call.curve_type == "spiral"
    assert call.radius_ft is None
    assert call.chord_bearing == "N 20° E"
    assert call.chord_length_ft == pytest.approx(100.0)
    assert call.distance_ft == pytest.approx(100.0)
    assert NOTE in (call.notes or "")
    assert (call.notes or "").count("positioned by") == 1


@pytest.mark.parametrize("strict", [True, False], ids=["strict", "non-strict"])
@pytest.mark.parametrize("impl", EXTRACT_CALLS)
def test_calls_parse_chord_only_spiral(impl, strict):
    calls = EXTRACT_CALLS[impl](DEED, strict)
    assert [c.course for c in calls] == [1, 2, 3, 4]
    assert calls[1].distance_ft == pytest.approx(100.0)
    assert calls[1].radius_ft is None
    assert NOTE in (calls[1].notes or "")


@pytest.mark.parametrize("impl", EXTRACT_CALLS)
def test_circular_curve_chord_without_radius_is_not_a_spiral(impl):
    text = DEED.replace("spiral curve", "curve")
    try:
        calls = EXTRACT_CALLS[impl](text, False)
    except ValueError:
        return
    assert all(NOTE not in (c.notes or "") for c in calls)
    assert all(c.curve_type != "spiral" for c in calls)


@pytest.mark.parametrize("impl", EXTRACT_CALLS)
def test_verification_positions_spiral_by_chord_without_certifying_arc(impl):
    calls = EXTRACT_CALLS[impl](DEED, False)
    result = VERIFY[impl](calls)
    assert result.misclosure_available
    assert not result.area_available
    assert not result.perimeter_available
    assert not result.geometry_verified
    curve = next(c for c in result.checks if c.name == "curve_consistency")
    assert curve.status == "blocked"
    assert any("spiral_geometry_unverified" in str(v) for v in vars(curve).values()) or any(
        "Spiral geometry is not verified" in w for w in result.warnings
    )


def test_plot_places_chord_only_spiral_by_chord():
    calls = package_extract_calls(DEED, strict=False)[0]
    request = PlotRequest(
        title="t", calls=tuple(PlotCall(id=f"c{c.course}", call=c) for c in calls)
    )
    geometry = prepare_plot(request).geometry
    assert [u.call_id for u in geometry.unresolved] == ["c2"]
    assert "positioned by stated chord only" in geometry.unresolved[0].reason
