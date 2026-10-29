"""Lossless derived-source delivery uses real producer replay and bound geometry."""

import base64
import hashlib
import json
from pathlib import Path

import pytest
from mp_models.corridor import CorridorRequest
from mp_models.dashboard import DashboardBundle
from mp_models.delivery import DeliveryRequest
from mp_models.plot import PlotPlacement, PlotScene
from mp_models.revisions import revision_template
from mp_review.corridor import analyze_corridor_file, replay_corridor
from mp_review.delivery import load_delivery, prepare_delivery, publish_delivery
from mp_review.plss import prepare_plss_file, replay_plss
from mp_review.revisions import publish_revision
from mp_verify.dashboard import _hash

PLUGIN = Path(__file__).parents[3] / "plugins/metesparser"


def source(tmp_path, kind):
    skill = "plot-corridor" if kind == "corridor" else "plot-plss-reference"
    raw = (PLUGIN / "skills" / skill / "references/example.json").read_bytes()
    input = tmp_path / (kind + ".json")
    input.write_bytes(raw)
    directory = tmp_path / kind
    response = (analyze_corridor_file if kind == "corridor" else prepare_plss_file)(
        input, directory
    )
    assert response["status"] == "needs_review"
    result = (replay_corridor if kind == "corridor" else replay_plss)(directory)
    layer_id = (
        result.boundary.request.calculation_id if kind == "corridor" else result.vector_layers[0].id
    )
    manifest = directory / (
        "corridor-manifest.json" if kind == "corridor" else "plss-manifest.json"
    )
    binding = {
        "id": kind + "-binding",
        "kind": kind,
        "layer_id": layer_id,
        "artifact_dir": str(directory),
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "input_sha256": result.input_sha256 if kind == "corridor" else result.input_hash,
        "geometry_sha256": result.boundary.geometry.geometry_hash
        if kind == "corridor"
        else _hash(result.vector_layers[0].model_dump(mode="json")),
    }
    return result, raw, binding


def request(tmp_path, kind, full_source=False):
    result, raw, binding = source(tmp_path, kind)
    bundle = DashboardBundle.model_validate_json(
        (PLUGIN / "skills/export-review-package/references/bundle-example.json").read_bytes()
    )
    revision = revision_template(bundle, revision_id="derived-delivery")
    root = tmp_path / "revisions"
    assert publish_revision(bundle, revision, root)["save_state"] == "published"
    fields = {
        "id": "package",
        "baseline": revision.baseline,
        "revision_id": revision.id,
        "revision_generation": revision.generation,
        "geometry": "scenario",
        "coordinate_mode": "local",
        "units": "international_ft",
        "layers": [
            {
                "id": binding["layer_id"],
                "kind": kind,
                "visible": True,
                "opacity": 1.0,
                "required": True,
            }
        ],
        "source_bindings": [binding],
        "formats": ["svg", "pdf", "dxf"],
        "include_full_source": full_source,
    }
    if kind == "plss_reference":
        fields.update(
            coordinate_mode="placed", scene_id=result.scenes[0].id, scenes=result.scenes, units="m"
        )
    return bundle, root / revision.id, DeliveryRequest.model_validate(fields), result, raw


def test_corridor_save_reopen_delivery_retains_raw_centerline_and_full_construction(tmp_path):
    bundle, revision, req, corridor, raw = request(tmp_path, "corridor")
    snapshot = prepare_delivery(bundle, revision, req)
    record = snapshot.derived_sources[0]
    assert base64.b64decode(record["raw_request_base64"]) == raw
    assert CorridorRequest.model_validate(record["canonical_request"]) == corridor.request
    assert record["boundary_origin_in_centerline_frame"] == list(
        corridor.boundary_origin_in_centerline_frame
    )
    assert record["error"] == corridor.error.model_dump(mode="json")
    first = snapshot.items[0].primitives[0]
    assert first.start == pytest.approx(corridor.polygon[0])
    assert first.input_status == "corridor_derived"
    assert first.recorded_bearing_deg is None and first.recorded_distance_ft is None
    assert snapshot.metrics[0].misclosure_ft is None
    published = publish_delivery(bundle, revision, req, tmp_path / "exports")
    assert published["status"] == "needs_review"
    restored = load_delivery(bundle, revision, tmp_path / "exports/package")
    assert restored == snapshot
    manifest = json.loads((tmp_path / "exports/package/delivery-manifest.json").read_text())
    assert manifest["snapshot_sha256"] == _hash(restored.model_dump(mode="json"))


@pytest.mark.parametrize("field", ["manifest_sha256", "input_sha256", "geometry_sha256"])
def test_binding_rejects_wrong_or_stale_source_identity(tmp_path, field):
    bundle, revision, req, _, _ = request(tmp_path, "corridor")
    data = req.model_dump(mode="json")
    data["source_bindings"][0][field] = "0" * 64
    with pytest.raises(ValueError):
        prepare_delivery(bundle, revision, DeliveryRequest.model_validate(data))


def test_selected_geometry_cannot_be_an_unrelated_id_with_a_valid_attachment(tmp_path):
    bundle, revision, req, _, _ = request(tmp_path, "corridor")
    data = req.model_dump(mode="json")
    data["source_bindings"][0]["layer_id"] = data["layers"][0]["id"] = "unrelated-deed"
    with pytest.raises(ValueError, match="identity"):
        prepare_delivery(bundle, revision, DeliveryRequest.model_validate(data))


def test_changed_source_breaks_frozen_delivery_replay_even_with_existing_package(tmp_path):
    bundle, revision, req, _, _ = request(tmp_path, "corridor")
    assert publish_delivery(bundle, revision, req, tmp_path / "exports")["status"] == "needs_review"
    path = Path(req.source_bindings[0].artifact_dir) / "request.json"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        load_delivery(bundle, revision, tmp_path / "exports/package")


def test_corridor_origin_is_composed_once_with_sourced_rotated_centerline_placement(tmp_path):
    bundle, revision, req, corridor, _ = request(tmp_path, "corridor")
    scene = PlotScene(
        id="corridor-grid",
        name="Supplied control grid",
        kind="projected",
        crs="EPSG:3857",
        units="m",
        basis="grid",
    )
    placement = PlotPlacement(
        id="centerline-control",
        calculation_id=corridor.centerline.request.calculation_id,
        geometry_hash=corridor.centerline.geometry.geometry_hash,
        scene_id=scene.id,
        status="referenced",
        rationale="Synthetic supplied origin and rotation",
        position_evidence=("supplied origin",),
        orientation_evidence=("supplied 90 degree clockwise rotation",),
        rotation_deg=90,
        translation=(1000, 2000),
    )
    data = req.model_dump(mode="json")
    data.update(
        coordinate_mode="placed",
        scene_id=scene.id,
        scenes=[scene.model_dump(mode="json")],
        placements=[placement.model_dump(mode="json")],
        units="m",
        formats=["svg", "dxf", "geojson"],
    )
    data["layers"][0].update(
        placement_id=placement.id, placement_sha256=_hash(placement.model_dump(mode="json"))
    )
    placed_req = DeliveryRequest.model_validate(data)
    snapshot = prepare_delivery(bundle, revision, placed_req)
    assert snapshot.items[0].primitives[0].start == pytest.approx((1000, 2003.048), abs=1e-9)
    assert snapshot.derived_sources[0]["supplied_centerline_placement"] == placement.model_dump(
        mode="json"
    )
    response = publish_delivery(bundle, revision, placed_req, tmp_path / "geo")
    assert response["status"] == "needs_review"
    features = json.loads((tmp_path / "geo/package/drawing.geojson").read_text())["features"]
    assert features and all(f["properties"]["kind"] == "corridor_boundary" for f in features)
    assert all(f["geometry"]["type"] == "Polygon" for f in features)
    lon, lat = features[0]["geometry"]["coordinates"][0][0]
    assert lon == pytest.approx(1000 / 20037508.342789244 * 180, abs=1e-9)
    assert lat > 0


def _arc_delivery_source(tmp_path):
    import math

    from mp_models.deed_call import DeedCall
    from mp_models.delivery import DeliveryItem
    from mp_models.plot import PlotPlacement
    from mp_models.plot_request import PlotCall, PlotRequest
    from mp_verify.plot import prepare_plot

    bundle, revision, base_request, _, _ = request(tmp_path, "corridor")
    radius, sweep = 100.0, 90.0
    arc_length = radius * math.radians(sweep)
    plot = prepare_plot(
        PlotRequest(
            title="Synthetic curved boundary",
            calculation_id=base_request.layers[0].id,
            foot_definition="international_ft",
            calls=(
                PlotCall(
                    id="boundary-arc",
                    source_reference="synthetic curved boundary",
                    call=DeedCall(
                        course=1,
                        direction_text="right circular arc",
                        distance_ft=arc_length,
                        bearing_azimuth_deg_from_north=0.0,
                        curve_dir="right",
                        radius_ft=radius,
                        delta_deg=sweep,
                        arc_length_ft=arc_length,
                    ),
                ),
                PlotCall(
                    id="boundary-close",
                    source_reference="synthetic closing chord",
                    call=DeedCall(
                        course=2,
                        direction_text="closing chord",
                        distance_ft=math.sqrt(2) * radius,
                        bearing_azimuth_deg_from_north=225.0,
                    ),
                ),
            ),
        )
    )
    scene = PlotScene(
        id="arc-grid",
        name="Synthetic projected frame",
        kind="projected",
        crs="EPSG:3857",
        units="m",
        basis="grid",
    )
    placement = PlotPlacement(
        id="arc-placement",
        calculation_id=plot.request.calculation_id,
        geometry_hash=plot.geometry.geometry_hash,
        scene_id=scene.id,
        rotation_deg=37.0,
        translation=(1000.0, 2000.0),
        status="referenced",
        rationale="Synthetic supplied transform",
        position_evidence=("synthetic origin",),
        orientation_evidence=("synthetic rotation",),
    )
    selection = base_request.layers[0]
    item = DeliveryItem(selection=selection, plot=plot, placement=placement)
    bound_request = base_request.model_copy(
        update={
            "coordinate_mode": "placed",
            "scene_id": scene.id,
            "scenes": (scene,),
            "placements": (placement,),
            "units": "m",
        }
    )
    record = {
        "layer_id": selection.id,
        "kind": "corridor",
        "binding": base_request.source_bindings[0].model_dump(mode="json"),
        "input_sha256": "a" * 64,
        "error": {"unit": "international_ft", "total_bound": 0.001},
        "boundary_origin_in_centerline_frame": [0.0, 0.0],
    }
    return item, record, bound_request, scene, placement


def test_curved_corridor_geojson_samples_placed_arc_to_requested_tolerance(tmp_path):
    import math

    from mp_models.webmap import WebMapOptions
    from mp_review.delivery_sources import delivery_source_features
    from mp_review.webmap import _Budget
    from mp_review.webmap_projection import build_web_map_projection
    from mp_verify.plot import transform_point

    item, record, request, scene, placement = _arc_delivery_source(tmp_path)
    tolerance = 0.05
    options = WebMapOptions(tolerance_m=tolerance)
    projection = build_web_map_projection(scene)
    feature = delivery_source_features(
        item, record, request, scene, options, _Budget(options.max_vertices), projection
    )[0]
    ring = feature["geometry"]["coordinates"][0]
    arc_end = projection.from_mercator(
        projection.to_mercator(
            transform_point(
                item.plot.geometry.primitives[0].end,
                placement,
                native_units="international_ft",
                scene_units=scene.units,
            )
        )
    )
    arc_end_index = min(range(len(ring)), key=lambda index: math.dist(ring[index], arc_end))
    assert math.dist(ring[arc_end_index], arc_end) < 1e-10
    assert arc_end_index > 3

    radius_m = item.plot.geometry.primitives[0].radius_ft * 0.3048
    arc_points = [projection.to_mercator(point) for point in ring[: arc_end_index + 1]]
    deviations = []
    for a, b in zip(arc_points, arc_points[1:], strict=False):
        chord = math.dist(a, b)
        deviations.append(radius_m - math.sqrt(max(0.0, radius_m**2 - (chord / 2) ** 2)))
    assert max(deviations) <= tolerance
    assert feature["properties"]["curve_linearization_tolerance_m"] == tolerance


@pytest.mark.parametrize(
    "options,code",
    [
        ("vertices", "vertex_limit"),
        ("depth", "sampling_limit"),
    ],
)
def test_curved_corridor_geojson_refuses_sampling_limits(tmp_path, options, code):
    from mp_models.webmap import WebMapOptions
    from mp_review.delivery_sources import delivery_source_features
    from mp_review.webmap import WebMapUnavailable, _Budget
    from mp_review.webmap_projection import build_web_map_projection

    item, record, request, scene, _ = _arc_delivery_source(tmp_path)
    sampling = (
        WebMapOptions(tolerance_m=0.05, max_vertices=3)
        if options == "vertices"
        else WebMapOptions(tolerance_m=1e-20, max_depth=1)
    )
    with pytest.raises(WebMapUnavailable) as exc:
        delivery_source_features(
            item,
            record,
            request,
            scene,
            sampling,
            _Budget(sampling.max_vertices),
            build_web_map_projection(scene),
        )
    assert exc.value.code == code


@pytest.mark.parametrize("full_source", [False, True])
def test_plss_delivery_preserves_original_reference_and_explicit_source_page_privacy(
    tmp_path, full_source
):
    bundle, revision, req, plss, raw = request(tmp_path, "plss_reference", full_source)
    snapshot = prepare_delivery(bundle, revision, req)
    record = snapshot.derived_sources[0]
    source_data = json.loads(raw)["dataset"]["source"]["data_base64"]
    assert record["canonical_request"]["dataset"]["references"][0]["corners"]
    assert record["source_hash"] == plss.source_hash
    assert record["dataset_hash"] == plss.dataset_hash
    assert record["canonical_request"]["dataset"]["source"]["data_base64"] == (
        source_data if full_source else None
    )
    assert record["raw_request_base64"] == (base64.b64encode(raw).decode() if full_source else None)
    assert record["source_bytes_omitted"] is (not full_source)
    assert snapshot.items[0].vector == plss.vector_layers[0]
    data = req.model_dump(mode="json")
    data["formats"] = ["svg", "dxf", "geojson"]
    published = publish_delivery(
        bundle, revision, DeliveryRequest.model_validate(data), tmp_path / "exports"
    )
    assert published["status"] == "needs_review"
    assert (
        load_delivery(bundle, revision, tmp_path / "exports/package").derived_sources[0] == record
    )
    features = json.loads((tmp_path / "exports/package/drawing.geojson").read_text())["features"]
    assert features[0]["properties"]["kind"] == "computed_plss_reference"


def test_plss_does_not_accept_a_different_target_scene_or_a_forged_prepared_layer(tmp_path):
    bundle, revision, req, _, _ = request(tmp_path, "plss_reference")
    changed = req.model_dump(mode="json")
    changed["scenes"][0]["crs"] = "EPSG:3395"
    with pytest.raises(ValueError, match="scene"):
        prepare_delivery(bundle, revision, DeliveryRequest.model_validate(changed))
    source_dir = Path(req.source_bindings[0].artifact_dir)
    data = json.loads((source_dir / "prepared-layer.json").read_text())
    data["vector_layers"][0]["label"] = "forged unrelated reference"
    (source_dir / "prepared-layer.json").write_text(json.dumps(data))
    with pytest.raises(ValueError):
        replay_plss(source_dir)


def test_plss_replay_rejects_forged_output_even_after_manifest_hashes_are_updated(tmp_path):
    bundle, revision, req, _, _ = request(tmp_path, "plss_reference")
    directory = Path(req.source_bindings[0].artifact_dir)
    path = directory / "prepared-layer.json"
    payload = json.loads(path.read_text())
    payload["vector_layers"][0]["coordinates"][0][0][0] += 1
    path.write_text(json.dumps(payload))
    manifest_path = directory / "plss-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["sha256"]["prepared-layer.json"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    data = req.model_dump(mode="json")
    data["source_bindings"][0]["manifest_sha256"] = hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    with pytest.raises(ValueError, match="fresh"):
        prepare_delivery(bundle, revision, DeliveryRequest.model_validate(data))


def test_corridor_placement_must_match_fresh_centerline_even_with_self_consistent_request_hash(
    tmp_path,
):
    bundle, revision, req, corridor, _ = request(tmp_path, "corridor")
    scene = PlotScene(
        id="grid", name="Supplied grid", kind="projected", crs="EPSG:3857", units="m", basis="grid"
    )
    placement = PlotPlacement(
        id="stale",
        calculation_id=corridor.centerline.request.calculation_id,
        geometry_hash="0" * 64,
        scene_id=scene.id,
        status="approximate",
        rationale="Supplied stale centerline transform",
    )
    data = req.model_dump(mode="json")
    data.update(
        coordinate_mode="placed",
        scene_id=scene.id,
        scenes=[scene.model_dump(mode="json")],
        placements=[placement.model_dump(mode="json")],
        units="m",
    )
    data["layers"][0].update(
        placement_id=placement.id, placement_sha256=_hash(placement.model_dump(mode="json"))
    )
    with pytest.raises(ValueError, match="stale"):
        prepare_delivery(bundle, revision, DeliveryRequest.model_validate(data))


def _placed_corridor_request(tmp_path):
    bundle, revision, req, corridor, _ = request(tmp_path, "corridor")
    scene = PlotScene(
        id="corridor-grid",
        name="Supplied control grid",
        kind="projected",
        crs="EPSG:3857",
        units="m",
        basis="grid",
    )
    placement = PlotPlacement(
        id="centerline-control",
        calculation_id=corridor.centerline.request.calculation_id,
        geometry_hash=corridor.centerline.geometry.geometry_hash,
        scene_id=scene.id,
        status="referenced",
        rationale="Synthetic supplied origin and rotation",
        position_evidence=("supplied origin",),
        orientation_evidence=("supplied 90 degree clockwise rotation",),
        rotation_deg=90,
        translation=(1000, 2000),
    )
    data = req.model_dump(mode="json")
    data.update(
        coordinate_mode="placed",
        scene_id=scene.id,
        scenes=[scene.model_dump(mode="json")],
        placements=[placement.model_dump(mode="json")],
        units="m",
        formats=["svg", "dxf", "geojson"],
    )
    data["layers"][0].update(
        placement_id=placement.id, placement_sha256=_hash(placement.model_dump(mode="json"))
    )
    return bundle, revision, data


def _with_failing_optional_layer(data):
    data = json.loads(json.dumps(data))
    bad = dict(data["source_bindings"][0], id="bad-binding", layer_id="bad-layer")
    data["source_bindings"].append(bad)
    data["layers"].append(
        {"id": "bad-layer", "kind": "corridor", "visible": True, "opacity": 1.0, "required": False}
    )
    return DeliveryRequest.model_validate(data)


def test_geojson_skips_optional_layer_that_failed_preparation(tmp_path):
    bundle, revision, data = _placed_corridor_request(tmp_path)
    req = _with_failing_optional_layer(data)
    snapshot = prepare_delivery(bundle, revision, req)
    assert any(o.layer_id == "bad-layer" for o in snapshot.omissions)
    response = publish_delivery(bundle, revision, req, tmp_path / "exports")
    assert response["status"] == "needs_review", response
    features = json.loads((tmp_path / "exports/package/drawing.geojson").read_text())["features"]
    assert features and all(f["properties"]["delivery_layer_id"] != "bad-layer" for f in features)


def test_failed_publish_does_not_strand_request_id(tmp_path, monkeypatch):
    import mp_review.delivery as delivery

    bundle, revision, data = _placed_corridor_request(tmp_path)
    req = DeliveryRequest.model_validate(data)

    def boom(*_args, **_kwargs):
        raise ValueError("simulated render failure")

    with monkeypatch.context() as patch:
        patch.setattr(delivery, "_geojson", boom)
        failed = publish_delivery(bundle, revision, req, tmp_path / "exports")
    assert failed["status"] == "error"
    assert not (tmp_path / "exports/package/pending.json").exists()
    retry = publish_delivery(bundle, revision, req, tmp_path / "exports")
    assert retry["status"] == "needs_review", retry


@pytest.mark.parametrize("fmt", ["dxf", "geojson"])
def test_rotation_without_labels_records_disclosed_omission_for_cad_gis(tmp_path, fmt):
    bundle, revision, data = _placed_corridor_request(tmp_path)
    data["presentation_rotation_deg"] = 30.0
    data["formats"] = ["svg", fmt]
    data["labels"] = []
    req = DeliveryRequest.model_validate(data)
    snapshot = prepare_delivery(bundle, revision, req)
    omitted = [o for o in snapshot.omissions if o.format == fmt]
    assert omitted and "rotation" in omitted[0].reason.lower()
    assert not [o for o in snapshot.omissions if o.format == "svg"]
    response = publish_delivery(bundle, revision, req, tmp_path / "exports")
    assert response["status"] == "needs_review", response
    assert any(o["format"] == fmt for o in response["omissions"])


def test_geojson_coordinates_ignore_presentation_rotation(tmp_path):
    bundle, revision, data = _placed_corridor_request(tmp_path)
    data["formats"] = ["geojson"]
    data["labels"] = []
    rotated = DeliveryRequest.model_validate({**data, "presentation_rotation_deg": 30.0})
    flat = DeliveryRequest.model_validate({**data, "id": "flat"})
    publish_delivery(bundle, revision, rotated, tmp_path / "exports")
    publish_delivery(bundle, revision, flat, tmp_path / "exports")

    def geometries(name):
        text = (tmp_path / "exports" / name / "drawing.geojson").read_text()
        return [f["geometry"] for f in json.loads(text)["features"]]

    assert geometries("package") == geometries("flat")


def test_inspect_delivery_surfaces_rotation_omission(tmp_path, monkeypatch, capsys):
    from mp_review.cli import main

    bundle, revision, data = _placed_corridor_request(tmp_path)
    data["presentation_rotation_deg"] = 30.0
    data["labels"] = []
    req = DeliveryRequest.model_validate(data)
    assert publish_delivery(bundle, revision, req, tmp_path / "exports")["status"] == "needs_review"
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(bundle.model_dump_json())
    monkeypatch.setattr(
        "sys.argv",
        [
            "metes-review",
            "inspect-delivery",
            str(bundle_path),
            "--revision-dir",
            str(revision),
            "--package-dir",
            str(tmp_path / "exports/package"),
        ],
    )
    with pytest.raises(SystemExit):
        main()
    payload = json.loads(capsys.readouterr().out)
    assert any("rotation" in o["reason"].lower() for o in payload["omissions"])


def _signed_area(ring):
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:], strict=False)) / 2


def _assert_rfc7946_orientation(features):
    polygons = 0
    for feature in features:
        geometry = feature["geometry"]
        if geometry["type"] == "Polygon":
            parts = [geometry["coordinates"]]
        elif geometry["type"] == "MultiPolygon":
            parts = geometry["coordinates"]
        else:
            continue
        for rings in parts:
            polygons += 1
            assert _signed_area(rings[0]) > 0, "exterior ring must be counterclockwise"
            assert all(_signed_area(hole) < 0 for hole in rings[1:])
    assert polygons


def test_corridor_geojson_exterior_ring_is_counterclockwise_and_hashed_after(tmp_path):
    bundle, revision, data = _placed_corridor_request(tmp_path)
    req = DeliveryRequest.model_validate(data)
    assert publish_delivery(bundle, revision, req, tmp_path / "exports")["status"] == "needs_review"
    package = tmp_path / "exports/package"
    _assert_rfc7946_orientation(json.loads((package / "drawing.geojson").read_text())["features"])
    manifest = json.loads((package / "delivery-manifest.json").read_text())
    digest = hashlib.sha256((package / "drawing.geojson").read_bytes()).hexdigest()
    assert manifest["artifacts"]["drawing.geojson"] == digest
    load_delivery(bundle, revision, package)


def test_plss_geojson_exterior_ring_is_counterclockwise(tmp_path):
    bundle, revision, req, _, _ = request(tmp_path, "plss_reference")
    data = req.model_dump(mode="json")
    data["formats"] = ["svg", "geojson"]
    published = publish_delivery(
        bundle, revision, DeliveryRequest.model_validate(data), tmp_path / "exports"
    )
    assert published["status"] == "needs_review", published
    features = json.loads((tmp_path / "exports/package/drawing.geojson").read_text())["features"]
    _assert_rfc7946_orientation(features)
