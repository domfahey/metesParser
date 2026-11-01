"""PR #60 round 37: CSV import validates each row's width, BOMs and blank rows.

A short row used to be padded with None (a truncated spiral became circular, an exception
row a boundary). Every data row must have exactly as many cells as the header; fully
empty rows are skipped everywhere; an Excel UTF-8 BOM is tolerated.
"""

from __future__ import annotations

import csv
import io

import mp_export.csv_writer as package_writer
import pytest
from mp_models import DeedCall
from mp_review.api import verify_file
from mp_review.plot import plot_file

from metesparser.csv_builder import CSVBuilder


def _good_lines() -> list[str]:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=package_writer.FIELDNAMES, lineterminator="\n")
    writer.writeheader()
    for i, az in enumerate([0, 90, 180, 270], 1):
        call = DeedCall(
            course=i,
            direction_text=f"c{i}",
            bearing_azimuth_deg_from_north=float(az),
            distance_ft=100.0,
        )
        writer.writerow(package_writer._call_to_row(call))
    return out.getvalue().splitlines()


@pytest.fixture(params=["package", "monolith"])
def read(request):
    if request.param == "package":
        return package_writer.csv_text_to_calls
    return CSVBuilder.csv_text_to_calls


@pytest.fixture
def lines():
    return _good_lines()


def _short(line: str) -> str:
    return ",".join(line.split(",")[:5])


def test_truncated_row_strict_raises(read, lines):
    text = "\n".join([*lines[:2], _short(lines[2]), *lines[3:]]) + "\n"
    with pytest.raises(ValueError, match=r"invalid CSV row 3: expected 22 cells, got 5"):
        read(text)


def test_truncated_row_non_strict_is_rejected_not_imported(read, lines):
    text = "\n".join([*lines[:2], _short(lines[2]), *lines[3:]]) + "\n"
    rejected: list[tuple[int, str]] = []
    calls = read(text, strict=False, rejected_rows=rejected)
    assert len(calls) == 3
    assert [r for r, _ in rejected] == [3]
    assert "expected 22 cells, got 5" in rejected[0][1]
    with pytest.raises(ValueError):
        read(text, strict=False)


def test_overlong_row_strict_and_non_strict(read, lines):
    text = "\n".join([lines[0], lines[1] + ",extra", *lines[2:]]) + "\n"
    with pytest.raises(ValueError, match="expected 22 cells, got 23"):
        read(text)
    rejected: list[tuple[int, str]] = []
    assert len(read(text, strict=False, rejected_rows=rejected)) == 3
    assert rejected[0][0] == 2


def test_legacy_header_short_row_rejected(read, lines):
    idx = package_writer.FIELDNAMES.index("curve_type")
    rows = [",".join(package_writer.LEGACY_FIELDNAMES)]
    for line in lines[1:]:
        cells = line.split(",")
        rows.append(",".join(cells[:idx] + cells[idx + 1 :]))
    rows[2] = _short(rows[2])
    with pytest.raises(ValueError, match="expected 21 cells, got 5"):
        read("\n".join(rows) + "\n")


def test_bom_text_and_file_import(read, lines, tmp_path):
    text = "﻿" + "\n".join(lines) + "\n"
    assert len(read(text)) == 4
    path = tmp_path / "excel.csv"
    path.write_bytes(text.encode("utf-8"))
    assert len(package_writer.csv_to_calls(str(path))) == 4
    assert len(CSVBuilder.csv_to_calls(str(path))) == 4


def test_blank_rows_are_skipped_consistently(read, lines):
    text = "\n".join([lines[0], lines[1], "", lines[2], "", *lines[3:]]) + "\n\n"
    assert len(read(text)) == 4


def test_review_csv_blank_rows_ok_and_short_row_error(lines, tmp_path):
    ok = tmp_path / "ok.csv"
    ok.write_text("\n".join([lines[0], lines[1], "", *lines[2:]]) + "\n")
    assert len(verify_file(ok)["calls"]) == 4
    bad = tmp_path / "bad.csv"
    bad.write_text("\n".join([*lines[:2], _short(lines[2]), *lines[3:]]) + "\n")
    result = verify_file(bad)
    assert result["status"] == "error"
    assert result["calls"] == []


def test_plot_csv_blank_rows_ok_and_short_row_error(lines, tmp_path):
    ok = tmp_path / "ok.csv"
    ok.write_text("\n".join([lines[0], lines[1], "", *lines[2:]]) + "\n")
    assert plot_file(ok, tmp_path / "ok-out")["status"] == "needs_review"
    bad = tmp_path / "bad.csv"
    bad.write_text("\n".join([*lines[:2], _short(lines[2]), *lines[3:]]) + "\n")
    assert plot_file(bad, tmp_path / "bad-out")["status"] == "error"
    assert not (tmp_path / "bad-out").exists()
