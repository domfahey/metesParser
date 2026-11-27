"""Regression tests for v0.7.0 verification and export bug fixes (Red-Green TDD)."""

from __future__ import annotations

import math
import tomllib
from datetime import UTC, datetime
from pathlib import Path

import mp_export.audit_html as pkg_audit_html
import pytest
from mp_export import export_verified_csv, legal_description_to_csv
from mp_export.csv_writer import _write_metadata, calls_to_csv
from mp_models import (
    AuditContext,
    CheckResult,
    DeedCall,
    ExtractionRecord,
    LegalDescription,
    Point,
    RunMetadata,
    SubdivisionReference,
    Tract,
    TractType,
)
from mp_verify import verify_closure
from mp_verify.checks import (
    check_curve_consistency,
    check_distance_reasonableness,
    check_straight_boundary_intersections,
    compare_double_entry,
)
from mp_verify.confidence import calculate_confidence_score
from mp_verify.topology import check_curved_boundary_intersections

from metesparser.audit_reporter import AuditReporter
from metesparser.models import (
    AuditContext as MonoAuditContext,
)
from metesparser.models import (
    ExtractionRecord as MonoExtractionRecord,
)
from metesparser.models import (
    RunMetadata as MonoRunMetadata,
)


def _line(course: int, azimuth: float, distance: float, **extra: object) -> DeedCall:
    return DeedCall(
        course=course,
        direction_text=f"az {azimuth}",
        bearing_azimuth_deg_from_north=azimuth,
        distance_ft=distance,
        **extra,  # type: ignore[arg-type]
    )


def _square(size: float = 100.0, course_start: int = 1, **extra: object) -> list[DeedCall]:
    return [
        _line(course_start + i, az, size, **extra) for i, az in enumerate((0.0, 90.0, 180.0, 270.0))
    ]


def _pkg_audit_context() -> AuditContext:
    return AuditContext(
        run_metadata=RunMetadata(
            parser_version="0.7.0",
            llm_provider="none",
            llm_model="none",
            prompt_hash="abc",
            timestamp_utc=datetime(2026, 11, 25, tzinfo=UTC),
            source_pdf="deed — café.pdf",
            cache_enabled=False,
        ),
        extraction_record=ExtractionRecord(
            raw_llm_response="raw",
            normalized_text="norm",
            llm_confidence=0.896,
        ),
    )


def _mono_audit_context() -> MonoAuditContext:
    return MonoAuditContext(
        run_metadata=MonoRunMetadata(
            parser_version="0.7.0",
            llm_provider="none",
            llm_model="none",
            prompt_hash="abc",
            timestamp_utc=datetime(2026, 11, 25, tzinfo=UTC),
            source_pdf="deed.pdf",
            cache_enabled=False,
        ),
        extraction_record=MonoExtractionRecord(
            raw_llm_response="raw",
            normalized_text="norm",
            llm_confidence=0.896,
        ),
    )


# ---------------------------------------------------------------------------
# 1. mp_verify/checks.py
# ---------------------------------------------------------------------------


def test_check_curve_consistency_reports_all_mismatches_same_and_multiple_curves() -> None:
    bad_arc_and_chord = DeedCall(
        course=1,
        direction_text="N 0° E",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=50.0,
        curve_dir="right",
        radius_ft=100.0,
        delta_deg=30.0,
        arc_length_ft=60.0,  # expected ~52.36
        chord_length_ft=65.0,  # expected ~51.76
    )
    bad_second_curve = DeedCall(
        course=2,
        direction_text="N 30° E",
        bearing_azimuth_deg_from_north=30.0,
        distance_ft=40.0,
        curve_dir="right",
        radius_ft=100.0,
        delta_deg=20.0,
        arc_length_ft=45.0,  # expected ~34.91
    )

    passed, warnings = check_curve_consistency([bad_arc_and_chord, bad_second_curve])

    assert passed is False
    assert any("Course 1: arc length inconsistency" in w for w in warnings)
    assert any("Course 1: chord length inconsistency" in w for w in warnings)
    assert any("Course 2: arc length inconsistency" in w for w in warnings)


def test_check_curve_consistency_continues_after_infeasible_chord_or_full_circle() -> None:
    infeasible_chord = DeedCall(
        course=1,
        direction_text="N 0° E",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=250.0,
        curve_dir="right",
        radius_ft=100.0,
        chord_bearing="N 45° E",
        chord_length_ft=250.0,
    )
    over_full_circle = DeedCall(
        course=2,
        direction_text="N 0° E",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=700.0,
        curve_dir="right",
        radius_ft=100.0,
        arc_length_ft=700.0,
    )
    bad_third = DeedCall(
        course=3,
        direction_text="N 0° E",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=50.0,
        curve_dir="left",
        radius_ft=100.0,
        delta_deg=30.0,
        arc_length_ft=75.0,
    )

    passed, warnings = check_curve_consistency([infeasible_chord, over_full_circle, bad_third])

    assert passed is False
    assert any("Course 1:" in w for w in warnings)
    assert any("Course 2:" in w for w in warnings)
    assert any("Course 3:" in w for w in warnings)


def test_compare_double_entry_formats_delta_to_four_decimals() -> None:
    c1 = DeedCall(
        course=1,
        direction_text="curve",
        bearing_quadrant="N 0° E",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=100.0,
        curve_dir="left",
        radius_ft=100.0,
        delta_deg=45.0010,
    )
    c2 = c1.model_copy(update={"delta_deg": 45.0020})

    discrepancies = compare_double_entry([c1], [c2])

    assert discrepancies == ["Course 1: Delta mismatch - 45.0010 vs 45.0020"]


def test_compare_double_entry_checks_flags_and_radial_bearing() -> None:
    c1 = DeedCall(
        course=1,
        direction_text="curve",
        bearing_quadrant="N 0° E",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=100.0,
        is_exception=True,
        is_tie_in=False,
        is_meander=True,
        non_tangent=True,
        radial_bearing="S 90° E",
    )
    c2 = DeedCall(
        course=1,
        direction_text="curve",
        bearing_quadrant="N 0° E",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=100.0,
        is_exception=False,
        is_tie_in=True,
        is_meander=False,
        non_tangent=False,
        radial_bearing="N 90° W",
    )

    discrepancies = compare_double_entry([c1], [c2])
    joined = "\n".join(discrepancies)

    assert "Course 1: Exception" in joined
    assert "Course 1: Tie-in" in joined
    assert "Course 1: Meander" in joined
    assert "Course 1: Non-tangent" in joined
    assert "Course 1: Radial bearing" in joined


def test_check_distance_reasonableness_uses_curve_arc_length() -> None:
    curve = DeedCall(
        course=1,
        direction_text="curve",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=0.1,  # placeholder / tiny chord
        curve_dir="right",
        radius_ft=100.0,
        arc_length_ft=100.0,
    )
    straight = _line(2, 90.0, 100.0)

    warnings = check_distance_reasonableness([curve, straight])

    assert not any("suspiciously short" in w for w in warnings)


# ---------------------------------------------------------------------------
# 2. mp_verify/{closure,topology,confidence}.py
# ---------------------------------------------------------------------------


def test_multi_tract_verify_closure_wires_double_entry_and_preserves_role_checks() -> None:
    main_calls = _square(100.0, course_start=1)
    exc_calls = _square(20.0, course_start=5, is_exception=True)
    tracts = [
        Tract(label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=main_calls),
        Tract(
            label="Exception 1",
            tract_type=TractType.EXCEPTION,
            role_basis="heading",
            calls=exc_calls,
        ),
    ]
    de_exc = list(exc_calls)
    de_exc[1] = de_exc[1].model_copy(update={"distance_ft": 25.0})
    double_entry = [*main_calls, *de_exc]

    audit = _pkg_audit_context()
    results = verify_closure(
        [*main_calls, *exc_calls],
        tracts=tracts,
        double_entry_calls=double_entry,
        audit_context=audit,
    )

    assert len(results) == 2
    main_res, exc_res = results
    main_de = next(c for c in main_res.checks if c.name == "double_entry")
    exc_de = next(c for c in exc_res.checks if c.name == "double_entry")
    assert main_de.status == "passed"
    assert exc_de.status == "failed"
    assert any("Double-entry discrepancy" in w for w in exc_res.warnings)
    # Matching is_exception=True on an EXCEPTION tract must not produce a false mismatch.
    assert not any("Exception flag mismatch" in w for w in exc_res.warnings)
    # Role checks & multi-tract audits preserved.
    assert any(c.name == "non_boundary_tract" and c.status == "blocked" for c in exc_res.checks)
    assert len(audit.tract_verification_audits) == 2
    assert audit.tract_verification_audits[0].tract_label == "Tract 1"
    assert audit.tract_verification_audits[1].tract_label == "Exception 1"


def test_multi_tract_verify_closure_preserves_inferred_role_block_with_double_entry() -> None:
    t1 = Tract(
        label="Tract 1", tract_type=TractType.MAIN, role_basis="inferred", calls=_square(100.0)
    )
    t2 = Tract(
        label="Tract 2", tract_type=TractType.ADDITION, role_basis="heading", calls=_square(50.0)
    )
    results = verify_closure(
        [*t1.calls, *t2.calls],
        tracts=[t1, t2],
        double_entry_calls=[*t1.calls, *t2.calls],
    )
    assert all(
        any(c.name == "description_roles_inferred" and c.status == "blocked" for c in r.checks)
        for r in results
    )
    assert all(
        any(c.name == "double_entry" and c.status == "passed" for c in r.checks) for r in results
    )


def test_closure_tolerance_propagates_to_exception_area_and_intersections() -> None:
    main = _square(100.0, course_start=1)
    # Exception loop closes within 0.03 ft (< 0.05 tolerance, >= 0.01 default).
    exc = [
        _line(5, 0.0, 20.0, is_exception=True),
        _line(6, 90.0, 20.0, is_exception=True),
        _line(7, 180.0, 20.0, is_exception=True),
        _line(8, 270.0, 20.03, is_exception=True),
    ]

    relaxed = verify_closure([*main, *exc], closure_tolerance_ft=0.05)
    assert relaxed.area_available is True
    assert relaxed.area_sq_ft == pytest.approx(10000.0 - 400.0, abs=1e-6)

    strict = verify_closure([*main, *exc])
    assert strict.area_available is False

    # Straight boundary intersection check respects closure_tolerance_ft for closing corner.
    pts = [
        Point(x=0.0, y=0.0),
        Point(x=0.0, y=20.0),
        Point(x=20.0, y=20.0),
        Point(x=20.0, y=0.0),
        Point(x=-0.03, y=0.0),
    ]
    assert check_straight_boundary_intersections(exc, pts, closure_tolerance_ft=0.05) == []

    # Curved boundary intersection check accepts closure_tolerance_ft without TypeError.
    arc_call = DeedCall(
        course=1,
        direction_text="arc",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=50.0 * math.pi,
        curve_dir="right",
        radius_ft=50.0,
        delta_deg=180.0,
        arc_length_ft=50.0 * math.pi,
    )
    close_line = _line(2, 270.0, 100.03)
    arc_pts = [Point(x=0.0, y=0.0), Point(x=100.0, y=0.0), Point(x=-0.03, y=0.0)]
    assert (
        check_curved_boundary_intersections(
            [arc_call, close_line], arc_pts, closure_tolerance_ft=0.05
        )
        == []
    )


def test_exception_area_requires_three_courses_unless_curved() -> None:
    main = _square(100.0, course_start=1)
    # 2 straight courses returning to origin (degenerate out-and-back): must NOT close!
    two_straight_exc = [
        _line(5, 0.0, 50.0, is_exception=True),
        _line(6, 180.0, 50.0, is_exception=True),
    ]
    result = verify_closure([*main, *two_straight_exc])
    assert result.area_available is False
    assert any("exception" in w.lower() for w in result.warnings)

    # Full-circle curved exception (1 course) SHOULD still close.
    circle_exc = [
        DeedCall(
            course=5,
            direction_text="circle",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=20.0 * math.pi,
            curve_dir="right",
            radius_ft=10.0,
            delta_deg=360.0,
            arc_length_ft=20.0 * math.pi,
            is_exception=True,
        )
    ]
    circle_res = verify_closure([*main, *circle_exc])
    assert circle_res.area_available is True
    assert circle_res.area_sq_ft == pytest.approx(10000.0 - math.pi * 100.0, abs=1e-6)


def test_negative_net_area_clamped_to_zero_with_warning() -> None:
    main = _square(100.0, course_start=1)  # 10,000 sq ft
    big_exc = _square(200.0, course_start=5, is_exception=True)  # 40,000 sq ft

    result = verify_closure([*main, *big_exc])

    assert result.area_sq_ft == 0.0
    assert result.area_acres == 0.0
    assert any("exceeds main" in w.lower() or "clamped" in w.lower() for w in result.warnings)
    assert result.is_fully_verified() is False


def test_confidence_zero_for_non_computable_and_includes_boundary_intersections() -> None:
    cardinal_only = [
        DeedCall(course=1, direction_text="Northerly", distance_ft=100.0),
        DeedCall(course=2, direction_text="Easterly", distance_ft=100.0),
        DeedCall(course=3, direction_text="Southerly", distance_ft=100.0),
        DeedCall(course=4, direction_text="Westerly", distance_ft=100.0),
    ]
    cardinal_result = verify_closure(cardinal_only)
    assert cardinal_result.misclosure_available is False
    assert cardinal_result.confidence_score == 0.0

    # Zero positioned calls with misclosure_available=False explicitly passed
    no_pos_calls = [
        DeedCall(
            course=1,
            direction_text="North",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=None,
            curve_dir="right",
            curve_type="spiral",
            radius_ft=100.0,
            delta_deg=5.0,
        )
    ]
    assert calculate_confidence_score(cardinal_result, no_pos_calls) == 0.0

    # Self-intersection check affects checks_score when applicable
    calls = _square(100.0)
    clean = verify_closure(calls)
    checks_passed = [
        CheckResult(name="interior_angles", status="passed", detail="ok"),
        CheckResult(name="curve_consistency", status="not_applicable", detail="no curves"),
        CheckResult(name="boundary_intersections", status="passed", detail="ok"),
    ]
    checks_failed_int = [
        CheckResult(name="interior_angles", status="passed", detail="ok"),
        CheckResult(name="curve_consistency", status="not_applicable", detail="no curves"),
        CheckResult(name="boundary_intersections", status="failed", detail="crossing"),
    ]
    r_pass = clean.model_copy(update={"checks": checks_passed})
    r_fail = clean.model_copy(update={"checks": checks_failed_int})
    assert calculate_confidence_score(r_fail, calls) < calculate_confidence_score(r_pass, calls)

    # Also recognizes explicit self_intersection check name when applicable
    checks_si_pass = [
        CheckResult(name="interior_angles", status="passed", detail="ok"),
        CheckResult(name="self_intersection", status="passed", detail="ok"),
    ]
    checks_si_fail = [
        CheckResult(name="interior_angles", status="passed", detail="ok"),
        CheckResult(name="self_intersection", status="failed", detail="crossing"),
    ]
    assert calculate_confidence_score(
        clean.model_copy(update={"checks": checks_si_fail}), calls
    ) < calculate_confidence_score(clean.model_copy(update={"checks": checks_si_pass}), calls)


# ---------------------------------------------------------------------------
# 3. mp_export & audit_reporter
# ---------------------------------------------------------------------------


def test_legal_description_to_csv_metadata_includes_area_and_plat_and_falsy_values(
    tmp_path: Path,
) -> None:
    ld = LegalDescription(
        calls=[
            DeedCall(
                course=1,
                direction_text="N 0° E — café",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=100.0,
            )
        ],
        stated_area_sq_ft=1000.0,
        stated_area_approximate=False,
        subdivision_ref=SubdivisionReference(
            lot="1",
            block="2",
            subdivision_name="Oak Estates",
            plat_book="14",
            plat_page="22",
        ),
    )
    out = tmp_path / "parcel.csv"
    legal_description_to_csv(ld, str(out))

    meta_text = (tmp_path / "parcel.metadata.txt").read_text(encoding="utf-8")
    assert "stated_area_sq_ft: 1000.0" in meta_text
    assert "stated_area_approximate: False" in meta_text
    assert "plat_book: 14" in meta_text
    assert "plat_page: 22" in meta_text

    # Direct _write_metadata preserves 0, 0.0, and False, while omitting None and ""
    direct_meta = tmp_path / "direct.metadata.txt"
    _write_metadata(
        {"count": 0, "area": 0.0, "approx": False, "empty": "", "missing": None},
        direct_meta,
    )
    direct_text = direct_meta.read_text(encoding="utf-8")
    assert "count: 0\n" in direct_text
    assert "area: 0.0\n" in direct_text
    assert "approx: False\n" in direct_text
    assert "empty:" not in direct_text
    assert "missing:" not in direct_text


def test_csv_writer_explicit_utf8_encoding_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import builtins

    write_encodings: list[str | None] = []
    real_open = builtins.open
    real_write_text = Path.write_text

    def tracked_open(file, mode="r", *args, **kwargs):
        if "w" in str(mode):
            write_encodings.append(kwargs.get("encoding"))
        return real_open(file, mode, *args, **kwargs)

    def tracked_write_text(self: Path, data: str, *args, **kwargs):
        write_encodings.append(kwargs.get("encoding"))
        return real_write_text(self, data, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", tracked_open)
    monkeypatch.setattr(Path, "write_text", tracked_write_text)

    calls = _square(100.0)
    calls[0] = calls[0].model_copy(update={"along": "line — café €"})
    result = verify_closure(calls)
    audit = _pkg_audit_context()

    out = tmp_path / "utf8_deed.csv"
    written = export_verified_csv(
        calls,
        result,
        str(out),
        legal_desc=LegalDescription(calls=calls, source_doc="café.pdf"),
        audit_context=audit,
    )
    assert len(written) == 1
    assert write_encodings
    assert all(enc == "utf-8" for enc in write_encodings), write_encodings

    write_encodings.clear()
    raw_out = tmp_path / "raw.csv"
    calls_to_csv(calls, str(raw_out), metadata={"source_doc": "café — deed.pdf"})
    assert write_encodings == ["utf-8", "utf-8"]


def test_export_verified_csv_prevents_double_verified_suffix(tmp_path: Path) -> None:
    calls = _square(100.0)
    result = verify_closure(calls)
    audit = _pkg_audit_context()

    out = tmp_path / "deed_verified.csv"
    written = export_verified_csv(calls, result, str(out), audit_context=audit)

    assert written == [tmp_path / "deed_verified.csv"]
    assert (tmp_path / "deed_verified.csv").exists()
    assert (tmp_path / "deed_verified.verification.txt").exists()
    assert (tmp_path / "deed_verified.audit.json").exists()
    assert (tmp_path / "deed_verified.audit.html").exists()
    assert not (tmp_path / "deed_verified_verified.csv").exists()
    assert not (tmp_path / "deed_verified_verified.verification.txt").exists()

    # Multi-tract also avoids _verified_verified_tract1
    tract = Tract(label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=calls)
    mt_dir = tmp_path / "mt"
    mt_dir.mkdir()
    mt_written = export_verified_csv(
        calls, result, str(mt_dir / "parcel_verified.csv"), tract_results=[(tract, result)]
    )
    assert mt_written == [mt_dir / "parcel_verified_tract1.csv"]
    assert not (mt_dir / "parcel_verified_verified_tract1.csv").exists()


def test_export_verified_csv_empty_tract_results_does_not_fall_through(tmp_path: Path) -> None:
    calls = _square(100.0)
    result = verify_closure(calls)

    with pytest.raises(ValueError, match="no parcel boundary tract"):
        export_verified_csv(calls, result, str(tmp_path / "deed.csv"), tract_results=[])

    assert list(tmp_path.iterdir()) == []


def test_audit_html_and_reporter_round_confidence_and_create_parent_dirs(tmp_path: Path) -> None:
    pkg_ctx = _pkg_audit_context()
    pkg_html = pkg_audit_html.generate_html(pkg_ctx)
    assert ">90%</span>" in pkg_html
    assert ">89%</span>" not in pkg_html

    pkg_target = tmp_path / "pkg_nested" / "sub" / "audit.html"
    pkg_audit_html.write_report(pkg_ctx, pkg_target)
    assert pkg_target.exists()

    mono_ctx = _mono_audit_context()
    mono_html = AuditReporter.generate_html(mono_ctx)
    assert ">90%</span>" in mono_html
    assert ">89%</span>" not in mono_html

    mono_target = tmp_path / "mono_nested" / "sub" / "audit.html"
    AuditReporter.write_report(mono_ctx, mono_target)
    assert mono_target.exists()


def test_mp_export_pyproject_declares_pydantic() -> None:
    pyproject = Path(__file__).resolve().parents[2] / "packages" / "mp-export" / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    deps = data["project"]["dependencies"]
    assert any(dep.startswith("pydantic>=") for dep in deps)
