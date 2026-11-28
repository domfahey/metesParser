"""Independent contract tests for immutable plotting and supplied map evidence."""

import json
import math
import random
import time
from pathlib import Path

import pytest
from mp_models.dashboard import DashboardBundle
from mp_models.plot import PlotPlacement, PlotScene, VectorLayer
from pydantic import ValidationError

FIXTURE = Path(__file__).parents[2] / "mp-review/tests/fixtures/dashboard-absolute.json"


def bundle_data():
    return json.loads(FIXTURE.read_text())


def layer(**changes):
    data = {
        "id": "layer",
        "label": "Synthetic",
        "source_id": "map",
        "scene_id": "scene",
        "geometry_type": "Polygon",
        "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
    }
    data.update(changes)
    return VectorLayer.model_validate(data)


def test_v1_bundle_renders_without_plot_options():
    bundle = DashboardBundle.model_validate(bundle_data())
    assert DashboardBundle.model_validate(bundle.model_dump(mode="json")) == bundle


def test_v1_rejects_v11_overlay_fields():
    data = bundle_data()
    data["scenes"] = []
    with pytest.raises(ValidationError, match="1.1"):
        DashboardBundle.model_validate(data)


def test_plot_inputs_are_immutable():
    scene = PlotScene(id="scene", name="Local", kind="local", units="unknown_ft")
    with pytest.raises(ValidationError, match="Instance is frozen"):
        scene.name = "changed"
    assert isinstance(layer().coordinates, tuple)


def test_local_scene_rejects_a_crs():
    with pytest.raises(ValidationError, match="local.*CRS"):
        PlotScene(id="scene", name="Local", kind="local", units="m", crs="EPSG:4326")


@pytest.mark.parametrize(
    ("coords", "expected_match"),
    [
        ([[[0, 0], [10, 0], [10, 10], [0, 10]]], "closed with at least three distinct vertices"),
        ([[[0, 0], [10, 10], [0, 10], [5, 0], [0, 0]]], "self-intersecting ring"),
        ([[[0, 0], [1, 0], [2, 0], [0, 0]]], "degenerate ring has zero area"),
        ([[[0, 0], [float("nan"), 0], [10, 10], [0, 0]]], "finite number"),
        (
            [
                [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
                [[20, 20], [21, 20], [21, 21], [20, 20]],
            ],
            "hole must be strictly inside its exterior",
        ),
    ],
)
def test_layer_rejects_nonfinite_and_invalid_rings(coords, expected_match):
    with pytest.raises(ValidationError, match=expected_match):
        layer(coordinates=coords)


def test_scene_rejects_unknown_units():
    with pytest.raises(ValidationError, match="Input should be"):
        PlotScene(id="scene", name="Bad", kind="local", units="furlong")


def test_layer_preserves_holes_and_multipolygons():
    rings = [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]], [[2, 2], [3, 2], [3, 3], [2, 3], [2, 2]]]
    assert len(layer(coordinates=rings).coordinates) == 2
    assert len(layer(geometry_type="MultiPolygon", coordinates=[rings]).coordinates) == 1


@pytest.mark.parametrize("reverse", [False, True])
def test_multipolygon_rejects_members_crossing_another_members_hole(reverse):
    outer = ((0, 0), (10, 0), (10, 10), (0, 10), (0, 0))
    hole = ((3, 3), (7, 3), (7, 7), (3, 7), (3, 3))
    crossing = ((4, 4), (9, 4), (9, 6), (4, 6), (4, 4))
    polygons = ((outer, hole), (crossing,))
    with pytest.raises(ValidationError, match="multipolygon"):
        layer(
            geometry_type="MultiPolygon",
            coordinates=polygons[::-1] if reverse else polygons,
        )


def test_multipolygon_preserves_an_island_wholly_within_another_members_hole():
    outer = ((0, 0), (10, 0), (10, 10), (0, 10), (0, 0))
    hole = ((3, 3), (7, 3), (7, 7), (3, 7), (3, 3))
    island = ((4, 4), (6, 4), (6, 6), (4, 6), (4, 4))
    polygons = ((outer, hole), (island,))
    assert layer(geometry_type="MultiPolygon", coordinates=polygons).coordinates == polygons


def test_referenced_placement_requires_position_and_orientation_evidence():
    with pytest.raises(ValidationError, match="orientation"):
        PlotPlacement(
            id="p",
            calculation_id="calc",
            geometry_hash="a" * 64,
            scene_id="s",
            status="referenced",
            rationale="one point",
            position_evidence=("address",),
        )


@pytest.mark.parametrize("field", ["scale", "shear", "reflection"])
def test_placement_rejects_scale_shear_reflection(field):
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PlotPlacement(
            id="p",
            calculation_id="calc",
            geometry_hash="a" * 64,
            scene_id="s",
            rationale="manual",
            **{field: 1},
        )


def test_blank_evidence_does_not_establish_referenced_placement():
    with pytest.raises(ValidationError, match="evidence"):
        PlotPlacement(
            id="p",
            calculation_id="calc",
            geometry_hash="a" * 64,
            scene_id="s",
            status="referenced",
            rationale="claimed",
            position_evidence=(" ",),
            orientation_evidence=("",),
        )


def test_plot_references_resolve_to_same_occurrence():
    data = bundle_data()
    data["schema_version"] = "1.1"
    data["scenes"] = [{"id": "scene", "name": "Local", "kind": "local", "units": "unknown_ft"}]
    data["placements"] = [
        {
            "id": "placement",
            "calculation_id": data["calculations"][0]["id"],
            "geometry_hash": "a" * 64,
            "scene_id": "scene",
            "rationale": "manual",
            "evidence_ids": ["missing"],
        }
    ]
    with pytest.raises(ValidationError, match="cross-occurrence evidence"):
        DashboardBundle.model_validate(data)


@pytest.mark.parametrize("reference", ["placement", "call"])
def test_comparison_source_references_are_validated(reference):
    data = bundle_data()
    data["schema_version"] = "1.1"
    data["scenes"] = [{"id": "scene", "name": "Local", "kind": "local", "units": "unknown_ft"}]
    data["placements"] = [
        {
            "id": "placement",
            "calculation_id": data["calculations"][0]["id"],
            "geometry_hash": "a" * 64,
            "scene_id": "scene",
            "rationale": "manual",
        }
    ]
    point = {"id": "control", "deed_point": [0, 0], "map_point": [1, 1]}
    if reference == "call":
        other = dict(data["occurrences"][0], id="other-occurrence")
        data["occurrences"].append(other)
        data["calls"].append(dict(data["calls"][0], id="other-call", occurrence_id=other["id"]))
        point["call_id"] = "other-call"
    data["comparison_specs"] = [
        {
            "id": "comparison",
            "placement_id": "missing" if reference == "placement" else "placement",
            "correspondences": [point],
        }
    ]
    with pytest.raises(ValidationError, match="unknown placement|cross-occurrence call"):
        DashboardBundle.model_validate(data)


def test_v1_rejects_comparison_specs_even_when_empty():
    data = bundle_data()
    data["comparison_specs"] = []
    with pytest.raises(ValidationError, match="1.1"):
        DashboardBundle.model_validate(data)


def test_plot_model_edge_guards_for_map_source_polygons_primitives_and_specs():
    from mp_models.plot import (
        MapSource,
        PlotComparisonSpec,
        PlotGeometry,
        PlotPrimitive,
        PointCorrespondence,
        plot_point_of_beginning,
        validate_polygon,
    )

    # MapSource rejects invalid base64.
    with pytest.raises(ValidationError, match="valid base64"):
        MapSource(id="m", label="M", sha256="a" * 64, data_base64="not-valid-b64!!!")

    # validate_polygon rejects nonfinite cross-product overflow and boundary-touching holes.
    with pytest.raises(ValueError, match="nonfinite polygon arithmetic"):
        validate_polygon((((0.0, 0.0), (1e200, 0.0), (0.0, 1e200), (0.0, 0.0)),))

    sq = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0))
    touching_hole = ((5.0, 0.0), (6.0, 1.0), (4.0, 1.0), (5.0, 0.0))
    with pytest.raises(ValueError, match="hole must be strictly inside its exterior"):
        validate_polygon((sq, touching_hole))

    # validate_polygon: empty polygon, duplicate adjacent vertices, overlapping/nested holes.
    with pytest.raises(ValueError, match="exterior ring"):
        validate_polygon(())
    with pytest.raises(ValueError, match="duplicate adjacent vertices"):
        validate_polygon((((0.0, 0.0), (5.0, 0.0), (5.0, 0.0), (0.0, 5.0), (0.0, 0.0)),))
    hole_a = ((1.0, 1.0), (6.0, 1.0), (6.0, 6.0), (1.0, 6.0), (1.0, 1.0))
    hole_b = ((2.0, 2.0), (4.0, 2.0), (4.0, 4.0), (2.0, 4.0), (2.0, 2.0))
    with pytest.raises(ValueError, match="holes must not overlap or nest"):
        validate_polygon((sq, hole_a, hole_b))

    # VectorLayer: empty MultiPolygon and wrong nesting depth.
    with pytest.raises(ValidationError, match="requires polygon coordinates"):
        layer(geometry_type="MultiPolygon", coordinates=())
    with pytest.raises(ValidationError, match="nesting must match geometry_type"):
        layer(geometry_type="MultiPolygon", coordinates=(sq,))

    # PlotPlacement scenario requires frozen baseline refs.
    with pytest.raises(ValidationError, match="frozen baseline references"):
        PlotPlacement(
            id="p",
            calculation_id="c",
            geometry_hash="a" * 64,
            scene_id="s",
            rationale="r",
            scenario_id="sc-1",
        )

    # PlotPrimitive arc requires all analytic circular fields.
    with pytest.raises(ValidationError, match="analytic circular geometry"):
        PlotPrimitive(kind="arc", call_id="c1", start=(0, 0), end=(1, 1), length_ft=1.5)

    # plot_point_of_beginning: explicit POB, fallback to first primitive start, empty -> None.
    prim = PlotPrimitive(kind="line", call_id="c1", start=(2.0, 3.0), end=(4.0, 5.0), length_ft=3.0)
    geom_explicit = PlotGeometry(
        id="g",
        calculation_id="c",
        frame_id="f",
        geometry_hash="a" * 64,
        primitives=(prim,),
        completeness="complete",
        point_of_beginning=(0.0, 0.0),
    )
    assert plot_point_of_beginning(geom_explicit) == (0.0, 0.0)
    assert plot_point_of_beginning(
        geom_explicit.model_copy(update={"point_of_beginning": None})
    ) == (
        2.0,
        3.0,
    )
    assert (
        plot_point_of_beginning(
            geom_explicit.model_copy(update={"point_of_beginning": None, "primitives": ()})
        )
        is None
    )

    # PlotComparisonSpec rejects duplicate point IDs.
    pt = PointCorrespondence(id="pt1", deed_point=(0, 0), map_point=(1, 1))
    with pytest.raises(ValidationError, match="must be unique"):
        PlotComparisonSpec(id="cmp", placement_id="pl", correspondences=(pt, pt))


def _brute_force_candidate_pairs(ring, eps=0.0):
    edges = list(zip(ring, ring[1:], strict=False))
    last = len(edges) - 1
    pairs = []
    for i, (a, b) in enumerate(edges):
        a_min_x, a_max_x = (a[0], b[0]) if a[0] <= b[0] else (b[0], a[0])
        a_min_y, a_max_y = (a[1], b[1]) if a[1] <= b[1] else (b[1], a[1])
        for j in range(i + 2, len(edges)):
            if i == 0 and j == last:
                continue
            c, d = edges[j]
            b_min_x, b_max_x = (c[0], d[0]) if c[0] <= d[0] else (d[0], c[0])
            b_min_y, b_max_y = (c[1], d[1]) if c[1] <= d[1] else (d[1], c[1])
            if (
                a_max_x + eps < b_min_x
                or b_max_x + eps < a_min_x
                or a_max_y + eps < b_min_y
                or b_max_y + eps < a_min_y
            ):
                continue
            pairs.append((a, b, c, d))
    return pairs


def _brute_force_self_intersects(ring):
    from mp_models.plot import _intersects

    edges = list(zip(ring, ring[1:], strict=False))
    last = len(edges) - 1
    for i, (a, b) in enumerate(edges):
        for j in range(i + 2, len(edges)):
            if i == 0 and j == last:
                continue
            c, d = edges[j]
            if _intersects(a, b, c, d):
                return True
    return False


def test_validate_polygon_matches_bruteforce_oracle_on_edge_cases_and_seeded_rings():
    from mp_models.plot import validate_polygon

    rings = [
        # Horizontal collinear overlap
        ((0, 0), (5, 0), (5, 2), (2, 2), (2, 0), (4, 0), (4, -2), (0, -2), (0, 0)),
        # Vertical collinear overlap
        ((0, 0), (0, 5), (2, 5), (2, 2), (0, 2), (0, 4), (-2, 4), (-2, 0), (0, 0)),
        # Diagonal collinear overlap
        ((0, 0), (5, 5), (5, 7), (2, 4), (1, 1), (3, 3), (0, 4), (0, 0)),
        # T-junction (vertex touches interior of non-adjacent edge)
        ((0, 0), (6, 0), (6, 4), (3, 4), (3, 0), (2, 2), (0, 4), (0, 0)),
        # Non-adjacent vertex touch (figure-8 pinch at (2, 2))
        ((0, 0), (4, 0), (2, 2), (4, 4), (0, 4), (2, 2), (0, 0)),
        # Valid rings exercising closing-edge exemption
        ((0, 0), (4, 0), (2, 2), (0, 0)),
        ((0, 0), (4, 0), (4, 4), (2, 1), (0, 4), (0, 0)),
    ]
    rng = random.Random(42)
    for _ in range(80):
        count = rng.randint(5, 16)
        pts = [
            (round(rng.uniform(-10, 10), 2), round(rng.uniform(-10, 10), 2)) for _ in range(count)
        ]
        ring = (*pts, pts[0])
        if len(set(ring[:-1])) < 3 or any(a == b for a, b in zip(ring, ring[1:], strict=False)):
            continue
        origin = ring[0]
        area = sum(
            (a[0] - origin[0]) * (b[1] - origin[1]) - (a[1] - origin[1]) * (b[0] - origin[0])
            for a, b in zip(ring, ring[1:], strict=False)
        )
        if area != 0:
            rings.append(ring)

    for ring in rings:
        expected_intersects = _brute_force_self_intersects(ring)
        if expected_intersects:
            with pytest.raises(ValueError, match="self-intersecting ring"):
                validate_polygon((ring,))
        else:
            validate_polygon((ring,))


@pytest.mark.parametrize("eps", [0.0, 1e-9, 0.25])
def test_ring_candidate_pairs_matches_bruteforce_aabb_oracle(eps):
    from mp_models.plot import _ring_candidate_pairs

    rings = [
        # Zero-length segment and near-epsilon vertical segments
        ((0.0, 0.0), (0.0, 0.0), (0.0, 1.0), (1e-10, 1.0), (1e-10, 0.0), (0.0, 0.0)),
        # Horizontal parallel edges at exact 0.25 vertical spacing
        (
            (0.0, 0.0),
            (2.0, 0.0),
            (2.0, 0.25),
            (0.0, 0.25),
            (0.0, 0.5),
            (2.0, 0.5),
            (2.0, 1.0),
            (0.0, 1.0),
            (0.0, 0.0),
        ),
        # Square verifying closing edge exemption
        ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)),
    ]
    rng = random.Random(42)
    for _ in range(80):
        count = rng.randint(4, 18)
        pts = [
            (
                rng.choice([0.0, 1.0, 1.0 + 1e-10, rng.uniform(-5, 5)]),
                rng.choice([0.0, 0.25, rng.uniform(-5, 5)]),
            )
            for _ in range(count)
        ]
        rings.append((*pts, pts[0]))

    for ring in rings:
        actual = sorted(_ring_candidate_pairs(ring, eps=eps))
        expected = sorted(_brute_force_candidate_pairs(ring, eps=eps))
        assert actual == expected


@pytest.mark.parametrize("bad_eps", [-1e-12, -1.0, float("nan"), float("inf"), float("-inf")])
def test_ring_candidate_pairs_rejects_invalid_eps(bad_eps):
    from mp_models.plot import _ring_candidate_pairs

    sq = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0))
    with pytest.raises(ValueError, match="sweep tolerance"):
        list(_ring_candidate_pairs(sq, eps=bad_eps))


def test_validate_polygon_large_ring_scaling_bound():
    from mp_models.plot import validate_polygon

    n = 4000
    pts = [
        (100.0 * math.cos(2.0 * math.pi * k / n), 100.0 * math.sin(2.0 * math.pi * k / n))
        for k in range(n)
    ]
    valid_ring = (*pts, pts[0])
    t0 = time.perf_counter()
    validate_polygon((valid_ring,))
    assert time.perf_counter() - t0 < 1.0

    crossing_pts = list(pts)
    crossing_pts[1], crossing_pts[n // 2] = crossing_pts[n // 2], crossing_pts[1]
    crossing_ring = (*crossing_pts, crossing_pts[0])
    t0 = time.perf_counter()
    with pytest.raises(ValueError, match="self-intersecting ring"):
        validate_polygon((crossing_ring,))
    assert time.perf_counter() - t0 < 1.0
