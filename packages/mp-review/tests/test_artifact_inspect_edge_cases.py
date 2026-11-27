"""High-signal replay, tampering, lineage-linking, and recommendation tests for artifact_inspect."""

from __future__ import annotations

import hashlib
import json
import shutil
from io import BytesIO
from pathlib import Path

import pytest
from mp_models.dashboard import DashboardBundle
from mp_models.plot import PlotScene
from mp_models.raster import RasterControl
from mp_models.webmap import WebMapRequest
from mp_review.api import review_file
from mp_review.artifact_inspect import inspect_artifacts
from mp_review.comparison import compare_descriptions_file
from mp_review.compose import compose_dashboard_file, compose_map_file
from mp_review.dashboard import dashboard_file, prepare_dashboard
from mp_review.diagnostics import diagnose_closure_file
from mp_review.online_map import render_map_file
from mp_review.plot import plot_file
from mp_review.raster_registration import fit_affine, image_layer

FIXTURES = Path(__file__).parent / "fixtures"
SOURCE_FIXTURES = FIXTURES / "source_handoff"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _wjson(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _nodes(res: dict, kind: str) -> list[dict]:
    return [a for a in res["artifacts"] if a["kind"] == kind]


def _codes(node: dict) -> set[str]:
    return {r["code"] for r in node["reasons"]}


def test_inspect_artifacts_path_read_manifest_and_hash_guards(tmp_path):
    # Base valid review output to mutate for public inspect_artifacts boundary checks
    src = tmp_path / "deed.txt"
    src.write_text(
        "BEGINNING at a pin; THENCE N 0°00' E 100 feet; THENCE N 90°00' E 100 feet; "
        "THENCE S 0°00' E 100 feet; THENCE S 90°00' W 100 feet to the point of beginning."
    )
    base_dir = tmp_path / "base-review"
    assert review_file(src, output_dir=base_dir)["status"] == "checks_passed"

    # Unsafe references in manifest: non-string, backslash, colon, NUL
    for idx, bad_ref in enumerate((123, "a\\b", "c:d", "a\x00b")):
        d = tmp_path / f"unsafe-ref-{idx}"
        shutil.copytree(base_dir, d)
        m = json.loads((d / "review-manifest.json").read_text())
        m["input"]["path"] = bad_ref
        _wjson(d / "review-manifest.json", m)
        res = inspect_artifacts(d, requested_stage="review")
        assert "unsafe_path" in _codes(_nodes(res, "review")[0])

    # Unreadable artifact (directory at declared artifact path -> unreadable_artifact / unverifiable)
    d_unreadable = tmp_path / "unreadable-review"
    shutil.copytree(base_dir, d_unreadable)
    (d_unreadable / "review.html").unlink()
    (d_unreadable / "review.html").mkdir()
    res_unreadable = inspect_artifacts(d_unreadable, requested_stage="review")
    disp_unreadable = _nodes(res_unreadable, "review_display")[0]
    assert "unreadable_artifact" in _codes(disp_unreadable)
    assert disp_unreadable["status"] == "unverifiable"

    # Non-object manifest -> invalid_manifest
    d_arr = tmp_path / "arr-manifest"
    d_arr.mkdir()
    (d_arr / "review-manifest.json").write_text("[]")
    res_arr = inspect_artifacts(d_arr, requested_stage="review")
    assert "invalid_manifest" in _codes(_nodes(res_arr, "review")[0])

    # Hash checks: None -> hash_unavailable; malformed -> invalid_hash
    d_none_hash = tmp_path / "none-hash"
    shutil.copytree(base_dir, d_none_hash)
    m_none = json.loads((d_none_hash / "review-manifest.json").read_text())
    m_none["artifacts"]["review.html"] = None
    _wjson(d_none_hash / "review-manifest.json", m_none)
    disp_none = _nodes(inspect_artifacts(d_none_hash, requested_stage="review"), "review_display")[
        0
    ]
    assert "hash_unavailable" in _codes(disp_none) and disp_none["status"] == "unverifiable"

    d_bad_hash = tmp_path / "bad-hash"
    shutil.copytree(base_dir, d_bad_hash)
    m_bad = json.loads((d_bad_hash / "review-manifest.json").read_text())
    m_bad["artifacts"]["review.html"] = "not-a-valid-sha256"
    _wjson(d_bad_hash / "review-manifest.json", m_bad)
    disp_bad = _nodes(inspect_artifacts(d_bad_hash, requested_stage="review"), "review_display")[0]
    assert "invalid_hash" in _codes(disp_bad) and disp_bad["status"] == "invalid"


def test_source_records_legacy_uncertainties_selection_fallbacks_and_recommendations(tmp_path):
    # 1. Malformed description-selection.json -> selection node surfaces schema failure
    b1 = tmp_path / "bad-sel"
    shutil.copytree(SOURCE_FIXTURES, b1)
    (b1 / "description-selection.json").write_text('{"schema_version": "1.1"}')
    res1 = inspect_artifacts(b1, requested_stage="extract")
    assert _nodes(res1, "selection")[0]["status"] == "invalid"

    # 2. Selection with acquisition_sha256 mismatch still resolves parent by acquisition_id
    # AND declared source uncertainties are carried into limitations
    b2 = tmp_path / "changed-acq"
    shutil.copytree(SOURCE_FIXTURES, b2)
    acq = json.loads((b2 / "source-acquisition.json").read_text())
    acq["uncertainties"] = [
        {
            "id": "unc-1",
            "description": "Faint digit on page 1",
            "source_id": acq["sources"][0]["id"],
            "page_ids": [acq["page_map"][0]["id"]],
        }
    ]
    _wjson(b2 / "source-acquisition.json", acq)
    res2 = inspect_artifacts(b2, requested_stage="extract")
    acq_node = _nodes(res2, "acquisition")[0]
    assert any("Faint digit" in lim or "uncertainties" in lim for lim in acq_node["limitations"])
    sel_node = _nodes(res2, "selection")[0]
    assert sel_node["dependency_ids"] == [acq_node["id"]]

    # 3. Selection without any acquisition -> missing_acquisition
    b3 = tmp_path / "no-acq"
    shutil.copytree(SOURCE_FIXTURES, b3)
    (b3 / "source-acquisition.json").unlink()
    res3 = inspect_artifacts(b3, requested_stage="extract")
    assert "missing_acquisition" in _codes(_nodes(res3, "selection")[0])

    # 4. Legacy 1.0 acquisition record -> legacy_source_schema
    b4 = tmp_path / "legacy-acq"
    shutil.copytree(SOURCE_FIXTURES, b4)
    legacy = json.loads((b4 / "source-acquisition.json").read_text())
    legacy["schema_version"] = "1.0"
    _wjson(b4 / "source-acquisition.json", legacy)
    res4 = inspect_artifacts(b4, requested_stage="convert")
    assert "legacy_source_schema" in _codes(_nodes(res4, "acquisition")[0])

    # 5. Requesting stage="plot" when only a valid .txt selection exists:
    # - finish pulls selection/acquisition into reachable
    # - command recommends `plot <txt> --output-dir ... --input-format text`
    b5 = tmp_path / "only-source"
    shutil.copytree(SOURCE_FIXTURES, b5)
    res5 = inspect_artifacts(b5, requested_stage="plot")
    cmd = res5["recommendations"][0]["command"]
    assert cmd is not None
    assert "--input-format" in cmd["arguments"] and "text" in cmd["arguments"]

    # 6. Two valid selections -> command refuses to guess and returns None
    b6 = tmp_path / "two-sels"
    shutil.copytree(SOURCE_FIXTURES, b6)
    sel_data = json.loads((b6 / "description-selection.json").read_text())
    cand2 = json.loads(json.dumps(sel_data["candidates"][0]))
    cand2["id"] = "cand-second"
    sel_data["candidates"].append(cand2)
    _wjson(b6 / "description-selection.json", sel_data)
    res6 = inspect_artifacts(b6, requested_stage="review")
    assert res6["recommendations"][0]["command"] is None

    # 7. Unlinked text review when selections exist -> unlinked_source_occurrence
    b7 = tmp_path / "unlinked-rev"
    shutil.copytree(SOURCE_FIXTURES, b7)
    other_txt = b7 / "unrelated.txt"
    other_txt.write_text("BEGINNING at a pin; THENCE N 0° E 50 feet;")
    review_file(other_txt, output_dir=b7 / "rev-unrelated")
    res7 = inspect_artifacts(b7, requested_stage="review")
    rev_node = _nodes(res7, "review")[0]
    assert "unlinked_source_occurrence" in _codes(rev_node)


def test_review_plot_diagnostics_comparison_and_direct_input_error_paths(tmp_path):
    # 1. Review manifest invalid kind/status, missing required artifacts, replay error
    # and root calls.json skipped when review-manifest.json exists
    r_root = tmp_path / "rev-cases"
    r_root.mkdir()
    bad_json = r_root / "bad.json"
    bad_json.write_text('{"not": "calls"}')
    res_err = review_file(bad_json, output_dir=r_root / "rev-err")
    assert res_err["status"] == "error"
    insp_err = inspect_artifacts(r_root / "rev-err", requested_stage="review")
    assert "replay_input_error" in _codes(_nodes(insp_err, "review")[0])

    # Invalid review manifest kind & missing artifacts keys
    r_bad_kind = tmp_path / "rev-bad-kind"
    shutil.copytree(r_root / "rev-err", r_bad_kind)
    m = json.loads((r_bad_kind / "review-manifest.json").read_text())
    m["kind"] = "wrong"
    _wjson(r_bad_kind / "review-manifest.json", m)
    assert "invalid_manifest" in _codes(
        _nodes(inspect_artifacts(r_bad_kind, requested_stage="review"), "review")[0]
    )

    r_miss_art = tmp_path / "rev-miss-art"
    shutil.copytree(r_root / "rev-err", r_miss_art)
    m2 = json.loads((r_miss_art / "review-manifest.json").read_text())
    m2["artifacts"].pop("audit.json")
    _wjson(r_miss_art / "review-manifest.json", m2)
    assert "missing_review_artifacts" in _codes(
        _nodes(inspect_artifacts(r_miss_art, requested_stage="review"), "review")[0]
    )

    # Direct input invalid_direct_input
    di_root = tmp_path / "direct-bad"
    di_root.mkdir()
    (di_root / "calls.json").write_text('{"invalid": 1}')
    di_res = inspect_artifacts(di_root, requested_stage="verify")
    assert "invalid_direct_input" in _codes(_nodes(di_res, "direct_input")[0])

    # 2. Plot errors: geometry_hash_mismatch, ambiguous_plot_source,
    # plot_replay_parameters_unavailable, algorithm_version_mismatch
    p_src = tmp_path / "square.json"
    p_src.write_text(
        json.dumps(
            [
                {
                    "course": 1,
                    "direction_text": "N 0 E",
                    "bearing_azimuth_deg_from_north": 0,
                    "distance_ft": 100,
                }
            ]
        )
    )
    p_base = tmp_path / "plot-base"
    assert plot_file(p_src, p_base, input_format="calls")["status"] == "needs_review"

    # geometry_hash_mismatch
    p1 = tmp_path / "plot-gh"
    shutil.copytree(p_base, p1)
    pm = json.loads((p1 / "plot-manifest.json").read_text())
    pm["geometry_hash"] = "0" * 64
    _wjson(p1 / "plot-manifest.json", pm)
    assert "geometry_hash_mismatch" in _codes(
        _nodes(inspect_artifacts(p1, requested_stage="plot"), "plot")[0]
    )

    # ambiguous_plot_source (two source files)
    p2 = tmp_path / "plot-2src"
    shutil.copytree(p_base, p2)
    (p2 / "source.txt").write_text("extra")
    assert "ambiguous_plot_source" in _codes(
        _nodes(inspect_artifacts(p2, requested_stage="plot"), "plot")[0]
    )

    # plot_replay_parameters_unavailable
    p3 = tmp_path / "plot-noparam"
    shutil.copytree(p_base, p3)
    pm3 = json.loads((p3 / "plot-manifest.json").read_text())
    pm3.pop("replay_version")
    _wjson(p3 / "plot-manifest.json", pm3)
    assert "plot_replay_parameters_unavailable" in _codes(
        _nodes(inspect_artifacts(p3, requested_stage="plot"), "plot")[0]
    )

    # algorithm_version_mismatch
    p4 = tmp_path / "plot-ver"
    shutil.copytree(p_base, p4)
    pm4 = json.loads((p4 / "plot-manifest.json").read_text())
    pm4["replay_version"] = "plot-input-replay-999"
    _wjson(p4 / "plot-manifest.json", pm4)
    assert "algorithm_version_mismatch" in _codes(
        _nodes(inspect_artifacts(p4, requested_stage="plot"), "plot")[0]
    )

    # 3. Diagnostics errors: algorithm_version_mismatch & replay_mismatch
    d_base = tmp_path / "diag-base"
    assert (
        diagnose_closure_file(FIXTURES / "diagnostics/request.json", d_base)["status"]
        == "needs_review"
    )

    d1 = tmp_path / "diag-ver"
    shutil.copytree(d_base, d1)
    dm = json.loads((d1 / "diagnostics-manifest.json").read_text())
    dm["algorithm_version"] = "old-v0"
    _wjson(d1 / "diagnostics-manifest.json", dm)
    assert "algorithm_version_mismatch" in _codes(
        _nodes(inspect_artifacts(d1, requested_stage="verify"), "diagnostics")[0]
    )

    d2 = tmp_path / "diag-tamper"
    shutil.copytree(d_base, d2)
    dm2 = json.loads((d2 / "diagnostics-manifest.json").read_text())
    dm2["request_sha256"] = "0" * 64
    _wjson(d2 / "diagnostics-manifest.json", dm2)
    assert "replay_mismatch" in _codes(
        _nodes(inspect_artifacts(d2, requested_stage="verify"), "diagnostics")[0]
    )

    # 4. Comparison algorithm_version_mismatch
    c_base = tmp_path / "comp-base"
    assert (
        compare_descriptions_file(FIXTURES / "comparison-synthetic.json", c_base)["status"]
        == "needs_review"
    )
    cm = json.loads((c_base / "comparison-manifest.json").read_text())
    cm["algorithm_version"] = "old-comp-v0"
    _wjson(c_base / "comparison-manifest.json", cm)
    assert "algorithm_version_mismatch" in _codes(
        _nodes(inspect_artifacts(c_base, requested_stage="compare-descriptions"), "comparison")[0]
    )


def test_broken_dashboard_prerequisite_reports_unavailable(tmp_path):
    broken_dash = tmp_path / "broken-dash"
    broken_dash.mkdir()
    (broken_dash / "stage-manifest.json").write_text('{"schema_version": "1.0"}')
    (broken_dash / "source.json").write_text("{bad")
    res_bd = inspect_artifacts(broken_dash, requested_stage="dashboard")
    assert "dashboard_prerequisite_unavailable" in _codes(_nodes(res_bd, "dashboard")[0])


def test_dashboard_online_map_composition_and_linking_edge_cases(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    pytest.importorskip("pyproj")

    # Dashboard with raster_layer + online_map
    data = json.loads((FIXTURES / "dashboard-absolute.json").read_text())
    data["schema_version"] = "1.1"
    data["calculations"][0]["frame"]["foot_definition"] = "international_ft"
    initial = prepare_dashboard(DashboardBundle.model_validate(data))
    scene = PlotScene(id="grid", name="Grid", kind="projected", crs="EPSG:3857", units="m")
    buf = BytesIO()
    Image.new("RGB", (8, 8), "white").save(buf, format="PNG")
    controls = (
        RasterControl(id="a", pixel=(0, 0), scene=(1000, 2000)),
        RasterControl(id="b", pixel=(8, 0), scene=(1080, 2000)),
        RasterControl(id="c", pixel=(0, 8), scene=(1000, 2080)),
    )
    rlayer, rsource = image_layer(
        buf.getvalue(), scene=scene, registration=fit_affine(controls), filename="scan.png"
    )
    data["scenes"] = [scene.model_dump(mode="json")]
    data["map_sources"] = [rsource.model_dump(mode="json")]
    data["raster_layers"] = [rlayer.model_dump(mode="json")]
    data["placements"] = [
        {
            "id": "pl-1",
            "calculation_id": "calc-one",
            "geometry_hash": initial.plots.geometries[0].geometry_hash,
            "scene_id": "grid",
            "rotation_deg": 0,
            "translation": [1000, 2000],
            "status": "approximate",
            "rationale": "Test control",
        }
    ]
    dash_src = tmp_path / "dash-src.json"
    _wjson(dash_src, data)
    dash_dir = tmp_path / "dash-full"
    dash_res = dashboard_file(dash_src, dash_dir, online_map=WebMapRequest(scene_id="grid"))
    assert dash_res["status"] == "needs_review", dash_res

    insp_dash = inspect_artifacts(dash_dir, requested_stage="render-map")
    om_node = _nodes(insp_dash, "online_map")[0]
    assert om_node["status"] == "present_valid", om_node["reasons"]
    assert om_node["dependency_ids"]

    # 3. Online map mismatches: map_source_unavailable, map_input_mismatch,
    # map_stage_mismatch, presentation_changed, missing_display_files
    om_orphan = tmp_path / "om-orphan"
    shutil.copytree(dash_dir, om_orphan)
    (om_orphan / "stage-manifest.json").unlink()
    assert "map_source_unavailable" in _codes(
        _nodes(inspect_artifacts(om_orphan, requested_stage="render-map"), "online_map")[0]
    )

    for mutate, expected_code in (
        (lambda m: m.__setitem__("input_hashes", {}), "map_input_mismatch"),
        (lambda m: m.__setitem__("request_sha256", "0" * 64), "map_stage_mismatch"),
        (lambda m: m.__setitem__("renderer_sha256", "0" * 64), "presentation_changed"),
        (lambda m: m.__setitem__("files", "not-a-dict"), "missing_display_files"),
    ):
        d = tmp_path / f"om-{expected_code}"
        shutil.copytree(dash_dir, d)
        wm_m = json.loads((d / "web-map-manifest.json").read_text())
        mutate(wm_m)
        _wjson(d / "web-map-manifest.json", wm_m)
        assert expected_code in _codes(
            _nodes(inspect_artifacts(d, requested_stage="render-map"), "online_map")[0]
        )

    # 4. Dashboard composition + standalone composition + online_map linking to composition
    # + composition error guards
    layer_path = tmp_path / "layer.json"
    _wjson(layer_path, {"scenes": [scene.model_dump(mode="json")]})
    comp_dash = tmp_path / "comp-dash"
    assert (
        compose_dashboard_file(
            FIXTURES / "dashboard-absolute.json", comp_dash, layers=[layer_path]
        )["status"]
        == "needs_review"
    )
    insp_cd = inspect_artifacts(comp_dash, requested_stage="render-map")
    assert _nodes(insp_cd, "composition")[0]["status"] == "present_valid"

    # Dashboard composition missing inputs/base-bundle.json and unknown kind
    for mutate_cm, expected_code in (
        (lambda m: m.__setitem__("inputs", "bad"), "missing_composition_inputs"),
        (lambda m: m["inputs"].pop("inputs/base-bundle.json"), "missing_composition_inputs"),
        (lambda m: m.__setitem__("kind", "unknown-kind"), "unknown_composition_kind"),
        (lambda m: m.__setitem__("geometry_hashes", {}), "geometry_hash_mismatch"),
    ):
        d = tmp_path / f"cd-{expected_code}-{abs(hash(str(mutate_cm)))}"
        shutil.copytree(comp_dash, d)
        cm = json.loads((d / "composition-manifest.json").read_text())
        mutate_cm(cm)
        _wjson(d / "composition-manifest.json", cm)
        assert expected_code in _codes(
            _nodes(inspect_artifacts(d, requested_stage="render-map"), "composition")[0]
        )

    # Composition invalid layer shapes (non-dict and non-list)
    for layer_content, tag in ("[]", "nondict"), ('{"scenes": "bad"}', "nonlist"):
        d = tmp_path / f"cd-layer-{tag}"
        shutil.copytree(comp_dash, d)
        lp = d / "inputs/layer-1.json"
        lp.write_text(layer_content)
        cm = json.loads((d / "composition-manifest.json").read_text())
        cm["inputs"]["inputs/layer-1.json"] = _sha(lp.read_bytes())
        _wjson(d / "composition-manifest.json", cm)
        assert "invalid_composition_layer" in _codes(
            _nodes(inspect_artifacts(d, requested_stage="render-map"), "composition")[0]
        )

    # Standalone composition: missing plot files, broken retained plot,
    # and online_map linked to composition + ambiguous plot identity
    chain_root = tmp_path / "standalone-chain"
    chain_root.mkdir()
    c_src = chain_root / "calls.json"
    _wjson(
        c_src,
        [
            {
                "course": 1,
                "direction_text": "N 0 E",
                "bearing_azimuth_deg_from_north": 0,
                "distance_ft": 100,
            }
        ],
    )
    assert plot_file(c_src, chain_root / "plot-1", input_format="calls")["status"] == "needs_review"
    assert plot_file(c_src, chain_root / "plot-2", input_format="calls")["status"] == "needs_review"
    assert (
        compose_map_file(chain_root / "plot-1", chain_root / "comp-1", layers=[layer_path])[
            "status"
        ]
        == "needs_review"
    )
    assert (
        render_map_file(
            chain_root / "comp-1/map-input.json",
            chain_root / "map-1",
            online_map=WebMapRequest(scene_id="grid"),
        )["status"]
        == "needs_review"
    )
    insp_sc = inspect_artifacts(chain_root, requested_stage="render-map")
    om_sc = _nodes(insp_sc, "online_map")[0]
    comp_sc = _nodes(insp_sc, "composition")[0]
    assert comp_sc["id"] in om_sc["dependency_ids"]

    # Standalone composition missing plot-manifest in inputs
    sc_miss = tmp_path / "sc-miss"
    shutil.copytree(chain_root / "comp-1", sc_miss)
    cm = json.loads((sc_miss / "composition-manifest.json").read_text())
    cm["inputs"].pop("inputs/plot/plot-manifest.json")
    _wjson(sc_miss / "composition-manifest.json", cm)
    assert "missing_composition_inputs" in _codes(
        _nodes(inspect_artifacts(sc_miss, requested_stage="render-map"), "composition")[0]
    )

    # Standalone composition whose retained plot fails validation -> plot_prerequisite_unavailable
    sc_bad_plot = tmp_path / "sc-bad-plot"
    shutil.copytree(chain_root / "comp-1", sc_bad_plot)
    bad_pi = sc_bad_plot / "inputs/plot/plot-input.json"
    bad_pi.write_text("{}")
    cm2 = json.loads((sc_bad_plot / "composition-manifest.json").read_text())
    cm2["inputs"]["inputs/plot/plot-input.json"] = _sha(bad_pi.read_bytes())
    _wjson(sc_bad_plot / "composition-manifest.json", cm2)
    assert "plot_prerequisite_unavailable" in _codes(
        _nodes(inspect_artifacts(sc_bad_plot, requested_stage="render-map"), "composition")[0]
    )

    # Ambiguous plot identity: online_map without composition alongside 2 identical plots
    amb_plot_root = tmp_path / "amb-plot"
    amb_plot_root.mkdir()
    shutil.copytree(chain_root / "plot-1", amb_plot_root / "plot-1")
    shutil.copytree(chain_root / "plot-2", amb_plot_root / "plot-2")
    shutil.copytree(chain_root / "map-1", amb_plot_root / "map-1")
    insp_amb_p = inspect_artifacts(amb_plot_root, requested_stage="render-map")
    assert "ambiguous_plot_identity" in _codes(_nodes(insp_amb_p, "online_map")[0])


def test_source_ref_linking_ambiguous_and_unlinked_acquisitions(tmp_path):
    # Two acquisitions with identical source ID/hash + dashboard referencing that doc -> ambiguous_source_occurrence
    # One acquisition with non-matching doc hash + dashboard -> unlinked_source_identity
    acq_src = json.loads((SOURCE_FIXTURES / "source-acquisition.json").read_text())
    doc_id = acq_src["sources"][0]["id"]
    doc_sha = acq_src["sources"][0]["sha256"]

    dash_data = json.loads((FIXTURES / "dashboard-absolute.json").read_text())
    dash_data["schema_version"] = "1.1"
    dash_data["documents"][0]["id"] = doc_id
    dash_data["documents"][0]["sha256"] = doc_sha
    # Remap page document_id references to match doc_id
    for p in dash_data["pages"]:
        p["document_id"] = doc_id

    amb_root = tmp_path / "amb-acq"
    amb_root.mkdir()
    for f in SOURCE_FIXTURES.iterdir():
        if f.is_file() and f.name != "description-selection.json":
            (amb_root / f.name).write_bytes(f.read_bytes())
    (amb_root / "acq-1").mkdir()
    (amb_root / "acq-2").mkdir()
    (amb_root / "acq-1/source-acquisition.json").write_bytes(
        (SOURCE_FIXTURES / "source-acquisition.json").read_bytes()
    )
    (amb_root / "acq-2/source-acquisition.json").write_bytes(
        (SOURCE_FIXTURES / "source-acquisition.json").read_bytes()
    )
    (amb_root / "source-acquisition.json").unlink()
    dash_in = tmp_path / "d-in.json"
    _wjson(dash_in, dash_data)
    assert dashboard_file(dash_in, amb_root / "dash")["status"] == "needs_review"

    insp_amb = inspect_artifacts(amb_root, requested_stage="verify")
    calc_amb = _nodes(insp_amb, "dashboard_calculations")[0]
    assert "ambiguous_source_occurrence" in _codes(calc_amb)

    # Unlinked source identity: one acquisition exists, dashboard references different doc hash
    unlinked_root = tmp_path / "unlinked-acq"
    shutil.copytree(SOURCE_FIXTURES, unlinked_root)
    (unlinked_root / "description-selection.json").unlink()
    dash_other = json.loads((FIXTURES / "dashboard-absolute.json").read_text())
    dash_other["schema_version"] = "1.1"
    dash_other["documents"][0]["sha256"] = "a" * 64
    dash_other_in = tmp_path / "d-other.json"
    _wjson(dash_other_in, dash_other)
    assert dashboard_file(dash_other_in, unlinked_root / "dash")["status"] == "needs_review"
    insp_un = inspect_artifacts(unlinked_root, requested_stage="verify")
    calc_un = _nodes(insp_un, "dashboard_calculations")[0]
    assert "unlinked_source_identity" in _codes(calc_un)
