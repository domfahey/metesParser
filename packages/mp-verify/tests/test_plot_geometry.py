"""Hand-computed analytic plots, independent of verifier traverse shortcuts."""

import json
import math
from pathlib import Path

import pytest
from mp_models.dashboard import DashboardBundle
from mp_verify.dashboard import _calculate
from mp_verify.plot import arc_point, build_dashboard_plots

FIXTURE = Path(__file__).parents[2] / "mp-review/tests/fixtures/dashboard-absolute.json"


def make_bundle(calls=None):
    data = json.loads(FIXTURE.read_text())
    data["scenarios"] = []
    if calls is not None:
        data["evidence"] = []
        data["calls"] = [
            {
                "id": f"call-{i}",
                "occurrence_id": data["occurrences"][0]["id"],
                "page_id": data["pages"][0]["id"],
                "quote": f"Course {i}",
                "reading_status": "certain",
                "call": dict(
                    {"course": i, "direction_text": "recorded", "distance_ft": 10}, **call
                ),
            }
            for i, call in enumerate(calls, 1)
        ]
    return DashboardBundle.model_validate(data)


def plot(bundle):
    return build_dashboard_plots(
        bundle, tuple(_calculate(bundle, s) for s in bundle.calculations)
    ).geometries[0]


def test_open_gap_is_not_closed_or_adjusted():
    bundle = make_bundle(
        [
            {"bearing_azimuth_deg_from_north": a, "distance_ft": d}
            for a, d in [(90, 100), (180, 60), (270, 100), (0, 59.8)]
        ]
    )
    geometry = plot(bundle)
    assert len(geometry.primitives) == 4
    assert geometry.misclosure_ft == pytest.approx(0.2)
    assert geometry.primitives[-1].end == pytest.approx((0, -0.2))


def test_unknown_middle_call_stops_anchored_chain():
    bundle = make_bundle(
        [{"bearing_azimuth_deg_from_north": 0}, {}, {"bearing_azimuth_deg_from_north": 90}]
    )
    before = bundle.model_dump_json()
    geometry = plot(bundle)
    assert len(geometry.primitives) == 1
    assert [u.call_id for u in geometry.unresolved] == ["call-2", "call-3"]
    assert geometry.completeness == "partial"
    assert geometry.area_sq_ft is None and geometry.misclosure_ft is None
    assert before == bundle.model_dump_json()


@pytest.mark.parametrize("direction,sign", [("right", 1), ("left", -1)])
def test_right_quarter_circle_uses_arc_geometry(direction, sign):
    geometry = plot(
        make_bundle(
            [
                {
                    "bearing_azimuth_deg_from_north": 0,
                    "curve_dir": direction,
                    "radius_ft": 100,
                    "delta_deg": 90,
                }
            ]
        )
    )
    arc = geometry.primitives[0]
    assert arc.kind == "arc"
    assert arc.center == pytest.approx((sign * 100, 0))
    assert arc.end == pytest.approx((sign * 100, 100))
    assert arc.length_ft == pytest.approx(50 * math.pi)
    assert arc_point(arc, 0.5) == pytest.approx(
        (sign * (100 - 100 / math.sqrt(2)), 100 / math.sqrt(2))
    )


def test_left_quarter_circle_and_chord_semantics():
    arc = plot(
        make_bundle(
            [{"curve_dir": "left", "radius_ft": 100, "delta_deg": 90, "chord_bearing": "N 45° W"}]
        )
    ).primitives[0]
    assert arc.start_tangent_deg == pytest.approx(0)
    assert arc.end == pytest.approx((-100, 100))


def test_underdetermined_curve_has_no_straight_fallback():
    g = plot(make_bundle([{"curve_dir": "right", "radius_ft": 100, "delta_deg": 90}]))
    assert not g.primitives and g.unresolved


@pytest.mark.parametrize("extras", [{"arc_length_ft": 100}, {"chord_length_ft": 100}])
def test_conflicting_curve_elements_withhold_arc(extras):
    g = plot(
        make_bundle(
            [
                dict(
                    bearing_azimuth_deg_from_north=0,
                    curve_dir="right",
                    radius_ft=100,
                    delta_deg=90,
                    **extras,
                )
            ]
        )
    )
    assert not g.primitives
    assert "inconsistent" in g.unresolved[0].reason


@pytest.mark.parametrize("flag", ["is_exception", "is_meander"])
def test_unsupported_components_have_explicit_notices(flag):
    g = plot(make_bundle([dict(bearing_azimuth_deg_from_north=0, **{flag: True})]))
    assert not g.primitives and g.unresolved


def test_relative_angle_geometry_retains_arbitrary_frame():
    data = json.loads((FIXTURE.parent / "dashboard-relative.json").read_text())
    bundle = DashboardBundle.model_validate(data)
    g = plot(bundle)
    assert len(g.primitives) == 4 and g.completeness == "complete"
    assert all(c.call.bearing_azimuth_deg_from_north is None for c in bundle.calls)


def test_relative_origin_is_preserved_and_gap_is_a_vector():
    data = json.loads((FIXTURE.parent / "dashboard-relative.json").read_text())
    data["calculations"][0]["relative"]["frame"]["origin"] = [1200.0, -250.0]
    geometry = plot(DashboardBundle.model_validate(data))
    assert geometry.primitives[0].start == (1200, -250)
    assert geometry.primitives[-1].end == pytest.approx((1200, -250))
    assert geometry.misclosure_ft == pytest.approx(0, abs=1e-10)


@pytest.mark.parametrize(
    "elements", [{}, {"curve_dir": "right", "radius_ft": 100, "delta_deg": 90}]
)
def test_spiral_type_is_never_fabricated_as_line_or_circular_arc(elements):
    geometry = plot(
        make_bundle([dict(bearing_azimuth_deg_from_north=0, curve_type="spiral", **elements)])
    )
    assert not geometry.primitives
    assert "spiral" in geometry.unresolved[0].reason


def test_conflicting_tangent_and_chord_orientation_withholds_arc():
    geometry = plot(
        make_bundle(
            [
                {
                    "bearing_azimuth_deg_from_north": 0,
                    "curve_dir": "right",
                    "radius_ft": 100,
                    "delta_deg": 90,
                    "chord_bearing": "S 45° E",
                }
            ]
        )
    )
    assert not geometry.primitives
    assert "inconsistent" in geometry.unresolved[0].reason


def test_consistent_tangent_and_chord_orientation_uses_circular_residual():
    geometry = plot(
        make_bundle(
            [
                {
                    "bearing_azimuth_deg_from_north": 350,
                    "curve_dir": "right",
                    "radius_ft": 100,
                    "delta_deg": 90,
                    "chord_bearing": "N 35° E",
                }
            ]
        )
    )
    assert geometry.primitives[0].start_tangent_deg == pytest.approx(350)


def _second_precision_curve(chord_bearing):
    delta = 45 + 15 / 60 + 15 / 3600  # 45 deg 15' 15"
    return make_bundle(
        [
            {
                "bearing_azimuth_deg_from_north": 0,
                "curve_dir": "right",
                "radius_ft": 100,
                "delta_deg": delta,
                "chord_bearing": chord_bearing,
            }
        ]
    )


def test_second_precision_chord_bearing_agrees_with_tangent():
    # True half-delta is 22 deg 37' 37.5"; the deed states whole seconds.
    geometry = plot(_second_precision_curve("N 22°37'38\" E"))
    assert geometry.primitives
    assert not geometry.unresolved


def test_one_arcminute_tangent_chord_disagreement_still_rejected():
    geometry = plot(_second_precision_curve("N 22°38'38\" E"))
    assert not geometry.primitives
    assert "inconsistent" in geometry.unresolved[0].reason
