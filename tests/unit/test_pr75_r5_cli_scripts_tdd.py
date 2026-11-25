"""Red-Green TDD suite for PR #75 Track 4 (Monolith CLI, Pipeline, Review Packet, Scripts, Config)."""

from __future__ import annotations

import ast
import importlib.util
import json
import math
import os
import re
import shutil
import signal
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from mp_models import DESCRIPTION_ROLES_NOTE, coerce_bool_field

from metesparser import cli
from metesparser.models import (
    AuditContext as MonolithAuditContext,
)
from metesparser.models import (
    CheckResult as MonolithCheckResult,
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
from metesparser.review_packet import _as_bool, generate_traverse_plot
from metesparser.run_registry import RunManifest, RunResults, format_comparison_table

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_script(script_name: str):
    spec = importlib.util.spec_from_file_location(
        f"r5_{script_name.removesuffix('.py')}",
        REPO_ROOT / "scripts" / script_name,
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _square_monolith_calls() -> list[MonolithDeedCall]:
    return [
        MonolithDeedCall(
            course=1,
            direction_text="N 0° E 100 ft",
            bearing_quadrant="N 0° E",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=100.0,
        ),
        MonolithDeedCall(
            course=2,
            direction_text="N 90° E 100 ft",
            bearing_quadrant="N 90° E",
            bearing_azimuth_deg_from_north=90.0,
            distance_ft=100.0,
        ),
        MonolithDeedCall(
            course=3,
            direction_text="S 0° E 100 ft",
            bearing_quadrant="S 0° E",
            bearing_azimuth_deg_from_north=180.0,
            distance_ft=100.0,
        ),
        MonolithDeedCall(
            course=4,
            direction_text="N 90° W 100 ft",
            bearing_quadrant="N 90° W",
            bearing_azimuth_deg_from_north=270.0,
            distance_ft=100.0,
        ),
    ]


def _make_closure(
    *,
    closure_passed: bool = True,
    misclosure_available: bool = True,
    misclosure_x_ft: float = 0.0,
    misclosure_y_ft: float = 0.0,
    misclosure_ft: float = 0.0,
    area_available: bool = True,
    area_sq_ft: float = 10000.0,
    perimeter_available: bool = True,
    perimeter_ft: float = 400.0,
    angle_check_passed: bool = True,
    curve_consistency_passed: bool = True,
    confidence_score: float = 0.9,
    warnings: list[str] | None = None,
    checks: list[MonolithCheckResult] | None = None,
) -> MonolithClosureResult:
    return MonolithClosureResult(
        misclosure_x_ft=misclosure_x_ft,
        misclosure_y_ft=misclosure_y_ft,
        misclosure_ft=misclosure_ft,
        area_sq_ft=area_sq_ft,
        area_acres=area_sq_ft / 43560.0,
        perimeter_ft=perimeter_ft,
        misclosure_available=misclosure_available,
        area_available=area_available,
        perimeter_available=perimeter_available,
        closure_passed=closure_passed,
        angle_check_passed=angle_check_passed,
        curve_consistency_passed=curve_consistency_passed,
        confidence_score=confidence_score,
        warnings=warnings or [],
        checks=checks or [],
    )


# ---------------------------------------------------------------------------
# 1. src/metesparser/cli.py: Simplification A1, aggregate_tract_closure,
#    verify_command bool guard, _unwrap_llm_model, extract_command, Pipeline
# ---------------------------------------------------------------------------


def test_cli_extract_and_verify_pass_closure_checker_kwargs_directly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """extract_command and verify_command must pass stated_area_sq_ft, tracts, and calls directly."""
    square = _square_monolith_calls()
    closed = _make_closure(closure_passed=True)
    verify_calls: list[dict[str, object]] = []
    summary_calls: list[dict[str, object]] = []

    def fake_verify_closure(
        calls: list[MonolithDeedCall],
        *,
        stated_area_sq_ft: float,
        tracts: list[MonolithTract] | None = None,
    ) -> MonolithClosureResult | list[MonolithClosureResult]:
        verify_calls.append(
            {"calls": calls, "stated_area_sq_ft": stated_area_sq_ft, "tracts": tracts}
        )
        if tracts is not None:
            return [closed for _ in tracts]
        return closed

    def fake_get_closure_summary(
        result: MonolithClosureResult,
        *,
        calls: list[MonolithDeedCall],
    ) -> str:
        summary_calls.append({"result": result, "calls": calls})
        return "summary"

    monkeypatch.setattr(
        "metesparser.closure_checker.ClosureChecker.verify_closure",
        staticmethod(fake_verify_closure),
    )
    monkeypatch.setattr(
        "metesparser.closure_checker.ClosureChecker.get_closure_summary",
        staticmethod(fake_get_closure_summary),
    )
    monkeypatch.setattr(
        "metesparser.csv_builder.CSVBuilder.export_verified_csv",
        staticmethod(lambda *_a, **_kw: []),
    )
    monkeypatch.setattr("metesparser.cli.RUNS_DIR", tmp_path / "runs")

    # 1. Multi-tract extract_command
    multi_pdf = tmp_path / "multi.pdf"
    multi_pdf.write_bytes(b"%PDF-1.4\n")
    tracts = [
        MonolithTract(
            label="Tract 1", tract_type=MonolithTractType.MAIN, role_basis="heading", calls=square
        ),
        MonolithTract(
            label="Tract 2",
            tract_type=MonolithTractType.ADDITION,
            role_basis="heading",
            calls=square[:2],
        ),
    ]
    multi_ld = MonolithLegalDescription(
        calls=[], tracts=tracts, stated_area_sq_ft=12345.0, source_doc="multi.pdf"
    )
    monkeypatch.setattr(
        "metesparser.pdf_processor.PDFProcessor",
        lambda **_kw: SimpleNamespace(
            process_deed_pdf=lambda _: multi_ld,
            prompts_dir=tmp_path,
            model_name="gpt-5.2",
        ),
    )
    cli.extract_command(str(multi_pdf), output=str(tmp_path / "multi.csv"))

    assert len(verify_calls) == 1
    assert verify_calls[0]["stated_area_sq_ft"] == 12345.0
    assert verify_calls[0]["tracts"] == tracts
    assert len(summary_calls) == 2
    assert summary_calls[0]["calls"] == tracts[0].calls
    assert summary_calls[1]["calls"] == tracts[1].calls

    # 2. Single-tract extract_command
    verify_calls.clear()
    summary_calls.clear()
    single_pdf = tmp_path / "single.pdf"
    single_pdf.write_bytes(b"%PDF-1.4\n")
    single_ld = MonolithLegalDescription(
        calls=square, stated_area_sq_ft=10000.0, source_doc="single.pdf"
    )
    monkeypatch.setattr(
        "metesparser.pdf_processor.PDFProcessor",
        lambda **_kw: SimpleNamespace(
            process_deed_pdf=lambda _: single_ld,
            prompts_dir=tmp_path,
            model_name="gpt-5.2",
        ),
    )
    cli.extract_command(str(single_pdf), output=str(tmp_path / "single.csv"))

    assert len(verify_calls) == 1
    assert verify_calls[0]["stated_area_sq_ft"] == 10000.0
    assert verify_calls[0]["tracts"] is None
    assert len(summary_calls) == 1
    assert summary_calls[0]["calls"] == square

    # 3. verify_command
    verify_calls.clear()
    summary_calls.clear()
    csv_file = tmp_path / "calls.csv"
    csv_file.write_text("course,direction_text,distance_ft\n", encoding="utf-8")
    monkeypatch.setattr(
        "metesparser.csv_builder.CSVBuilder.csv_to_calls",
        staticmethod(lambda _p: square),
    )
    cli.verify_command(str(csv_file), stated_area=9876.5)

    assert len(verify_calls) == 1
    assert verify_calls[0]["stated_area_sq_ft"] == 9876.5
    assert verify_calls[0]["tracts"] is None
    assert len(summary_calls) == 1
    assert summary_calls[0]["calls"] == square


def test_aggregate_tract_closure_public_symbol_and_easement_only_deed() -> None:
    """Public aggregate_tract_closure must reject easement/exception-only deeds and retire private alias."""
    assert hasattr(cli, "aggregate_tract_closure")
    assert not hasattr(cli, "_aggregate_tract_closure")

    easement = MonolithTract(
        label="Easement 1",
        tract_type=MonolithTractType.EASEMENT,
        role_basis="heading",
        calls=[],
    )
    easement_res = _make_closure(closure_passed=True, area_available=True, area_sq_ft=5000.0)

    agg = cli.aggregate_tract_closure([(easement, easement_res)])
    assert agg.closure_passed is False
    assert agg.area_available is False
    assert agg.area_sq_ft == 0.0
    assert agg.area_acres == 0.0
    assert not agg.is_fully_verified()


def test_aggregate_tract_closure_does_not_leak_misclosure_when_unavailable() -> None:
    """When misclosure_available is False on any selected tract, misclosure values must all be 0.0."""
    t1 = MonolithTract(
        label="Tract 1", tract_type=MonolithTractType.MAIN, role_basis="heading", calls=[]
    )
    t2 = MonolithTract(
        label="Tract 2", tract_type=MonolithTractType.ADDITION, role_basis="heading", calls=[]
    )
    r1 = _make_closure(
        closure_passed=False,
        misclosure_available=True,
        misclosure_x_ft=0.3,
        misclosure_y_ft=0.4,
        misclosure_ft=0.5,
    )
    r2 = _make_closure(
        closure_passed=False,
        misclosure_available=False,
        misclosure_x_ft=0.0,
        misclosure_y_ft=0.0,
        misclosure_ft=0.0,
    )
    agg_multi = cli.aggregate_tract_closure([(t1, r1), (t2, r2)])
    assert agg_multi.misclosure_available is False
    assert agg_multi.misclosure_ft == 0.0
    assert agg_multi.misclosure_x_ft == 0.0
    assert agg_multi.misclosure_y_ft == 0.0

    r_single_unavail = _make_closure(
        closure_passed=False,
        misclosure_available=False,
        misclosure_x_ft=1.2,
        misclosure_y_ft=-0.8,
        misclosure_ft=1.44,
    )
    agg_single = cli.aggregate_tract_closure([(t1, r_single_unavail)])
    assert agg_single.misclosure_available is False
    assert agg_single.misclosure_ft == 0.0
    assert agg_single.misclosure_x_ft == 0.0
    assert agg_single.misclosure_y_ft == 0.0


def test_aggregate_tract_closure_exception_disables_gross_area_and_surfaces_failure() -> None:
    """An EXCEPTION tract disables gross parcel area and propagates exception closure failure."""
    main_tract = MonolithTract(
        label="Tract 1", tract_type=MonolithTractType.MAIN, role_basis="heading", calls=[]
    )
    exc_tract = MonolithTract(
        label="Exception 1", tract_type=MonolithTractType.EXCEPTION, role_basis="heading", calls=[]
    )
    main_closed = _make_closure(
        closure_passed=True,
        area_available=True,
        area_sq_ft=10000.0,
        angle_check_passed=False,
    )
    exc_closed_warn = _make_closure(
        closure_passed=True,
        area_available=True,
        area_sq_ft=1000.0,
        warnings=["Exception tract warning"],
    )

    agg_closed = cli.aggregate_tract_closure(
        [(main_tract, main_closed), (exc_tract, exc_closed_warn)]
    )
    assert agg_closed.closure_passed is True
    assert agg_closed.area_available is False
    assert agg_closed.area_sq_ft == 0.0
    assert agg_closed.area_acres == 0.0
    assert not agg_closed.is_fully_verified()
    assert "Exception tract warning" in agg_closed.warnings

    manifest = RunManifest(
        run_id="r5-warn",
        timestamp_utc=datetime.now(UTC),
        source_pdf="multi.pdf",
        llm_provider="openai",
        llm_model="gpt-5.2",
        cache_enabled=False,
        parser_version="1.0.0",
        results=RunResults.from_closure(agg_closed, call_count=4),
    )
    table = format_comparison_table([manifest])
    assert "WARN" in table
    assert "FAIL" not in table

    exc_failed = _make_closure(
        closure_passed=False,
        misclosure_ft=2.5,
        warnings=[],
    )
    agg_failed = cli.aggregate_tract_closure([(main_tract, main_closed), (exc_tract, exc_failed)])
    assert agg_failed.closure_passed is False
    assert agg_failed.area_available is False
    assert agg_failed.area_sq_ft == 0.0
    assert any("Exception 1" in w for w in agg_failed.warnings)


def test_aggregate_tract_closure_includes_exception_failure_metrics_and_keeps_boundary_perimeter() -> (
    None
):
    """Exception failures must reflect in misclosure/checks/confidence while keeping boundary perimeter."""
    main_tract = MonolithTract(
        label="Tract 1", tract_type=MonolithTractType.MAIN, role_basis="heading", calls=[]
    )
    exc_tract = MonolithTract(
        label="Exception 1", tract_type=MonolithTractType.EXCEPTION, role_basis="heading", calls=[]
    )
    main_closed = _make_closure(
        closure_passed=True,
        misclosure_available=True,
        misclosure_x_ft=0.0001,
        misclosure_y_ft=0.0,
        misclosure_ft=0.0001,
        area_available=True,
        area_sq_ft=10000.0,
        perimeter_available=True,
        perimeter_ft=400.0,
        angle_check_passed=True,
        curve_consistency_passed=True,
        confidence_score=1.0,
    )
    exc_failed = _make_closure(
        closure_passed=False,
        misclosure_available=True,
        misclosure_x_ft=30.0,
        misclosure_y_ft=40.0,
        misclosure_ft=50.0,
        area_available=False,
        area_sq_ft=0.0,
        perimeter_available=True,
        perimeter_ft=150.0,
        angle_check_passed=False,
        curve_consistency_passed=False,
        confidence_score=0.2,
    )

    agg_failed = cli.aggregate_tract_closure([(main_tract, main_closed), (exc_tract, exc_failed)])
    assert agg_failed.closure_passed is False
    assert agg_failed.misclosure_available is True
    assert agg_failed.misclosure_ft == pytest.approx(50.0)
    assert agg_failed.misclosure_x_ft == 0.0
    assert agg_failed.misclosure_y_ft == 0.0
    assert agg_failed.angle_check_passed is False
    assert agg_failed.curve_consistency_passed is False
    assert agg_failed.confidence_score == pytest.approx(0.2)
    assert agg_failed.area_available is False
    assert agg_failed.area_sq_ft == 0.0
    assert agg_failed.area_acres == 0.0
    assert agg_failed.perimeter_available is True
    assert agg_failed.perimeter_ft == pytest.approx(400.0)

    exc_unpositioned = _make_closure(
        closure_passed=False,
        misclosure_available=False,
        misclosure_x_ft=0.0,
        misclosure_y_ft=0.0,
        misclosure_ft=0.0,
        area_available=False,
        area_sq_ft=0.0,
        perimeter_available=False,
        perimeter_ft=0.0,
        angle_check_passed=False,
        curve_consistency_passed=True,
        confidence_score=0.1,
    )
    agg_unpos = cli.aggregate_tract_closure(
        [(main_tract, main_closed), (exc_tract, exc_unpositioned)]
    )
    assert agg_unpos.closure_passed is False
    assert agg_unpos.misclosure_available is False
    assert agg_unpos.misclosure_ft == 0.0
    assert agg_unpos.misclosure_x_ft == 0.0
    assert agg_unpos.misclosure_y_ft == 0.0
    assert agg_unpos.angle_check_passed is False
    assert agg_unpos.confidence_score == pytest.approx(0.1)
    assert agg_unpos.area_available is False
    assert agg_unpos.area_sq_ft == 0.0
    assert agg_unpos.area_acres == 0.0
    assert agg_unpos.perimeter_available is True
    assert agg_unpos.perimeter_ft == pytest.approx(400.0)


def test_aggregate_tract_closure_propagates_failed_and_blocked_checks() -> None:
    """Non-passing structured checks (failed/blocked) must be propagated with tract label."""
    main_tract = MonolithTract(
        label="Tract 1", tract_type=MonolithTractType.MAIN, role_basis="heading", calls=[]
    )
    exc_tract = MonolithTract(
        label="Exception 1", tract_type=MonolithTractType.EXCEPTION, role_basis="heading", calls=[]
    )
    main_res = _make_closure(
        closure_passed=False,
        checks=[
            MonolithCheckResult(
                name="traverse_closure",
                status="failed",
                reason="misclosure_exceeds_tolerance",
                detail="Misclosure 0.50 ft exceeds 0.01 ft",
            ),
            MonolithCheckResult(
                name="interior_angles",
                status="passed",
                detail="Interior angles sum to 360 deg",
            ),
        ],
    )
    exc_res = _make_closure(
        closure_passed=True,
        checks=[
            MonolithCheckResult(
                name="non_boundary_tract",
                status="blocked",
                reason="exception_tract",
                detail="Exception tract cannot be verified as boundary",
            ),
            MonolithCheckResult(
                name="curve_consistency",
                status="not_applicable",
                detail="No curves present",
            ),
        ],
    )

    agg = cli.aggregate_tract_closure([(main_tract, main_res), (exc_tract, exc_res)])
    names_statuses = [(c.name, c.status) for c in agg.checks]
    assert ("traverse_closure", "failed") in names_statuses
    assert ("non_boundary_tract", "blocked") in names_statuses
    assert all(c.status in ("failed", "blocked") for c in agg.checks)
    assert any("Tract 1" in c.detail for c in agg.checks if c.name == "traverse_closure")
    assert any("Exception 1" in c.detail for c in agg.checks if c.name == "non_boundary_tract")


@pytest.mark.parametrize("bad_bool", [True, False])
def test_verify_command_rejects_boolean_stated_area(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, bad_bool: bool
) -> None:
    """Bool values must be rejected by verify_command's stated_area guard before loading CSV."""
    csv_file = tmp_path / "calls.csv"
    csv_file.write_text("course,direction_text,distance_ft\n", encoding="utf-8")
    monkeypatch.setattr(
        "metesparser.csv_builder.CSVBuilder.csv_to_calls",
        lambda _p: pytest.fail("verify_command must reject bool stated_area before loading CSV"),
    )
    with pytest.raises(SystemExit) as exc:
        cli.verify_command(str(csv_file), stated_area=bad_bool)  # type: ignore[arg-type]
    assert exc.value.code == 1


def test_unwrap_llm_model_prefers_public_model_name_before_private_client() -> None:
    """_unwrap_llm_model should prefer processor.model_name / client.model_name over _client."""

    class _PrivateTrapClient:
        model_name = "public-client-model"

        @property
        def _client(self) -> object:
            raise AssertionError("Should not touch private _client when public model_name exists")

    class _ProcessorWithModelName:
        model_name = "public-processor-model"

        @property
        def client(self) -> object:
            raise AssertionError("Should not touch client when processor.model_name exists")

    assert cli._unwrap_llm_model(_ProcessorWithModelName()) == "public-processor-model"
    assert (
        cli._unwrap_llm_model(SimpleNamespace(client=_PrivateTrapClient())) == "public-client-model"
    )
    # Legacy fallback still works when model_name is absent
    legacy_wrapper = SimpleNamespace(_client=SimpleNamespace(model="legacy-inner-model"))
    assert cli._unwrap_llm_model(SimpleNamespace(client=legacy_wrapper)) == "legacy-inner-model"


def test_extract_command_multi_tract_unverified_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When no boundary tract verifies in multi-tract extract, fall back to unverified CSV."""
    pdf = tmp_path / "multi_unverified.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    output = tmp_path / "out.csv"
    tracts = [
        MonolithTract(
            label="Tract 1",
            tract_type=MonolithTractType.MAIN,
            role_basis="heading",
            calls=_square_monolith_calls()[:2],
        ),
        MonolithTract(
            label="Easement 1",
            tract_type=MonolithTractType.EASEMENT,
            role_basis="heading",
            calls=_square_monolith_calls(),
        ),
    ]
    legal_desc = MonolithLegalDescription(
        calls=[], tracts=tracts, source_doc="multi_unverified.pdf"
    )
    unverified_exports: list[tuple[MonolithLegalDescription, str]] = []
    verified_exports: list[object] = []

    monkeypatch.setattr(
        "metesparser.pdf_processor.PDFProcessor",
        lambda **_kw: SimpleNamespace(
            process_deed_pdf=lambda _: legal_desc,
            prompts_dir=tmp_path,
            model_name="gpt-5.2",
        ),
    )
    monkeypatch.setattr(
        "metesparser.csv_builder.CSVBuilder.export_verified_csv",
        lambda *args, **kwargs: verified_exports.append((args, kwargs)),
    )
    monkeypatch.setattr(
        "metesparser.csv_builder.CSVBuilder.legal_description_to_csv",
        lambda ld, path: unverified_exports.append((ld, path)),
    )
    monkeypatch.setattr("metesparser.cli.RUNS_DIR", tmp_path / "runs")

    cli.extract_command(str(pdf), output=str(output))

    assert verified_exports == []
    assert len(unverified_exports) == 1
    assert unverified_exports[0][1] == str(output)


def test_extract_command_inferred_role_blocks_verified_export_and_marks_calls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Inferred description roles must stamp DESCRIPTION_ROLES_NOTE and never call export_verified_csv."""
    pdf = tmp_path / "inferred.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    output = tmp_path / "out.csv"
    square = _square_monolith_calls()
    tracts = [
        MonolithTract(
            label="Tract 1",
            tract_type=MonolithTractType.MAIN,
            role_basis="inferred",
            calls=square,
        ),
        MonolithTract(
            label="Tract 2",
            tract_type=MonolithTractType.ADDITION,
            role_basis="inferred",
            calls=square,
        ),
    ]
    legal_desc = MonolithLegalDescription(calls=square, tracts=tracts, source_doc="inferred.pdf")
    unverified_exports: list[MonolithLegalDescription] = []
    verified_exports: list[object] = []

    monkeypatch.setattr(
        "metesparser.pdf_processor.PDFProcessor",
        lambda **_kw: SimpleNamespace(
            process_deed_pdf=lambda _: legal_desc,
            prompts_dir=tmp_path,
            model_name="gpt-5.2",
        ),
    )
    monkeypatch.setattr(
        "metesparser.csv_builder.CSVBuilder.export_verified_csv",
        lambda *args, **kwargs: verified_exports.append((args, kwargs)),
    )
    monkeypatch.setattr(
        "metesparser.csv_builder.CSVBuilder.legal_description_to_csv",
        lambda ld, _path: unverified_exports.append(ld),
    )
    monkeypatch.setattr("metesparser.cli.RUNS_DIR", tmp_path / "runs")

    cli.extract_command(str(pdf), output=str(output))

    assert verified_exports == []
    assert len(unverified_exports) == 1
    exported_ld = unverified_exports[0]
    assert all(DESCRIPTION_ROLES_NOTE in (c.notes or "") for c in exported_ld.calls)
    assert all(
        DESCRIPTION_ROLES_NOTE in (c.notes or "")
        for tract in exported_ld.tracts
        for c in tract.calls
    )


@pytest.mark.parametrize("audit", [False, True])
@pytest.mark.parametrize("multi_tract", [False, True])
def test_pipeline_converts_monolith_legal_description_single_and_multi_tract(
    monkeypatch: pytest.MonkeyPatch, audit: bool, multi_tract: bool
) -> None:
    """Pipeline(audit=False/True) must handle monolith LegalDescription for single and multi-tract."""
    from mp_models import AuditContext as PkgAuditContext
    from mp_models import ClosureResult as PkgClosureResult

    square = _square_monolith_calls()
    if multi_tract:
        monolith_legal = MonolithLegalDescription(
            calls=[],
            tracts=[
                MonolithTract(
                    label="Tract 1",
                    tract_type=MonolithTractType.MAIN,
                    role_basis="heading",
                    calls=square,
                    stated_area_sq_ft=10000.0,
                ),
                MonolithTract(
                    label="Tract 2",
                    tract_type=MonolithTractType.ADDITION,
                    role_basis="heading",
                    calls=square,
                    stated_area_sq_ft=10000.0,
                ),
            ],
            source_doc="multi.pdf",
        )
    else:
        monolith_legal = MonolithLegalDescription(
            calls=square,
            stated_area_sq_ft=10000.0,
            source_doc="single.pdf",
        )

    monolith_audit = MonolithAuditContext(
        run_metadata=MonolithRunMetadata(
            parser_version="0.7.0",
            llm_provider="openai",
            llm_model="gpt-5.2",
            prompt_hash="abc",
            timestamp_utc=datetime.now(UTC),
            source_pdf=monolith_legal.source_doc or "test.pdf",
            cache_enabled=False,
        )
    )
    mock_processor = MagicMock()
    mock_processor.process_deed_pdf.return_value = (
        (monolith_legal, monolith_audit) if audit else monolith_legal
    )
    monkeypatch.setattr("metesparser.pipeline.PDFProcessor", lambda **_kw: mock_processor)

    out = Pipeline(provider="openai", cache=False, audit=audit).run(Path("deed.pdf"))

    if audit:
        assert isinstance(out, tuple)
        closure_part, audit_part = out
        assert isinstance(audit_part, PkgAuditContext)
    else:
        assert not isinstance(out, tuple)
        closure_part = out

    if multi_tract:
        assert isinstance(closure_part, list)
        assert len(closure_part) == 2
        assert all(isinstance(r, PkgClosureResult) and r.is_fully_verified() for r in closure_part)
    else:
        assert isinstance(closure_part, PkgClosureResult)
        assert closure_part.is_fully_verified()


# ---------------------------------------------------------------------------
# 2. scripts/extract_sample_deeds.py
# ---------------------------------------------------------------------------


def test_extract_sample_deeds_uses_public_aggregate_is_boundary_and_logs_written_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """extract_sample_deeds.py must log written CSV paths and reject easement-only / exception-failing deeds."""
    mod = _load_script("extract_sample_deeds.py")
    out_dir = tmp_path / "extractions"
    sample_dir = tmp_path / "samples"
    sample_dir.mkdir()
    for name in ("multi.pdf", "easement_only.pdf", "exc_failing.pdf"):
        (sample_dir / name).write_bytes(b"%PDF")

    square = _square_monolith_calls()
    multi_ld = MonolithLegalDescription(
        source_doc="multi.pdf",
        calls=[],
        tracts=[
            MonolithTract(
                label="Tract 1",
                tract_type=MonolithTractType.MAIN,
                calls=square,
                role_basis="heading",
            ),
            MonolithTract(
                label="Tract 2",
                tract_type=MonolithTractType.ADDITION,
                calls=square,
                role_basis="heading",
            ),
        ],
    )
    easement_only_ld = MonolithLegalDescription(
        source_doc="easement_only.pdf",
        calls=[],
        tracts=[
            MonolithTract(
                label="Easement 1",
                tract_type=MonolithTractType.EASEMENT,
                calls=square,
                role_basis="heading",
            ),
        ],
    )
    exc_failing_ld = MonolithLegalDescription(
        source_doc="exc_failing.pdf",
        calls=[],
        tracts=[
            MonolithTract(
                label="Tract 1",
                tract_type=MonolithTractType.MAIN,
                calls=square,
                role_basis="heading",
            ),
            MonolithTract(
                label="Exception 1",
                tract_type=MonolithTractType.EXCEPTION,
                calls=square,
                role_basis="heading",
            ),
        ],
    )

    verified = _make_closure(closure_passed=True)
    main_unverified_closing = _make_closure(
        closure_passed=True,
        misclosure_ft=0.0001,
        warnings=["boundary requires review"],
    )
    exc_failed = _make_closure(closure_passed=False, misclosure_ft=12.5)

    deeds_by_name = {
        "multi.pdf": (multi_ld, [verified, verified]),
        "easement_only.pdf": (easement_only_ld, [verified]),
        "exc_failing.pdf": (exc_failing_ld, [main_unverified_closing, exc_failed]),
    }
    verified_export_docs: list[str] = []

    def fake_process_deed_pdf(path: str) -> MonolithLegalDescription:
        return deeds_by_name[Path(path).name][0]

    def fake_verify_closure(_calls: object, *, stated_area_sq_ft: float, tracts: object) -> object:
        assert tracts is not None
        for ld, results in deeds_by_name.values():
            if ld.tracts == tracts:
                return results
        raise AssertionError("Unexpected tracts")

    def fake_export_verified_csv(**kw: object) -> list[Path]:
        ld = kw["legal_desc"]
        assert isinstance(ld, MonolithLegalDescription)
        assert ld.source_doc is not None
        verified_export_docs.append(ld.source_doc)
        return [
            out_dir / "multi_tract_1_verified.csv",
            out_dir / "multi_tract_2_verified.csv",
        ]

    monkeypatch.setattr(mod, "OUTPUT_DIR", out_dir)
    monkeypatch.setattr(mod, "SAMPLE_DEEDS_DIR", sample_dir)
    monkeypatch.setattr(
        mod,
        "SAMPLE_PDFS",
        [
            ("multi.pdf", "multi"),
            ("easement_only.pdf", "easement_only"),
            ("exc_failing.pdf", "exc_failing"),
        ],
    )
    monkeypatch.setattr(
        mod,
        "PDFProcessor",
        lambda: SimpleNamespace(process_deed_pdf=fake_process_deed_pdf),
    )
    monkeypatch.setattr(mod.ClosureChecker, "verify_closure", staticmethod(fake_verify_closure))
    monkeypatch.setattr(
        mod.CSVBuilder,
        "legal_description_to_csv",
        staticmethod(lambda _ld, p: Path(p).write_text("csv", encoding="utf-8")),
    )
    monkeypatch.setattr(
        mod.CSVBuilder,
        "export_verified_csv",
        staticmethod(fake_export_verified_csv),
    )

    mod.main()
    out = capsys.readouterr().out
    assert "multi_tract_1_verified.csv" in out
    assert "multi_tract_2_verified.csv" in out
    assert "multi_verified.csv" not in out
    assert verified_export_docs == ["multi.pdf"]
    assert "✓ VERIFIED multi.pdf" in out
    assert "⚠ OPEN easement_only.pdf" in out
    assert "⚠ OPEN exc_failing.pdf" in out
    assert "✓ CLOSES easement_only.pdf" not in out
    assert "✓ CLOSES exc_failing.pdf" not in out

    easement_report = (out_dir / "easement_only_extraction_report.txt").read_text(encoding="utf-8")
    exc_report = (out_dir / "exc_failing_extraction_report.txt").read_text(encoding="utf-8")
    assert "✗ OPEN" in easement_report
    assert "✗ OPEN" in exc_report
    assert "12.5000 ft" in exc_report


# ---------------------------------------------------------------------------
# 3. src/metesparser/review_packet.py: _as_bool strictness & arc simplification
# ---------------------------------------------------------------------------


def test_review_packet_as_bool_matches_public_mp_models_coerce_bool_field() -> None:
    """_as_bool must match public mp_models.coerce_bool_field coercion and ValueError behavior."""
    for val, expected in (
        (True, True),
        (False, False),
        (None, False),
        (1, True),
        (0, False),
        (1.0, True),
        (0.0, False),
        ("true", True),
        (" 1 ", True),
        ("YES", True),
        ("y", True),
        ("on", True),
        ("false", False),
        ("0", False),
        ("NO", False),
        ("n", False),
        ("off", False),
        ("", False),
    ):
        assert _as_bool(val) is expected
        assert _as_bool(val) is coerce_bool_field(val)

    with pytest.raises(ValueError, match="Invalid boolean value: 'maybe'"):
        _as_bool("maybe")
    with pytest.raises(ValueError):
        coerce_bool_field("maybe")


@pytest.mark.parametrize("bad_val", ["unknown", "maybe", "N/A", "2", 2, -1])
def test_review_packet_as_bool_rejects_unrecognized_values(bad_val: object) -> None:
    """_as_bool must raise ValueError instead of falling through to bool(value)."""
    with pytest.raises(ValueError, match="Invalid boolean value"):
        _as_bool(bad_val)


@pytest.mark.parametrize("flag_field", ["is_tie_in", "is_exception", "non_tangent"])
def test_generate_traverse_plot_records_invalid_boolean_as_invalid_course(flag_field: str) -> None:
    """Unrecognized boolean strings must flag course as invalid instead of dropping it silently."""
    gt = {
        "expected_calls": [
            {
                "course": 1,
                "direction_text": "N 0° E 100 ft",
                "bearing_azimuth_deg_from_north": 0.0,
                "distance_ft": 100.0,
                flag_field: "maybe",
            },
            {
                "course": 2,
                "direction_text": "N 90° E 100 ft",
                "bearing_azimuth_deg_from_north": 90.0,
                "distance_ft": 100.0,
            },
        ]
    }
    html = generate_traverse_plot(gt)
    assert "<svg" not in html
    assert "Incomplete traverse plot" in html
    assert "1" in html


def test_generate_traverse_plot_single_call_with_invalid_tie_in_reports_incomplete() -> None:
    """A sole course with invalid boolean must report incomplete course, not 'No plottable calls'."""
    gt = {
        "expected_calls": [
            {
                "course": 3,
                "direction_text": "N 0° E 100 ft",
                "bearing_azimuth_deg_from_north": 0.0,
                "distance_ft": 100.0,
                "is_tie_in": "unknown",
            }
        ]
    }
    html = generate_traverse_plot(gt)
    assert "Incomplete traverse plot" in html
    assert "3" in html


def test_generate_traverse_plot_renders_non_split_major_and_minor_arcs() -> None:
    """Regression check for Simplification A2: minor/major arcs keep valid SVG path and signed viewBox bounds."""
    for curve_dir, delta, expected_large, expected_sweep, bounds in (
        ("right", 90.0, 0, 1, (0.0, 50.0, -50.0, 0.0)),
        ("left", 270.0, 1, 0, (-100.0, 0.0, -50.0, 50.0)),
        ("right", 270.0, 1, 1, (0.0, 100.0, -50.0, 50.0)),
    ):
        radius = 50.0
        arc_len = radius * math.radians(delta)
        gt = {
            "expected_calls": [
                {
                    "course": 1,
                    "direction_text": f"curve {curve_dir} R={radius} delta={delta}",
                    "bearing_azimuth_deg_from_north": 0.0,
                    "distance_ft": arc_len,
                    "curve_dir": curve_dir,
                    "radius_ft": radius,
                    "delta_deg": delta,
                    "arc_length_ft": arc_len,
                }
            ]
        }
        svg = generate_traverse_plot(gt)
        assert "<svg" in svg
        assert f"A 50.00,50.00 0 {expected_large},{expected_sweep}" in svg
        vb_match = re.search(r"viewBox='([^']+)'", svg)
        assert vb_match is not None
        vb_x, vb_y, vb_w, vb_h = (float(v) for v in vb_match.group(1).split())
        exp_min_x, exp_max_x, exp_min_y, exp_max_y = bounds
        assert vb_x <= exp_min_x
        assert vb_x + vb_w >= exp_max_x
        assert vb_y <= exp_min_y
        assert vb_y + vb_h >= exp_max_y


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    [
        ("radius_ft", -10.0),
        ("radius_ft", True),
        ("delta_deg", 400.0),
    ],
)
def test_generate_traverse_plot_handles_invalid_curve_deed_call_values(
    field_name: str, bad_value: object
) -> None:
    """Invalid curve fields must be caught and reported as Incomplete traverse plot instead of raising."""
    curve_call: dict[str, Any] = {
        "course": 2,
        "direction_text": "curve right R=50 delta=90",
        "bearing_azimuth_deg_from_north": 0.0,
        "distance_ft": 78.54,
        "curve_dir": "right",
        "radius_ft": 50.0,
        "delta_deg": 90.0,
        "arc_length_ft": 78.54,
    }
    curve_call[field_name] = bad_value
    gt = {
        "expected_calls": [
            {
                "course": 1,
                "direction_text": "N 0° E 100 ft",
                "bearing_azimuth_deg_from_north": 0.0,
                "distance_ft": 100.0,
            },
            curve_call,
        ]
    }
    html = generate_traverse_plot(gt)
    assert "<svg" not in html
    assert "Incomplete traverse plot" in html
    assert "course(s) 2." in html


def test_generate_traverse_plot_split_arc_without_entry_azimuth_reports_incomplete() -> None:
    """A standalone split-arc curve with no bearing/radial/chord cannot determine entry tangent."""
    from mp_models import DeedCall as PkgDeedCall
    from mp_verify.tangents import entry_azimuth

    radius = 50.0
    arc_len = 2.0 * math.pi * radius
    call_data: dict[str, Any] = {
        "course": 1,
        "direction_text": "full circle curve right R=50 delta=360",
        "bearing_azimuth_deg_from_north": None,
        "distance_ft": arc_len,
        "curve_dir": "right",
        "radius_ft": radius,
        "delta_deg": 360.0,
        "arc_length_ft": arc_len,
        "radial_bearing": None,
        "chord_bearing": None,
    }
    assert (
        entry_azimuth(
            PkgDeedCall(
                course=1,
                direction_text=call_data["direction_text"],
                distance_ft=arc_len,
                curve_dir="right",
                radius_ft=radius,
                delta_deg=360.0,
                arc_length_ft=arc_len,
            )
        )
        is None
    )

    html = generate_traverse_plot({"expected_calls": [call_data]})
    assert "<svg" not in html
    assert "Incomplete traverse plot" in html
    assert "course(s) 1." in html


@pytest.mark.parametrize("delta", [360.0, 359.98])
def test_generate_traverse_plot_split_arc_guard_records_none_entry_azimuth_as_invalid(
    monkeypatch: pytest.MonkeyPatch, delta: float
) -> None:
    """Split-arc branch must record the course as invalid when entry_azimuth returns None."""
    radius = 50.0
    arc_len = radius * math.radians(delta)
    gt = {
        "expected_calls": [
            {
                "course": 4,
                "direction_text": f"split-arc curve right R={radius} delta={delta}",
                "bearing_azimuth_deg_from_north": 0.0,
                "distance_ft": arc_len,
                "curve_dir": "right",
                "radius_ft": radius,
                "delta_deg": delta,
                "arc_length_ft": arc_len,
            }
        ]
    }
    called: list[object] = []

    def _none_entry_azimuth(call: object) -> None:
        called.append(call)
        return None

    monkeypatch.setattr("mp_verify.tangents.entry_azimuth", _none_entry_azimuth)

    html = generate_traverse_plot(gt)
    assert len(called) == 1
    assert "<svg" not in html
    assert "Incomplete traverse plot" in html
    assert "course(s) 4." in html


# ---------------------------------------------------------------------------
# 4. scripts/build_claude_plugin.py: PEP-427/PEP-440 wheel check & UTF-8
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_wheel",
    [
        "mp_models-1.0.0-py3-none.whl",  # only 4 components
        "mp_models-1.0.0-1-2-py3-none-any.whl",  # 7 components
        "mp_models-..-py3-none-any.whl",  # non-PEP-440 version
        "mp_models-1.0.0.whl-py3-none-any.whl",  # non-PEP-440 version
        "mp_models-notaversion-py3-none-any.whl",  # non-PEP-440 version
        "mp_models-1.0.0--none-any.whl",  # empty py tag
        "mp_models-1.0.0-py3--any.whl",  # empty abi tag
        "mp_models-1.0.0-py3-none-.whl",  # empty plat tag
        "mp_models-1.0.0-abc-py3-none-any.whl",  # build tag must start with digit
        "mp_models-1.0.0-py3-none-any+bad.whl",  # '+' not allowed in platform tag
    ],
)
def test_build_claude_plugin_enforces_pep427_and_pep440_wheel_names(bad_wheel: str) -> None:
    builder = _load_script("build_claude_plugin.py")
    with pytest.raises(ValueError, match="Unexpected wheel filename"):
        builder.runtime_project([Path(bad_wheel)])


def _workspace_wheels(builder: Any, overrides: dict[str, str] | None = None) -> list[Path]:
    overrides = overrides or {}
    return [
        Path(overrides.get(pkg, f"{pkg.replace('-', '_')}-1.0.0-py3-none-any.whl"))
        for pkg in builder.PACKAGES
    ]


@pytest.mark.parametrize(
    ("wheel_name", "expected_version"),
    [
        ("mp_models-1.0.0-1build-py3-none-any.whl", "1.0.0"),
        ("mp_models-1.0.0rc1-py3-none-any.whl", "1.0.0rc1"),
        ("mp_models-1.0.0.post1-py3-none-any.whl", "1.0.0.post1"),
        ("mp_models-1.0.0+local.1-py3-none-any.whl", "1.0.0+local.1"),
    ],
)
def test_build_claude_plugin_accepts_valid_pep427_wheels(
    wheel_name: str, expected_version: str
) -> None:
    import tomllib

    builder = _load_script("build_claude_plugin.py")
    wheels = _workspace_wheels(builder, {"mp-models": wheel_name})
    project = tomllib.loads(builder.runtime_project(wheels))
    assert f"mp-models=={expected_version}" in project["project"]["dependencies"]


def test_build_claude_plugin_rejects_missing_workspace_wheel() -> None:
    builder = _load_script("build_claude_plugin.py")
    partial_wheels = _workspace_wheels(builder)[:-1]
    with pytest.raises(ValueError, match="Missing workspace wheel"):
        builder.runtime_project(partial_wheels)


def test_build_claude_plugin_rejects_empty_wheels_when_require_all_wheels() -> None:
    builder = _load_script("build_claude_plugin.py")
    with pytest.raises(ValueError, match="Missing workspace wheel"):
        builder.runtime_project([], require_all_wheels=True)


@pytest.mark.parametrize("emit_count", [0, 5])
def test_build_claude_plugin_build_rejects_missing_wheels_before_locking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, emit_count: int
) -> None:
    builder = _load_script("build_claude_plugin.py")
    monkeypatch.setattr(builder.shutil, "which", lambda _name: "/fake/uv")
    built = 0
    lock_called = False

    def fake_run(arguments: list[str], *, cwd: Path) -> None:
        nonlocal built, lock_called
        if arguments[1] == "build":
            if built < emit_count:
                output_dir = Path(arguments[arguments.index("--out-dir") + 1])
                package = arguments[arguments.index("--package") + 1]
                (output_dir / f"{package.replace('-', '_')}-1.0.0-py3-none-any.whl").write_bytes(
                    b"wheel"
                )
            built += 1
        elif arguments[1] == "lock":
            lock_called = True

    monkeypatch.setattr(builder, "run", fake_run)
    with pytest.raises(ValueError, match="Missing workspace wheel"):
        builder.build(tmp_path / "plugin.zip")
    assert not lock_called
    assert not (tmp_path / "plugin.zip").exists()


@pytest.mark.parametrize(
    "extra_wheel",
    [
        "pyproj-3.7.0-cp311-cp311-manylinux_2_17_x86_64.whl",
        "mp_ocr-1.0.0-py3-none-any.whl",
    ],
)
def test_build_claude_plugin_rejects_unexpected_external_wheel(extra_wheel: str) -> None:
    builder = _load_script("build_claude_plugin.py")
    wheels = [*_workspace_wheels(builder), Path(extra_wheel)]
    with pytest.raises(ValueError, match="Unexpected wheel package"):
        builder.runtime_project(wheels)


def test_build_claude_plugin_passes_utf8_encoding_to_all_read_and_write_text() -> None:
    source = (REPO_ROOT / "scripts" / "build_claude_plugin.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in ("read_text", "write_text")
    ]
    assert calls, "Expected read_text/write_text calls in build_claude_plugin.py"
    for call in calls:
        encoding_kw = next((kw for kw in call.keywords if kw.arg == "encoding"), None)
        assert encoding_kw is not None, f"Missing encoding= on line {call.lineno}"
        assert isinstance(encoding_kw.value, ast.Constant) and encoding_kw.value.value == "utf-8"


# ---------------------------------------------------------------------------
# 5. scripts/parse_pdfs_to_md.sh: option/missing/case/dup/dash/partial-rc tests
# ---------------------------------------------------------------------------


def _setup_parse_script_env(
    tmp_path: Path, fake_parse_body: str
) -> tuple[Path, Path, Path, dict[str, str]]:
    repo_root = tmp_path / "repo"
    scripts_dir = repo_root / "scripts"
    sample_dir = repo_root / "sample_deeds"
    scripts_dir.mkdir(parents=True)
    sample_dir.mkdir(parents=True)

    script_copy = scripts_dir / "parse_pdfs_to_md.sh"
    script_copy.write_text(
        (REPO_ROOT / "scripts" / "parse_pdfs_to_md.sh").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    os.chmod(script_copy, 0o755)

    fake_home = tmp_path / "home"
    parse_cache = fake_home / ".parse"
    parse_cache.mkdir(parents=True)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in (
        "bash",
        "dirname",
        "basename",
        "mktemp",
        "rm",
        "cat",
        "find",
        "sort",
        "cp",
        "tr",
        "python3",
    ):
        resolved = shutil.which(tool)
        if resolved:
            (bin_dir / tool).symlink_to(resolved)

    fake_parse = bin_dir / "parse"
    fake_parse.write_text(
        "#!/usr/bin/env bash\n" + fake_parse_body.replace("__PARSE_CACHE__", str(parse_cache)),
        encoding="utf-8",
    )
    os.chmod(fake_parse, 0o755)

    env = {
        "PATH": str(bin_dir),
        "HOME": str(fake_home),
        "LLAMA_CLOUD_API_KEY": "test-key",
    }
    return script_copy, sample_dir, parse_cache, env


def test_parse_pdfs_rejects_unrecognized_flag(tmp_path: Path) -> None:
    script, _, _, env = _setup_parse_script_env(tmp_path, "exit 0\n")
    proc = subprocess.run(
        ["bash", str(script), "--bad-flag"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
    assert "--bad-flag" in proc.stderr


def test_parse_pdfs_missing_explicit_file_exits_nonzero_without_misleading_message(
    tmp_path: Path,
) -> None:
    script, _, _, env = _setup_parse_script_env(tmp_path, "exit 0\n")
    proc = subprocess.run(
        ["bash", str(script), "does_not_exist.pdf"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "All sample deeds already have .md files" not in proc.stdout
    assert "does_not_exist.pdf" in proc.stderr


def test_parse_pdfs_uppercase_pdf_extension_produces_clean_md(tmp_path: Path) -> None:
    script, sample_dir, _, env = _setup_parse_script_env(
        tmp_path,
        'printf "parsed upper\\n" > "__PARSE_CACHE__/UPPER_DEED.PDF.md"\nexit 0\n',
    )
    upper_pdf = sample_dir / "UPPER_DEED.PDF"
    upper_pdf.write_bytes(b"%PDF")

    proc = subprocess.run(
        ["bash", str(script), str(upper_pdf)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert (sample_dir / "UPPER_DEED.md").read_text(encoding="utf-8") == "parsed upper\n"
    assert not (sample_dir / "UPPER_DEED.PDF.md").exists()


def test_parse_pdfs_detects_duplicate_basenames_before_invoking_parse(tmp_path: Path) -> None:
    invoked_marker = tmp_path / "parse_was_invoked"
    script, _, _, env = _setup_parse_script_env(
        tmp_path,
        f'printf "invoked\\n" > "{invoked_marker}"\nexit 0\n',
    )
    dir_a = tmp_path / "dir_a"
    dir_b = tmp_path / "dir_b"
    dir_a.mkdir()
    dir_b.mkdir()
    pdf_a = dir_a / "same.pdf"
    pdf_b = dir_b / "same.pdf"
    pdf_a.write_bytes(b"%PDF")
    pdf_b.write_bytes(b"%PDF")

    proc = subprocess.run(
        ["bash", str(script), str(pdf_a), str(pdf_b)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "same.pdf" in proc.stderr
    assert not invoked_marker.exists()


def test_parse_pdfs_handles_leading_dash_filename_with_double_dash(tmp_path: Path) -> None:
    script, sample_dir, _, env = _setup_parse_script_env(
        tmp_path,
        'printf "dash ok\\n" > "__PARSE_CACHE__/-dash.pdf.md"\nexit 0\n',
    )
    dash_pdf = sample_dir / "-dash.pdf"
    dash_pdf.write_bytes(b"%PDF")

    proc = subprocess.run(
        ["bash", str(script), "--force", "--", "-dash.pdf"],
        cwd=sample_dir,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert (sample_dir / "-dash.md").read_text(encoding="utf-8") == "dash ok\n"


def test_parse_pdfs_copies_partial_successes_when_parse_exits_nonzero(tmp_path: Path) -> None:
    script, sample_dir, _, env = _setup_parse_script_env(
        tmp_path,
        'printf "ok content\\n" > "__PARSE_CACHE__/ok.pdf.md"\nexit 2\n',
    )
    pdf_ok = sample_dir / "ok.pdf"
    pdf_fail = sample_dir / "fail.pdf"
    pdf_ok.write_bytes(b"%PDF")
    pdf_fail.write_bytes(b"%PDF")

    proc = subprocess.run(
        ["bash", str(script), str(pdf_ok), str(pdf_fail)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert (sample_dir / "ok.md").read_text(encoding="utf-8") == "ok content\n"
    assert not (sample_dir / "fail.md").exists()
    assert "Done: 1 parsed, 1 failed." in proc.stdout


def test_parse_pdfs_exits_nonzero_when_parse_fails_even_if_all_outputs_exist(
    tmp_path: Path,
) -> None:
    script, sample_dir, _, env = _setup_parse_script_env(
        tmp_path,
        'printf "ok content\\n" > "__PARSE_CACHE__/ok.pdf.md"\nexit 3\n',
    )
    pdf_ok = sample_dir / "ok.pdf"
    pdf_ok.write_bytes(b"%PDF")

    proc = subprocess.run(
        ["bash", str(script), str(pdf_ok)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert (sample_dir / "ok.md").read_text(encoding="utf-8") == "ok content\n"


def test_parse_pdfs_missing_arg_alongside_valid_exits_before_invoking_parse(
    tmp_path: Path,
) -> None:
    invoked_marker = tmp_path / "parse_was_invoked"
    script, sample_dir, _, env = _setup_parse_script_env(
        tmp_path,
        f'printf "invoked\\n" > "{invoked_marker}"\n'
        'printf "good md\\n" > "__PARSE_CACHE__/good.pdf.md"\nexit 0\n',
    )
    good_pdf = sample_dir / "good.pdf"
    good_pdf.write_bytes(b"%PDF")

    proc = subprocess.run(
        ["bash", str(script), str(good_pdf), "missing.pdf"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
    assert "missing.pdf" in proc.stderr
    assert not invoked_marker.exists()
    assert not (sample_dir / "good.md").exists()


def test_parse_pdfs_clears_stale_cache_before_parse_without_force(tmp_path: Path) -> None:
    script, sample_dir, parse_cache, env = _setup_parse_script_env(
        tmp_path,
        "exit 2\n",
    )
    deed_pdf = sample_dir / "deed.pdf"
    deed_pdf.write_bytes(b"%PDF")
    deed_md = sample_dir / "deed.md"
    deed_md.write_text("original md\n", encoding="utf-8")
    stale_cache = parse_cache / "deed.pdf.md"
    stale_cache.write_text("stale cached md\n", encoding="utf-8")

    proc = subprocess.run(
        ["bash", str(script), str(deed_pdf)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
    assert deed_md.read_text(encoding="utf-8") == "original md\n"
    assert not stale_cache.exists()
    assert "Done: 0 parsed, 1 failed." in proc.stdout


def test_parse_pdfs_no_arg_discovery_uppercase_pdf_creates_and_skips_second_run(
    tmp_path: Path,
) -> None:
    invocations = tmp_path / "invocations.log"
    script, sample_dir, _, env = _setup_parse_script_env(
        tmp_path,
        f'printf "run\\n" >> "{invocations}"\n'
        'printf "parsed upper\\n" > "__PARSE_CACHE__/UPPER_DEED.PDF.md"\nexit 0\n',
    )
    upper_pdf = sample_dir / "UPPER_DEED.PDF"
    upper_pdf.write_bytes(b"%PDF")

    first = subprocess.run(
        ["bash", str(script)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert first.returncode == 0, first.stderr
    assert (sample_dir / "UPPER_DEED.md").read_text(encoding="utf-8") == "parsed upper\n"
    assert not (sample_dir / "UPPER_DEED.PDF.md").exists()
    assert invocations.read_text(encoding="utf-8").splitlines() == ["run"]

    second = subprocess.run(
        ["bash", str(script)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert second.returncode == 0, second.stderr
    assert "No PDFs to process." in second.stdout
    assert invocations.read_text(encoding="utf-8").splitlines() == ["run"]


def test_parse_pdfs_rejects_case_insensitive_cache_collision_across_dirs(tmp_path: Path) -> None:
    invoked_marker = tmp_path / "parse_was_invoked"
    script, _, _, env = _setup_parse_script_env(
        tmp_path,
        f'printf "invoked\\n" > "{invoked_marker}"\nexit 0\n',
    )
    dir_a = tmp_path / "d1"
    dir_b = tmp_path / "d2"
    dir_a.mkdir()
    dir_b.mkdir()
    pdf_a = dir_a / "deed.pdf"
    pdf_b = dir_b / "deed.PDF"
    pdf_a.write_bytes(b"%PDF")
    pdf_b.write_bytes(b"%PDF")

    proc = subprocess.run(
        ["bash", str(script), str(pdf_a), str(pdf_b)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
    assert "deed.PDF" in proc.stderr
    assert not invoked_marker.exists()


def test_parse_pdfs_rejects_same_dir_output_path_collisions(tmp_path: Path) -> None:
    invoked_marker = tmp_path / "parse_was_invoked"
    script, sample_dir, _, env = _setup_parse_script_env(
        tmp_path,
        f'printf "invoked\\n" > "{invoked_marker}"\nexit 0\n',
    )
    pdf_lower = sample_dir / "deed.pdf"
    pdf_no_ext = sample_dir / "deed"
    pdf_lower.write_bytes(b"%PDF")
    pdf_no_ext.write_bytes(b"%PDF")

    # 1. Same-dir `deed` + `deed.pdf` collide on target_md (`deed.md`) despite different basenames
    proc_no_ext = subprocess.run(
        ["bash", str(script), str(pdf_no_ext), str(pdf_lower)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_no_ext.returncode == 1
    assert "deed.md" in proc_no_ext.stderr
    assert not invoked_marker.exists()

    # 2. Same-dir `deed.pdf` + `deed.PDF` (on case-sensitive OR case-insensitive FS) collide
    pdf_upper = sample_dir / "deed.PDF"
    if not pdf_upper.exists():
        pdf_upper.write_bytes(b"%PDF")
    proc_case = subprocess.run(
        ["bash", str(script), str(pdf_lower), str(pdf_upper)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_case.returncode == 1
    assert not invoked_marker.exists()

    # 3. Symlinked parent directory alias for `deed` + `deed.pdf` resolves canonical dir and collides
    sym_dir = tmp_path / "sample_symlink"
    sym_dir.symlink_to(sample_dir)
    proc_symlink = subprocess.run(
        ["bash", str(script), str(pdf_no_ext), str(sym_dir / "deed.pdf")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_symlink.returncode == 1
    assert "deed.md" in proc_symlink.stderr
    assert not invoked_marker.exists()


def test_parse_pdfs_cleans_up_temp_config_on_sigint_during_parse(tmp_path: Path) -> None:
    cfg_path_file = tmp_path / "cfg_path.txt"
    ready_marker = tmp_path / "parse_ready"
    isolated_tmp = tmp_path / "tmp"
    isolated_tmp.mkdir()
    script, sample_dir, _, env = _setup_parse_script_env(
        tmp_path,
        'cfg=""\n'
        "while [ $# -gt 0 ]; do\n"
        '  if [ "$1" = "-c" ]; then cfg="$2"; shift 2; continue; fi\n'
        "  shift\n"
        "done\n"
        f'printf "%s" "$cfg" > "{cfg_path_file}"\n'
        f'printf "ready\\n" > "{ready_marker}"\n'
        'exec python3 -c "import signal, time; signal.signal(signal.SIGINT, signal.SIG_DFL); time.sleep(30)"\n',
    )
    env["TMPDIR"] = str(isolated_tmp)
    deed_pdf = sample_dir / "deed.pdf"
    deed_pdf.write_bytes(b"%PDF")

    proc = subprocess.Popen(
        ["bash", str(script), str(deed_pdf)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 5.0
        while not ready_marker.exists():
            if proc.poll() is not None:
                stdout, stderr = proc.communicate(timeout=2)
                pytest.fail(
                    f"parse_pdfs_to_md.sh exited early ({proc.returncode}): {stdout} {stderr}"
                )
            if time.monotonic() > deadline:
                pytest.fail("Timed out waiting for fake parse to start")
            time.sleep(0.02)

        temp_cfg = Path(cfg_path_file.read_text(encoding="utf-8"))
        assert temp_cfg.exists(), "Temp config should exist while parse is running"

        os.killpg(proc.pid, signal.SIGINT)
        proc.communicate(timeout=5)
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate(timeout=2)

    assert not temp_cfg.exists(), "SIGINT trap must remove temp config file holding API key"
    assert list(isolated_tmp.iterdir()) == []
    assert proc.returncode == 130


@pytest.mark.parametrize("bad_api_key", [None, "", "   ", 123, True])
def test_parse_pdfs_rejects_null_blank_or_non_string_semtools_api_key(
    tmp_path: Path, bad_api_key: object
) -> None:
    invoked_marker = tmp_path / "parse_was_invoked"
    script, sample_dir, _, env = _setup_parse_script_env(
        tmp_path,
        f'printf "invoked\\n" > "{invoked_marker}"\nexit 0\n',
    )
    env.pop("LLAMA_CLOUD_API_KEY", None)
    fake_home = Path(env["HOME"])
    (fake_home / ".semtools_config.json").write_text(
        json.dumps({"parse": {"api_key": bad_api_key}}),
        encoding="utf-8",
    )
    deed_pdf = sample_dir / "deed.pdf"
    deed_pdf.write_bytes(b"%PDF")

    proc = subprocess.run(
        ["bash", str(script), str(deed_pdf)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
    assert "Error: No API key found" in proc.stderr
    assert not invoked_marker.exists()


# ---------------------------------------------------------------------------
# 6. .env.example cleanup
# ---------------------------------------------------------------------------


def test_env_example_omits_unused_anthropic_key_and_keeps_active_vars() -> None:
    content = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "ANTHROPIC_API_KEY" not in content
    for var in (
        "OPENAI_API_KEY=",
        "GEMINI_API_KEY=",
        "METESPARSER_LLM_PROVIDER=",
        "METESPARSER_LOG_LEVEL=",
        "METESPARSER_LOG_FORMAT=",
    ):
        assert var in content


# ---------------------------------------------------------------------------
# 7. scripts/backfill_run_registry.py: FAIL/WARN/PASS status parity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dry_run", [True, False])
@pytest.mark.parametrize(
    ("deed_stem", "closure_passed", "warnings", "expected_status"),
    [
        ("passing_warn", True, ["Stated area differs by 12%"], "WARN"),
        ("passing_clean", True, [], "PASS"),
        ("failing_clean", False, [], "FAIL"),
        ("failing_warn", False, ["Closure error exceeds tolerance"], "FAIL"),
    ],
)
def test_backfill_run_registry_prints_fail_warn_pass_status_consistently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    dry_run: bool,
    deed_stem: str,
    closure_passed: bool,
    warnings: list[str],
    expected_status: str,
) -> None:
    """backfill_run_registry must print FAIL/WARN/PASS consistently with run_registry.py."""
    mod = _load_script("backfill_run_registry.py")
    sample_dir = tmp_path / "sample_deeds"
    sample_dir.mkdir()
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    runs_dir = tmp_path / "runs"
    (sample_dir / f"{deed_stem}.ground_truth.json").write_text(
        json.dumps(
            {
                "expected_calls": [
                    {
                        "course": 1,
                        "direction_text": "N 0° E",
                        "bearing_azimuth_deg_from_north": 0.0,
                        "distance_ft": 100.0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    closure = _make_closure(
        closure_passed=closure_passed,
        misclosure_ft=0.0 if closure_passed else 2.5,
        warnings=warnings,
    )
    monkeypatch.setattr(mod, "SAMPLE_DEEDS_DIR", sample_dir)
    monkeypatch.setattr(mod, "PROMPTS_DIR", prompts_dir)
    monkeypatch.setattr(
        mod.ClosureChecker,
        "verify_closure",
        staticmethod(lambda _calls, **_kw: closure),
    )

    written = mod.backfill(runs_dir, dry_run=dry_run)
    assert written == 1

    out = capsys.readouterr().out
    prefix = "DRY RUN:" if dry_run else "WROTE:"
    status_lines = [line.strip() for line in out.splitlines() if prefix in line]
    assert len(status_lines) == 1
    assert status_lines[0].endswith(f", {expected_status}")
    for other_status in {"PASS", "WARN", "FAIL"} - {expected_status}:
        assert not status_lines[0].endswith(f", {other_status}")

    if not dry_run:
        manifests = list(runs_dir.glob("*.json"))
        assert len(manifests) == 1
        loaded = RunManifest.model_validate_json(manifests[0].read_text(encoding="utf-8"))
        table = format_comparison_table([loaded])
        assert table.splitlines()[-1].strip().endswith(expected_status)
