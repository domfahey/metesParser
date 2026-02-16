from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

from metesparser import cli
from metesparser.models import DeedCall, LegalDescription


def _verified_square_calls() -> list[DeedCall]:
    return [
        DeedCall(
            course=1,
            direction_text="North",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=100.0,
        ),
        DeedCall(
            course=2,
            direction_text="East",
            bearing_azimuth_deg_from_north=90.0,
            distance_ft=100.0,
        ),
        DeedCall(
            course=3,
            direction_text="South",
            bearing_azimuth_deg_from_north=180.0,
            distance_ft=100.0,
        ),
        DeedCall(
            course=4,
            direction_text="West",
            bearing_azimuth_deg_from_north=270.0,
            distance_ft=100.0,
        ),
    ]


def _open_traverse_calls() -> list[DeedCall]:
    return [
        DeedCall(
            course=1,
            direction_text="North",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=100.0,
        ),
        DeedCall(
            course=2,
            direction_text="East",
            bearing_azimuth_deg_from_north=90.0,
            distance_ft=100.0,
        ),
    ]


def _stub_processor(legal_desc: LegalDescription):
    class _Processor:
        def process_deed_pdf(self, _pdf_path: str) -> LegalDescription:
            return legal_desc

    return lambda provider=None, **kwargs: _Processor()


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    """Read CSV rows and assert the export shape is valid."""
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert rows, "Expected CLI-exported CSV to contain at least one row"
    assert rows[0].keys() >= {"course", "direction_text", "distance_ft"}
    return rows


@pytest.mark.e2e
def test_cli_extract_and_verify_railcar_flow_happy_path(monkeypatch, tmp_path, capsys):
    pdf_path = tmp_path / "parcel.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    legal_desc = LegalDescription(
        source_doc="parcel.pdf",
        pob_description="a point",
        calls=_verified_square_calls(),
    )
    monkeypatch.setattr("metesparser.pdf_processor.PDFProcessor", _stub_processor(legal_desc))

    monkeypatch.setattr(sys, "argv", ["metesparser", "extract", str(pdf_path)])
    cli.main()

    extract_output = capsys.readouterr().out
    verified_csv = tmp_path / "parcel_verified.csv"
    verification_txt = verified_csv.with_suffix(".verification.txt")
    metadata_txt = verified_csv.with_suffix(".metadata.txt")
    verified_rows = _read_csv_rows(verified_csv)

    assert verified_csv.exists()
    assert verification_txt.exists()
    assert metadata_txt.exists()
    assert len(verified_rows) == 4
    expected_verified = [
        ("1", "North", 100.0),
        ("2", "East", 100.0),
        ("3", "South", 100.0),
        ("4", "West", 100.0),
    ]
    for row, expected in zip(verified_rows, expected_verified, strict=True):
        assert row["course"] == expected[0]
        assert row["direction_text"] == expected[1]
        assert float(row["distance_ft"]) == pytest.approx(expected[2], abs=0.001)
    assert "CLOSURE VERIFICATION SUMMARY" in extract_output
    assert "Status: FULLY VERIFIED ✓" in verification_txt.read_text(encoding="utf-8")
    assert "source_doc: parcel.pdf" in metadata_txt.read_text(encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["metesparser", "verify", str(verified_csv)])
    cli.main()

    verify_output = capsys.readouterr().out
    assert "Status: FULLY VERIFIED ✓" in verify_output


@pytest.mark.e2e
def test_cli_extract_and_verify_open_traverse_is_rejected(monkeypatch, tmp_path, capsys):
    pdf_path = tmp_path / "open_traverse.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    legal_desc = LegalDescription(
        source_doc="open_traverse.pdf",
        pob_description="a point",
        calls=_open_traverse_calls(),
    )
    monkeypatch.setattr("metesparser.pdf_processor.PDFProcessor", _stub_processor(legal_desc))

    monkeypatch.setattr(sys, "argv", ["metesparser", "extract", str(pdf_path)])
    cli.main()

    unverified_csv = tmp_path / "open_traverse.csv"
    unverified_rows = _read_csv_rows(unverified_csv)

    assert unverified_csv.exists()
    assert len(unverified_rows) == 2
    expected_unverified = [
        ("1", "North", 100.0),
        ("2", "East", 100.0),
    ]
    for row, expected in zip(unverified_rows, expected_unverified, strict=True):
        assert row["course"] == expected[0]
        assert row["direction_text"] == expected[1]
        assert float(row["distance_ft"]) == pytest.approx(expected[2], abs=0.001)

    monkeypatch.setattr(sys, "argv", ["metesparser", "verify", str(unverified_csv)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    verify_output = capsys.readouterr().out
    assert "Status: NEEDS REVIEW" in verify_output
