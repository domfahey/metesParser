"""High-signal error-handling and security edge cases for corridor, plss, raster_picker, relative, dashboard."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest
from mp_models.dashboard import DashboardBundle
from mp_review.corridor import analyze_corridor_file, replay_corridor
from mp_review.dashboard import prepare_dashboard
from mp_review.plss import prepare_plss_file, replay_plss
from mp_review.raster_picker import prepare_raster_picker_file
from mp_review.relative import review_relative_file
from PIL import Image

FIXTURES = Path(__file__).parent / "fixtures"
PLUGIN = Path(__file__).resolve().parents[3] / "plugins/metesparser"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_corridor_replay_and_symlink_tamper_guards(tmp_path):
    src = tmp_path / "corridor.json"
    src.write_bytes((PLUGIN / "skills/plot-corridor/references/example.json").read_bytes())

    # Symlink / missing input fails closed (line 28)
    sym_in = tmp_path / "sym-in.json"
    sym_in.symlink_to(src)
    assert analyze_corridor_file(sym_in, tmp_path / "o1")["status"] == "error"

    base = tmp_path / "cor-base"
    assert analyze_corridor_file(src, base)["status"] == "needs_review"

    # Symlink / missing bundle dir refused (line 110)
    sym_dir = tmp_path / "sym-dir"
    sym_dir.symlink_to(base, target_is_directory=True)
    with pytest.raises(ValueError, match="regular directory"):
        replay_corridor(sym_dir)

    # Canonical request disagrees with exact source request (line 125)
    d1 = tmp_path / "cor-canon-diff"
    shutil.copytree(base, d1)
    canon = json.loads((d1 / "corridor-request.json").read_text())
    canon["id"] = "other-corridor"
    canon_bytes = json.dumps(canon, indent=2, sort_keys=True).encode() + b"\n"
    (d1 / "corridor-request.json").write_bytes(canon_bytes)
    m1 = json.loads((d1 / "corridor-manifest.json").read_text())
    m1["canonical_request_sha256"] = _sha(canon_bytes)
    (d1 / "corridor-manifest.json").write_text(json.dumps(m1))
    with pytest.raises(ValueError, match="differs from its exact source input"):
        replay_corridor(d1)

    # Result identity mismatch vs manifest input_sha256 (line 128)
    d2 = tmp_path / "cor-id-diff"
    shutil.copytree(base, d2)
    m2 = json.loads((d2 / "corridor-manifest.json").read_text())
    m2["input_sha256"] = "0" * 64
    (d2 / "corridor-manifest.json").write_text(json.dumps(m2))
    with pytest.raises(ValueError, match="identities differ"):
        replay_corridor(d2)

    # Supported corridor missing boundary_html_sha256 in manifest (line 156)
    d3 = tmp_path / "cor-no-html"
    shutil.copytree(base, d3)
    m3 = json.loads((d3 / "corridor-manifest.json").read_text())
    m3["boundary_html_sha256"] = None
    (d3 / "corridor-manifest.json").write_text(json.dumps(m3))
    with pytest.raises(ValueError, match="display identity is missing or unexpected"):
        replay_corridor(d3)

    # Unsupported corridor with stray boundary-prepared.json on disk (line 136)
    unsup_data = json.loads(src.read_text())
    unsup_data["widths"][0]["start_left_ft"] = 5000.0
    unsup_data["widths"][0]["end_left_ft"] = 5000.0
    unsup_src = tmp_path / "unsup.json"
    unsup_src.write_text(json.dumps(unsup_data))
    unsup_dir = tmp_path / "cor-unsup"
    res = analyze_corridor_file(unsup_src, unsup_dir)
    if res["status"] == "needs_review" and res["corridor"]["boundary"] is None:
        (unsup_dir / "boundary-prepared.json").write_text("{}")
        with pytest.raises(ValueError, match="Unexpected prepared geometry"):
            replay_corridor(unsup_dir)


def test_plss_symlink_missing_and_unexpected_prepared_layer_guards(tmp_path):
    src = tmp_path / "plss.json"
    src.write_bytes((PLUGIN / "skills/plot-plss-reference/references/example.json").read_bytes())

    # Symlink / missing input (line 84)
    assert prepare_plss_file(tmp_path / "missing.json", tmp_path / "o1")["status"] == "error"

    base = tmp_path / "plss-base"
    assert prepare_plss_file(src, base)["status"] == "needs_review"

    # Symlink bundle dir (line 115) & missing artifact file (line 120)
    sym_dir = tmp_path / "sym-plss"
    sym_dir.symlink_to(base, target_is_directory=True)
    with pytest.raises(ValueError, match="regular directory"):
        replay_plss(sym_dir)

    d_miss = tmp_path / "plss-miss"
    shutil.copytree(base, d_miss)
    (d_miss / "request.json").unlink()
    with pytest.raises(ValueError, match="regular, complete artifact files"):
        replay_plss(d_miss)

    # Unsupported PLSS result with stray prepared-layer.json on disk (line 134)
    unsup = json.loads(src.read_text())
    unsup["selected_reference_id"] = "no-such-section"
    unsup_src = tmp_path / "plss-unsup.json"
    unsup_src.write_text(json.dumps(unsup))
    unsup_dir = tmp_path / "plss-unsup-dir"
    res = prepare_plss_file(unsup_src, unsup_dir)
    assert res["status"] == "needs_review" and res["availability"] != "computed"
    (unsup_dir / "prepared-layer.json").write_text("{}")
    with pytest.raises(ValueError, match="cannot contain a prepared layer"):
        replay_plss(unsup_dir)


def test_raster_picker_input_validation_matrix_and_exif_guard(tmp_path, monkeypatch):
    import mp_review.raster_registration as reg_mod

    img = tmp_path / "scan.png"
    Image.new("RGB", (10, 10), "white").save(img)
    base_cfg = {
        "scene": {"id": "g", "name": "G", "kind": "local", "units": "m", "basis": "local"},
        "controls": [],
    }
    cfg = tmp_path / "controls.json"
    cfg.write_text(json.dumps(base_cfg))

    # Missing image (line 28)
    assert (
        prepare_raster_picker_file(tmp_path / "missing.png", cfg, tmp_path / "p0")["status"]
        == "error"
    )

    # Non-dict controls JSON (line 58)
    arr_cfg = tmp_path / "arr.json"
    arr_cfg.write_text("[]")
    assert prepare_raster_picker_file(img, arr_cfg, tmp_path / "p1")["status"] == "error"

    # Duplicate control names (line 64)
    dup_cfg = tmp_path / "dup.json"
    dup_cfg.write_text(
        json.dumps(
            {
                **base_cfg,
                "controls": [
                    {"id": "c1", "pixel": [0, 0], "scene": [0, 0]},
                    {"id": "c1", "pixel": [5, 5], "scene": [5, 5]},
                ],
            }
        )
    )
    assert prepare_raster_picker_file(img, dup_cfg, tmp_path / "p2")["status"] == "error"

    # Optional supplied matrix validated (line 66)
    mat_cfg = tmp_path / "mat.json"
    mat_cfg.write_text(json.dumps({**base_cfg, "matrix": [1, 0, 0, 0, 1, 0]}))
    ok = prepare_raster_picker_file(img, mat_cfg, tmp_path / "p3")
    assert ok["status"] == "needs_review"

    # EXIF orientation != 1 caught by picker's own PIL check even if image_orientation bypassed (line 78)
    exif_img = tmp_path / "oriented.jpg"
    im = Image.new("RGB", (10, 10), "white")
    exif = Image.Exif()
    exif[274] = 6
    im.save(exif_img, format="JPEG", exif=exif.tobytes())
    monkeypatch.setattr(reg_mod, "image_orientation", lambda data: None)
    res_exif = prepare_raster_picker_file(exif_img, cfg, tmp_path / "p4")
    assert res_exif["status"] == "error"
    assert "EXIF-oriented" in res_exif["errors"][0]["message"]


def test_relative_and_dashboard_atomic_and_error_guards(tmp_path, monkeypatch):
    # relative.py output_error (111-112) and artifact_error (159-160)
    rel_src = PLUGIN / "skills/deed-closure-dashboard/references/relative-rectangle.json"
    blocker = tmp_path / "blocker"
    blocker.write_text("file")
    res_out_err = review_relative_file(rel_src, output_dir=blocker / "child")
    assert res_out_err["status"] == "error"
    assert res_out_err["errors"][0]["code"] == "output_error"

    import mp_review.relative as rel_mod

    monkeypatch.setattr(
        rel_mod, "_report", lambda r, t: (_ for _ in ()).throw(ValueError("render fail"))
    )
    res_art_err = review_relative_file(rel_src, output_dir=tmp_path / "rel-out")
    assert res_art_err["status"] == "error"
    assert any(e["code"] == "artifact_error" for e in res_art_err["errors"])
    monkeypatch.undo()

    # dashboard.py atomic symlink refusal (37), fsync cleanup (44-46), symlink cache_dir (87)
    bundle = DashboardBundle.model_validate_json((FIXTURES / "dashboard-absolute.json").read_text())

    sym_cache_out = tmp_path / "cache-sym-file"
    sym_cache_out.mkdir()
    real_f = tmp_path / "real.json"
    real_f.write_text("{}")
    (sym_cache_out / "source-review.json").symlink_to(real_f)
    with pytest.raises(ValueError, match="Refusing symlink output"):
        prepare_dashboard(bundle, cache_dir=sym_cache_out)

    fsync_cache = tmp_path / "cache-fsync"
    fsync_cache.mkdir()
    monkeypatch.setattr(os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("fsync boom")))
    with pytest.raises(OSError, match="fsync boom"):
        prepare_dashboard(bundle, cache_dir=fsync_cache)
    assert list(fsync_cache.iterdir()) == []
    monkeypatch.undo()

    real_cache = tmp_path / "real-cache"
    real_cache.mkdir()
    sym_cache = tmp_path / "sym-cache"
    sym_cache.symlink_to(real_cache, target_is_directory=True)
    with pytest.raises(ValueError, match="must not be a symlink"):
        prepare_dashboard(bundle, cache_dir=sym_cache)
