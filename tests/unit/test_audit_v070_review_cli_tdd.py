"""Red-Green TDD regression suite for v0.7.0 review engine, CLI, pipeline, review_packet, and run_registry fixes."""

from __future__ import annotations

import importlib
import json
import math
import tomllib
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from metesparser import cli
from metesparser.llm_cache import CachedLLMClient
from metesparser.models import (
    AuditContext as MonolithAuditContext,
)
from metesparser.models import (
    ClosureResult as MonolithClosureResult,
)
from metesparser.models import (
    DeedCall as MonolithDeedCall,
)
from metesparser.models import (
    LegalDescription as MonolithLegalDescription,
)
from metesparser.models import (
    RunMetadata as MonolithRunMetadata,
)
from metesparser.models import (
    Tract as MonolithTract,
)
from metesparser.models import (
    TractType as MonolithTractType,
)
from metesparser.pipeline import Pipeline
from metesparser.review_packet import (
    _CALL_COLUMNS,
    _review_css,
    build_closure_section,
    build_metadata_section,
    generate_all_packets,
    generate_review_html,
    generate_traverse_plot,
    load_ground_truth,
)
from metesparser.run_registry import (
    PromptVersion,
    RunManifest,
    RunResults,
    _git_sha_for_file,
    _short_prompt_sha,
    format_comparison_table,
    load_run_manifests,
    write_run_manifest,
)

# ---------------------------------------------------------------------------
# 1. mp-review fixes
# ---------------------------------------------------------------------------


def test_corpus_missing_call_index_does_not_vacuously_pass_on_null(tmp_path):
    from mp_review.corpus import run_corpus

    empty_calls_file = tmp_path / "empty.json"
    empty_calls_file.write_text("[]", encoding="utf-8")
    manifest = {
        "schema_version": "1.0",
        "reviewed_basis": "Missing call index must never pass vacuously when expected value is null.",
        "cases": [
            {
                "id": "missing-call",
                "input": {"kind": "json", "path": "empty.json"},
                "expect": {"selected_calls": [{"bearing_azimuth_deg_from_north": None}]},
            }
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = run_corpus(manifest_path)

    assert report["status"] == "failed"
    assert report["cases"][0]["status"] == "failed"
    assert report["cases"][0]["assertions"][0]["passed"] is False


@pytest.mark.parametrize(
    "tol_key,tol_value",
    [
        ("misclosure_ft_tolerance", -0.01),
        ("area_sq_ft_tolerance", True),
        ("numeric_tolerance", False),
        ("numeric_tolerance", float("nan")),
        ("misclosure_ft_tolerance", float("inf")),
        ("area_sq_ft_tolerance", "0.1"),
    ],
)
def test_corpus_rejects_negative_non_finite_and_bool_tolerances(tol_key, tol_value):
    from mp_review.corpus import _validate_case

    case = {
        "id": "bad-tol",
        "input": {"kind": "text", "path": "square.txt"},
        "expect": {"status": "checks_passed", tol_key: tol_value},
    }
    with pytest.raises(ValueError):
        _validate_case(case)


def test_review_file_strips_utf8_bom_for_text_and_json(tmp_path):
    from mp_review import review_file

    square_text = (
        "BEGINNING at an iron pin; THENCE N 0° E 100 feet; "
        "THENCE N 90° E 100 feet; THENCE S 0° E 100 feet; "
        "THENCE N 90° W 100 feet to the point of beginning."
    )
    bom_txt = tmp_path / "bom.txt"
    bom_txt.write_bytes(b"\xef\xbb\xbf" + square_text.encode("utf-8"))
    txt_result = review_file(bom_txt)
    assert txt_result["status"] == "checks_passed", txt_result["errors"]

    calls_payload = [
        {
            "course": 1,
            "direction_text": "N 0 E",
            "bearing_azimuth_deg_from_north": 0.0,
            "distance_ft": 100.0,
        },
        {
            "course": 2,
            "direction_text": "N 90 E",
            "bearing_azimuth_deg_from_north": 90.0,
            "distance_ft": 100.0,
        },
        {
            "course": 3,
            "direction_text": "S 0 E",
            "bearing_azimuth_deg_from_north": 180.0,
            "distance_ft": 100.0,
        },
        {
            "course": 4,
            "direction_text": "N 90 W",
            "bearing_azimuth_deg_from_north": 270.0,
            "distance_ft": 100.0,
        },
    ]
    bom_json = tmp_path / "bom.json"
    bom_json.write_bytes(b"\xef\xbb\xbf" + json.dumps(calls_payload).encode("utf-8"))
    json_result = review_file(bom_json)
    assert json_result["status"] == "checks_passed", json_result["errors"]


def test_review_file_supports_tracts_only_legal_description_json(tmp_path):
    from mp_review import review_file

    square_calls = [
        {
            "course": 1,
            "direction_text": "N 0 E",
            "bearing_azimuth_deg_from_north": 0.0,
            "distance_ft": 100.0,
        },
        {
            "course": 2,
            "direction_text": "N 90 E",
            "bearing_azimuth_deg_from_north": 90.0,
            "distance_ft": 100.0,
        },
        {
            "course": 3,
            "direction_text": "S 0 E",
            "bearing_azimuth_deg_from_north": 180.0,
            "distance_ft": 100.0,
        },
        {
            "course": 4,
            "direction_text": "N 90 W",
            "bearing_azimuth_deg_from_north": 270.0,
            "distance_ft": 100.0,
        },
    ]
    payload = {
        "tracts": [
            {
                "label": "Tract 1",
                "tract_type": "main",
                "role_basis": "single",
                "calls": square_calls,
            }
        ]
    }
    json_path = tmp_path / "tracts_only.json"
    json_path.write_text(json.dumps(payload), encoding="utf-8")

    result = review_file(json_path)

    assert result["status"] == "checks_passed", result["errors"]
    assert len(result["calls"]) == 4


def test_review_file_tracts_json_enforces_multi_parcel_and_role_guardrails(tmp_path):
    from mp_review import review_file

    square_calls = [
        {
            "course": 1,
            "direction_text": "N 0 E",
            "bearing_azimuth_deg_from_north": 0.0,
            "distance_ft": 100.0,
        },
        {
            "course": 2,
            "direction_text": "N 90 E",
            "bearing_azimuth_deg_from_north": 90.0,
            "distance_ft": 100.0,
        },
        {
            "course": 3,
            "direction_text": "S 0 E",
            "bearing_azimuth_deg_from_north": 180.0,
            "distance_ft": 100.0,
        },
        {
            "course": 4,
            "direction_text": "N 90 W",
            "bearing_azimuth_deg_from_north": 270.0,
            "distance_ft": 100.0,
        },
    ]
    multi_boundary = {
        "tracts": [
            {
                "label": "Tract 1",
                "tract_type": "main",
                "role_basis": "heading",
                "calls": square_calls,
            },
            {
                "label": "Tract 2",
                "tract_type": "addition",
                "role_basis": "heading",
                "calls": square_calls,
            },
        ]
    }
    multi_path = tmp_path / "multi_boundary.json"
    multi_path.write_text(json.dumps(multi_boundary), encoding="utf-8")
    multi_out = tmp_path / "multi_out"
    multi_res = review_file(multi_path, output_dir=multi_out)
    assert multi_res["status"] == "error"
    assert multi_res["errors"][0]["code"] == "invalid_input"
    assert not (multi_out / "calls_verified.csv").exists()

    inferred_roles = {
        "tracts": [
            {
                "label": "Tract 1",
                "tract_type": "main",
                "role_basis": "inferred",
                "calls": square_calls,
            },
        ]
    }
    inferred_path = tmp_path / "inferred.json"
    inferred_path.write_text(json.dumps(inferred_roles), encoding="utf-8")
    inferred_out = tmp_path / "inferred_out"
    inferred_res = review_file(inferred_path, output_dir=inferred_out)
    assert inferred_res["status"] == "needs_review"
    assert any(err["code"] == "description_roles_inferred" for err in inferred_res["errors"])
    assert not (inferred_out / "calls_verified.csv").exists()

    easement_only = {
        "tracts": [
            {
                "label": "Easement 1",
                "tract_type": "easement",
                "role_basis": "heading",
                "calls": square_calls,
            },
        ]
    }
    easement_path = tmp_path / "easement.json"
    easement_path.write_text(json.dumps(easement_only), encoding="utf-8")
    easement_out = tmp_path / "easement_out"
    easement_res = review_file(easement_path, output_dir=easement_out)
    assert easement_res["status"] != "checks_passed"
    assert not (easement_out / "calls_verified.csv").exists()


def test_prepare_text_propagates_stated_area_approximate():
    from mp_review.text import prepare_text

    text = (
        "BEGINNING at an iron pin; THENCE N 0° E 208.71 feet; "
        "THENCE N 90° E 208.71 feet; THENCE S 0° E 208.71 feet; "
        "THENCE N 90° W 208.71 feet to the point of beginning, "
        "containing 1 acre, more or less."
    )
    prepared = prepare_text(text)

    assert prepared.legal_description.stated_area_sq_ft == pytest.approx(43560.0)
    assert prepared.legal_description.stated_area_approximate is True


def test_review_records_verified_sidecars_in_artifacts(tmp_path):
    from mp_review import review_text

    square = (
        "BEGINNING at an iron pin; THENCE N 0° E 100 feet; "
        "THENCE N 90° E 100 feet; THENCE S 0° E 100 feet; "
        "THENCE N 90° W 100 feet to the point of beginning."
    )
    out_dir = tmp_path / "out"
    result = review_text(square, output_dir=out_dir)

    assert result["status"] == "checks_passed"
    assert "calls_verified.csv" in result["artifacts"]
    assert "calls_verified.verification.txt" in result["artifacts"]
    assert "calls_verified.metadata.txt" in result["artifacts"]
    assert Path(result["artifacts"]["calls_verified.verification.txt"]).is_file()
    assert Path(result["artifacts"]["calls_verified.metadata.txt"]).is_file()


def test_review_surfaces_infer_distance_unit_advisory():
    from mp_review import review_text

    text = (
        "BEGINNING at a stone; THENCE N 0° E 100 varas; "
        "THENCE N 90° E 100 varas; THENCE S 0° E 100 varas; "
        "THENCE N 90° W 100 varas to the point of beginning."
    )
    result = review_text(text)

    assert any("varas" in item.lower() for item in result["limitations"])


def test_read_settings_walks_upward_for_project_root_markers(tmp_path):
    from mp_review.settings import SettingsError, read_settings

    # Case 1: nested inside .claude/
    proj_a = tmp_path / "proj_a"
    nested_settings = proj_a / ".claude" / "nested" / "metesparser.local.md"
    nested_settings.parent.mkdir(parents=True)
    nested_settings.write_text('---\noutput_dir: "out"\n---\n', encoding="utf-8")
    parsed_a = read_settings(nested_settings)
    assert parsed_a["output_dir"] == (proj_a / "out").resolve()

    # Case 2: located under config/ with pyproject.toml marker at proj_b root
    proj_b = tmp_path / "proj_b"
    (proj_b / "config").mkdir(parents=True)
    (proj_b / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    cfg_settings = proj_b / "config" / "settings.md"
    cfg_settings.write_text('---\noutput_dir: "reviews"\n---\n', encoding="utf-8")
    parsed_b = read_settings(cfg_settings)
    assert parsed_b["output_dir"] == (proj_b / "reviews").resolve()

    # Case 3: isolated directory with no markers falls back safely to parent, not parent.parent
    isolated = tmp_path / "isolated" / "sub"
    isolated.mkdir(parents=True)
    iso_settings = isolated / "settings.md"
    iso_settings.write_text('---\noutput_dir: "../escape"\n---\n', encoding="utf-8")
    with pytest.raises(SettingsError, match="within the project directory"):
        read_settings(iso_settings)


def test_mp_review_main_module_guarded_by_dunder_main():
    mod = importlib.import_module("mp_review.__main__")
    assert mod is not None
    source = Path("packages/mp-review/src/mp_review/__main__.py").read_text(encoding="utf-8")
    assert 'if __name__ == "__main__":' in source or "if __name__ == '__main__':" in source


def test_mp_review_pyproject_declares_dev_optional_dependencies():
    data = tomllib.loads(Path("packages/mp-review/pyproject.toml").read_text(encoding="utf-8"))
    dev_deps = data["project"]["optional-dependencies"]["dev"]
    joined = " ".join(dev_deps)
    assert "pytest>=8.3.0" in joined
    assert "ruff>=0.8.0" in joined
    assert "mypy>=1.14.0" in joined


# ---------------------------------------------------------------------------
# 2. src/metesparser/cli.py fixes
# ---------------------------------------------------------------------------


def test_extract_command_unwraps_cached_llm_client_model_and_empty_env_provider(
    monkeypatch, tmp_path
):
    pdf = tmp_path / "deed.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    output = tmp_path / "out.csv"
    runs_dir = tmp_path / "runs"
    legal_desc = MonolithLegalDescription(
        calls=[
            MonolithDeedCall(
                course=1,
                direction_text="N 90° E",
                bearing_azimuth_deg_from_north=90.0,
                distance_ft=10.0,
            )
        ],
        source_doc="deed.pdf",
    )
    verified = MonolithClosureResult(
        misclosure_x_ft=0.0,
        misclosure_y_ft=0.0,
        misclosure_ft=0.0,
        area_sq_ft=100.0,
        area_acres=100.0 / 43560.0,
        perimeter_ft=40.0,
        closure_passed=True,
        angle_check_passed=True,
        curve_consistency_passed=True,
        warnings=[],
    )
    inner_client = SimpleNamespace(model="gpt-5.2-mini")
    cached_client = CachedLLMClient(inner_client, tmp_path / "cache")  # type: ignore[arg-type]

    monkeypatch.setenv("METESPARSER_LLM_PROVIDER", "")
    monkeypatch.setattr(
        "metesparser.pdf_processor.PDFProcessor",
        lambda **_kw: SimpleNamespace(
            process_deed_pdf=lambda _: legal_desc,
            prompts_dir=tmp_path,
            client=cached_client,
        ),
    )
    monkeypatch.setattr(
        "metesparser.closure_checker.ClosureChecker.verify_closure",
        lambda calls, area=0.0: verified,
    )
    monkeypatch.setattr(
        "metesparser.closure_checker.ClosureChecker.get_closure_summary",
        lambda result: "VERIFIED",
    )
    monkeypatch.setattr(
        "metesparser.csv_builder.CSVBuilder.export_verified_csv",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr("metesparser.cli.RUNS_DIR", runs_dir)

    cli.extract_command(str(pdf), output=str(output))

    manifests = load_run_manifests(runs_dir)
    assert len(manifests) == 1
    assert manifests[0].llm_model == "gpt-5.2-mini"
    assert manifests[0].llm_provider == "openai"


@pytest.mark.parametrize("bad_area", ["0", "-10", "nan", "inf", "-inf"])
def test_main_verify_rejects_non_positive_or_non_finite_area(monkeypatch, tmp_path, bad_area):
    csv = tmp_path / "calls.csv"
    csv.write_text("course,direction_text,distance_ft\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["metesparser", "verify", str(csv), "--area", bad_area])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


@pytest.mark.parametrize("bad_area", [0.0, -5.0, float("nan"), float("inf")])
def test_verify_command_rejects_non_positive_or_non_finite_area(monkeypatch, tmp_path, bad_area):
    csv = tmp_path / "calls.csv"
    csv.write_text("course,direction_text,distance_ft\n", encoding="utf-8")
    verified = MonolithClosureResult(
        misclosure_x_ft=0.0,
        misclosure_y_ft=0.0,
        misclosure_ft=0.0,
        area_sq_ft=100.0,
        area_acres=100.0 / 43560.0,
        perimeter_ft=40.0,
        closure_passed=True,
        angle_check_passed=True,
        curve_consistency_passed=True,
        warnings=[],
    )
    monkeypatch.setattr("metesparser.csv_builder.CSVBuilder.csv_to_calls", lambda _: [])
    monkeypatch.setattr(
        "metesparser.closure_checker.ClosureChecker.verify_closure",
        lambda calls, area=0.0: verified,
    )
    monkeypatch.setattr(
        "metesparser.closure_checker.ClosureChecker.get_closure_summary",
        lambda result: "VERIFIED",
    )
    with pytest.raises(SystemExit) as exc:
        cli.verify_command(str(csv), stated_area=bad_area)
    assert exc.value.code == 1


def test_extract_command_passes_tracts_stated_area_and_calls_to_closure_checker(
    monkeypatch, tmp_path
):
    pdf = tmp_path / "multi.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    output = tmp_path / "out.csv"

    square_calls = [
        MonolithDeedCall(
            course=1, direction_text="N 0° E", bearing_azimuth_deg_from_north=0.0, distance_ft=100.0
        ),
        MonolithDeedCall(
            course=2,
            direction_text="N 90° E",
            bearing_azimuth_deg_from_north=90.0,
            distance_ft=100.0,
        ),
        MonolithDeedCall(
            course=3,
            direction_text="S 0° E",
            bearing_azimuth_deg_from_north=180.0,
            distance_ft=100.0,
        ),
        MonolithDeedCall(
            course=4,
            direction_text="N 90° W",
            bearing_azimuth_deg_from_north=270.0,
            distance_ft=100.0,
        ),
    ]
    tracts = [
        MonolithTract(
            label="Tract 1",
            tract_type=MonolithTractType.MAIN,
            role_basis="heading",
            calls=square_calls,
            stated_area_sq_ft=10000.0,
        ),
        MonolithTract(
            label="Tract 2",
            tract_type=MonolithTractType.ADDITION,
            role_basis="heading",
            calls=square_calls,
            stated_area_sq_ft=10000.0,
        ),
    ]
    legal_desc = MonolithLegalDescription(
        calls=[],
        tracts=tracts,
        stated_area_sq_ft=20000.0,
        source_doc="multi.pdf",
    )

    seen_verify: list[dict[str, object]] = []
    seen_summary_calls: list[object] = []

    from metesparser.closure_checker import ClosureChecker

    orig_verify = ClosureChecker.verify_closure
    orig_summary = ClosureChecker.get_closure_summary

    def spy_verify(calls, stated_area_sq_ft=0.0, **kwargs):
        seen_verify.append(
            {
                "calls": calls,
                "stated_area_sq_ft": stated_area_sq_ft,
                "tracts": kwargs.get("tracts"),
            }
        )
        return orig_verify(calls, stated_area_sq_ft=stated_area_sq_ft, **kwargs)

    def spy_summary(result, calls=None):
        seen_summary_calls.append(calls)
        return orig_summary(result, calls=calls)

    monkeypatch.setattr(
        "metesparser.pdf_processor.PDFProcessor",
        lambda **_kw: SimpleNamespace(
            process_deed_pdf=lambda _: legal_desc,
            prompts_dir=tmp_path,
            client=SimpleNamespace(model="gpt-5.2"),
        ),
    )
    monkeypatch.setattr(ClosureChecker, "verify_closure", spy_verify)
    monkeypatch.setattr(ClosureChecker, "get_closure_summary", spy_summary)
    monkeypatch.setattr("metesparser.cli.RUNS_DIR", tmp_path / "runs")

    cli.extract_command(str(pdf), output=str(output))

    assert len(seen_verify) == 1
    assert seen_verify[0]["tracts"] == tracts
    assert seen_verify[0]["stated_area_sq_ft"] == 20000.0
    assert len(seen_summary_calls) == 2
    assert all(c is not None for c in seen_summary_calls)


# ---------------------------------------------------------------------------
# 3. src/metesparser/pipeline.py fixes
# ---------------------------------------------------------------------------


def test_pipeline_source_has_no_cast_and_converts_monolith_models(monkeypatch):
    source = Path("src/metesparser/pipeline.py").read_text(encoding="utf-8")
    assert "cast(" not in source

    monolith_calls = [
        MonolithDeedCall(
            course=1, direction_text="N 0° E", bearing_azimuth_deg_from_north=0.0, distance_ft=100.0
        ),
        MonolithDeedCall(
            course=2,
            direction_text="N 90° E",
            bearing_azimuth_deg_from_north=90.0,
            distance_ft=100.0,
        ),
        MonolithDeedCall(
            course=3,
            direction_text="S 0° E",
            bearing_azimuth_deg_from_north=180.0,
            distance_ft=100.0,
        ),
        MonolithDeedCall(
            course=4,
            direction_text="N 90° W",
            bearing_azimuth_deg_from_north=270.0,
            distance_ft=100.0,
        ),
    ]
    monolith_legal = MonolithLegalDescription(
        calls=monolith_calls,
        stated_area_sq_ft=10000.0,
        source_doc="test.pdf",
    )
    monolith_audit = MonolithAuditContext(
        run_metadata=MonolithRunMetadata(
            parser_version="0.7.0",
            llm_provider="openai",
            llm_model="gpt-5.2",
            prompt_hash="abc",
            timestamp_utc=datetime.now(UTC),
            source_pdf="test.pdf",
            cache_enabled=False,
        )
    )

    mock_processor = MagicMock()
    mock_processor.process_deed_pdf.return_value = (monolith_legal, monolith_audit)
    monkeypatch.setattr("metesparser.pipeline.PDFProcessor", lambda **_kw: mock_processor)

    from mp_models import AuditContext as PkgAuditContext
    from mp_models import ClosureResult as PkgClosureResult

    pipe = Pipeline(provider="openai", cache=False, audit=True)
    result = pipe.run(Path("test.pdf"))

    assert isinstance(result, tuple)
    closure, audit_ctx = result
    assert isinstance(closure, PkgClosureResult)
    assert isinstance(audit_ctx, PkgAuditContext)
    assert closure.is_fully_verified() is True


# ---------------------------------------------------------------------------
# 4. src/metesparser/review_packet.py fixes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw_json", ["[]", '"hello"', "123", "null"])
def test_load_ground_truth_rejects_non_dict_json(tmp_path, raw_json):
    gt_file = tmp_path / "non_dict.ground_truth.json"
    gt_file.write_text(raw_json, encoding="utf-8")
    with pytest.raises(ValueError):
        load_ground_truth(gt_file)


def test_review_packet_handles_null_deed_info_and_null_address():
    gt_null_info = {
        "deed_info": None,
        "expected_calls": [],
        "expected_closure": {},
        "expected_legal_description": "BEGINNING...",
        "expected_pob": "a point",
        "raw_ocr_text": "raw",
    }
    meta_html = build_metadata_section(gt_null_info, "deed.pdf")
    assert "Unknown Address" in meta_html
    full_html = generate_review_html(gt_null_info, "deed.pdf")
    assert "<title>Review Packet &mdash; Unknown</title>" in full_html

    gt_null_addr = {**gt_null_info, "deed_info": {"address": None}}
    assert "Unknown Address" in build_metadata_section(gt_null_addr, "deed.pdf")


def test_closure_section_renders_na_when_closure_passed_is_none():
    gt = {"expected_closure": {"closure_passed": None}}
    html = build_closure_section(gt)
    assert "><strong>N/A</strong><" in html
    assert "PASS" not in html
    assert "FAIL" not in html


def test_generate_all_packets_uses_removesuffix_for_double_suffix_names(tmp_path):
    src = tmp_path / "src"
    out = tmp_path / "out"
    src.mkdir()
    gt = {
        "deed_info": {"address": "1 Main St"},
        "expected_calls": [],
        "expected_closure": {"closure_passed": True},
        "expected_legal_description": "BEGINNING...",
        "expected_pob": "a point",
        "raw_ocr_text": "raw",
    }
    (src / "foo.ground_truth.ground_truth.json").write_text(json.dumps(gt), encoding="utf-8")

    paths = generate_all_packets(src, out)

    assert len(paths) == 1
    assert paths[0].name == "foo.ground_truth_review.html"
    assert "foo.ground_truth.pdf" in paths[0].read_text(encoding="utf-8")


def test_call_columns_surfaces_all_csv_fields_and_notes_css_wraps():
    from mp_export.csv_writer import FIELDNAMES

    column_keys = [key for _, key in _CALL_COLUMNS]
    assert set(FIELDNAMES).issubset(set(column_keys))
    css = _review_css()
    assert "nth-child(13)" in css


def test_generate_traverse_plot_handles_curves_tie_ins_and_exceptions():
    gt_with_tie_in_and_exception = {
        "expected_calls": [
            {
                "course": 1,
                "bearing_azimuth_deg_from_north": 45.0,
                "distance_ft": 50.0,
                "is_tie_in": True,
            },
            {"course": 2, "bearing_azimuth_deg_from_north": 0.0, "distance_ft": 100.0},
            {"course": 3, "bearing_azimuth_deg_from_north": 90.0, "distance_ft": 100.0},
            {"course": 4, "bearing_azimuth_deg_from_north": 180.0, "distance_ft": 100.0},
            {"course": 5, "bearing_azimuth_deg_from_north": 270.0, "distance_ft": 100.0},
            {
                "course": 6,
                "bearing_azimuth_deg_from_north": None,
                "distance_ft": 20.0,
                "is_exception": True,
            },
        ]
    }
    svg_tie_exc = generate_traverse_plot(gt_with_tie_in_and_exception)
    assert "<svg" in svg_tie_exc
    path_line = next(line for line in svg_tie_exc.splitlines() if "<path " in line)
    assert " Z'" in path_line

    gt_with_curve = {
        "expected_calls": [
            {
                "course": 1,
                "direction_text": "right semicircle, radius 10 feet",
                "bearing_azimuth_deg_from_north": 90.0,
                "distance_ft": math.pi * 10.0,
                "curve_dir": "right",
                "radius_ft": 10.0,
                "delta_deg": 180.0,
            },
            {
                "course": 2,
                "direction_text": "north 20 feet",
                "bearing_azimuth_deg_from_north": 0.0,
                "distance_ft": 20.0,
            },
        ]
    }
    svg_curve = generate_traverse_plot(gt_with_curve)
    assert "<svg" in svg_curve
    curve_path = next(line for line in svg_curve.splitlines() if "<path " in line)
    assert " A " in curve_path
    assert " Z'" in curve_path


# ---------------------------------------------------------------------------
# 5. src/metesparser/run_registry.py fixes
# ---------------------------------------------------------------------------


def test_git_sha_for_file_works_for_relative_path_and_checks_returncode(monkeypatch):
    sha = _git_sha_for_file(Path("prompts/normalize_text.yaml"))
    assert sha is not None and len(sha) == 40

    monkeypatch.setattr(
        "metesparser.run_registry.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="deadbeef\n"),
    )
    assert _git_sha_for_file(Path("prompts/normalize_text.yaml")) is None

    def _raise_oserror(*args, **kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr("metesparser.run_registry.subprocess.run", _raise_oserror)
    assert _git_sha_for_file(Path("prompts/normalize_text.yaml")) is None


def test_write_and_format_normalize_non_utc_timestamp_to_utc(tmp_path):
    tz_plus_5 = timezone(timedelta(hours=5))
    manifest = RunManifest(
        run_id="tz-test",
        timestamp_utc=datetime(2026, 2, 16, 15, 0, 0, tzinfo=tz_plus_5),
        source_pdf="deed.pdf",
        llm_provider="openai",
        llm_model="gpt-5.2",
        cache_enabled=False,
        prompt_versions={},
        results=RunResults(
            call_count=4,
            closure_passed=True,
            misclosure_ft=0.0,
            area_sq_ft=10000.0,
            confidence_score=0.9,
            warnings=[],
        ),
        parser_version="0.7.0",
    )
    written = write_run_manifest(manifest, tmp_path)
    assert written.name.startswith("2026-02-16T100000")

    loaded = load_run_manifests(tmp_path)
    table = format_comparison_table(loaded)
    assert "2026-02-16 10:00" in table


def test_short_prompt_sha_prioritizes_active_prompts_over_extract_calls():
    manifest = RunManifest(
        run_id="prompt-prio",
        timestamp_utc=datetime(2026, 2, 16, 12, 0, 0, tzinfo=UTC),
        source_pdf="deed.pdf",
        llm_provider="openai",
        llm_model="gpt-5.2",
        cache_enabled=False,
        prompt_versions={
            "extract_calls": PromptVersion(git_sha="deadbeef1111", content_hash="0000000"),
            "extract_text_from_pdf": PromptVersion(git_sha="1234567abcdef", content_hash="1111111"),
        },
        results=RunResults(
            call_count=4,
            closure_passed=True,
            misclosure_ft=0.0,
            area_sq_ft=10000.0,
            confidence_score=0.9,
            warnings=[],
        ),
        parser_version="0.7.0",
    )
    assert _short_prompt_sha(manifest) == "1234567"


def test_format_comparison_table_shows_warn_when_passed_with_warnings():
    manifest = RunManifest(
        run_id="warn-test",
        timestamp_utc=datetime(2026, 2, 16, 12, 0, 0, tzinfo=UTC),
        source_pdf="deed.pdf",
        llm_provider="openai",
        llm_model="gpt-5.2",
        cache_enabled=False,
        prompt_versions={},
        results=RunResults(
            call_count=4,
            closure_passed=True,
            misclosure_ft=0.001,
            area_sq_ft=10000.0,
            confidence_score=0.85,
            warnings=["Adjacent course bearing reversal"],
        ),
        parser_version="0.7.0",
    )
    table = format_comparison_table([manifest])
    assert "WARN" in table
    assert "PASS" not in table
