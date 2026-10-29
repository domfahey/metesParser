"""Source-constrained local geometry must never become recorded bearings."""

import math

import pytest
from mp_models import RelativeDescription
from mp_verify import analyze_relative


def description(*, angles=(90, 90, 90, 90), distances=(100, 60, 100, 60), **frame):
    """A closed, clockwise rectangle with its closing angle recorded."""
    ids = [f"c{i + 1}" for i in range(len(distances))]
    source = {"reference": " book 1, page 2 \n", "quote": "  deed wording\n unchanged "}
    return {
        "frame": {
            "name": "arbitrary local frame",
            "first_azimuth_deg": 0,
            "origin": [0, 0],
            "orientation": "cw",
            **frame,
        },
        "courses": [
            {"course_id": key, "distance_ft": distance, "source": source}
            for key, distance in zip(ids, distances, strict=True)
        ],
        "constraints": [
            {
                "constraint_id": f"angle-{i}",
                "kind": "interior",
                "from_course": ids[i - 1],
                "to_course": key,
                "angle_deg": angles[i],
                "source": source,
            }
            for i, key in enumerate(ids)
        ],
    }


def analyze(data):
    return analyze_relative(RelativeDescription.model_validate(data))


def test_rectangle_is_local_analysis_not_engine_verification():
    model = RelativeDescription.model_validate(description())
    original = model.model_dump_json()
    result = analyze_relative(model)
    assert result.status == "analyzed"
    assert result.misclosure_ft == pytest.approx(0, abs=1e-10)
    assert result.area_sq_ft == pytest.approx(6000)
    assert result.perimeter_ft == 320
    assert result.stated_angle_sum_deg == 360
    assert result.expected_angle_sum_deg == 360
    assert result.computed_closing_angle_deg == pytest.approx(90)
    assert [c.local_azimuth_deg for c in result.courses] == [0, 90, 180, 270]
    assert result.engine_verified is False
    assert result.verified_export_eligible is False
    assert result.method == "local_angle_analysis"
    assert result.area_basis == "implicit_closing_segment"
    assert all(c.recorded_bearing_azimuth_deg_from_north is None for c in model.courses)
    assert result.description == model
    assert model.model_dump_json() == original


@pytest.mark.parametrize("orientation", ["cw", "ccw"])
@pytest.mark.parametrize("rotation", [0, 37.25, 359.999, -112.5])
def test_rotation_translation_and_reverse_traversal(orientation, rotation):
    result = analyze(
        description(orientation=orientation, first_azimuth_deg=rotation, origin=[1e9, -2e9])
    )
    assert result.status == "analyzed"
    assert result.area_sq_ft == pytest.approx(6000, abs=1e-8)
    assert result.misclosure_ft == pytest.approx(0, abs=1e-10)
    assert (result.points[0].x, result.points[0].y) == (1e9, -2e9)


def test_reflex_interior_and_explicit_exterior_complement_agree():
    data = description(
        angles=(90, 90, 45, 270, 45),
        distances=(100, 100, math.hypot(50, 50), math.hypot(50, 50), 100),
        first_azimuth_deg=90,
        orientation="ccw",
    )
    interior = analyze(data)
    data["constraints"][3].update(
        kind="exterior", angle_deg=90, exterior_convention="interior_complement"
    )
    exterior = analyze(data)
    assert interior.status == exterior.status == "analyzed"
    assert exterior.area_sq_ft == pytest.approx(7500)
    assert exterior.misclosure_ft == pytest.approx(0, abs=1e-10)
    assert exterior.stated_angle_sum_deg == 540
    assert exterior.points == interior.points


def test_reversing_concave_boundary_preserves_its_actual_vertices():
    diagonal = math.hypot(50, 50)
    forward = analyze(
        description(
            angles=(90, 90, 45, 270, 45),
            distances=(100, 100, diagonal, diagonal, 100),
            first_azimuth_deg=90,
            orientation="ccw",
        )
    )
    reverse = analyze(
        description(
            angles=(90, 45, 270, 45, 90),
            distances=(100, diagonal, diagonal, 100, 100),
            first_azimuth_deg=0,
            orientation="cw",
        )
    )
    assert forward.status == reverse.status == "analyzed"
    assert reverse.area_sq_ft == pytest.approx(forward.area_sq_ft)
    for a, b in zip(forward.points, reversed(reverse.points), strict=True):
        assert a.x == pytest.approx(b.x, abs=1e-10)
        assert a.y == pytest.approx(b.y, abs=1e-10)


def test_nonadjacent_parallel_and_perpendicular_constraints():
    data = description()
    data["constraints"] = [
        {
            "constraint_id": "ab",
            "kind": "perpendicular",
            "from_course": "c1",
            "to_course": "c2",
            "turn": "right",
            "source": {"reference": "p1", "quote": "right angles"},
        },
        {
            "constraint_id": "ac",
            "kind": "parallel",
            "from_course": "c1",
            "to_course": "c3",
            "parallel_direction": "opposite",
            "source": {"reference": "p1", "quote": "parallel"},
        },
        {
            "constraint_id": "bd",
            "kind": "parallel",
            "from_course": "c2",
            "to_course": "c4",
            "parallel_direction": "opposite",
            "source": {"reference": "p1", "quote": "parallel"},
        },
    ]
    result = analyze(data)
    assert result.status == "analyzed"
    assert result.area_sq_ft == pytest.approx(6000)
    assert result.stated_angle_sum_deg is None


@pytest.mark.parametrize("kind", ["parallel", "perpendicular", "exterior"])
def test_ambiguous_interpretation_stays_unresolved_even_when_other_calls_close(kind):
    data = description()
    constraint = data["constraints"][1]
    constraint["kind"] = kind
    if kind != "exterior":
        constraint.pop("angle_deg")
    result = analyze(data)
    assert result.status == "unresolved"
    assert result.points == result.courses == ()
    assert result.area_sq_ft is result.misclosure_ft is None
    assert any(issue.code == "ambiguous_constraint" for issue in result.issues)


def test_disconnected_constraint_graph_is_unresolved_not_fitted_to_close():
    data = description()
    data["constraints"] = data["constraints"][1:2]
    result = analyze(data)
    assert result.status == "unresolved"
    assert result.points == ()
    assert any(issue.code == "insufficient_constraints" for issue in result.issues)


def test_contradictory_closing_angle_rejects_all_geometry():
    data = description()
    data["constraints"][0]["angle_deg"] = 89
    result = analyze(data)
    assert result.status == "inconsistent"
    assert result.points == result.courses == ()
    assert result.area_sq_ft is None
    assert any(issue.code == "contradictory_constraints" for issue in result.issues)


def test_complete_angle_ring_rejects_extra_winding_hidden_by_modulo_arithmetic():
    result = analyze(description(angles=(270, 270, 270, 270)))
    assert result.status == "inconsistent"
    assert result.points == ()
    assert any("angle sum" in issue.message for issue in result.issues)


def test_disconnected_conflicting_cycle_is_still_rejected():
    data = description()
    data["constraints"] = [
        {
            "constraint_id": "bc",
            "kind": "parallel",
            "from_course": "c2",
            "to_course": "c3",
            "parallel_direction": "same",
            "source": {"reference": "p1", "quote": "parallel"},
        },
        {
            "constraint_id": "cb",
            "kind": "parallel",
            "from_course": "c3",
            "to_course": "c2",
            "parallel_direction": "opposite",
            "source": {"reference": "p2", "quote": "opposite"},
        },
    ]
    assert analyze(data).status == "inconsistent"


def test_open_traverse_is_reported_without_adjustment():
    result = analyze(description(distances=(100, 60, 100, 59.8)))
    assert result.status == "analyzed"
    assert result.misclosure_ft == pytest.approx(0.2)
    assert result.misclosure_x_ft == pytest.approx(0.2)
    assert result.precision_denominator == pytest.approx(1599)
    assert result.points[-1].x == pytest.approx(0.2)
    assert result.verified_export_eligible is False


def test_constraints_can_resolve_backwards_from_anchored_first_course():
    data = description()
    data["constraints"] = data["constraints"][:3]
    result = analyze(data)
    assert result.status == "analyzed"
    assert result.area_sq_ft == pytest.approx(6000)
    assert result.stated_angle_sum_deg is None


def test_source_wording_and_known_recorded_bearing_are_preserved_not_used_as_frame():
    data = description()
    data["courses"][0]["recorded_bearing_azimuth_deg_from_north"] = 37
    result = analyze(data)
    assert result.description.courses[0].recorded_bearing_azimuth_deg_from_north == 37
    assert result.courses[0].local_azimuth_deg == 0
    assert result.description.constraints[0].source.quote == "  deed wording\n unchanged "
    assert result.description.constraints[0].source.reference == " book 1, page 2 \n"


def test_unrepresentable_geometry_returns_no_nonfinite_numbers():
    data = description(distances=(1e308, 1e308, 1e308, 1e308))
    result = analyze(data)
    assert result.status == "unresolved"
    assert result.points == ()
    assert any(issue.code == "numerical_range" for issue in result.issues)
    result.model_dump_json()


@pytest.mark.parametrize("origin, distance", [(1e20, 100), (1e9, 1e-10)])
def test_translation_that_collapses_points_is_not_reported_as_usable_geometry(origin, distance):
    result = analyze(description(origin=[origin, origin], distances=(distance,) * 4))
    assert result.status == "unresolved"
    assert result.points == result.courses == ()
    assert result.area_sq_ft is None
    assert any(issue.code == "numerical_range" for issue in result.issues)
