"""Plot/overlay stage boundaries preserve the deed's independent verification."""

import base64
import copy
import hashlib
import json
from io import BytesIO
from pathlib import Path

import pytest
from mp_models.dashboard import DashboardBundle, PreparedDashboard
from mp_review.dashboard import dashboard_file, prepare_dashboard, validate_prepared_dashboard

FIXTURE = Path(__file__).parent / "fixtures/dashboard-absolute.json"


def source():
    value = json.loads(FIXTURE.read_text())
    value["schema_version"] = "1.1"
    value["calculations"][0]["frame"]["foot_definition"] = "international_ft"
    return value


def mapped():
    value = source()
    initial = prepare_dashboard(DashboardBundle.model_validate(value))
    value["scenes"] = [
        {"id": "map-frame", "name": "Synthetic map", "kind": "local", "units": "international_ft"}
    ]
    value["map_sources"] = [{"id": "map-source", "label": "Synthetic", "sha256": "0" * 64}]
    value["vector_layers"] = [
        {
            "id": "parcel-map",
            "label": "Parcel map",
            "source_id": "map-source",
            "scene_id": "map-frame",
            "geometry_type": "Polygon",
            "coordinates": [[[0, 0], [100, 0], [100, 50], [0, 50], [0, 0]]],
        }
    ]
    value["placements"] = [
        {
            "id": "map-placement",
            "calculation_id": value["calculations"][0]["id"],
            "geometry_hash": initial.plots.geometries[0].geometry_hash,
            "scene_id": "map-frame",
            "translation": [0, 0],
            "rotation_deg": 0,
            "status": "approximate",
            "rationale": "Synthetic manual alignment",
        }
    ]
    return value


def test_plot_preparation_retains_source_geometry_and_status():
    value = source()
    original = copy.deepcopy(value)
    prepared = prepare_dashboard(DashboardBundle.model_validate(value))
    assert len(prepared.plots.geometries) == 1
    assert len(prepared.plots.geometries[0].primitives) == 4
    assert prepared.plots.geometries[0].area_sq_ft == pytest.approx(5000)
    assert prepared.calculations[0].engine_verified
    assert value == original
    assert prepared.manifest.plot_output_hash


def test_overlay_changes_preserve_source_and_calculation_hashes(tmp_path):
    value = mapped()
    initial = prepare_dashboard(DashboardBundle.model_validate(value), cache_dir=tmp_path)
    value["placements"][0]["translation"] = [1000, 2000]
    changed = prepare_dashboard(DashboardBundle.model_validate(value), cache_dir=tmp_path)
    assert changed.manifest.source_review_hash == initial.manifest.source_review_hash
    assert changed.manifest.calculation_input_hash == initial.manifest.calculation_input_hash
    assert changed.manifest.calculation_output_hash == initial.manifest.calculation_output_hash
    assert changed.manifest.plot_output_hash == initial.manifest.plot_output_hash
    assert changed.manifest.placement_output_hash != initial.manifest.placement_output_hash
    assert changed.manifest.cache_reused
    assert changed.calculations == initial.calculations
    assert "map_sources" not in json.loads((tmp_path / "source-review.json").read_text())


def test_opacity_only_changes_presentation_hash(tmp_path):
    value = mapped()
    initial = prepare_dashboard(DashboardBundle.model_validate(value), cache_dir=tmp_path)
    value["plot_view"] = {"opacity": [["parcel-map", 0.2]]}
    changed = prepare_dashboard(DashboardBundle.model_validate(value), cache_dir=tmp_path)
    for key in (
        "source_review_hash",
        "calculation_output_hash",
        "plot_output_hash",
        "map_output_hash",
        "placement_output_hash",
    ):
        assert getattr(changed.manifest, key) == getattr(initial.manifest, key)
    assert changed.manifest.presentation_hash != initial.manifest.presentation_hash


def test_map_changes_invalidate_only_map_and_dependent_placement(tmp_path):
    value = mapped()
    initial = prepare_dashboard(DashboardBundle.model_validate(value), cache_dir=tmp_path)
    value["vector_layers"][0]["coordinates"][0][1][0] = 100.2
    changed = prepare_dashboard(DashboardBundle.model_validate(value), cache_dir=tmp_path)
    assert changed.manifest.map_input_hash != initial.manifest.map_input_hash
    assert changed.manifest.placement_input_hash != initial.manifest.placement_input_hash
    assert changed.manifest.calculation_input_hash == initial.manifest.calculation_input_hash
    assert changed.manifest.plot_output_hash == initial.manifest.plot_output_hash


def test_source_change_rejects_stale_placement():
    value = mapped()
    value["calls"][0]["call"]["distance_ft"] = 101
    with pytest.raises(ValueError, match="stale|hash"):
        prepare_dashboard(DashboardBundle.model_validate(value))


def test_named_correspondences_are_hashed_and_delivered(tmp_path):
    value = mapped()
    initial = prepare_dashboard(DashboardBundle.model_validate(value))
    value["comparison_specs"] = [
        {
            "id": "anchor-check",
            "placement_id": "map-placement",
            "correspondences": [
                {"id": "first-anchor", "deed_point": [0, 0], "map_point": [0, 0]},
                {"id": "second-anchor", "deed_point": [100, 0], "map_point": [100.2, 0]},
            ],
        }
    ]
    compared = prepare_dashboard(DashboardBundle.model_validate(value), cache_dir=tmp_path)
    assert compared.manifest.placement_input_hash != initial.manifest.placement_input_hash
    assert compared.manifest.calculation_input_hash == initial.manifest.calculation_input_hash
    results = json.loads((tmp_path / "placements.json").read_text())["comparisons"]
    assert results[0]["maximum"] == pytest.approx(0.2)
    assert results[0]["rms"] == pytest.approx(0.2 / 2**0.5)
    assert results[0]["comparison_id"] == "anchor-check"


def test_forged_prepared_plot_is_rejected():
    initial = prepare_dashboard(DashboardBundle.model_validate(source()))
    value = initial.model_dump(mode="json")
    value["plots"]["geometries"][0]["primitives"][0]["end"] = [999, 999]
    with pytest.raises(ValueError, match="deterministic"):
        validate_prepared_dashboard(PreparedDashboard.model_validate(value))


def test_tampered_plot_cache_is_repaired_and_offline_delivery_is_reproducible(tmp_path):
    value = mapped()
    path = tmp_path / "input.json"
    raw = json.dumps(value, indent=2).encode() + b"\n\n"
    path.write_bytes(raw)
    cache = tmp_path / "cache"
    first = dashboard_file(path, tmp_path / "cold", cache_dir=cache)
    assert first["status"] == "needs_review", first
    assert not first["verified_export_eligible"]
    saved = json.loads((cache / "plot-geometry.json").read_text())
    saved[0]["area_sq_ft"] = 999
    (cache / "plot-geometry.json").write_text(json.dumps(saved))
    second = dashboard_file(path, tmp_path / "warm", cache_dir=cache)
    assert second["status"] == "needs_review", second
    repaired = json.loads((cache / "plot-geometry.json").read_text())
    assert repaired[0]["area_sq_ft"] == pytest.approx(5000)
    assert (tmp_path / "cold/dashboard.html").read_bytes() == (
        tmp_path / "warm/dashboard.html"
    ).read_bytes()
    assert (tmp_path / "warm/source.json").read_bytes() == raw
    assert not list((tmp_path / "warm").glob("*.csv"))
    for name in ("plot-geometry.json", "map-layers.json", "placements.json"):
        assert (tmp_path / "warm" / name).exists()


def test_delivery_retains_original_map_asset_bytes(tmp_path):
    value = mapped()
    raw_map = b'{"synthetic_map": true}\n'
    value["map_sources"][0].update(
        sha256=hashlib.sha256(raw_map).hexdigest(),
        data_base64=base64.b64encode(raw_map).decode(),
        filename="../../untrusted-map.json",
    )
    path = tmp_path / "input.json"
    path.write_text(json.dumps(value))
    result = dashboard_file(path, tmp_path / "delivery")
    assert result["status"] == "needs_review", result
    retained = tmp_path / "delivery/assets/map-source.bin"
    assert retained.read_bytes() == raw_map
    assert result["artifacts"]["assets/map-source.bin"] == str(retained)
    assert not (tmp_path / "untrusted-map.json").exists()


def raster_bundle():
    from mp_models.plot import PlotScene
    from mp_review.raster_registration import image_layer, supplied_affine
    from PIL import Image

    value = mapped()
    image = BytesIO()
    Image.new("RGB", (2, 2), "white").save(image, format="PNG")
    scene = PlotScene.model_validate(value["scenes"][0])
    layer, map_source = image_layer(
        image.getvalue(),
        scene=scene,
        registration=supplied_affine((1, 0, 0, 0, -1, 0)),
        filename="synthetic.png",
    )
    value["map_sources"].append(map_source.model_dump(mode="json"))
    value["raster_layers"] = [layer.model_dump(mode="json")]
    return value, image.getvalue()


def test_raster_delivery_validates_asset_and_preserves_deed_hashes(tmp_path):
    value, raw = raster_bundle()
    initial = prepare_dashboard(DashboardBundle.model_validate(mapped()))
    prepared = prepare_dashboard(DashboardBundle.model_validate(value))
    assert initial.manifest.calculation_input_hash == prepared.manifest.calculation_input_hash
    assert initial.manifest.plot_output_hash == prepared.manifest.plot_output_hash
    value["raster_layers"][0]["registration"]["matrix"][2] = 20
    changed = prepare_dashboard(DashboardBundle.model_validate(value))
    assert changed.manifest.map_input_hash != prepared.manifest.map_input_hash
    assert changed.calculations == initial.calculations
    path = tmp_path / "input.json"
    path.write_text(json.dumps(value))
    result = dashboard_file(path, tmp_path / "delivery")
    assert result["status"] == "needs_review", result
    source_id = value["raster_layers"][0]["source_id"]
    assert (tmp_path / f"delivery/assets/{source_id}.bin").read_bytes() == raw
    assert "data:image/png;base64," in (tmp_path / "delivery/dashboard.html").read_text()


def test_raster_declared_dimensions_are_freshly_checked():
    value, _ = raster_bundle()
    value["raster_layers"][0]["width"] = 3
    with pytest.raises(ValueError, match="dimensions"):
        prepare_dashboard(DashboardBundle.model_validate(value))
