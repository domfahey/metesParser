"""Source-linked immutable baseline plotting, independent of scenario support."""

import json
import re
from pathlib import Path

import pytest
from mp_export.dashboard_html import render_dashboard
from mp_models.dashboard import DashboardBundle
from mp_verify.dashboard import calculate_dashboard

FIXTURES = Path(__file__).resolve().parents[3] / "packages/mp-review/tests/fixtures"


def data():
    return json.loads((FIXTURES / "dashboard-absolute.json").read_text())


def rendered(value=None):
    return render_dashboard(calculate_dashboard(DashboardBundle.model_validate(value or data())))


def test_baseline_svg_preserves_open_gap_and_source_courses():
    value = data()
    value["calls"][-1]["call"]["distance_ft"] = 49.8
    result = rendered(value)
    assert 'data-baseline-plot="calc-one"' in result
    paths = re.findall(r'<path[^>]+data-plot-call="([^"]+)"[^>]* d="([^"]+)"', result)
    assert {p[0] for p in paths} == {c["id"] for c in value["calls"]}
    assert all("Z" not in path.upper() for _, path in paths)
    assert 'class="plot-gap"' in result
    assert "0.200 ft" in result


def test_unknown_middle_call_shows_only_anchored_prefix():
    value = data()
    value["calls"][1]["call"]["bearing_azimuth_deg_from_north"] = None
    result = rendered(value)
    assert 'data-plot-call="call-one"' in result
    assert 'data-plot-call="call-two"' not in result
    assert 'data-plot-call="call-three"' not in result
    assert "partial" in result
    assert 'data-unresolved-call="call-two"' in result


def test_plot_selection_resolves_call_source_and_explicit_local_axes():
    result = rendered()
    assert 'data-call-row="call-one"' in result
    assert 'data-source-call="call-one"' in result
    assert 'data-page-id="page-one"' in result
    assert "Local +Y" in result
    assert "Recorded bearings do not establish geographic north" in result
    for control in ("plot-zoom-in", "plot-zoom-out", "plot-fit", "plot-reset", "plot-gap-detail"):
        assert f'id="{control}"' in result


def test_baseline_and_scenario_are_separate_offline_layers():
    result = rendered()
    assert 'data-baseline-layer="calc-one"' in result
    assert 'id="scenario-plot-layer"' in result
    assert "No supplied map layers" in result
    assert "data:application" not in result
    assert "https://" not in result


def test_baseline_quarter_circle_is_an_arc_without_browser_curve_editing():
    value = data()
    value["scenarios"] = []
    value["evidence"] = []
    value["calls"] = value["calls"][:1]
    value["calls"][0]["call"].update(curve_dir="right", radius_ft=100, delta_deg=90)
    result = rendered(value)
    path = re.search(r'<path[^>]+data-plot-call="call-one"[^>]* d="([^"]+)"', result)[1]
    arc = re.search(r"A ([^ ]+) ([^ ]+) 0 0 1 ([^ ]+) ([^ ]+)", path)
    assert arc is not None
    assert list(map(float, arc.groups())) == pytest.approx([100, 100, 100, -100], abs=0.001)
    assert "Browser geometry supports complete straight boundaries only" in result


def test_python_browser_placement_agreement_requires_actual_node():
    import shutil
    import subprocess

    from mp_models.plot import PlotPlacement
    from mp_verify.plot import transform_point

    node = shutil.which("node")
    assert node is not None, "Node execution is a required plotting gate"
    placement = PlotPlacement(
        id="placed",
        calculation_id="calc-one",
        geometry_hash="a" * 64,
        scene_id="scene",
        rotation_deg=90,
        translation=(1000, 2000),
        rationale="Synthetic",
    )
    script = FIXTURES.parents[2] / "mp-export/src/mp_export/dashboard_assets/dashboard.js"
    command = "const m=require(process.argv[1]);process.stdout.write(JSON.stringify(m.scenePoints([[0,0],[0,10]],JSON.parse(process.argv[2]),'international_ft','international_ft')));"
    result = subprocess.run(
        [node, "-e", command, str(script), placement.model_dump_json()],
        text=True,
        capture_output=True,
        check=True,
    )
    points = json.loads(result.stdout)
    assert points == [[1000, 2000], [1010, 2000]]
    for source, point in zip([(0, 0), (0, 10)], points, strict=True):
        assert point == pytest.approx(
            transform_point(
                source, placement, native_units="international_ft", scene_units="international_ft"
            ),
            abs=0.001,
        )


def map_data(placed=False):
    value = data()
    value["schema_version"] = "1.1"
    value["calculations"][0]["frame"]["foot_definition"] = "international_ft"
    value["scenes"] = [
        {"id": "scene", "name": "Synthetic scene", "kind": "local", "units": "international_ft"}
    ]
    value["map_sources"] = [
        {
            "id": "source",
            "label": '<script>alert("map")</script>',
            "sha256": "a" * 64,
            "filename": "synthetic.json",
            "native_units": "international_ft",
        }
    ]
    value["vector_layers"] = [
        {
            "id": "map",
            "label": "Synthetic context",
            "source_id": "source",
            "scene_id": "scene",
            "geometry_type": "Polygon",
            "coordinates": [
                [[0, 0], [110, 0], [110, 110], [0, 110], [0, 0]],
                [[10, 10], [20, 10], [20, 20], [10, 20], [10, 10]],
            ],
        }
    ]
    if placed:
        geometry = calculate_dashboard(DashboardBundle.model_validate(value)).plots.geometries[0]
        value["placements"] = [
            {
                "id": "placed",
                "calculation_id": "calc-one",
                "geometry_hash": geometry.geometry_hash,
                "scene_id": "scene",
                "rotation_deg": 90,
                "translation": [1000, 2000],
                "rationale": "Synthetic context only",
            }
        ]
    return value


def test_optional_unplaced_map_uses_independent_comparison_view():
    result = rendered(map_data())
    assert 'class="plot independent-map"' in result
    assert "Unplaced — separate map evidence" in result
    # No map primitive may enter the native deed scene without placement.
    baseline = re.search(r'<svg[^>]+data-baseline-plot="calc-one"(.*?)</svg>', result, re.S)[1]
    assert "data-map-layer=" not in baseline
    assert "Retrieved: unknown; source date: unknown" in result


def test_placed_vector_holes_and_escaped_map_provenance():
    result = rendered(map_data(True))
    baseline = re.search(r'<svg[^>]+data-baseline-plot="calc-one"(.*?)</svg>', result, re.S)[1]
    assert 'data-map-layer="map"' in baseline
    assert 'fill-rule="evenodd"' in baseline
    assert re.search(r'class="map-polygon"', baseline)
    assert '<script>alert("map")</script>' not in result
    assert "&lt;script&gt;" in result
    assert "clockwise 90°" in result


def test_scene_viewport_is_presentation_only_and_preserves_native_geometry():
    value = data()
    value["schema_version"] = "1.1"
    before = calculate_dashboard(DashboardBundle.model_validate(value))
    value["plot_view"] = {"viewport": [10, 20, 200, 100], "labels": ["course", "distance"]}
    after = calculate_dashboard(DashboardBundle.model_validate(value))
    result = render_dashboard(after)
    assert 'data-initial-viewbox="10 -120 200 100"' in result
    assert before.plots.geometries == after.plots.geometries
    assert before.calculations == after.calculations


def test_named_map_residuals_are_labelled_separately_from_deed_closure():
    value = map_data(True)
    value["comparison_specs"] = [
        {
            "id": "named-fit",
            "placement_id": "placed",
            "correspondences": [
                {
                    "id": "corner-check",
                    "call_id": "call-one",
                    "deed_point": [0, 0],
                    "map_point": [1000.2, 2000],
                }
            ],
        }
    ]
    result = rendered(value)
    assert "Named-point comparison named-fit: compared" in result
    assert "RMS 0.200 international_ft" in result
    assert "maximum 0.200 international_ft" in result
    assert "not survey accuracy" in result
    assert "corner-check" in result


def raster_data():
    value = map_data(True)
    page = value["pages"][0]
    value["map_sources"].append(
        {
            "id": "scan-source",
            "label": "Synthetic supplied scan",
            "sha256": page["image_sha256"],
            "filename": "synthetic.png",
            "native_units": "international_ft",
        }
    )
    value["raster_layers"] = [
        {
            "id": "scan",
            "label": "Synthetic scan",
            "scene_id": "scene",
            "source_id": "scan-source",
            "mime_type": "image/png",
            "width": 1,
            "height": 1,
            "sha256": page["image_sha256"],
            "data_base64": page["image"].split(",")[1],
            "registration": {"matrix": [0, 2, 1000, 3, 0, 2000], "method": "supplied_affine"},
        }
    ]
    return value


def test_raster_pixel_center_edges_and_affine_are_embedded_offline():
    result = rendered(raster_data())
    assert 'data-raster-layer="scan"' in result
    assert 'x="-0.5" y="-0.5" width="1" height="1"' in result
    assert 'transform="matrix(0 3 2 0 1000 2000)"' in result
    assert 'transform="scale(1 -1)"' in result
    assert "integer_pixel_centers" in result
    assert "Fit RMS" in result and "Checkpoint RMS" in result
