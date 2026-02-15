from __future__ import annotations

import importlib.util
import math
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker
from metesparser.models import ClosureResult, DeedCall, LegalDescription


def _load_script_module(script_name: str):
    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "scripts" / script_name
    spec = importlib.util.spec_from_file_location(f"test_{script_name}", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sample_closure_result() -> ClosureResult:
    return ClosureResult(
        misclosure_x_ft=0.0,
        misclosure_y_ft=0.0,
        misclosure_ft=0.0,
        area_sq_ft=100.0,
        area_acres=100.0 / 43560.0,
        perimeter_ft=100.0,
        closure_passed=True,
        angle_check_passed=True,
        curve_consistency_passed=True,
        warnings=[],
    )


def test_extract_calls_skips_incomplete_curve_and_continues() -> None:
    text = (
        "THENCE along a curve to the right having a radius of 50 feet to a point; "
        "THENCE N 10° E 100 feet to a point"
    )

    calls = CallExtractor.extract_calls(text)
    assert len(calls) == 1
    assert calls[0].course == 1
    assert math.isclose(calls[0].distance_ft, 100.0, abs_tol=0.001)


def test_compute_traverse_moves_curve_with_radius_and_arc_length_without_delta() -> None:
    call = DeedCall(
        course=1,
        direction_text="curve",
        bearing_azimuth_deg_from_north=90.0,
        distance_ft=25.0,
        curve_dir="right",
        radius_ft=50.0,
        arc_length_ft=25.0,
    )

    points = ClosureChecker.compute_traverse([call])
    assert len(points) == 2
    assert math.hypot(points[-1].x, points[-1].y) > 0.0


def test_compute_traverse_treats_zero_delta_curve_as_straight_distance() -> None:
    call = DeedCall(
        course=1,
        direction_text="curve",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=100.0,
        curve_dir="left",
        radius_ft=50.0,
        delta_deg=0.0,
        arc_length_ft=0.0,
        chord_length_ft=0.0,
    )

    points = ClosureChecker.compute_traverse([call])
    assert len(points) == 2
    assert math.isclose(points[-1].x, 0.0, abs_tol=0.001)
    assert math.isclose(points[-1].y, 100.0, abs_tol=0.001)


def test_extract_sample_deeds_report_shows_zero_azimuth_and_runtime_timestamp(
    tmp_path: Path,
) -> None:
    module = _load_script_module("extract_sample_deeds.py")
    legal_desc = LegalDescription(
        source_doc="example.pdf",
        calls=[
            DeedCall(
                course=1,
                direction_text="N 0° E",
                bearing_quadrant="N 0° E",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=100.0,
            )
        ],
    )
    output_file = tmp_path / "report.txt"

    module.create_extraction_report(legal_desc, _sample_closure_result(), output_file)
    report = output_file.read_text()
    report_lines = report.splitlines()

    assert "Source PDF: example.pdf" in report_lines
    assert any(line == "Azimuth:         0.00°" for line in report_lines)
    date_lines = [line for line in report.splitlines() if line.startswith("Date Extracted: ")]
    assert len(date_lines) == 1
    date_line = date_lines[0]
    timestamp = date_line.removeprefix("Date Extracted: ").strip()
    datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


def test_31_pennbrook_script_prints_zero_azimuth(monkeypatch, capsys) -> None:
    module = _load_script_module("test_31_pennbrook_text.py")
    fake_call = DeedCall(
        course=1,
        direction_text="N 0° E",
        bearing_quadrant="N 0° E",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=10.0,
    )

    monkeypatch.setattr(
        module,
        "TextParser",
        SimpleNamespace(
            normalize_legal_description=lambda text: "normalized",
            extract_pob=lambda text: "POB",
            split_into_calls=lambda text: ["N 0° E 10 feet to a point"],
        ),
    )
    monkeypatch.setattr(
        module,
        "CallExtractor",
        SimpleNamespace(extract_calls=lambda text: [fake_call]),
    )
    monkeypatch.setattr(
        module,
        "ClosureChecker",
        SimpleNamespace(verify_closure=lambda calls: _sample_closure_result()),
    )

    module.main()
    output = capsys.readouterr().out
    output_lines = output.splitlines()
    assert "CALL 1:" in output_lines
    assert any(line == "  Azimuth:    0.00°" for line in output_lines)
    assert any(line.startswith("Closure Status: ") for line in output_lines)
