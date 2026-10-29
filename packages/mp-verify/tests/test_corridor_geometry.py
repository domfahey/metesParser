"""Independent corridor construction, provenance and failure acceptance."""

import copy
import math

import pytest
from mp_models.corridor import CorridorRequest, CorridorResult
from mp_verify.corridor import analyze_corridor, validate_corridor_result


def line(id="road", distance=100, bearing=90):
    return {
        "id": id,
        "source_reference": "deed page 3 " + id,
        "quote": "  original " + id + "  ",
        "call": {
            "course": 1,
            "direction_text": "recorded course",
            "distance_ft": distance,
            "bearing_azimuth_deg_from_north": bearing,
        },
    }


def arc(id="road", radius=100, sweep=90, tangent=0, direction="right"):
    record = line(id, radius * math.radians(sweep), tangent)
    record["call"].update(
        curve_dir=direction,
        radius_ft=radius,
        delta_deg=sweep,
        arc_length_ft=radius * math.radians(sweep),
    )
    return record


def width(
    id="width",
    start="road",
    end=None,
    left=(20, 20),
    right=(10, 10),
    rule="step",
    start_fraction=0,
    end_fraction=1,
):
    return {
        "id": id,
        "start": {"call_id": start, "fraction": start_fraction},
        "end": {"call_id": end or start, "fraction": end_fraction},
        "left_start": left[0],
        "left_end": left[1],
        "right_start": right[0],
        "right_end": right[1],
        "rule": rule,
        "source_refs": [{"source_id": "deed", "page": 3, "quote": "  widths " + id + "  "}],
    }


def request(calls=None, widths=None, cap="butt", join="bevel", error=0.01):
    calls = calls or [line()]
    return CorridorRequest.model_validate(
        {
            "id": "easement",
            "centerline": {
                "calculation_id": "centerline",
                "title": "utility centerline",
                "foot_definition": "international_ft",
                "calls": calls,
            },
            "widths": widths
            if widths is not None
            else [width(start=calls[0]["id"], end=calls[-1]["id"])],
            "width_unit": "international_ft",
            "join": join,
            "cap": cap,
            "construction_source_refs": [{"source_id": "survey", "quote": "join and cap evidence"}],
            "error_budget": {"max_error": error, "unit": "international_ft", "max_segments": 2048},
        }
    )


def area(result):
    assert result.availability == "supported", result.limitations
    return result.boundary.geometry.area_sq_ft


def test_straight_asymmetric_strip_retains_full_canonical_definition():
    req = request()
    before = req.model_dump_json()
    result = analyze_corridor(req)
    assert area(result) == pytest.approx(3000)
    assert min(p[1] for p in result.polygon) == pytest.approx(-10)
    assert max(p[1] for p in result.polygon) == pytest.approx(20)
    assert result.centerline.geometry.misclosure_ft == pytest.approx(100)
    assert result.request == req and req.model_dump_json() == before
    assert result.request.widths[0].source_refs[0].quote == "  widths width  "
    assert result.boundary_edges and all(edge.width_interval_ids for edge in result.boundary_edges)
    assert not result.engine_verified and not result.verified_export_eligible
    assert result.error.total_bound <= req.error_budget.max_error
    assert (
        validate_corridor_result(CorridorResult.model_validate_json(result.model_dump_json()))
        == result
    )


@pytest.mark.parametrize(
    "cap,expected", [("butt", 3000), ("square", 3900), ("round", 3000 + math.pi * 15**2)]
)
def test_cap_construction_has_declared_effect_for_asymmetric_widths(cap, expected):
    result = analyze_corridor(request(cap=cap, error=0.0005))
    assert area(result) == pytest.approx(expected, abs=0.1)
    if cap == "square":
        assert min(p[0] for p in result.polygon) == pytest.approx(-15)
        assert max(p[0] for p in result.polygon) == pytest.approx(115)


def test_reverse_traversal_with_side_swap_reproduces_asymmetric_strip():
    forward = analyze_corridor(request())
    reverse = analyze_corridor(request([line(bearing=270)], [width(left=(10, 10), right=(20, 20))]))
    shifted = {(round(x + 100, 8), round(y, 8)) for x, y in reverse.polygon}
    assert shifted == {(round(x, 8), round(y, 8)) for x, y in forward.polygon}
    assert area(reverse) == pytest.approx(area(forward))


def test_straight_taper_uses_endpoint_widths_without_per_course_average_geometry():
    req = request(widths=[width(left=(10, 30), right=(5, 15), rule="linear_taper")])
    result = analyze_corridor(req)
    assert area(result) == pytest.approx(3000)
    points = result.polygon
    assert any(math.dist(p, (0, 10)) < 1e-8 for p in points)
    assert any(math.dist(p, (100, 30)) < 1e-8 for p in points)
    assert result.request.widths[0].left_start == 10 and result.request.widths[0].left_end == 30


def test_circular_offsets_have_independently_computed_annular_sector_area():
    result = analyze_corridor(request([arc()], error=0.0005))
    expected = math.pi / 4 * (120**2 - 90**2)
    assert area(result) == pytest.approx(expected, abs=0.2)
    assert result.error.linearization_bound > 0
    assert result.error.method == "second_derivative_chord_bound"


def test_curved_taper_has_declared_pointwise_error_bound():
    req = request([arc()], [width(left=(10, 30), right=(5, 15), rule="linear_taper")], error=0.002)
    result = analyze_corridor(req)
    # Polar integration: 1/2 integral[(R+L)^2-(R-Rwidth)^2] dtheta.
    expected = math.pi / 4 * (2 * 100 * 30 + (10**2 + 10 * 30 + 30**2 - 5**2 - 5 * 15 - 15**2) / 3)
    assert area(result) == pytest.approx(expected, abs=0.8)
    assert result.error.total_bound <= 0.002

    # Distance of independent exact midpoint offsets to the output boundary.
    def segment_distance(p, a, b):
        d = (b[0] - a[0], b[1] - a[1])
        t = max(0, min(1, ((p[0] - a[0]) * d[0] + (p[1] - a[1]) * d[1]) / (d[0] ** 2 + d[1] ** 2)))
        return math.dist(p, (a[0] + t * d[0], a[1] + t * d[1]))

    for i in range(101):
        t = i / 100
        theta = math.pi / 2 * t
        for radius in (100 + 10 + 20 * t, 100 - 5 - 10 * t):
            point = (100 - radius * math.cos(theta), radius * math.sin(theta))
            separation = min(
                segment_distance(point, a, b)
                for a, b in zip(result.polygon, result.polygon[1:], strict=False)
            )
            assert separation <= result.error.total_bound + 1e-9


@pytest.mark.parametrize("join", ["bevel", "miter", "round"])
def test_straight_corner_joins_trim_inside_without_self_intersection(join):
    req = request(
        [line("east"), line("north", bearing=0)],
        [width(start="east", end="north", left=(10, 10), right=(10, 10))],
        join=join,
        error=0.0005,
    )
    result = analyze_corridor(req)
    expected = 4000 if join == "miter" else 3950 if join == "bevel" else 3900 + math.pi * 25
    assert area(result) == pytest.approx(expected, abs=0.1)


@pytest.mark.parametrize("kind", ["missing", "overlap", "out_of_order", "zero_interval"])
def test_width_coverage_failure_is_explicit_without_polygon(kind):
    rows = [
        width(id="a", start_fraction=0, end_fraction=0.5),
        width(id="b", start_fraction=0.5, end_fraction=1),
    ]
    if kind == "missing":
        rows[1]["start"]["fraction"] = 0.6
    elif kind == "overlap":
        rows[1]["start"]["fraction"] = 0.4
    elif kind == "out_of_order":
        rows.reverse()
    else:
        rows[0]["end"]["fraction"] = 0
    result = analyze_corridor(request(widths=rows))
    assert result.availability in {"unsupported", "incomplete"}
    assert result.polygon is None and result.boundary is None and result.limitations


def test_step_widths_are_preserved_at_exact_interval_boundary():
    rows = [
        width(id="a", end_fraction=0.5, left=(10, 10), right=(5, 5)),
        width(id="b", start_fraction=0.5, left=(20, 20), right=(10, 10)),
    ]
    result = analyze_corridor(request(widths=rows))
    assert area(result) == pytest.approx(2250)
    assert any(math.dist(p, (50, 10)) < 1e-8 for p in result.polygon)
    assert any(math.dist(p, (50, 20)) < 1e-8 for p in result.polygon)


@pytest.mark.parametrize(
    "kind", ["crossing", "inner_radius", "nontangent_arc_join", "miter_limit", "too_tight_budget"]
)
def test_unsupported_or_unsafe_topology_never_becomes_normal_area(kind):
    req = request()
    if kind == "crossing":
        req = request([line("a", 100, 45), line("b", 70, 270), line("c", 100, 135)])
    elif kind == "inner_radius":
        req = request([arc(radius=5)])
    elif kind == "nontangent_arc_join":
        req = request([arc("a"), line("b", bearing=0)])
    elif kind == "miter_limit":
        req = request([line("a"), line("b", bearing=269)], join="miter")
    else:
        data = request([arc()], error=1e-12).model_dump()
        data["error_budget"]["max_segments"] = 8
        req = CorridorRequest.model_validate(data)
    result = analyze_corridor(req)
    assert result.availability in {"unsupported", "topology_failed", "topology_unavailable"}
    assert result.polygon is None and result.boundary is None and result.error is None


def test_changed_width_definition_invalidates_prepared_corridor_result():
    result = analyze_corridor(request())
    data = copy.deepcopy(result.model_dump())
    data["request"]["widths"][0].update(left_start=30, left_end=30)
    with pytest.raises(ValueError, match="fresh"):
        validate_corridor_result(CorridorResult.model_validate(data))


def test_reversed_steps_and_taper_preserve_width_order_and_shape():
    forward = [
        width(id="step", end_fraction=0.5, left=(10, 10), right=(5, 5)),
        width(id="taper", start_fraction=0.5, left=(20, 30), right=(10, 15), rule="linear_taper"),
    ]
    reverse = [
        width(id="taper", end_fraction=0.5, left=(15, 10), right=(30, 20), rule="linear_taper"),
        width(id="step", start_fraction=0.5, left=(5, 5), right=(10, 10)),
    ]
    a = analyze_corridor(request(widths=forward))
    b = analyze_corridor(request([line(bearing=270)], reverse))
    assert area(a) == pytest.approx(area(b))
    assert {(round(x, 8), round(y, 8)) for x, y in a.polygon} == {
        (round(x + 100, 8), round(y, 8)) for x, y in b.polygon
    }
    assert tuple(row.id for row in a.request.widths) == ("step", "taper")
    assert tuple(row.id for row in b.request.widths) == ("taper", "step")


def test_reversed_circular_centerline_with_side_swap_reproduces_offset_shape():
    a = analyze_corridor(request([arc()], error=0.002))
    b = analyze_corridor(
        request(
            [arc(tangent=270, direction="left")],
            [width(left=(10, 10), right=(20, 20))],
            error=0.002,
        )
    )
    assert area(a) == pytest.approx(area(b))
    assert {(round(x, 8), round(y, 8)) for x, y in a.polygon} == {
        (round(x + 100, 8), round(y + 100, 8)) for x, y in b.polygon
    }


def test_declared_width_and_error_units_are_converted_without_losing_definition():
    data = request(widths=[width(left=(3.048, 3.048), right=(3.048, 3.048))]).model_dump()
    data["width_unit"] = "m"
    data["error_budget"] = {"max_error": 0.001, "unit": "m", "max_segments": 2048}
    result = analyze_corridor(CorridorRequest.model_validate(data))
    assert area(result) == pytest.approx(2000)
    assert result.request.width_unit == result.error.unit == "m"
    assert result.error.total_bound <= 0.001
    assert result.boundary_origin_in_centerline_frame == pytest.approx((0, 10))
    assert {edge.role for edge in result.boundary_edges} >= {"start_cap", "end_cap"}


def test_one_taper_range_crosses_tangent_line_arc_line_without_width_averaging():
    req = request(
        [line("before", 50, 0), arc("bend"), line("after", 50, 90)],
        [width(start="before", end="after", left=(10, 20), right=(5, 10), rule="linear_taper")],
    )
    result = analyze_corridor(req)
    assert result.availability == "supported", result.limitations
    total = 100 + 50 * math.pi
    width_at_arc_start = 10 + 10 * 50 / total
    assert any(math.dist(p, (-width_at_arc_start, 50)) < 1e-8 for p in result.polygon)
    assert any(math.dist(p, (150, 170)) < 1e-8 for p in result.polygon)
    assert {id for edge in result.boundary_edges for id in edge.centerline_call_ids} == {
        "before",
        "bend",
        "after",
    }
    assert all(edge.width_interval_ids == ("width",) for edge in result.boundary_edges)


def test_approximation_cannot_establish_topology_in_an_unresolved_narrow_arc_gap():
    result = analyze_corridor(request([arc(sweep=359.999)], error=0.01))
    assert result.availability == "topology_unavailable"
    assert "approximation error" in result.limitations[-1]
    assert result.boundary is None and result.polygon is None


def test_boundary_plot_origin_is_explicit_and_reproduces_centerline_frame_points():
    result = analyze_corridor(request(cap="round"))
    assert result.availability == "supported"
    origin = result.boundary_origin_in_centerline_frame
    for primitive, expected in zip(
        result.boundary.geometry.primitives, result.polygon[:-1], strict=True
    ):
        assert (primitive.start[0] + origin[0], primitive.start[1] + origin[1]) == pytest.approx(
            expected, abs=result.error.floating_point_bound
        )
