"""Red-Green TDD regression tests for Track 4 (review_packet, pdf_processor, cli, scripts)."""

from __future__ import annotations

import importlib.util
import math
import re
from pathlib import Path

import pytest
import structlog.testing

from metesparser import cli
from metesparser.models import (
    ClosureResult,
    DeedCall,
    LegalDescription,
    Tract,
    TractType,
)
from metesparser.pdf_processor import PDFProcessor
from metesparser.review_packet import generate_traverse_plot
from metesparser.run_registry import RunManifest, RunResults, format_comparison_table


def _load_script(script_name: str):
    spec = importlib.util.spec_from_file_location(
        script_name.removesuffix(".py"),
        Path(__file__).resolve().parents[2] / "scripts" / script_name,
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# 1. review_packet.py: 360-deg full-circle arcs, viewBox guard, bool strings
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("curve_dir", "expected_flag", "expected_x_min", "expected_x_max"),
    [
        ("right", 1, 0.0, 200.0),
        ("left", 0, -200.0, 0.0),
    ],
)
def test_generate_traverse_plot_full_circle_360_deg_renders_two_arcs_and_valid_viewbox(
    curve_dir: str,
    expected_flag: int,
    expected_x_min: float,
    expected_x_max: float,
) -> None:
    """360-degree curves must split into two 180-deg SVG arcs with full diameter viewBox."""
    radius = 100.0
    circumference = 2.0 * math.pi * radius
    gt = {
        "expected_calls": [
            {
                "course": 1,
                "direction_text": f"{curve_dir} 360-deg circle radius 100 ft",
                "bearing_azimuth_deg_from_north": 0.0,
                "distance_ft": circumference,
                "curve_dir": curve_dir,
                "radius_ft": radius,
                "delta_deg": 360.0,
                "arc_length_ft": circumference,
            }
        ]
    }

    svg = generate_traverse_plot(gt)
    assert "<svg" in svg

    path_line = next(line for line in svg.splitlines() if "<path " in line)
    arc_cmds = re.findall(rf"\bA\s+100\.00,100\.00\s+0\s+0,{expected_flag}\b", path_line)
    assert len(arc_cmds) == 2

    stroke_match = re.search(r"stroke-width='([^']+)'", path_line)
    assert stroke_match is not None
    assert float(stroke_match.group(1)) > 0.0

    vb_match = re.search(r"viewBox='([^']+)'", svg)
    assert vb_match is not None
    vb_x, vb_y, vb_w, vb_h = (float(v) for v in vb_match.group(1).split())
    assert vb_x <= expected_x_min
    assert vb_x + vb_w >= expected_x_max
    assert vb_y <= -100.0
    assert vb_y + vb_h >= 100.0


def test_generate_traverse_plot_string_false_booleans_do_not_drop_calls_or_make_curves() -> None:
    """String 'false' on is_tie_in, is_exception, non_tangent must behave as False."""
    gt = {
        "expected_calls": [
            {
                "course": 1,
                "direction_text": "N 0° E 100 ft",
                "bearing_azimuth_deg_from_north": 0.0,
                "distance_ft": 100.0,
                "is_tie_in": "false",
                "is_exception": "false",
                "non_tangent": "false",
            },
            {
                "course": 2,
                "direction_text": "N 90° E 100 ft",
                "bearing_azimuth_deg_from_north": 90.0,
                "distance_ft": 100.0,
                "is_tie_in": "0",
                "is_exception": "no",
                "non_tangent": "",
            },
            {
                "course": 3,
                "direction_text": "S 0° E 100 ft",
                "bearing_azimuth_deg_from_north": 180.0,
                "distance_ft": 100.0,
            },
            {
                "course": 4,
                "direction_text": "N 90° W 100 ft",
                "bearing_azimuth_deg_from_north": 270.0,
                "distance_ft": 100.0,
            },
        ]
    }
    svg = generate_traverse_plot(gt)
    assert "<svg" in svg
    path_line = next(line for line in svg.splitlines() if "<path " in line)
    assert path_line.count(" L ") == 4
    assert " Z'" in path_line


def test_generate_traverse_plot_invalid_or_unpositioned_curve_returns_incomplete_message() -> None:
    """An unpositioned non-tangent curve without radial/chord returns the incomplete-course HTML."""
    gt = {
        "expected_calls": [
            {
                "course": 7,
                "direction_text": "non-tangent curve right R=100, delta=30",
                "bearing_azimuth_deg_from_north": 0.0,
                "distance_ft": 52.36,
                "curve_dir": "right",
                "radius_ft": 100.0,
                "delta_deg": 30.0,
                "non_tangent": True,
            }
        ]
    }
    html = generate_traverse_plot(gt)
    assert "<svg" not in html
    assert "Incomplete traverse plot" in html
    assert "7" in html


def test_generate_traverse_plot_chord_only_and_spiral_curve_render_line_fallback() -> None:
    """Chord-only circular curves and spirals must render L segment fallbacks."""
    chord_only_gt = {
        "expected_calls": [
            {
                "course": 1,
                "direction_text": "curve right R=100, chord N 90 E 50 ft",
                "distance_ft": 50.0,
                "curve_dir": "right",
                "radius_ft": 100.0,
                "chord_bearing": "N 90°00' E",
                "chord_length_ft": 50.0,
            }
        ]
    }
    svg_chord = generate_traverse_plot(chord_only_gt)
    assert "<svg" in svg_chord
    chord_path = next(line for line in svg_chord.splitlines() if "<path " in line)
    assert " L " in chord_path
    assert " A " not in chord_path

    spiral_gt = {
        "expected_calls": [
            {
                "course": 1,
                "direction_text": "spiral curve, chord N 0 E 50 ft",
                "distance_ft": 50.0,
                "curve_type": "spiral",
                "chord_bearing": "N 0°00' E",
                "chord_length_ft": 50.0,
            }
        ]
    }
    svg_spiral = generate_traverse_plot(spiral_gt)
    assert "<svg" in svg_spiral
    spiral_path = next(line for line in svg_spiral.splitlines() if "<path " in line)
    assert " L " in spiral_path
    assert " A " not in spiral_path


def test_generate_traverse_plot_viewbox_guard_on_subepsilon_span() -> None:
    """Floating-point residuals like 1e-12 must not produce viewBox width/height of 0.00."""
    gt = {
        "expected_calls": [
            {
                "course": 1,
                "direction_text": "N 0° E 1e-12 ft",
                "bearing_azimuth_deg_from_north": 0.0,
                "distance_ft": 1e-12,
            }
        ]
    }
    svg = generate_traverse_plot(gt)
    vb_match = re.search(r"viewBox='([^']+)'", svg)
    assert vb_match is not None
    _, _, vb_w, vb_h = (float(v) for v in vb_match.group(1).split())
    assert vb_w >= 1.0
    assert vb_h >= 1.0


# ---------------------------------------------------------------------------
# 2. pdf_processor.py: surface invalid non-positive stated area
# ---------------------------------------------------------------------------


def test_pdf_processor_surfaces_warning_and_audit_signal_for_non_positive_stated_area(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-positive stated area must log a warning and record an audit signal."""
    text = (
        "BEGINNING at an iron pin; "
        "THENCE N 0°00' E 100.00 feet; "
        "THENCE N 90°00' E 100.00 feet; "
        "THENCE S 0°00' E 100.00 feet; "
        "THENCE N 90°00' W 100.00 feet to the point of beginning, "
        "containing 0 acres, more or less."
    )
    pdf_path = tmp_path / "zero_area.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    processor = PDFProcessor(client=object(), cache=False)  # type: ignore[arg-type]
    monkeypatch.setattr(processor, "extract_legal_description", lambda _p: text)
    monkeypatch.setattr(processor, "normalize_legal_description", lambda t: t)

    with structlog.testing.capture_logs() as cap_logs:
        legal_desc, audit_ctx = processor.process_deed_pdf(str(pdf_path), audit=True)

    assert legal_desc.stated_area_sq_ft is None
    assert legal_desc.stated_area_approximate is False
    assert any(
        entry.get("log_level") == "warning" and "stated area" in str(entry.get("event", "")).lower()
        for entry in cap_logs
    )
    assert audit_ctx.extraction_record is not None
    assert audit_ctx.extraction_record.confidence_signals.get("valid_stated_area") is False


# ---------------------------------------------------------------------------
# 3. cli.py: _aggregate_tract_closure closure_passed semantics
# ---------------------------------------------------------------------------


def test_aggregate_tract_closure_closure_passed_true_when_closed_with_warnings() -> None:
    """Closed multi-tract run with warnings must yield closure_passed=True and WARN status."""
    from datetime import UTC, datetime

    main_tract = Tract(label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=[])
    exc_tract = Tract(
        label="Exception 1", tract_type=TractType.EXCEPTION, role_basis="heading", calls=[]
    )
    main_res = ClosureResult(
        misclosure_x_ft=0.0,
        misclosure_y_ft=0.0,
        misclosure_ft=0.0,
        area_sq_ft=10000.0,
        area_acres=10000.0 / 43560.0,
        perimeter_ft=400.0,
        closure_passed=True,
        angle_check_passed=False,
        curve_consistency_passed=True,
        warnings=[],
    )
    exc_res = ClosureResult(
        misclosure_x_ft=0.0,
        misclosure_y_ft=0.0,
        misclosure_ft=0.0,
        area_sq_ft=100.0,
        area_acres=100.0 / 43560.0,
        perimeter_ft=40.0,
        closure_passed=True,
        angle_check_passed=True,
        curve_consistency_passed=True,
        warnings=["Exception tract warning"],
    )

    agg = cli._aggregate_tract_closure([(main_tract, main_res), (exc_tract, exc_res)])
    assert agg.closure_passed is True
    assert not agg.is_fully_verified()
    assert "Exception tract warning" in agg.warnings

    manifest = RunManifest(
        run_id="r1",
        timestamp_utc=datetime.now(UTC),
        source_pdf="multi.pdf",
        llm_provider="openai",
        llm_model="gpt-5.2",
        cache_enabled=False,
        parser_version="1.0.0",
        results=RunResults.from_closure(agg, call_count=4),
    )
    table = format_comparison_table([manifest])
    assert "WARN" in table
    assert "FAIL" not in table


# ---------------------------------------------------------------------------
# 4. scripts/extract_sample_deeds.py: multi-tract handling
# ---------------------------------------------------------------------------


def _make_call(course: int) -> DeedCall:
    return DeedCall(
        course=course,
        direction_text="N 0° E",
        bearing_quadrant="N 0° E",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=100.0,
    )


def test_extract_sample_deeds_multi_tract_uses_all_calls_and_boundary_closure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Easement-first multi-tract deed must verify all_calls, report boundary closure, and num_calls."""
    mod = _load_script("extract_sample_deeds.py")
    out_dir = tmp_path / "extractions"
    sample_dir = tmp_path / "samples"
    sample_dir.mkdir()
    (sample_dir / "multi.pdf").write_bytes(b"%PDF")

    easement_calls = [_make_call(1)]
    main_calls = [_make_call(2), _make_call(3), _make_call(4), _make_call(5)]
    easement_tract = Tract(
        label="Easement 1", tract_type="easement", calls=easement_calls, role_basis="heading"
    )
    main_tract = Tract(label="Tract 1", tract_type="main", calls=main_calls, role_basis="heading")
    # Simulate legal_desc where flat calls only holds main_calls (or subset), while all_calls has 5
    legal_desc = LegalDescription(
        source_doc="multi.pdf",
        calls=main_calls,
        tracts=[easement_tract, main_tract],
        stated_area_sq_ft=10000.0,
    )

    easement_closure = ClosureResult(
        misclosure_x_ft=5.0,
        misclosure_y_ft=0.0,
        misclosure_ft=5.0,
        area_sq_ft=0.0,
        area_acres=0.0,
        perimeter_ft=100.0,
        closure_passed=False,
        angle_check_passed=False,
        curve_consistency_passed=True,
        warnings=["Easement open"],
    )
    main_closure = ClosureResult(
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
    )

    seen_verify: list[tuple[list[DeedCall], list[Tract] | None]] = []

    def fake_verify_closure(calls, stated_area_sq_ft=0.0, **kwargs):
        seen_verify.append((calls, kwargs.get("tracts")))
        return [easement_closure, main_closure]

    monkeypatch.setattr(mod, "OUTPUT_DIR", out_dir)
    monkeypatch.setattr(mod, "SAMPLE_DEEDS_DIR", sample_dir)
    monkeypatch.setattr(mod, "SAMPLE_PDFS", [("multi.pdf", "multi")])
    monkeypatch.setattr(
        mod,
        "PDFProcessor",
        lambda: type("P", (), {"process_deed_pdf": lambda _self, _p: legal_desc})(),
    )
    monkeypatch.setattr(mod.ClosureChecker, "verify_closure", staticmethod(fake_verify_closure))
    monkeypatch.setattr(
        mod.CSVBuilder,
        "legal_description_to_csv",
        staticmethod(lambda _ld, p: Path(p).write_text("csv", encoding="utf-8")),
    )
    monkeypatch.setattr(mod.CSVBuilder, "export_verified_csv", staticmethod(lambda **_kw: []))

    mod.main()

    assert len(seen_verify) == 1
    assert len(seen_verify[0][0]) == 5  # all_calls, not just 4
    out = capsys.readouterr().out
    assert "5 calls extracted" in out
    assert "✓ VERIFIED multi.pdf" in out


def test_extract_sample_deeds_easement_only_deed_does_not_report_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An easement-only deed has no boundary tract and must not report ✓ CLOSES or ✓ VERIFIED."""
    mod = _load_script("extract_sample_deeds.py")
    out_dir = tmp_path / "extractions"
    sample_dir = tmp_path / "samples"
    sample_dir.mkdir()
    (sample_dir / "ease.pdf").write_bytes(b"%PDF")

    easement_calls = [_make_call(1), _make_call(2), _make_call(3), _make_call(4)]
    easement_tract = Tract(
        label="Easement 1", tract_type="easement", calls=easement_calls, role_basis="heading"
    )
    legal_desc = LegalDescription(
        source_doc="ease.pdf",
        calls=[],
        tracts=[easement_tract],
    )
    easement_closure = ClosureResult(
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
    )

    monkeypatch.setattr(mod, "OUTPUT_DIR", out_dir)
    monkeypatch.setattr(mod, "SAMPLE_DEEDS_DIR", sample_dir)
    monkeypatch.setattr(mod, "SAMPLE_PDFS", [("ease.pdf", "ease")])
    monkeypatch.setattr(
        mod,
        "PDFProcessor",
        lambda: type("P", (), {"process_deed_pdf": lambda _self, _p: legal_desc})(),
    )
    monkeypatch.setattr(
        mod.ClosureChecker, "verify_closure", staticmethod(lambda *_a, **_kw: [easement_closure])
    )
    monkeypatch.setattr(
        mod.CSVBuilder,
        "legal_description_to_csv",
        staticmethod(lambda _ld, p: Path(p).write_text("csv", encoding="utf-8")),
    )
    monkeypatch.setattr(mod.CSVBuilder, "export_verified_csv", staticmethod(lambda **_kw: []))

    mod.main()
    out = capsys.readouterr().out
    assert "✓ CLOSES" not in out
    assert "✓ VERIFIED" not in out
    assert "⚠ OPEN ease.pdf" in out


# ---------------------------------------------------------------------------
# 5. scripts/build_claude_plugin.py: duplicate / PEP 503 wheel rejection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "wheels",
    [
        [
            Path("mp_models-1.0.0-py3-none-any.whl"),
            Path("mp_models-1.0.0-cp312-none-any.whl"),
        ],
        [
            Path("mp_models-1.0.0-py3-none-any.whl"),
            Path("Mp.Models-1.0.0-py3-none-any.whl"),
        ],
        [
            Path("mp.models-1.0.0-py3-none-any.whl"),
            Path("mp_models-2.0.0-py3-none-any.whl"),
        ],
    ],
)
def test_runtime_project_rejects_duplicate_and_pep503_equivalent_wheels(
    wheels: list[Path],
) -> None:
    """Duplicate package names (even same version or PEP 503 variants) must raise ValueError."""
    builder = _load_script("build_claude_plugin.py")
    with pytest.raises(ValueError):
        builder.runtime_project(wheels)
