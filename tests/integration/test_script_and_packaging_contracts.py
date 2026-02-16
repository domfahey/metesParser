from __future__ import annotations

import importlib.util
import tomllib
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from metesparser.models import ClosureResult, DeedCall, LegalDescription

pytestmark = pytest.mark.integration


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


def test_extract_sample_deeds_script_points_to_repo_sample_deeds() -> None:
    module = _load_script_module("extract_sample_deeds.py")
    expected = Path(module.__file__).resolve().parent.parent / "sample_deeds"
    assert module.SAMPLE_DEEDS_DIR == expected


def test_generate_ground_truth_notes_uses_runtime_timestamp(tmp_path: Path) -> None:
    module = _load_script_module("generate_ground_truth.py")

    class FakeProcessor:
        def extract_text_from_pdf(self, pdf_path: str) -> str:
            return "RAW"

        def extract_legal_description(self, pdf_path: str) -> str:
            return "THENCE N 45° E 100 feet to a point"

        def normalize_legal_description(self, legal_desc_text: str) -> str:
            return legal_desc_text

    pdf_path = tmp_path / "example.pdf"
    pdf_path.write_bytes(b"%PDF")

    result = module.generate_ground_truth(pdf_path, FakeProcessor())
    notes = result["notes"]

    assert notes.startswith("Ground truth generated at ")
    timestamp = notes.removeprefix("Ground truth generated at ")
    datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


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


def test_wheel_build_config_force_includes_packaged_prompts() -> None:
    pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text())

    force_include = (
        pyproject.get("tool", {})
        .get("hatch", {})
        .get("build", {})
        .get("targets", {})
        .get("wheel", {})
        .get("force-include", {})
    )

    assert force_include.get("src/metesparser/prompts") == "metesparser/prompts"


def test_root_package_exports_documented_public_classes() -> None:
    import metesparser

    assert hasattr(metesparser, "PDFProcessor")
    assert hasattr(metesparser, "ClosureChecker")
    assert hasattr(metesparser, "CallExtractor")
    assert hasattr(metesparser, "CSVBuilder")
    assert hasattr(metesparser, "TextParser")
    assert hasattr(metesparser, "LegalDescription")
