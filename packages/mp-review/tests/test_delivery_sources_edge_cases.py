"""Edge-case binding, replay, placement, and GeoJSON feature tests for delivery_sources."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from mp_models.dashboard import DashboardBundle
from mp_models.delivery import (
    DeliveryItem,
    DeliveryLayer,
    DeliveryRequest,
    DeliverySourceBinding,
)
from mp_models.plot import PlotPlacement, PlotScene
from mp_models.revisions import revision_template
from mp_models.webmap import WebMapOptions
from mp_review import delivery_sources as ds
from mp_review.corridor import analyze_corridor_file, replay_corridor
from mp_review.plss import prepare_plss_file, replay_plss
from mp_review.webmap import _Budget
from mp_review.webmap_projection import build_web_map_projection
from mp_verify.dashboard import _hash

PLUGIN = Path(__file__).resolve().parents[3] / "plugins/metesparser"


def _bundle() -> DashboardBundle:
    return DashboardBundle.model_validate_json(
        (PLUGIN / "skills/export-review-package/references/bundle-example.json").read_bytes()
    )


def _corridor_dir(tmp_path: Path):
    src = tmp_path / "corridor.json"
    src.write_bytes((PLUGIN / "skills/plot-corridor/references/example.json").read_bytes())
    out = tmp_path / "corridor-out"
    assert analyze_corridor_file(src, out)["status"] == "needs_review"
    result = replay_corridor(out)
    manifest = out / "corridor-manifest.json"
    binding = DeliverySourceBinding(
        id="cor-bind",
        kind="corridor",
        layer_id=result.boundary.request.calculation_id,
        artifact_dir=str(out),
        manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
        input_sha256=result.input_sha256,
        geometry_sha256=result.boundary.geometry.geometry_hash,
    )
    layer = DeliveryLayer(
        id=binding.layer_id, kind="corridor", visible=True, opacity=1.0, required=True
    )
    return out, result, binding, layer


def _plss_dir(tmp_path: Path):
    src = tmp_path / "plss.json"
    src.write_bytes((PLUGIN / "skills/plot-plss-reference/references/example.json").read_bytes())
    out = tmp_path / "plss-out"
    assert prepare_plss_file(src, out)["status"] == "needs_review"
    result = replay_plss(out)
    manifest = out / "plss-manifest.json"
    binding = DeliverySourceBinding(
        id="plss-bind",
        kind="plss_reference",
        layer_id=result.vector_layers[0].id,
        artifact_dir=str(out),
        manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
        input_sha256=result.input_hash,
        geometry_sha256=_hash(result.vector_layers[0].model_dump(mode="json")),
    )
    layer = DeliveryLayer(
        id=binding.layer_id, kind="plss_reference", visible=True, opacity=1.0, required=True
    )
    return out, result, binding, layer


def _base_request(
    bundle: DashboardBundle,
    binding: DeliverySourceBinding,
    layer: DeliveryLayer,
    **overrides,
) -> DeliveryRequest:
    rev = revision_template(bundle, revision_id="r1")
    data = {
        "id": "pkg",
        "baseline": rev.baseline,
        "revision_id": rev.id,
        "revision_generation": 0,
        "geometry": "scenario",
        "coordinate_mode": "local",
        "units": "international_ft",
        "layers": [layer],
        "source_bindings": [binding],
        "formats": ["svg"],
        **overrides,
    }
    return DeliveryRequest.model_validate(data)


def test_read_scene_and_binding_helpers_fail_closed(tmp_path):
    import shutil

    bundle = _bundle()
    out, result, binding, layer = _corridor_dir(tmp_path)
    req = _base_request(bundle, binding, layer)

    # Missing artifact manifest fails closed via prepare_delivery_source
    missing_binding = binding.model_copy(update={"artifact_dir": str(tmp_path / "missing-dir")})
    with pytest.raises(ValueError, match="regular, intact"):
        ds.prepare_delivery_source(missing_binding, layer, req, bundle)

    # Symlinked artifact manifest fails closed via prepare_delivery_source
    sym_dir = tmp_path / "sym-corridor"
    shutil.copytree(out, sym_dir)
    real_manifest = tmp_path / "ext-corridor-manifest.json"
    real_manifest.write_bytes((sym_dir / "corridor-manifest.json").read_bytes())
    (sym_dir / "corridor-manifest.json").unlink()
    (sym_dir / "corridor-manifest.json").symlink_to(real_manifest)
    sym_binding = binding.model_copy(update={"artifact_dir": str(sym_dir)})
    with pytest.raises(ValueError, match="regular, intact"):
        ds.prepare_delivery_source(sym_binding, layer, req, bundle)

    # Kind or layer_id mismatch fails closed
    wrong_layer = layer.model_copy(update={"id": "other-layer"})
    with pytest.raises(ValueError, match="identity differ"):
        ds.prepare_delivery_source(binding, wrong_layer, req, bundle)

    # Conflicting scene identity with baseline and missing scene_id fail closed in placed mode
    baseline_scene = PlotScene(id="s1", name="S1", kind="projected", crs="EPSG:3857", units="m")
    bundle_with_scene = bundle.model_copy(update={"scenes": (baseline_scene,)})
    conflicting = baseline_scene.model_copy(update={"name": "Different"})
    req_conflict = DeliveryRequest.model_construct(
        scene_id="s1",
        scenes=(conflicting,),
        coordinate_mode="placed",
        placements=(),
        units="m",
        include_full_source=False,
    )
    with pytest.raises(ValueError, match="conflicts with baseline"):
        ds.prepare_delivery_source(binding, layer, req_conflict, bundle_with_scene)

    req_missing_scene = DeliveryRequest.model_construct(
        scene_id=None,
        scenes=(),
        coordinate_mode="placed",
        placements=(),
        units="m",
        include_full_source=False,
    )
    with pytest.raises(ValueError, match="explicitly selected scene"):
        ds.prepare_delivery_source(binding, layer, req_missing_scene, bundle)


def test_corridor_binding_revision_standalone_placement_and_toctou_checks(tmp_path, monkeypatch):
    bundle = _bundle()
    out, result, binding, layer = _corridor_dir(tmp_path)
    req = _base_request(bundle, binding, layer)

    # Revision corridor binding missing corridor_result / raw request
    rev_binding = DeliverySourceBinding.model_construct(
        id="rb",
        kind="corridor",
        layer_id=binding.layer_id,
        artifact_dir=None,
        revision_corridor_id=result.request.id,
        manifest_sha256="0" * 64,
        input_sha256=binding.input_sha256,
        geometry_sha256=binding.geometry_sha256,
    )
    with pytest.raises(ValueError, match="retained request and result"):
        ds.prepare_delivery_source(rev_binding, layer, req, bundle)

    # Revision corridor raw request differs from result.request
    other_req = result.request.model_copy(update={"id": "different-corridor"})
    with pytest.raises(ValueError, match="differs from its retained raw request"):
        ds.prepare_delivery_source(
            rev_binding,
            layer,
            req,
            bundle,
            corridor_result=result,
            corridor_raw_request=other_req.model_dump_json().encode(),
        )

    # Revision corridor result.request.id != binding.revision_corridor_id
    bad_rev_id_binding = rev_binding.model_copy(update={"revision_corridor_id": "other-id"})
    with pytest.raises(ValueError, match="Revision corridor identity differs"):
        ds.prepare_delivery_source(
            bad_rev_id_binding,
            layer,
            req,
            bundle,
            corridor_result=result,
            corridor_raw_request=result.request.model_dump_json().encode(),
        )

    # Standalone corridor binding without artifact_dir (or with stray corridor_result)
    with pytest.raises(ValueError, match="Standalone corridor binding requires"):
        ds.prepare_delivery_source(binding, layer, req, bundle, corridor_result=result)

    # Unsupported corridor result rejected
    unsupported = result.model_copy(update={"availability": "unsupported", "boundary": None})
    monkeypatch.setattr(ds, "replay_corridor", lambda d: unsupported)
    with pytest.raises(ValueError, match="fully supported corridor"):
        ds.prepare_delivery_source(binding, layer, req, bundle)
    monkeypatch.undo()

    # Placed corridor errors: unplaced/missing placement, wrong placement hash, wrong calculation/scene
    scene = PlotScene(id="g1", name="G1", kind="projected", crs="EPSG:3857", units="m")
    placed_req = DeliveryRequest.model_construct(
        coordinate_mode="placed",
        scene_id="g1",
        scenes=(scene,),
        placements=(),
        units="m",
        include_full_source=False,
    )
    with pytest.raises(ValueError, match="explicit placed centerline transform"):
        ds.prepare_delivery_source(binding, layer, placed_req, bundle)

    good_placement = PlotPlacement(
        id="p1",
        calculation_id=result.centerline.request.calculation_id,
        geometry_hash=result.centerline.geometry.geometry_hash,
        scene_id="g1",
        rotation_deg=0.0,
        translation=(1000.0, 2000.0),
        status="approximate",
        rationale="test",
    )
    placed_req_with_p = DeliveryRequest.model_construct(
        coordinate_mode="placed",
        scene_id="g1",
        scenes=(scene,),
        placements=(good_placement,),
        units="m",
        include_full_source=False,
    )
    layer_bad_hash = layer.model_copy(update={"placement_id": "p1", "placement_sha256": "0" * 64})
    with pytest.raises(ValueError, match="placement hash differs"):
        ds.prepare_delivery_source(binding, layer_bad_hash, placed_req_with_p, bundle)

    wrong_calc_p = good_placement.model_copy(update={"calculation_id": "wrong-calc"})
    placed_req_wrong = DeliveryRequest.model_construct(
        coordinate_mode="placed",
        scene_id="g1",
        scenes=(scene,),
        placements=(wrong_calc_p,),
        units="m",
        include_full_source=False,
    )
    layer_wrong_calc = layer.model_copy(
        update={
            "placement_id": "p1",
            "placement_sha256": _hash(wrong_calc_p.model_dump(mode="json")),
        }
    )
    with pytest.raises(ValueError, match="original centerline and selected scene"):
        ds.prepare_delivery_source(binding, layer_wrong_calc, placed_req_wrong, bundle)

    # TOCTOU: request.json changed after replay_corridor
    real_read = ds._read
    monkeypatch.setattr(
        ds,
        "_read",
        lambda p: b'{"tampered":true}' if p.name == "request.json" else real_read(p),
    )
    with pytest.raises(ValueError, match="changed during replay"):
        ds.prepare_delivery_source(binding, layer, req, bundle)
    monkeypatch.undo()

    # TOCTOU: manifest changed during replay (second read differs)
    reads = {"n": 0}

    def flipping_read(p: Path) -> bytes:
        data = real_read(p)
        if p.name == "corridor-manifest.json":
            reads["n"] += 1
            if reads["n"] > 1:
                return data + b" "
        return data

    monkeypatch.setattr(ds, "_read", flipping_read)
    with pytest.raises(ValueError, match="manifest changed during replay"):
        ds.prepare_delivery_source(binding, layer, req, bundle)
    monkeypatch.undo()

    # OSError wrapped cleanly
    monkeypatch.setattr(ds, "_read", lambda p: (_ for _ in ()).throw(OSError("io fail")))
    with pytest.raises(ValueError, match="unavailable for fresh replay"):
        ds.prepare_delivery_source(binding, layer, req, bundle)


def test_plss_binding_and_delivery_source_features_edge_cases(tmp_path, monkeypatch):
    bundle = _bundle()
    out, plss, binding, layer = _plss_dir(tmp_path)
    scene = plss.scenes[0]
    req = _base_request(
        bundle,
        binding,
        layer,
        coordinate_mode="placed",
        scene_id=scene.id,
        scenes=[scene],
        units="m",
    )

    # PLSS binding without artifact_dir
    no_dir = binding.model_copy(update={"artifact_dir": None})
    with pytest.raises(ValueError, match="requires its artifact directory"):
        ds.prepare_delivery_source(no_dir, layer, req, bundle)

    # PLSS wrong manifest hash
    bad_m = binding.model_copy(update={"manifest_sha256": "0" * 64})
    with pytest.raises(ValueError, match="manifest hash differs"):
        ds.prepare_delivery_source(bad_m, layer, req, bundle)

    # PLSS unavailable / non-computed result
    monkeypatch.setattr(
        ds, "replay_plss", lambda d: plss.model_copy(update={"availability": "unavailable"})
    )
    with pytest.raises(ValueError, match="computed, supported PLSS"):
        ds.prepare_delivery_source(binding, layer, req, bundle)
    monkeypatch.undo()

    # PLSS selection.id differs from producer layer id
    other_bind = binding.model_copy(update={"layer_id": "other-plss"})
    other_layer = layer.model_copy(update={"id": "other-plss"})
    with pytest.raises(ValueError, match="differs from producer reference"):
        ds.prepare_delivery_source(other_bind, other_layer, req, bundle)

    # PLSS input/geometry hash mismatch
    bad_hash = binding.model_copy(update={"input_sha256": "0" * 64})
    with pytest.raises(ValueError, match="PLSS input/geometry hash differs"):
        ds.prepare_delivery_source(bad_hash, layer, req, bundle)

    # PLSS local mode or placement_id refused
    local_req = req.model_copy(update={"coordinate_mode": "local", "scene_id": None})
    with pytest.raises(ValueError, match="retains its own supplied scene"):
        ds.prepare_delivery_source(binding, layer, local_req, bundle)

    # PLSS TOCTOU on request.json
    real_read = ds._read
    monkeypatch.setattr(
        ds,
        "_read",
        lambda p: b'{"tampered":true}' if p.name == "request.json" else real_read(p),
    )
    with pytest.raises(ValueError, match="PLSS source request changed"):
        ds.prepare_delivery_source(binding, layer, req, bundle)
    monkeypatch.undo()

    # corridor_export_ring requires plot and placement
    proj = build_web_map_projection(
        PlotScene(id="g", name="G", kind="projected", crs="EPSG:3857", units="m")
    )
    empty_cor_item = DeliveryItem(
        selection=DeliveryLayer(
            id="cor-1", kind="corridor", visible=True, opacity=1.0, required=False
        )
    )
    with pytest.raises(ValueError, match="composed explicit placement"):
        ds.corridor_export_ring(
            empty_cor_item,
            PlotScene(id="g", name="G", kind="projected", crs="EPSG:3857", units="m"),
            WebMapOptions(),
            proj,
        )

    # delivery_source_features: mismatched source_record
    with pytest.raises(ValueError, match="differs from source binding"):
        ds.delivery_source_features(
            empty_cor_item,
            {"layer_id": "wrong", "kind": "corridor"},
            req,
            scene,
            WebMapOptions(),
            _Budget(100),
            proj,
        )

    # delivery_source_features: corridor ring < 4 points rejected; unclosed ring >= 4 points closed
    cor_record = {
        "layer_id": "cor-1",
        "kind": "corridor",
        "binding": {
            "id": "b1",
            "manifest_sha256": "a" * 64,
            "geometry_sha256": "b" * 64,
        },
        "input_sha256": "c" * 64,
        "error": None,
        "boundary_origin_in_centerline_frame": [0.0, 0.0],
    }
    with pytest.raises(ValueError, match="closed boundary ring"):
        ds.delivery_source_features(
            empty_cor_item,
            cor_record,
            req,
            scene,
            WebMapOptions(),
            _Budget(100),
            proj,
            ring=[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)],
        )
    unclosed_ring = [(0.0, 0.0), (0.01, 0.0), (0.01, 0.01), (0.0, 0.01)]
    feats = ds.delivery_source_features(
        empty_cor_item,
        cor_record,
        req,
        scene,
        WebMapOptions(),
        _Budget(100),
        proj,
        ring=unclosed_ring,
    )
    ring_out = feats[0]["geometry"]["coordinates"][0]
    assert ring_out[0] == ring_out[-1] and len(ring_out) == 5

    # delivery_source_features: PLSS missing vector or wrong scene_id rejected
    plss_item = DeliveryItem(selection=layer, vector=None)
    plss_record = {"layer_id": layer.id, "kind": "plss_reference"}
    with pytest.raises(ValueError, match="retain its original scene"):
        ds.delivery_source_features(
            plss_item, plss_record, req, scene, WebMapOptions(), _Budget(100), proj
        )
