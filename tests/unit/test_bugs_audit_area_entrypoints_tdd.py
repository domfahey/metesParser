"""Regression coverage for forwarding deed area into verification entrypoints."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from metesparser import cli
from metesparser.models import DeedCall, LegalDescription
from metesparser.pipeline import Pipeline


def _square_description() -> LegalDescription:
    return LegalDescription(
        calls=[
            DeedCall(
                course=index,
                direction_text=bearing,
                bearing_azimuth_deg_from_north=azimuth,
                distance_ft=100.0,
            )
            for index, (bearing, azimuth) in enumerate(
                (("N 90 E", 90.0), ("S 0 E", 180.0), ("S 90 W", 270.0), ("N 0 E", 0.0)),
                start=1,
            )
        ],
        source_doc="deed.pdf",
        stated_area_sq_ft=20_000.0,
    )


@pytest.mark.parametrize("audit", [False, True])
def test_pipeline_forwards_stated_area_for_verification(monkeypatch, audit):
    from mp_models import AuditContext

    from metesparser import pipeline

    description = _square_description()
    audit_context = (
        AuditContext(
            run_metadata={
                "parser_version": "test",
                "llm_provider": "test",
                "llm_model": "test",
                "prompt_hash": "test",
                "timestamp_utc": datetime.now(UTC),
                "source_pdf": "deed.pdf",
                "cache_enabled": False,
            }
        )
        if audit
        else None
    )

    def process_deed_pdf(_path: str, *, audit: bool):
        return (description, audit_context) if audit else description

    monkeypatch.setattr(
        pipeline,
        "PDFProcessor",
        lambda **_: SimpleNamespace(process_deed_pdf=process_deed_pdf),
    )

    result = Pipeline(audit=audit).run(Path("deed.pdf"))
    closure = result[0] if audit else result

    assert closure.area_sq_ft == pytest.approx(10_000.0)
    assert any("differs from stated by 50.0%" in warning for warning in closure.warnings)


def test_cli_extract_exports_unverified_csv_when_stated_area_mismatches(monkeypatch, tmp_path):
    pdf = tmp_path / "deed.pdf"
    pdf.write_text("mocked PDF")
    description = _square_description()
    exports: list[str] = []

    monkeypatch.setattr(
        "metesparser.pdf_processor.PDFProcessor",
        lambda **_: SimpleNamespace(process_deed_pdf=lambda _path: description),
    )
    monkeypatch.setattr(
        "metesparser.csv_builder.CSVBuilder.legal_description_to_csv",
        lambda _description, output_path: exports.append(output_path),
    )

    verified_exports: list[str] = []
    monkeypatch.setattr(
        "metesparser.csv_builder.CSVBuilder.export_verified_csv",
        lambda _calls, _closure, output_path, _description: verified_exports.append(output_path),
    )
    monkeypatch.setattr(cli, "RUNS_DIR", tmp_path / "runs")

    cli.extract_command(str(pdf), output=str(tmp_path / "out.csv"))

    assert exports == [str(tmp_path / "out.csv")]
    assert verified_exports == []
