"""Red-Green TDD regression tests for Section 2: Export, Pipeline, mp-review, CLI, Run Registry & Review Packet."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from mp_export import calls_to_csv as pkg_calls_to_csv
from mp_export import legal_description_to_csv as pkg_legal_description_to_csv
from mp_models import AuditContext as PkgAuditContext
from mp_models import ClosureResult as PkgClosureResult
from mp_models import DeedCall as PkgDeedCall
from mp_models import LegalDescription as PkgLegalDescription
from mp_models import SubdivisionReference as PkgSubdivisionReference
from mp_models import VerificationAudit as PkgVerificationAudit
from mp_review import review_text
from mp_review.settings import SettingsError, read_settings

from metesparser import cli
from metesparser.csv_builder import CSVBuilder
from metesparser.models import (
    AuditContext,
    ClosureResult,
    DeedCall,
    LegalDescription,
    Point,
    RunMetadata,
    SubdivisionReference,
    Tract,
    TractType,
)
from metesparser.pipeline import Pipeline
from metesparser.review_packet import build_call_table
from metesparser.run_registry import (
    PromptVersion,
    RunManifest,
    RunResults,
    _short_prompt_sha,
    format_comparison_table,
)


def _square_calls(call_cls):
    return [
        call_cls(
            course=i + 1,
            direction_text=f"course {i + 1}",
            bearing_azimuth_deg_from_north=az,
            distance_ft=100.0,
        )
        for i, az in enumerate((0.0, 90.0, 180.0, 270.0))
    ]


# ---------------------------------------------------------------------------
# Item 1: CSV metadata export completeness & falsy values
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("backend", ["package", "monolith"])
def test_legal_description_to_csv_exports_area_and_plat_metadata(backend, tmp_path):
    if backend == "package":
        call_cls = PkgDeedCall
        ld_cls = PkgLegalDescription
        sub_cls = PkgSubdivisionReference
        export_fn = pkg_legal_description_to_csv
    else:
        call_cls = DeedCall
        ld_cls = LegalDescription
        sub_cls = SubdivisionReference
        export_fn = CSVBuilder.legal_description_to_csv

    ld = ld_cls(
        calls=_square_calls(call_cls),
        source_doc="deed.pdf",
        stated_area_sq_ft=10000.0,
        stated_area_approximate=False,
        subdivision_ref=sub_cls(
            lot="5",
            block="B",
            subdivision_name="Oakwood",
            plat_book="12",
            plat_page="45",
        ),
    )
    out = tmp_path / "out.csv"
    export_fn(ld, str(out))

    metadata_text = (tmp_path / "out.metadata.txt").read_text(encoding="utf-8")
    assert "stated_area_sq_ft: 10000.0" in metadata_text
    assert "stated_area_approximate: False" in metadata_text
    assert "plat_book: 12" in metadata_text
    assert "plat_page: 45" in metadata_text


@pytest.mark.parametrize("backend", ["package", "monolith"])
def test_calls_to_csv_preserves_falsy_metadata_values(backend, tmp_path):
    if backend == "package":
        call_cls = PkgDeedCall
        export_fn = pkg_calls_to_csv
    else:
        call_cls = DeedCall
        export_fn = CSVBuilder.calls_to_csv

    out = tmp_path / "falsy.csv"
    export_fn(
        _square_calls(call_cls),
        str(out),
        metadata={
            "zero_int": 0,
            "zero_float": 0.0,
            "flag": False,
            "empty_str": "",
            "none_val": None,
            "label": "ok",
        },
    )

    metadata_text = (tmp_path / "falsy.metadata.txt").read_text(encoding="utf-8")
    assert "zero_int: 0" in metadata_text
    assert "zero_float: 0.0" in metadata_text
    assert "flag: False" in metadata_text
    assert "label: ok" in metadata_text
    assert "empty_str:" not in metadata_text
    assert "none_val:" not in metadata_text


# ---------------------------------------------------------------------------
# Item 2: mp-review settings project-root resolution
# ---------------------------------------------------------------------------


def test_read_settings_resolves_project_root_via_markers_over_parent_parent(tmp_path):
    project = tmp_path / "myproj"
    project.mkdir()
    (project / "pyproject.toml").write_text("[project]\nname = 'myproj'\n", encoding="utf-8")

    nested_settings = project / "nested" / "config" / "settings.md"
    nested_settings.parent.mkdir(parents=True)
    nested_settings.write_text('---\nenabled: true\noutput_dir: "out"\n---\n', encoding="utf-8")

    parsed = read_settings(nested_settings)
    assert parsed["output_dir"] == (project / "out").resolve()


def test_read_settings_fallback_without_markers_stays_within_settings_dir(tmp_path):
    plain_dir = tmp_path / "plain"
    plain_dir.mkdir()
    settings_file = plain_dir / "settings.md"
    settings_file.write_text('---\nenabled: true\noutput_dir: "out"\n---\n', encoding="utf-8")

    parsed = read_settings(settings_file)
    assert parsed["output_dir"] == (plain_dir / "out").resolve()

    escaping_file = plain_dir / "escape.md"
    escaping_file.write_text("---\noutput_dir: ../outside\n---\n", encoding="utf-8")
    with pytest.raises(SettingsError, match="within the project directory"):
        read_settings(escaping_file)


# ---------------------------------------------------------------------------
# Item 3: src/metesparser/cli.py multi-tract & closure summary
# ---------------------------------------------------------------------------


def test_extract_command_passes_tracts_and_stated_area_to_verify_closure(monkeypatch, tmp_path):
    pdf = tmp_path / "multi.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    calls = _square_calls(DeedCall)
    tracts = [
        Tract(label="Tract 1", tract_type=TractType.MAIN, calls=calls, stated_area_sq_ft=10000.0),
        Tract(label="Tract 2", tract_type=TractType.MAIN, calls=calls, stated_area_sq_ft=10000.0),
    ]
    legal_desc = LegalDescription(
        calls=calls + calls,
        tracts=tracts,
        stated_area_sq_ft=20000.0,
        source_doc="multi.pdf",
    )

    verified = ClosureResult(
        misclosure_x_ft=0.0,
        misclosure_y_ft=0.0,
        misclosure_ft=0.0,
        area_sq_ft=10000.0,
        area_acres=10000.0 / 43560.0,
        perimeter_ft=400.0,
        closure_passed=True,
        angle_check_passed=True,
        curve_consistency_passed=True,
        warnings=[],
        points=[Point(x=0.0, y=0.0), Point(x=0.0, y=100.0)],
    )

    seen_verify: list[dict[str, object]] = []
    seen_summary_calls: list[object] = []
    seen_export: list[dict[str, object]] = []

    def fake_verify_closure(
        calls_arg,
        stated_area_sq_ft: float = 0.0,
        *,
        tracts: list[Tract] | None = None,
    ):
        seen_verify.append(
            {
                "calls": calls_arg,
                "stated_area_sq_ft": stated_area_sq_ft,
                "tracts": tracts,
            }
        )
        return [verified, verified]

    def fake_summary(result, calls=None):
        seen_summary_calls.append(calls)
        return "SUMMARY"

    def fake_export(
        calls_arg, closure_result, output_path, legal_desc_obj=None, *, tract_results=None
    ):
        seen_export.append(
            {
                "calls": calls_arg,
                "closure_result": closure_result,
                "output_path": output_path,
                "legal_desc": legal_desc_obj,
                "tract_results": tract_results,
            }
        )
        return [Path(output_path)]

    monkeypatch.setattr(
        "metesparser.pdf_processor.PDFProcessor",
        lambda **_kw: SimpleNamespace(process_deed_pdf=lambda _: legal_desc),
    )
    monkeypatch.setattr(
        "metesparser.closure_checker.ClosureChecker.verify_closure", fake_verify_closure
    )
    monkeypatch.setattr(
        "metesparser.closure_checker.ClosureChecker.get_closure_summary", fake_summary
    )
    monkeypatch.setattr("metesparser.csv_builder.CSVBuilder.export_verified_csv", fake_export)
    monkeypatch.setattr("metesparser.cli.RUNS_DIR", tmp_path / "runs")

    cli.extract_command(str(pdf), output=str(tmp_path / "out.csv"))

    assert len(seen_verify) == 1
    assert seen_verify[0]["stated_area_sq_ft"] == 20000.0
    assert seen_verify[0]["tracts"] == tracts
    assert len(seen_summary_calls) == 2
    assert seen_summary_calls[0] == tracts[0].calls
    assert len(seen_export) == 1
    assert seen_export[0]["tract_results"] == [(tracts[0], verified), (tracts[1], verified)]


def test_extract_and_verify_commands_include_quality_breakdown_via_calls(
    monkeypatch, tmp_path, capsys
):
    pdf = tmp_path / "square.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    calls = _square_calls(DeedCall)
    legal_desc = LegalDescription(calls=calls, source_doc="square.pdf")

    monkeypatch.setattr(
        "metesparser.pdf_processor.PDFProcessor",
        lambda **_kw: SimpleNamespace(process_deed_pdf=lambda _: legal_desc),
    )
    monkeypatch.setattr("metesparser.cli.RUNS_DIR", tmp_path / "runs")

    cli.extract_command(str(pdf), output=str(tmp_path / "square.csv"))
    extract_out = capsys.readouterr().out
    assert "Quality Breakdown:" in extract_out

    verified_csv = tmp_path / "square_verified.csv"
    cli.verify_command(str(verified_csv))
    verify_out = capsys.readouterr().out
    assert "Quality Breakdown:" in verify_out


# ---------------------------------------------------------------------------
# Item 4: src/metesparser/pipeline.py model type safety
# ---------------------------------------------------------------------------


def test_pipeline_audit_converts_monolith_models_to_mp_models(monkeypatch, tmp_path):
    pdf = tmp_path / "deed.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    monolith_ld = LegalDescription(calls=_square_calls(DeedCall), source_doc="deed.pdf")
    monolith_ctx = AuditContext(
        run_metadata=RunMetadata(
            parser_version="0.5.0",
            llm_provider="openai",
            llm_model="gpt-5.2",
            prompt_hash="abc123",
            timestamp_utc=datetime(2026, 1, 1, tzinfo=UTC),
            source_pdf="deed.pdf",
            cache_enabled=False,
        )
    )

    monkeypatch.setattr(
        "metesparser.pipeline.PDFProcessor",
        lambda **_kw: SimpleNamespace(
            process_deed_pdf=lambda _path, audit=False: (monolith_ld, monolith_ctx)
        ),
    )

    result, audit_ctx = Pipeline(audit=True).run(pdf)
    assert isinstance(result, PkgClosureResult)
    assert isinstance(audit_ctx, PkgAuditContext)
    assert isinstance(audit_ctx.verification_audit, PkgVerificationAudit)


# ---------------------------------------------------------------------------
# Item 5: src/metesparser/run_registry.py prompt SHA & warning status
# ---------------------------------------------------------------------------


def test_short_prompt_sha_prioritizes_active_prompts_over_extract_calls():
    base_kwargs = {
        "run_id": "r1",
        "timestamp_utc": datetime(2026, 2, 16, 12, 0, tzinfo=UTC),
        "source_pdf": "deed.pdf",
        "llm_provider": "openai",
        "llm_model": "gpt-5.2",
        "cache_enabled": False,
        "results": RunResults(
            call_count=4,
            closure_passed=True,
            misclosure_ft=0.0,
            area_sq_ft=10000.0,
            confidence_score=0.95,
            warnings=[],
        ),
        "parser_version": "0.5.0",
    }

    m1 = RunManifest(
        prompt_versions={
            "extract_calls": PromptVersion(git_sha="00000001111111", content_hash="h_unused_1"),
            "extract_legal_description": PromptVersion(git_sha="aaaaaaa1111111", content_hash="h1"),
            "extract_text_from_pdf": PromptVersion(git_sha="bbbbbbb1111111", content_hash="h2"),
            "normalize_text": PromptVersion(git_sha="ccccccc1111111", content_hash="h3"),
        },
        **base_kwargs,
    )
    m2 = RunManifest(
        prompt_versions={
            "extract_calls": PromptVersion(git_sha="99999991111111", content_hash="h_unused_2"),
            "extract_legal_description": PromptVersion(git_sha="aaaaaaa1111111", content_hash="h1"),
            "extract_text_from_pdf": PromptVersion(git_sha="bbbbbbb1111111", content_hash="h2"),
            "normalize_text": PromptVersion(git_sha="ccccccc1111111", content_hash="h3"),
        },
        **base_kwargs,
    )
    m3 = RunManifest(
        prompt_versions={
            "extract_calls": PromptVersion(git_sha="00000001111111", content_hash="h_unused_1"),
            "extract_legal_description": PromptVersion(git_sha="aaaaaaa1111111", content_hash="h1"),
            "extract_text_from_pdf": PromptVersion(git_sha="ddddddd1111111", content_hash="h2_new"),
            "normalize_text": PromptVersion(git_sha="ccccccc1111111", content_hash="h3"),
        },
        **base_kwargs,
    )

    sha1 = _short_prompt_sha(m1)
    sha2 = _short_prompt_sha(m2)
    sha3 = _short_prompt_sha(m3)

    assert sha1 != "0000000"
    assert sha1 == sha2  # unused extract_calls change must not change short prompt SHA
    assert sha1 != sha3  # active prompt change must change short prompt SHA


def test_format_comparison_table_distinguishes_pass_with_warnings():
    warn_manifest = RunManifest(
        run_id="r-warn",
        timestamp_utc=datetime(2026, 2, 16, 12, 0, tzinfo=UTC),
        source_pdf="warn_deed.pdf",
        llm_provider="openai",
        llm_model="gpt-5.2",
        cache_enabled=False,
        prompt_versions={"normalize_text": PromptVersion(git_sha="abc1234", content_hash="h")},
        results=RunResults(
            call_count=4,
            closure_passed=True,
            misclosure_ft=0.0,
            area_sq_ft=10000.0,
            confidence_score=0.75,
            warnings=["Area mismatch"],
        ),
        parser_version="0.5.0",
    )
    table = format_comparison_table([warn_manifest])
    row = [line for line in table.splitlines() if "2026-02-16 12:00" in line][0]
    assert "WARN" in row
    assert "PASS" not in row
    assert "FAIL" not in row


# ---------------------------------------------------------------------------
# Item 6: src/metesparser/review_packet.py complete call columns
# ---------------------------------------------------------------------------


def test_build_call_table_includes_omitted_csv_fields():
    gt = {
        "expected_calls": [
            {
                "course": 1,
                "direction_text": "along a curve to the right",
                "bearing_quadrant": None,
                "bearing_azimuth_deg_from_north": None,
                "distance_ft": 141.42,
                "curve_dir": "right",
                "radius_ft": 100.0,
                "delta_deg": 90.0,
                "arc_length_ft": 157.08,
                "chord_bearing": "S 45°00' E",
                "chord_length_ft": 141.42,
                "along": "Oak Drive",
                "to": "an iron pin",
                "monument_type": "iron_pin",
                "monument_status": "found",
                "is_exception": True,
                "is_meander": True,
                "is_tie_in": True,
                "non_tangent": True,
                "radial_bearing": "N 45°00' E",
                "notes": "non-tangent curve",
            }
        ]
    }
    html = build_call_table(gt)
    assert "S 45°00&#x27; E" in html or "S 45°00' E" in html
    assert "141.42" in html
    assert "N 45°00&#x27; E" in html or "N 45°00' E" in html
    assert "found" in html
    assert "exception" in html
    assert "meander" in html
    assert "tie-in" in html
    assert "non-tangent" in html


# ---------------------------------------------------------------------------
# Item 7: mp_review/api.py unit-inference advisory
# ---------------------------------------------------------------------------


def test_review_text_surfaces_unit_inference_advisory():
    text = (
        "BEGINNING at an iron pin; "
        "THENCE N 0° E 100 varas; "
        "THENCE N 90° E 100 varas; "
        "THENCE S 0° E 100 varas; "
        "THENCE N 90° W 100 varas to the point of beginning."
    )
    result = review_text(text)
    assert result["status"] == "checks_passed"
    assert "advisories" in result
    assert any("varas" in adv for adv in result["advisories"])
