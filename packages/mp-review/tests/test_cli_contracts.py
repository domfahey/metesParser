"""In-process CLI dispatch, exit-code contract, and __main__ entry point tests."""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path

import pytest
from mp_models.dashboard import DashboardBundle
from mp_models.delivery import DeliveryRequest
from mp_models.revisions import revision_template
from mp_review import cli
from mp_review.revisions import publish_revision

FIXTURES = Path(__file__).parent / "fixtures"
PLUGIN = Path(__file__).resolve().parents[3] / "plugins/metesparser"


def _invoke(monkeypatch, capsys, argv: list[str]) -> tuple[int, dict]:
    monkeypatch.setattr(sys, "argv", ["metes-review", *argv])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    out = capsys.readouterr().out
    assert len(out.splitlines()) == 1, out
    return int(exc.value.code), json.loads(out)


def test_python_module_entrypoint_executes_main(tmp_path, monkeypatch, capsys):
    output = tmp_path / "out"
    monkeypatch.setattr(
        sys,
        "argv",
        ["metes-review", "review", str(FIXTURES / "square.txt"), "--output-dir", str(output)],
    )
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("mp_review", run_name="__main__")
    assert exc.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "checks_passed"


def test_cli_settings_error_review_and_verify_exit_codes(tmp_path, monkeypatch, capsys):
    bad_settings = tmp_path / "bad-settings.md"
    bad_settings.write_text("---\nunknown_option: 1\n---\n")
    code, res = _invoke(
        monkeypatch,
        capsys,
        [
            "review",
            str(FIXTURES / "square.txt"),
            "--output-dir",
            str(tmp_path / "never"),
            "--settings",
            str(bad_settings),
        ],
    )
    assert code == 2
    assert res["status"] == "error"
    assert res["errors"][0]["code"] == "invalid_settings"
    assert not (tmp_path / "never").exists()

    # verify on valid JSON calls -> exit 0
    calls_json = tmp_path / "calls.json"
    out_rev = tmp_path / "rev"
    code, res = _invoke(
        monkeypatch, capsys, ["review", str(FIXTURES / "square.txt"), "--output-dir", str(out_rev)]
    )
    assert code == 0 and res["status"] == "checks_passed"
    calls_json.write_bytes((out_rev / "calls.json").read_bytes())

    code, res = _invoke(
        monkeypatch, capsys, ["verify", str(calls_json), "--output-dir", str(tmp_path / "ver")]
    )
    assert code == 0 and res["status"] == "checks_passed"

    # verify on .txt -> exit 2 error
    code, res = _invoke(
        monkeypatch,
        capsys,
        ["verify", str(FIXTURES / "square.txt"), "--output-dir", str(tmp_path / "ver-bad")],
    )
    assert code == 2 and res["status"] == "error"


def test_cli_advisory_subcommands_in_process(tmp_path, monkeypatch, capsys):
    # derive-plss
    plss_src = PLUGIN / "skills/plot-plss-reference/references/example.json"
    code, res = _invoke(
        monkeypatch, capsys, ["derive-plss", str(plss_src), "--output-dir", str(tmp_path / "plss")]
    )
    assert code == 1 and res["status"] == "needs_review"

    # diagnose-closure
    diag_src = FIXTURES / "diagnostics/request.json"
    code, res = _invoke(
        monkeypatch,
        capsys,
        ["diagnose-closure", str(diag_src), "--output-dir", str(tmp_path / "diag")],
    )
    assert code == 1 and res["status"] == "needs_review"

    # compare-descriptions
    comp_src = FIXTURES / "comparison-synthetic.json"
    code, res = _invoke(
        monkeypatch,
        capsys,
        ["compare-descriptions", str(comp_src), "--output-dir", str(tmp_path / "comp")],
    )
    assert code == 1 and res["status"] == "needs_review"

    # analyze-relative
    rel_src = PLUGIN / "skills/deed-closure-dashboard/references/relative-rectangle.json"
    code, res = _invoke(
        monkeypatch,
        capsys,
        ["analyze-relative", str(rel_src), "--output-dir", str(tmp_path / "rel")],
    )
    assert code == 1 and res["status"] == "needs_review"

    # dashboard
    dash_src = FIXTURES / "dashboard-absolute.json"
    code, res = _invoke(
        monkeypatch,
        capsys,
        ["dashboard", str(dash_src), "--output-dir", str(tmp_path / "dash")],
    )
    assert code == 1 and res["status"] == "needs_review"


def test_cli_serve_map_and_fetch_parcel_routes(tmp_path, monkeypatch, capsys):
    import mp_review.map_preview as preview_mod
    import mp_review.parcel_provider as provider_mod

    # serve-map success
    monkeypatch.setattr(preview_mod, "serve_map_preview", lambda directory, port=8765: None)
    code, res = _invoke(monkeypatch, capsys, ["serve-map", str(tmp_path), "--port", "8765"])
    assert code == 0 and res["status"] == "passed"

    # serve-map error
    def fail_serve(directory, port=8765):
        raise ValueError("manifest missing")

    monkeypatch.setattr(preview_mod, "serve_map_preview", fail_serve)
    code, res = _invoke(monkeypatch, capsys, ["serve-map", str(tmp_path), "--port", "8765"])
    assert code == 2 and res["errors"][0]["code"] == "map_preview_unavailable"

    # fetch-parcel with stubbed provider (no network)
    monkeypatch.setattr(
        provider_mod,
        "fetch_njgin",
        lambda **kwargs: {"schema_version": "1.1", "status": "empty", "query": kwargs},
    )
    parcel_out = tmp_path / "parcel.json"
    code, res = _invoke(
        monkeypatch,
        capsys,
        [
            "fetch-parcel",
            "--municipality",
            "0101",
            "--block",
            "1",
            "--lot",
            "2",
            "--target-crs",
            "EPSG:3857",
            "--output",
            str(parcel_out),
        ],
    )
    assert code == 0 and res["status"] == "passed"
    assert res["acquisition_status"] == "empty"
    assert parcel_out.is_file()


def test_cli_revision_and_delivery_subcommands_and_error_paths(tmp_path, monkeypatch, capsys):
    bundle_path = FIXTURES / "dashboard-absolute.json"
    bundle = DashboardBundle.model_validate_json(bundle_path.read_text())

    # revision-template writes new file (exit 1), refuses overwrite (exit 2)
    tpl_path = tmp_path / "sub/template.json"
    code, res = _invoke(
        monkeypatch,
        capsys,
        [
            "revision-template",
            str(bundle_path),
            "--output",
            str(tpl_path),
            "--revision-id",
            "rev-1",
        ],
    )
    assert code == 1 and res["status"] == "needs_review"
    assert tpl_path.is_file()

    code, res = _invoke(
        monkeypatch,
        capsys,
        [
            "revision-template",
            str(bundle_path),
            "--output",
            str(tpl_path),
            "--revision-id",
            "rev-1",
        ],
    )
    assert code == 2 and res["errors"][0]["code"] == "invalid_revision"

    # Publish revision, then inspect-revision and render-revision and export-review
    rev_store = tmp_path / "revisions"
    rev = revision_template(bundle, revision_id="rev-1")
    assert publish_revision(bundle, rev, rev_store)["save_state"] == "published"
    rev_dir = rev_store / "rev-1"

    code, res = _invoke(
        monkeypatch,
        capsys,
        ["inspect-revision", str(bundle_path), "--revision-dir", str(rev_dir)],
    )
    assert code == 1 and res["status"] == "needs_review"
    assert res["revision"]["revision"]["id"] == "rev-1"

    code, res = _invoke(
        monkeypatch,
        capsys,
        [
            "render-revision",
            str(bundle_path),
            "--revision-dir",
            str(rev_dir),
            "--output-dir",
            str(tmp_path / "rendered-rev"),
        ],
    )
    assert code == 1 and res["status"] == "needs_review"

    req = DeliveryRequest(
        id="pkg-1",
        baseline=rev.baseline,
        revision_id="rev-1",
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
                "required": True,
            }
        ],
        formats=["svg"],
    )
    req_path = tmp_path / "delivery-request.json"
    req_path.write_text(req.model_dump_json())
    deliv_out = tmp_path / "deliveries"
    code, res = _invoke(
        monkeypatch,
        capsys,
        [
            "export-review",
            str(bundle_path),
            "--revision-dir",
            str(rev_dir),
            "--request",
            str(req_path),
            "--output-dir",
            str(deliv_out),
        ],
    )
    assert code == 1 and res["status"] == "needs_review"

    # inspect-delivery on missing package -> invalid_delivery (exit 2)
    code, res = _invoke(
        monkeypatch,
        capsys,
        [
            "inspect-delivery",
            str(bundle_path),
            "--revision-dir",
            str(rev_dir),
            "--package-dir",
            str(tmp_path / "no-such-pkg"),
        ],
    )
    assert code == 2 and res["errors"][0]["code"] == "invalid_delivery"
