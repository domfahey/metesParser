"""High-signal security, replay, omission, and error-handling tests for delivery.py."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
from pathlib import Path

import pytest
from mp_models.dashboard import DashboardBundle
from mp_models.delivery import (
    DeliveryLayer,
    DeliveryRequest,
    DeliverySourceBinding,
)
from mp_models.plot import PlotPlacement, PlotScene
from mp_models.revisions import revision_template
from mp_review import delivery as dmod
from mp_review.corridor import analyze_corridor_file, replay_corridor
from mp_review.delivery import (
    load_delivery,
    prepare_delivery,
    publish_delivery,
    replay_delivery,
)
from mp_review.json_input import InvalidInputJson
from mp_review.revisions import load_revision, publish_revision
from mp_review.webmap_projection import WebMapUnavailable
from mp_verify.dashboard import _hash

FIXTURES = Path(__file__).parent / "fixtures"
PLUGIN = Path(__file__).resolve().parents[3] / "plugins/metesparser"


def _abs_setup(tmp_path: Path):
    bundle = DashboardBundle.model_validate_json((FIXTURES / "dashboard-absolute.json").read_text())
    rev = revision_template(bundle, revision_id="pub")
    rev_root = tmp_path / "revs"
    assert publish_revision(bundle, rev, rev_root)["save_state"] == "published"
    req = DeliveryRequest(
        id="pkg",
        baseline=rev.baseline,
        revision_id="pub",
        revision_generation=0,
        geometry="scenario",
        coordinate_mode="local",
        units="unknown_ft",
        layers=[
            {
                "id": "calc-one",
                "kind": "calculation",
                "visible": True,
                "opacity": 1.0,
                "required": False,
            }
        ],
        formats=["svg"],
    )
    return bundle, rev_root / "pub", req


def _placed_setup(tmp_path: Path, *, with_edit: bool = False):
    raw = json.loads((FIXTURES / "dashboard-absolute.json").read_text())
    raw["schema_version"] = "1.1"
    raw["calculations"][0]["frame"]["foot_definition"] = "international_ft"
    raw["scenes"] = [
        {"id": "g1", "name": "G1", "kind": "projected", "crs": "EPSG:3857", "units": "m"}
    ]
    bundle = DashboardBundle.model_validate(raw)
    rev_data = revision_template(bundle, revision_id="pub-p").model_dump(mode="json")
    if with_edit:
        rev_data["edits"] = [
            {
                "call_id": "call-one",
                "occurrence_id": "occ-one",
                "tract_id": "parcel-one",
                "document_id": "doc-one",
                "raw_fields": {"distance_ft": "101"},
                "rationale": "Hypothetical tweak.",
            }
        ]
    rev_root = tmp_path / "revs-p"
    assert publish_revision(bundle, rev_data, rev_root)["save_state"] == "published"
    prepared = load_revision(bundle, rev_root / "pub-p")
    geom_hash = prepared.current_geometry[0].plot.geometry.geometry_hash
    placement = PlotPlacement(
        id="pl-1",
        calculation_id="calc-one",
        geometry_hash=geom_hash,
        scene_id="g1",
        rotation_deg=0.0,
        translation=(1000.0, 2000.0),
        status="approximate",
        rationale="test",
    )
    req = DeliveryRequest(
        id="pkg-placed",
        baseline=prepared.revision.baseline,
        revision_id="pub-p",
        revision_generation=0,
        geometry="scenario",
        coordinate_mode="placed",
        scene_id="g1",
        units="m",
        placements=[placement],
        layers=[
            {
                "id": "calc-one",
                "kind": "calculation",
                "visible": True,
                "opacity": 1.0,
                "required": False,
                "placement_id": "pl-1",
                "placement_sha256": _hash(placement.model_dump(mode="json")),
            }
        ],
        formats=["svg", "geojson"],
    )
    return bundle, rev_root / "pub-p", req, placement


def test_prepare_delivery_validation_errors_for_version_scenes_placements_and_layers(
    tmp_path, monkeypatch
):
    bundle, rev_dir, req = _abs_setup(tmp_path)

    # Unsupported exporter version
    with pytest.raises(ValueError, match="exporter version"):
        prepare_delivery(bundle, rev_dir, req, exporter_version="delivery-99")

    # Duplicate supplied placement ID
    p1 = PlotPlacement(
        id="dup",
        calculation_id="calc-one",
        geometry_hash="a" * 64,
        scene_id="s1",
        rotation_deg=0.0,
        translation=(0.0, 0.0),
        status="approximate",
        rationale="r",
    )
    req_dup_p = {
        **req.model_dump(mode="json"),
        "placements": [p1.model_dump(mode="json"), p1.model_dump(mode="json")],
    }
    with pytest.raises(ValueError, match="Duplicate supplied placement"):
        prepare_delivery(bundle, rev_dir, req_dup_p)

    # Supplied scene conflicts with baseline scene
    s1 = PlotScene(id="s1", name="S1", kind="projected", crs="EPSG:3857", units="m")
    b_scene = bundle.model_copy(update={"scenes": (s1,)})
    rev_s = revision_template(b_scene, revision_id="pub-s")
    assert publish_revision(b_scene, rev_s, tmp_path / "revs-s")["save_state"] == "published"
    req_conflict = req.model_copy(
        update={
            "baseline": rev_s.baseline,
            "revision_id": "pub-s",
            "scenes": (s1.model_copy(update={"name": "Conflict"}),),
        }
    )
    with pytest.raises(ValueError, match="conflicts with baseline scene"):
        prepare_delivery(b_scene, tmp_path / "revs-s/pub-s", req_conflict)

    # Unknown requested placement scene
    with pytest.raises(ValueError, match="Unknown requested placement scene"):
        prepare_delivery(
            bundle,
            rev_dir,
            req.model_copy(update={"coordinate_mode": "placed", "scene_id": "missing"}),
        )

    # GeoJSON without placed projected scene
    with pytest.raises(ValueError, match="projected scene and placed"):
        prepare_delivery(bundle, rev_dir, req.model_copy(update={"formats": ("geojson",)}))

    # Required unknown calculation -> no current geometry
    with pytest.raises(ValueError, match="no current geometry"):
        prepare_delivery(
            bundle,
            rev_dir,
            req.model_copy(
                update={
                    "layers": (
                        DeliveryLayer(
                            id="no-calc",
                            kind="calculation",
                            visible=True,
                            opacity=1.0,
                            required=True,
                        ),
                    )
                }
            ),
        )

    # Calculation with incomplete geometry
    real_load = dmod.load_revision

    def incomplete_load(b, d):
        prep = real_load(b, d)
        g = prep.current_geometry[0]
        bad_geom = g.plot.geometry.model_copy(update={"completeness": "partial"})
        bad_plot = g.plot.model_copy(update={"geometry": bad_geom})
        return prep.model_copy(
            update={"current_geometry": (g.model_copy(update={"plot": bad_plot}),)}
        )

    monkeypatch.setattr(dmod, "load_revision", incomplete_load)
    with pytest.raises(ValueError, match="unresolved geometry"):
        prepare_delivery(
            bundle,
            rev_dir,
            req.model_copy(
                update={
                    "layers": (
                        DeliveryLayer(
                            id="calc-one",
                            kind="calculation",
                            visible=True,
                            opacity=1.0,
                            required=True,
                        ),
                    )
                }
            ),
        )
    monkeypatch.undo()

    # Placed calculation with missing placement_id and mismatched placement calculation/scene
    b_p, r_p, req_p, placement = _placed_setup(tmp_path)
    req_no_pl = req_p.model_copy(
        update={
            "layers": (
                DeliveryLayer(
                    id="calc-one",
                    kind="calculation",
                    visible=True,
                    opacity=1.0,
                    required=True,
                    placement_id="missing",
                    placement_sha256="0" * 64,
                ),
            )
        }
    )
    with pytest.raises(ValueError, match="Explicit fresh placement identity"):
        prepare_delivery(b_p, r_p, req_no_pl)

    bad_p = placement.model_copy(update={"status": "unplaced"})
    req_bad_p = req_p.model_copy(
        update={
            "placements": (bad_p,),
            "layers": (
                DeliveryLayer(
                    id="calc-one",
                    kind="calculation",
                    visible=True,
                    opacity=1.0,
                    required=True,
                    placement_id=bad_p.id,
                    placement_sha256=_hash(bad_p.model_dump(mode="json")),
                ),
            ),
        }
    )
    with pytest.raises(ValueError, match="calculation/scene/status mismatch"):
        prepare_delivery(b_p, r_p, req_bad_p)

    # Context vector/raster layer errors: local mode, placement_id set, unknown vector, unknown raster
    with pytest.raises(ValueError, match="explicit placed scene"):
        prepare_delivery(
            bundle,
            rev_dir,
            req.model_copy(
                update={
                    "layers": (
                        DeliveryLayer(
                            id="v1", kind="vector", visible=True, opacity=1.0, required=True
                        ),
                    )
                }
            ),
        )
    with pytest.raises(ValueError, match="not deed placement"):
        prepare_delivery(
            b_p,
            r_p,
            req_p.model_copy(
                update={
                    "layers": (
                        DeliveryLayer(
                            id="v1",
                            kind="vector",
                            visible=True,
                            opacity=1.0,
                            required=True,
                            placement_id="pl-1",
                            placement_sha256="0" * 64,
                        ),
                    )
                }
            ),
        )
    with pytest.raises(ValueError, match="cross-scene vector"):
        prepare_delivery(
            b_p,
            r_p,
            req_p.model_copy(
                update={
                    "layers": (
                        DeliveryLayer(
                            id="v-missing", kind="vector", visible=True, opacity=1.0, required=True
                        ),
                    )
                }
            ),
        )
    with pytest.raises(ValueError, match="cross-scene raster"):
        prepare_delivery(
            b_p,
            r_p,
            req_p.model_copy(
                update={
                    "layers": (
                        DeliveryLayer(
                            id="r-missing", kind="raster", visible=True, opacity=1.0, required=True
                        ),
                    )
                }
            ),
        )

    # No visible representable content
    with pytest.raises(ValueError, match="no selected representable content"):
        prepare_delivery(
            bundle,
            rev_dir,
            req.model_copy(
                update={
                    "layers": (
                        DeliveryLayer(
                            id="calc-one",
                            kind="calculation",
                            visible=False,
                            opacity=1.0,
                            required=False,
                        ),
                    )
                }
            ),
        )


def test_revision_corridor_binding_checks_in_prepare_delivery(tmp_path, monkeypatch):
    bundle, rev_dir, req = _abs_setup(tmp_path)
    cor_src = tmp_path / "cor.json"
    cor_src.write_bytes((PLUGIN / "skills/plot-corridor/references/example.json").read_bytes())
    cor_out = tmp_path / "cor-out"
    assert analyze_corridor_file(cor_src, cor_out)["status"] == "needs_review"
    cor_res = replay_corridor(cor_out)
    cid = cor_res.request.id

    # Publish schema 1.2 revision with corridor
    rev_data = revision_template(bundle, revision_id="rev-cor").model_dump(mode="json")
    rev_data["schema_version"] = "1.2"
    rev_data["corridors"] = [
        {"id": cid, "action": "retain", "raw_request_json": cor_src.read_text()}
    ]
    assert publish_revision(bundle, rev_data, tmp_path / "revs-cor")["save_state"] == "published"
    rc_dir = tmp_path / "revs-cor/rev-cor"
    m_sha = hashlib.sha256((rc_dir / "manifest.json").read_bytes()).hexdigest()

    good_binding = DeliverySourceBinding(
        id="rc-bind",
        kind="corridor",
        layer_id=cor_res.boundary.request.calculation_id,
        revision_corridor_id=cid,
        manifest_sha256=m_sha,
        input_sha256=cor_res.input_sha256,
        geometry_sha256=cor_res.boundary.geometry.geometry_hash,
    )
    cor_req = req.model_copy(
        update={
            "revision_id": "rev-cor",
            "units": "international_ft",
            "layers": (
                DeliveryLayer(
                    id=good_binding.layer_id,
                    kind="corridor",
                    visible=True,
                    opacity=1.0,
                    required=True,
                ),
            ),
            "source_bindings": (good_binding,),
        }
    )

    # 1. Wrong layer_id in binding -> line 169
    bad_layer_b = good_binding.model_copy(update={"layer_id": "wrong-boundary"})
    with pytest.raises(ValueError, match="layer identity differs"):
        prepare_delivery(
            bundle,
            rc_dir,
            cor_req.model_copy(
                update={
                    "layers": (
                        DeliveryLayer(
                            id="wrong-boundary",
                            kind="corridor",
                            visible=True,
                            opacity=1.0,
                            required=True,
                        ),
                    ),
                    "source_bindings": (bad_layer_b,),
                }
            ),
        )

    # 2. Unsupported prepared corridor result -> line 160
    real_load = dmod.load_revision

    def unsupported_cor_load(b, d):
        prep = real_load(b, d)
        item = prep.corridor_results[0]
        bad_item = item.model_copy(
            update={"result": item.result.model_copy(update={"availability": "unsupported"})}
        )
        return prep.model_copy(update={"corridor_results": (bad_item,)})

    monkeypatch.setattr(dmod, "load_revision", unsupported_cor_load)
    with pytest.raises(ValueError, match="identity or geometry is unsupported"):
        prepare_delivery(bundle, rc_dir, cor_req)

    # 3. Missing manifest.json on disk while load_revision returns parsed -> line 132
    monkeypatch.setattr(dmod, "load_revision", lambda b, d: real_load(b, rc_dir))
    with pytest.raises(ValueError, match="requires its published manifest"):
        prepare_delivery(bundle, tmp_path / "empty-dir", cor_req)


def _signed_area(ring: list[list[float]]) -> float:
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:], strict=False)) / 2


def _rehash_delivery_artifact(directory: Path, name: str) -> None:
    manifest_path = directory / "delivery-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["artifacts"][name] = hashlib.sha256((directory / name).read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))


def test_geojson_rfc7946_hypothetical_kind_and_omission_helpers(tmp_path, monkeypatch):
    # MultiPolygon winding orientation (exterior CW -> CCW; hole CCW -> CW) via public publish_delivery
    raw = json.loads((FIXTURES / "dashboard-absolute.json").read_text())
    raw["schema_version"] = "1.1"
    raw["calculations"][0]["frame"]["foot_definition"] = "international_ft"
    raw["scenes"] = [
        {"id": "g1", "name": "G1", "kind": "projected", "crs": "EPSG:3857", "units": "m"}
    ]
    raw["map_sources"] = [
        {
            "id": "src-v1",
            "label": "MultiPolygon fixture",
            "sha256": "a" * 64,
            "native_crs": "EPSG:3857",
            "native_units": "m",
        }
    ]
    raw["vector_layers"] = [
        {
            "id": "mp-layer",
            "label": "MP Layer",
            "source_id": "src-v1",
            "scene_id": "g1",
            "geometry_type": "MultiPolygon",
            "coordinates": [
                [
                    [
                        [1000.0, 2000.0],
                        [1000.0, 2010.0],
                        [1010.0, 2010.0],
                        [1010.0, 2000.0],
                        [1000.0, 2000.0],
                    ],
                    [
                        [1002.0, 2002.0],
                        [1004.0, 2002.0],
                        [1004.0, 2004.0],
                        [1002.0, 2004.0],
                        [1002.0, 2002.0],
                    ],
                ]
            ],
        }
    ]
    b_mp = DashboardBundle.model_validate(raw)
    rev_mp = revision_template(b_mp, revision_id="pub-mp")
    assert publish_revision(b_mp, rev_mp, tmp_path / "revs-mp")["save_state"] == "published"
    rev_mp_dir = tmp_path / "revs-mp/pub-mp"
    prep_mp = load_revision(b_mp, rev_mp_dir)
    pl_mp = PlotPlacement(
        id="pl-mp",
        calculation_id="calc-one",
        geometry_hash=prep_mp.current_geometry[0].plot.geometry.geometry_hash,
        scene_id="g1",
        rotation_deg=0.0,
        translation=(1000.0, 2000.0),
        status="approximate",
        rationale="test",
    )
    req_mp = DeliveryRequest(
        id="pkg-mp",
        baseline=prep_mp.revision.baseline,
        revision_id="pub-mp",
        revision_generation=0,
        geometry="scenario",
        coordinate_mode="placed",
        scene_id="g1",
        units="m",
        placements=[pl_mp],
        layers=[
            {
                "id": "calc-one",
                "kind": "calculation",
                "visible": True,
                "opacity": 1.0,
                "required": False,
                "placement_id": "pl-mp",
                "placement_sha256": _hash(pl_mp.model_dump(mode="json")),
            },
            {
                "id": "mp-layer",
                "kind": "vector",
                "visible": True,
                "opacity": 1.0,
                "required": False,
            },
        ],
        formats=["svg", "geojson"],
    )
    pub_mp = publish_delivery(b_mp, rev_mp_dir, req_mp, tmp_path / "deliv-mp")
    assert pub_mp["status"] == "needs_review", pub_mp
    gj_mp = json.loads((tmp_path / "deliv-mp/pkg-mp/drawing.geojson").read_text())
    mp_feat = next(f for f in gj_mp["features"] if f["geometry"]["type"] == "MultiPolygon")
    assert _signed_area(mp_feat["geometry"]["coordinates"][0][0]) > 0
    assert _signed_area(mp_feat["geometry"]["coordinates"][0][1]) < 0

    # Non-area WebMapUnavailable from require_area propagates via prepare_delivery
    import mp_review.webmap as wm

    monkeypatch.setattr(
        wm,
        "require_area",
        lambda p, e: (_ for _ in ()).throw(WebMapUnavailable("invalid_scene", "bad")),
    )
    with pytest.raises(WebMapUnavailable) as exc:
        prepare_delivery(b_mp, rev_mp_dir, req_mp)
    assert exc.value.code == "invalid_scene"
    monkeypatch.undo()

    # Hypothetical course gets kind="scenario_course" in GeoJSON
    bundle, rev_dir, req, _ = _placed_setup(tmp_path, with_edit=True)
    pub = publish_delivery(bundle, rev_dir, req, tmp_path / "deliv")
    assert pub["status"] == "needs_review", pub
    pkg_placed = tmp_path / "deliv/pkg-placed"
    gj = json.loads((pkg_placed / "drawing.geojson").read_text())
    kinds = {f["properties"].get("call_id"): f["properties"].get("kind") for f in gj["features"]}
    assert kinds["call-one"] == "scenario_course"

    # Recorded GeoJSON omission inconsistency & contradiction checks via public load_delivery
    outside_reason = (
        "Outside the deed-selected coordinate operation's area of use; omitted from GeoJSON "
        "and retained in scene-coordinate formats and the snapshot"
    )

    def _copy_with_omissions(name: str, src_dir: Path, omissions: list[dict]) -> Path:
        dst = tmp_path / name
        shutil.copytree(src_dir, dst)
        snap = json.loads((dst / "snapshot.json").read_text())
        snap["omissions"] = omissions
        (dst / "snapshot.json").write_text(json.dumps(snap))
        _rehash_delivery_artifact(dst, "snapshot.json")
        return dst

    om_dup = _copy_with_omissions(
        "om-dup",
        pkg_placed,
        [
            {"format": "geojson", "layer_id": None, "reason": "GeoJSON omitted: no op"},
            {"format": "geojson", "layer_id": None, "reason": "GeoJSON omitted: no op 2"},
        ],
    )
    with pytest.raises(ValueError, match="inconsistent"):
        load_delivery(bundle, rev_dir, om_dup)

    req_gj_only = req.model_copy(update={"id": "pkg-gj-only", "formats": ("geojson",)})
    assert (
        publish_delivery(bundle, rev_dir, req_gj_only, tmp_path / "deliv-gj")["status"]
        == "needs_review"
    )
    om_req = _copy_with_omissions(
        "om-req",
        tmp_path / "deliv-gj/pkg-gj-only",
        [{"format": "geojson", "layer_id": None, "reason": "GeoJSON omitted: no op"}],
    )
    with pytest.raises(ValueError, match="contradicts required layers"):
        load_delivery(bundle, rev_dir, om_req)

    om_calc = _copy_with_omissions(
        "om-calc",
        pkg_placed,
        [{"format": "geojson", "layer_id": "calc-one", "reason": outside_reason}],
    )
    with pytest.raises(ValueError, match="contradicts the request"):
        load_delivery(bundle, rev_dir, om_calc)


def test_publish_staging_cleanup_and_replay_security_guards(tmp_path, monkeypatch):
    bundle, rev_dir, req = _abs_setup(tmp_path)
    pkg_tag = hashlib.sha256(b"pkg").hexdigest()[:12]

    # Symlink delivery store refused
    real_store = tmp_path / "real-store"
    real_store.mkdir()
    sym_store = tmp_path / "sym-store"
    sym_store.symlink_to(real_store, target_is_directory=True)
    res_sym = publish_delivery(bundle, rev_dir, req, sym_store)
    assert res_sym["save_state"] == "failed" and "symlink" in res_sym["errors"][0]

    # Staging directory creation retries on FileExistsError collision via publish_delivery
    collision_store = tmp_path / "collision-store"
    collision_store.mkdir()
    tokens = iter(["aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb"])
    monkeypatch.setattr(secrets, "token_hex", lambda n: next(tokens))
    pre_colliding = collision_store / f".publishing-{os.getpid()}-aaaaaaaaaaaaaaaa-{pkg_tag}"
    pre_colliding.mkdir()
    res_col = publish_delivery(bundle, rev_dir, req, collision_store)
    assert res_col["save_state"] == "published", res_col
    assert (collision_store / "pkg/delivery-manifest.json").is_file()
    pre_colliding.rmdir()
    monkeypatch.undo()

    # Legacy incomplete directory rmdir OSError wrapped cleanly via publish_delivery
    legacy_store = tmp_path / "legacy-store"
    legacy_dir = legacy_store / "pkg"
    legacy_dir.mkdir(parents=True)
    monkeypatch.setattr(Path, "rmdir", lambda self: (_ for _ in ()).throw(OSError("busy")))
    res_legacy = publish_delivery(bundle, rev_dir, req, legacy_store)
    assert res_legacy["save_state"] == "failed"
    assert "refusing to modify" in res_legacy["errors"][0]
    monkeypatch.undo()
    legacy_dir.rmdir()

    # Windows (os.name == "nt") branches in publish_delivery staging/fsync cleanup
    nt_store = tmp_path / "nt-store"

    class _NtOs:
        name = "nt"

        def __getattr__(self, attr: str):
            return getattr(os, attr)

    monkeypatch.setattr(dmod, "os", _NtOs())
    res_nt = publish_delivery(bundle, rev_dir, req, nt_store)
    assert res_nt["save_state"] == "published", res_nt
    monkeypatch.undo()

    # Stale staging cleanup ignores PermissionError from os.kill (foreign live process)
    perm_store = tmp_path / "perm-store"
    perm_store.mkdir()
    foreign_staging = perm_store / f".publishing-999999-0123456789abcdef-{pkg_tag}"
    foreign_staging.mkdir()
    monkeypatch.setattr(
        os, "kill", lambda pid, sig: (_ for _ in ()).throw(PermissionError("denied"))
    )
    res_perm = publish_delivery(bundle, rev_dir, req, perm_store)
    assert res_perm["save_state"] == "published", res_perm
    assert foreign_staging.is_dir()
    foreign_staging.rmdir()
    monkeypatch.undo()

    # publish_delivery race where target appears after staging and non-exists rename OSError
    real_write_once = dmod._write_once
    race_store = tmp_path / "race-store"

    def racing_write(path: Path, content: bytes) -> None:
        real_write_once(path, content)
        if path.name == "delivery-manifest.json":
            (race_store / "pkg").mkdir(exist_ok=True)

    monkeypatch.setattr(dmod, "_write_once", racing_write)
    res_race = publish_delivery(bundle, rev_dir, req, race_store)
    assert res_race["save_state"] == "failed" and "already published" in res_race["errors"][0]
    monkeypatch.undo()

    err_store = tmp_path / "err-store"
    monkeypatch.setattr(os, "rename", lambda a, b: (_ for _ in ()).throw(OSError("rename failed")))
    res_ren = publish_delivery(bundle, rev_dir, req, err_store)
    assert res_ren["save_state"] == "failed" and "rename failed" in res_ren["errors"][0]
    monkeypatch.undo()

    # Replay security & corruption checks
    good_store = tmp_path / "good-store"
    assert publish_delivery(bundle, rev_dir, req, good_store)["save_state"] == "published"
    pkg_dir = good_store / "pkg"

    def _copy_pkg(name: str) -> Path:
        dst = tmp_path / name
        shutil.copytree(pkg_dir, dst)
        return dst

    # replay_delivery wraps InvalidInputJson
    monkeypatch.setattr(
        dmod, "_replay_delivery", lambda *a, **k: (_ for _ in ()).throw(InvalidInputJson("deep"))
    )
    with pytest.raises(ValueError, match="nested too deeply"):
        replay_delivery(bundle, rev_dir, pkg_dir)
    monkeypatch.undo()

    # symlink package directory
    sym_pkg = tmp_path / "sym-pkg"
    sym_pkg.symlink_to(pkg_dir, target_is_directory=True)
    with pytest.raises(ValueError, match="Unsafe delivery directory"):
        load_delivery(bundle, rev_dir, sym_pkg)

    # symlink manifest
    p1 = _copy_pkg("p-sym-m")
    ext_m = tmp_path / "ext-dm.json"
    ext_m.write_bytes((p1 / "delivery-manifest.json").read_bytes())
    (p1 / "delivery-manifest.json").unlink()
    (p1 / "delivery-manifest.json").symlink_to(ext_m)
    with pytest.raises(ValueError, match="Unsafe delivery manifest"):
        load_delivery(bundle, rev_dir, p1)

    # unsafe artifact name
    p2 = _copy_pkg("p-bad-name")
    m = json.loads((p2 / "delivery-manifest.json").read_text())
    m["artifacts"]["../evil.json"] = "0" * 64
    (p2 / "delivery-manifest.json").write_text(json.dumps(m))
    with pytest.raises(ValueError, match="Unsafe delivery artifact"):
        load_delivery(bundle, rev_dir, p2)

    # missing artifact file
    p3 = _copy_pkg("p-missing")
    (p3 / "metrics.json").unlink()
    with pytest.raises(ValueError, match="missing artifact"):
        load_delivery(bundle, rev_dir, p3)

    # manifest missing core artifact key
    p4 = _copy_pkg("p-incomplete-inv")
    m = json.loads((p4 / "delivery-manifest.json").read_text())
    m["artifacts"].pop("calls.json")
    (p4 / "delivery-manifest.json").write_text(json.dumps(m))
    with pytest.raises(ValueError, match="inventory incomplete"):
        load_delivery(bundle, rev_dir, p4)

    # malformed snapshot.json (valid hash in manifest)
    p5 = _copy_pkg("p-bad-snap")
    bad_snap = b"[]"
    (p5 / "snapshot.json").write_bytes(bad_snap)
    _rehash_delivery_artifact(p5, "snapshot.json")
    with pytest.raises(ValueError, match="snapshot artifact is malformed"):
        load_delivery(bundle, rev_dir, p5)

    # extra artifact in manifest vs expected inventory (full-source.json when include_full_source=False)
    p6 = _copy_pkg("p-extra-art")
    extra_bytes = b"{}"
    (p6 / "full-source.json").write_bytes(extra_bytes)
    _rehash_delivery_artifact(p6, "full-source.json")
    with pytest.raises(ValueError, match="artifact inventory mismatch"):
        load_delivery(bundle, rev_dir, p6)


def test_recorded_geojson_and_recorded_area_edge_cases(tmp_path, monkeypatch):
    import mp_review.webmap_projection as wp
    import pyproj

    bundle, rev_dir, req, _ = _placed_setup(tmp_path)
    pub = publish_delivery(bundle, rev_dir, req, tmp_path / "d-gj")
    assert pub["status"] == "needs_review"
    base_pkg = tmp_path / "d-gj/pkg-placed"
    base_gj = json.loads((base_pkg / "drawing.geojson").read_text())

    def _tamper_geojson(name: str, payload: bytes) -> Path:
        dst = tmp_path / name
        shutil.copytree(base_pkg, dst)
        (dst / "drawing.geojson").write_bytes(payload)
        _rehash_delivery_artifact(dst, "drawing.geojson")
        return dst

    # Malformed projection metadata in drawing.geojson rejected by load_delivery
    bad_meta_gj = json.loads(json.dumps(base_gj))
    bad_meta_gj["metesparser"]["projection"].update(source_crs_wkt=123, accuracy_m=True)
    with pytest.raises(ValueError, match="coordinate operation mismatch"):
        load_delivery(
            bundle, rev_dir, _tamper_geojson("gj-bad-meta", json.dumps(bad_meta_gj).encode())
        )

    # Missing pyproj degrades replay_delivery cleanly to geojson_coordinates="not_verified"
    monkeypatch.setattr(
        wp,
        "_projection_dependencies",
        lambda: (_ for _ in ()).throw(WebMapUnavailable("dependency_unavailable", "no pyproj")),
    )
    replay = replay_delivery(bundle, rev_dir, base_pkg)
    assert replay.geojson_coordinates == "not_verified"
    assert any("cannot be instantiated" in f for f in replay.findings)
    monkeypatch.undo()

    # Invalid WKT rejected by load_delivery
    bad_wkt_gj = json.loads(json.dumps(base_gj))
    bad_wkt_gj["metesparser"]["projection"]["source_crs_wkt"] = "INVALID_WKT"
    with pytest.raises(ValueError, match="coordinate operation mismatch"):
        load_delivery(
            bundle, rev_dir, _tamper_geojson("gj-bad-wkt", json.dumps(bad_wkt_gj).encode())
        )

    # Mismatched CRS WKT rejected by load_delivery
    wrong_crs_gj = json.loads(json.dumps(base_gj))
    wrong_crs_gj["metesparser"]["projection"]["source_crs_wkt"] = pyproj.CRS.from_epsg(
        2193
    ).to_wkt()
    with pytest.raises(ValueError, match="differs from the scene CRS"):
        load_delivery(
            bundle, rev_dir, _tamper_geojson("gj-wrong-crs", json.dumps(wrong_crs_gj).encode())
        )

    # Missing metesparser metadata block rejected by load_delivery
    with pytest.raises(ValueError, match="identity or coordinate operation mismatch"):
        load_delivery(
            bundle,
            rev_dir,
            _tamper_geojson("gj-no-meta", b'{"type":"FeatureCollection","features":[]}'),
        )

    # Mismatched feature revision_id rejected by load_delivery
    bad_rev_gj = json.loads(json.dumps(base_gj))
    bad_rev_gj["features"][0]["properties"]["revision_id"] = "wrong-rev"
    with pytest.raises(ValueError, match="feature identity mismatch"):
        load_delivery(
            bundle, rev_dir, _tamper_geojson("gj-bad-rev", json.dumps(bad_rev_gj).encode())
        )
