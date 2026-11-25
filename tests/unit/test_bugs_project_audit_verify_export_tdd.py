"""Regression tests for verification, export, and audit report bugs (Red-Green TDD)."""

from __future__ import annotations

import math
import tomllib
from datetime import UTC, datetime
from pathlib import Path

import mp_verify.checks as mp_checks
import pytest
from mp_export import calls_to_csv, csv_to_calls, export_verified_csv
from mp_export.audit_html import generate_html, write_report
from mp_models import (
    AuditContext as PkgAuditContext,
)
from mp_models import (
    ClosureResult as PkgClosureResult,
)
from mp_models import (
    DeedCall as PkgDeedCall,
)
from mp_models import (
    ExtractionRecord as PkgExtractionRecord,
)
from mp_models import (
    RunMetadata as PkgRunMetadata,
)
from mp_models import (
    Tract as PkgTract,
)
from mp_models import (
    TractType as PkgTractType,
)
from mp_verify import verify_closure as pkg_verify_closure
from mp_verify.closure import compute_traverse as pkg_compute_traverse

from metesparser.audit_reporter import AuditReporter
from metesparser.closure_checker import ClosureChecker
from metesparser.csv_builder import CSVBuilder
from metesparser.models import (
    AuditContext,
    ClosureResult,
    DeedCall,
    ExtractionRecord,
    RunMetadata,
    Tract,
    TractType,
)


def _square(call_cls, size: float = 100.0):
    return [
        call_cls(
            course=i + 1,
            direction_text=f"course {i + 1}",
            bearing_azimuth_deg_from_north=az,
            distance_ft=size,
        )
        for i, az in enumerate((0.0, 90.0, 180.0, 270.0))
    ]


def _make_audit_ctx(audit_cls, run_cls):
    return audit_cls(
        run_metadata=run_cls(
            parser_version="0.5.0",
            llm_provider="test",
            llm_model="test-model",
            prompt_hash="abc",
            timestamp_utc=datetime(2026, 1, 1, tzinfo=UTC),
            source_pdf="deed.pdf",
            cache_enabled=False,
        )
    )


@pytest.fixture(params=["package", "monolith"])
def verify_api(request):
    if request.param == "package":
        return (
            PkgDeedCall,
            PkgAuditContext,
            PkgRunMetadata,
            pkg_verify_closure,
            pkg_compute_traverse,
            mp_checks.compare_double_entry,
        )
    return (
        DeedCall,
        AuditContext,
        RunMetadata,
        ClosureChecker.verify_closure,
        ClosureChecker.compute_traverse,
        ClosureChecker.compare_double_entry,
    )


@pytest.fixture(params=["package", "monolith"])
def export_api(request):
    if request.param == "package":
        return (
            PkgDeedCall,
            PkgClosureResult,
            PkgTract,
            PkgTractType,
            PkgAuditContext,
            PkgRunMetadata,
            PkgExtractionRecord,
            pkg_verify_closure,
            calls_to_csv,
            csv_to_calls,
            export_verified_csv,
            generate_html,
            write_report,
        )
    return (
        DeedCall,
        ClosureResult,
        Tract,
        TractType,
        AuditContext,
        RunMetadata,
        ExtractionRecord,
        ClosureChecker.verify_closure,
        CSVBuilder.calls_to_csv,
        CSVBuilder.csv_to_calls,
        CSVBuilder.export_verified_csv,
        AuditReporter.generate_html,
        AuditReporter.write_report,
    )


# ---------------------------------------------------------------------------
# V1: Inverted interior_angles audit detail
# ---------------------------------------------------------------------------


def test_v1_interior_angles_detail_skipped_when_fewer_than_3_courses(verify_api):
    call_cls, audit_cls, run_cls, verify_fn, _, _ = verify_api
    calls = _square(call_cls)[:2]
    ctx = _make_audit_ctx(audit_cls, run_cls)
    verify_fn(calls, audit_context=ctx)
    check = next(c for c in ctx.verification_audit.checks if c.name == "interior_angles")
    assert check.passed is True
    assert check.detail == "skipped (curves present, incomplete bearings, or fewer than 3 courses)"


def test_v1_interior_angles_detail_skipped_when_curves_present(verify_api):
    call_cls, audit_cls, run_cls, verify_fn, _, _ = verify_api
    calls = [
        call_cls(
            course=1,
            direction_text="curve",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=100.0,
            curve_dir="right",
            radius_ft=100.0,
            delta_deg=90.0,
            arc_length_ft=100.0 * math.pi / 2,
        ),
        *_square(call_cls)[1:],
    ]
    ctx = _make_audit_ctx(audit_cls, run_cls)
    verify_fn(calls, audit_context=ctx)
    check = next(c for c in ctx.verification_audit.checks if c.name == "interior_angles")
    assert check.passed is True
    assert check.detail == "skipped (curves present, incomplete bearings, or fewer than 3 courses)"


def test_v1_interior_angles_detail_failed_when_straight_polygon_angles_fail(verify_api):
    call_cls, audit_cls, run_cls, verify_fn, _, _ = verify_api
    # 3 straight courses with zero turn between each (sum of deflections = 0 != +-360)
    calls = [
        call_cls(
            course=i + 1,
            direction_text="straight",
            bearing_azimuth_deg_from_north=az,
            distance_ft=100.0,
        )
        for i, az in enumerate((0.0, 0.0, 0.0))
    ]
    ctx = _make_audit_ctx(audit_cls, run_cls)
    result = verify_fn(calls, audit_context=ctx)
    assert result.angle_check_passed is False
    check = next(c for c in ctx.verification_audit.checks if c.name == "interior_angles")
    assert check.passed is False
    assert check.detail == "interior angle sum failed"


def test_v1_interior_angles_detail_passed_for_valid_polygon(verify_api):
    call_cls, audit_cls, run_cls, verify_fn, _, _ = verify_api
    calls = _square(call_cls)
    ctx = _make_audit_ctx(audit_cls, run_cls)
    verify_fn(calls, audit_context=ctx)
    check = next(c for c in ctx.verification_audit.checks if c.name == "interior_angles")
    assert check.passed is True
    assert check.detail == "all-straight polygon angles sum correctly"


# ---------------------------------------------------------------------------
# V2: compute_traverse crash on arc_length_ft > 2*pi*radius_ft & negative chord
# ---------------------------------------------------------------------------


def test_v2_compute_traverse_and_verify_handle_arc_exceeding_full_circle(verify_api):
    call_cls, _, _, verify_fn, compute_traverse_fn, _ = verify_api
    # arc = 700 > 2*pi*100 (~628.32), delta_deg is None -> implied delta > 360
    curve = call_cls(
        course=1,
        direction_text="curve",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=50.0,
        curve_dir="right",
        radius_ft=100.0,
        arc_length_ft=700.0,
    )
    points = compute_traverse_fn([curve])
    assert len(points) == 2
    assert points[1].y == pytest.approx(50.0)

    result = verify_fn([curve, *_square(call_cls)[1:]])
    assert result.curve_consistency_passed is False


def test_v2_compute_traverse_with_chord_bearing_avoids_negative_chord_on_overfull_arc(verify_api):
    call_cls, _, _, verify_fn, compute_traverse_fn, _ = verify_api
    curve = call_cls(
        course=1,
        direction_text="curve",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=50.0,
        curve_dir="right",
        radius_ft=100.0,
        arc_length_ft=700.0,
        chord_bearing="N 00°00' E",
    )
    points = compute_traverse_fn([curve])
    # Falls back to straight line (0 deg, 50 ft) -> y = +50.0 instead of negative chord
    assert points[1].y == pytest.approx(50.0)

    result = verify_fn([curve])
    assert result.curve_consistency_passed is False


# ---------------------------------------------------------------------------
# V3: check_curve_consistency early return in mp_verify.checks
# ---------------------------------------------------------------------------


def test_v3_check_curve_consistency_collects_all_curves_and_both_arc_and_chord():
    c1 = PkgDeedCall(
        course=1,
        direction_text="curve 1",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=100.0,
        curve_dir="right",
        radius_ft=100.0,
        delta_deg=90.0,
        arc_length_ft=10.0,  # inconsistent
        chord_length_ft=10.0,  # also inconsistent
    )
    c2 = PkgDeedCall(
        course=2,
        direction_text="curve 2",
        bearing_azimuth_deg_from_north=90.0,
        distance_ft=100.0,
        curve_dir="right",
        radius_ft=100.0,
        arc_length_ft=700.0,  # > 2*pi*R
    )
    c3 = PkgDeedCall(
        course=3,
        direction_text="curve 3",
        bearing_azimuth_deg_from_north=180.0,
        distance_ft=100.0,
        curve_dir="left",
        radius_ft=100.0,
        delta_deg=90.0,
        arc_length_ft=10.0,  # inconsistent
    )
    passed, warnings = mp_checks.check_curve_consistency([c1, c2, c3])
    assert passed is False
    assert any("Course 1: arc length inconsistency" in w for w in warnings)
    assert any("Course 1: chord length inconsistency" in w for w in warnings)
    assert any("Course 2: arc length exceeds full circle" in w for w in warnings)
    assert any("Course 3: arc length inconsistency" in w for w in warnings)


# ---------------------------------------------------------------------------
# V5: compare_double_entry delta formatting (4 decimals)
# ---------------------------------------------------------------------------


def test_v5_compare_double_entry_formats_delta_to_4_decimals(verify_api):
    call_cls, _, _, _, _, compare_fn = verify_api
    c1 = call_cls(
        course=1,
        direction_text="curve",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=100.0,
        curve_dir="right",
        radius_ft=100.0,
        delta_deg=45.0000,
    )
    c2 = c1.model_copy(update={"delta_deg": 45.0010})
    discrepancies = compare_fn([c1], [c2])
    assert len(discrepancies) == 1
    assert "45.0000 vs 45.0010" in discrepancies[0]


# ---------------------------------------------------------------------------
# V7 & V10: verification_audit checks (parallelism, area_reasonableness, double_entry)
#           and dead code removal
# ---------------------------------------------------------------------------


def test_v7_verification_audit_includes_parallelism_area_and_double_entry(verify_api):
    call_cls, audit_cls, run_cls, verify_fn, _, _ = verify_api
    calls = _square(call_cls)
    calls[1] = calls[1].model_copy(update={"along": "continuing along same line"})
    double_entry = _square(call_cls)
    double_entry[0] = double_entry[0].model_copy(update={"distance_ft": 105.0})

    ctx = _make_audit_ctx(audit_cls, run_cls)
    verify_fn(
        calls,
        stated_area_sq_ft=5000.0,
        double_entry_calls=double_entry,
        audit_context=ctx,
    )
    checks_by_name = {c.name: c for c in ctx.verification_audit.checks}
    assert "parallelism" in checks_by_name
    assert checks_by_name["parallelism"].passed is False
    assert "area_reasonableness" in checks_by_name
    assert checks_by_name["area_reasonableness"].passed is False
    assert "double_entry" in checks_by_name
    assert checks_by_name["double_entry"].passed is False


def test_v10_dead_check_double_entry_removed():
    assert not hasattr(mp_checks, "check_double_entry")


# ---------------------------------------------------------------------------
# E1: UTF-8 encoding & CSV BOM / newline=""
# ---------------------------------------------------------------------------


def test_e1_csv_utf8_and_bom_roundtrip(export_api, tmp_path):
    call_cls, _, _, _, _, _, _, verify_fn, write_csv, load_csv, export_csv, _, _ = export_api
    calls = [
        call_cls(
            course=i + 1,
            direction_text=f"N {i}°00′00″ E — Señorita",
            bearing_azimuth_deg_from_north=az,
            distance_ft=100.0,
            along="Müller Lane — line",
            to="Café pin № 1",
            notes="über boundary",
        )
        for i, az in enumerate((0.0, 90.0, 180.0, 270.0))
    ]
    result = verify_fn(calls)
    out = tmp_path / "utf8.csv"
    export_csv(calls, result, str(out))

    loaded = load_csv(str(tmp_path / "utf8_verified.csv"))
    assert loaded[0].along == "Müller Lane — line"
    assert loaded[0].notes == "über boundary"

    # Also test reading a UTF-8 BOM CSV
    bom_path = tmp_path / "bom.csv"
    write_csv(calls, str(bom_path))
    bom_bytes = b"\xef\xbb\xbf" + bom_path.read_bytes()
    bom_path.write_bytes(bom_bytes)
    bom_loaded = load_csv(str(bom_path))
    assert len(bom_loaded) == 4
    assert bom_loaded[0].course == 1


# ---------------------------------------------------------------------------
# E2: csv_to_calls truncated rows & invalid headers in strict=True
# ---------------------------------------------------------------------------


def test_e2_csv_to_calls_rejects_missing_required_headers(export_api, tmp_path):
    _, _, _, _, _, _, _, _, _, load_csv, _, _, _ = export_api
    bad_header = tmp_path / "bad_header.csv"
    bad_header.write_text("foo,bar,baz\n1,2,3\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required columns"):
        load_csv(str(bad_header), strict=True)


def test_e2_csv_to_calls_rejects_truncated_and_extra_column_rows(export_api, tmp_path):
    _, _, _, _, _, _, _, _, _, load_csv, _, _, _ = export_api
    truncated = tmp_path / "truncated.csv"
    # Truncated row omits trailing optional column 'notes' (5 values for 6 columns)
    truncated.write_text(
        "course,direction_text,bearing_quadrant,bearing_azimuth_deg_from_north,distance_ft,notes\n"
        "1,N 0 E,N 0 E,0.0,100.0\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid CSV row 2"):
        load_csv(str(truncated), strict=True)
    assert load_csv(str(truncated), strict=False) == []

    extra_cols = tmp_path / "extra_cols.csv"
    extra_cols.write_text(
        "course,direction_text,bearing_quadrant,bearing_azimuth_deg_from_north,distance_ft,notes\n"
        "1,N 0 E,N 0 E,0.0,100.0,ok,EXTRA\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid CSV row 2"):
        load_csv(str(extra_cols), strict=True)
    assert load_csv(str(extra_cols), strict=False) == []


# ---------------------------------------------------------------------------
# E3: export_verified_csv tract_results=[], stale audit sidecars, double _verified
# ---------------------------------------------------------------------------


def test_e3_export_empty_tract_results_does_not_export_single_tract(export_api, tmp_path):
    call_cls, _, _, _, _, _, _, verify_fn, _, _, export_csv, _, _ = export_api
    calls = _square(call_cls)
    result = verify_fn(calls)
    paths = export_csv(calls, result, str(tmp_path / "deed.csv"), tract_results=[])
    assert paths == []
    assert not (tmp_path / "deed_verified.csv").exists()


def test_e3_export_multi_tract_removes_stale_audit_sidecars(export_api, tmp_path):
    (
        call_cls,
        _,
        tract_cls,
        tract_type_cls,
        audit_cls,
        run_cls,
        _,
        verify_fn,
        _,
        _,
        export_csv,
        _,
        _,
    ) = export_api
    calls = _square(call_cls)
    result = verify_fn(calls)
    t1 = tract_cls(label="Tract 1", tract_type=tract_type_cls.MAIN, calls=calls)
    out = tmp_path / "deed.csv"
    ctx = _make_audit_ctx(audit_cls, run_cls)

    export_csv(calls, result, str(out), tract_results=[(t1, result)], audit_context=ctx)
    assert (tmp_path / "deed_verified.audit.json").exists()
    assert (tmp_path / "deed_verified.audit.html").exists()

    export_csv(calls, result, str(out), tract_results=[(t1, result)], audit_context=None)
    assert not (tmp_path / "deed_verified.audit.json").exists()
    assert not (tmp_path / "deed_verified.audit.html").exists()


def test_e3_export_avoids_double_verified_suffix(export_api, tmp_path):
    call_cls, _, _, _, _, _, _, verify_fn, _, _, export_csv, _, _ = export_api
    calls = _square(call_cls)
    result = verify_fn(calls)
    out = tmp_path / "deed_verified.csv"
    paths = export_csv(calls, result, str(out))
    assert paths == [tmp_path / "deed_verified.csv"]
    assert not (tmp_path / "deed_verified_verified.csv").exists()
    assert (tmp_path / "deed_verified.verification.txt").exists()


# ---------------------------------------------------------------------------
# E4 & E5: audit_html / audit_reporter rounding and mkdir
# ---------------------------------------------------------------------------


def test_e4_confidence_percentage_uses_round(export_api):
    _, _, _, _, audit_cls, run_cls, ext_cls, _, _, _, _, gen_html, _ = export_api
    ctx = _make_audit_ctx(audit_cls, run_cls)
    # 0.29 * 100 == 28.999999999999996 in float -> int() yields 28%, round() yields 29%
    ctx.extraction_record = ext_cls(
        raw_llm_response="raw",
        normalized_text="norm",
        llm_confidence=0.29,
    )
    html_out = gen_html(ctx)
    assert "29%" in html_out


def test_e5_write_report_creates_parent_directories(export_api, tmp_path):
    _, _, _, _, audit_cls, run_cls, _, _, _, _, _, _, write_fn = export_api
    ctx = _make_audit_ctx(audit_cls, run_cls)
    report_path = tmp_path / "nested" / "dir" / "report.audit.html"
    write_fn(ctx, report_path)
    assert report_path.exists()


# ---------------------------------------------------------------------------
# E7: mp-export packaging metadata (py.typed, pydantic dep, accurate description)
# ---------------------------------------------------------------------------


def test_e7_mp_export_packaging_metadata():
    pkg_dir = Path(__file__).resolve().parents[2] / "packages" / "mp-export"
    assert (pkg_dir / "src" / "mp_export" / "py.typed").exists()
    pyproject = tomllib.loads((pkg_dir / "pyproject.toml").read_text(encoding="utf-8"))
    deps = pyproject["project"]["dependencies"]
    assert any(d.startswith("pydantic>=") for d in deps)
    assert "CSV, JSON, and audit HTML" not in pyproject["project"]["description"]
