"""Tests for mp_export CSV writer module."""

from __future__ import annotations

import csv

import pytest


def _make_closure_result(*, closure_passed=True, misclosure_ft=0.0, area_sq_ft=10000.0, **kw):
    """Create a ClosureResult with all required fields populated."""
    from mp_models import ClosureResult

    defaults = {
        "misclosure_x_ft": 0.0,
        "misclosure_y_ft": 0.0,
        "misclosure_ft": misclosure_ft,
        "area_sq_ft": area_sq_ft,
        "area_acres": area_sq_ft / 43560.0,
        "perimeter_ft": 400.0,
        "closure_passed": closure_passed,
        "angle_check_passed": True,
        "curve_consistency_passed": True,
        "warnings": [],
    }
    defaults.update(kw)
    return ClosureResult(**defaults)


def test_csv_fieldnames_count():
    """FIELDNAMES should have exactly 22 fields matching the CSV schema."""
    from mp_export.csv_writer import FIELDNAMES

    assert len(FIELDNAMES) == 22


def test_fieldnames_order():
    """FIELDNAMES must maintain the canonical column order."""
    from mp_export.csv_writer import FIELDNAMES

    assert FIELDNAMES[0] == "course"
    assert FIELDNAMES[1] == "direction_text"
    assert FIELDNAMES[4] == "distance_ft"
    assert FIELDNAMES[20] == "notes"
    assert FIELDNAMES[-1] == "curve_type"


def test_calls_to_csv_creates_file(tmp_path):
    """calls_to_csv should create a CSV file with header and data rows."""
    from mp_export.csv_writer import calls_to_csv
    from mp_models import DeedCall

    calls = [
        DeedCall(
            course=1,
            direction_text="North 45 East",
            bearing_quadrant="N 45\u00b000' E",
            bearing_azimuth_deg_from_north=45.0,
            distance_ft=100.0,
        ),
    ]
    out = tmp_path / "test.csv"
    calls_to_csv(calls, str(out))
    assert out.exists()
    with open(out) as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["course"] == "1"
    assert rows[0]["bearing_azimuth_deg_from_north"] == "45.000000"
    assert rows[0]["distance_ft"] == "100.00"


def test_calls_to_csv_boolean_fields(tmp_path):
    """Boolean fields should be written as 'true'/'false' strings."""
    from mp_export.csv_writer import calls_to_csv
    from mp_models import DeedCall

    calls = [
        DeedCall(
            course=1,
            direction_text="North 45 East",
            bearing_quadrant="N 45\u00b000' E",
            bearing_azimuth_deg_from_north=45.0,
            distance_ft=100.0,
            is_exception=True,
            non_tangent=True,
        ),
    ]
    out = tmp_path / "test.csv"
    calls_to_csv(calls, str(out))
    with open(out) as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert rows[0]["is_exception"] == "true"
    assert rows[0]["non_tangent"] == "true"
    assert rows[0]["is_meander"] == "false"


def test_calls_to_csv_with_metadata(tmp_path):
    """calls_to_csv should write a metadata sidecar file when metadata provided."""
    from mp_export.csv_writer import calls_to_csv
    from mp_models import DeedCall

    calls = [
        DeedCall(
            course=1,
            direction_text="North",
            bearing_quadrant="N 00\u00b000' E",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=50.0,
        ),
    ]
    out = tmp_path / "test.csv"
    calls_to_csv(calls, str(out), metadata={"source_doc": "deed.pdf"})
    metadata_path = tmp_path / "test.metadata.txt"
    assert metadata_path.exists()
    content = metadata_path.read_text()
    assert "source_doc: deed.pdf" in content


def test_csv_to_calls_roundtrip(tmp_path):
    """csv_to_calls should reconstruct DeedCall objects from a CSV file."""
    from mp_export.csv_writer import calls_to_csv, csv_to_calls
    from mp_models import DeedCall

    calls = [
        DeedCall(
            course=1,
            direction_text="North 45 East",
            bearing_quadrant="N 45\u00b000' E",
            bearing_azimuth_deg_from_north=45.0,
            distance_ft=100.0,
        ),
    ]
    out = tmp_path / "test.csv"
    calls_to_csv(calls, str(out))
    loaded = csv_to_calls(str(out))
    assert len(loaded) == 1
    assert loaded[0].course == 1
    assert loaded[0].distance_ft == 100.0
    assert loaded[0].bearing_azimuth_deg_from_north == 45.0


def test_csv_to_calls_skips_invalid_rows(tmp_path):
    """Non-strict csv_to_calls records rejected rows; it never drops them silently."""
    from mp_export.csv_writer import FIELDNAMES, csv_to_calls

    out = tmp_path / "bad.csv"
    with open(out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        # Write a row with missing required fields
        writer.writerow(dict.fromkeys(FIELDNAMES, ""))

    with pytest.raises(ValueError, match="rejected_rows"):
        csv_to_calls(str(out), strict=False)
    rejected: list[tuple[int, str]] = []
    loaded = csv_to_calls(str(out), strict=False, rejected_rows=rejected)
    assert len(loaded) == 0
    assert [row for row, _ in rejected] == [2]


def test_call_to_row_empty_optional_fields():
    """Optional fields should produce empty strings when None."""
    from mp_export.csv_writer import _call_to_row
    from mp_models import DeedCall

    call = DeedCall(
        course=1,
        direction_text="North",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=100.0,
    )
    row = _call_to_row(call)
    assert row["bearing_quadrant"] == ""
    assert row["curve_dir"] == ""
    assert row["along"] == ""
    assert row["monument_type"] == ""


def test_legal_description_to_csv(tmp_path):
    """legal_description_to_csv should export calls and metadata from a LegalDescription."""
    from mp_export.csv_writer import legal_description_to_csv
    from mp_models import DeedCall, LegalDescription

    ld = LegalDescription(
        calls=[
            DeedCall(
                course=1,
                direction_text="North",
                bearing_quadrant="N 00\u00b000' E",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=100.0,
            ),
        ],
        source_doc="test_deed.pdf",
    )
    out = tmp_path / "legal.csv"
    legal_description_to_csv(ld, str(out))
    assert out.exists()
    metadata_path = tmp_path / "legal.metadata.txt"
    assert metadata_path.exists()


def test_export_verified_csv_rejects_unverified(tmp_path):
    """export_verified_csv should raise ValueError if closure checks failed."""
    import pytest
    from mp_export.csv_writer import export_verified_csv
    from mp_models import DeedCall

    calls = [
        DeedCall(
            course=1,
            direction_text="North",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=100.0,
        ),
    ]
    result = _make_closure_result(
        closure_passed=False,
        misclosure_ft=5.0,
        area_sq_ft=0.0,
        warnings=["test warning"],
    )
    with pytest.raises(ValueError, match="verification checks failed"):
        export_verified_csv(calls, result, str(tmp_path / "out.csv"))


def test_export_verified_csv_creates_verified_file(tmp_path):
    """export_verified_csv should create a _verified.csv and .verification.txt."""
    from mp_export.csv_writer import export_verified_csv
    from mp_models import DeedCall

    calls = [
        DeedCall(
            course=1,
            direction_text="North",
            bearing_quadrant="N 00\u00b000' E",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=100.0,
        ),
        DeedCall(
            course=2,
            direction_text="East",
            bearing_quadrant="N 90\u00b000' E",
            bearing_azimuth_deg_from_north=90.0,
            distance_ft=100.0,
        ),
        DeedCall(
            course=3,
            direction_text="South",
            bearing_quadrant="S 00\u00b000' E",
            bearing_azimuth_deg_from_north=180.0,
            distance_ft=100.0,
        ),
        DeedCall(
            course=4,
            direction_text="West",
            bearing_quadrant="N 90\u00b000' W",
            bearing_azimuth_deg_from_north=270.0,
            distance_ft=100.0,
        ),
    ]
    from mp_verify import verify_closure

    result = verify_closure(calls)
    out = tmp_path / "deed.csv"
    export_verified_csv(calls, result, str(out))
    verified_path = tmp_path / "deed_verified.csv"
    assert verified_path.exists()
    summary_path = tmp_path / "deed_verified.verification.txt"
    assert summary_path.exists()


def test_export_verified_csv_with_audit_context(tmp_path):
    """export_verified_csv should write audit JSON and HTML when audit_context provided."""
    from datetime import UTC, datetime

    from mp_export.csv_writer import export_verified_csv
    from mp_models import AuditContext, DeedCall, RunMetadata

    calls = [
        DeedCall(
            course=1,
            direction_text="North",
            bearing_quadrant="N 00\u00b000' E",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=100.0,
        ),
        DeedCall(
            course=2,
            direction_text="East",
            bearing_quadrant="N 90\u00b000' E",
            bearing_azimuth_deg_from_north=90.0,
            distance_ft=100.0,
        ),
        DeedCall(
            course=3,
            direction_text="South",
            bearing_quadrant="S 00\u00b000' E",
            bearing_azimuth_deg_from_north=180.0,
            distance_ft=100.0,
        ),
        DeedCall(
            course=4,
            direction_text="West",
            bearing_quadrant="N 90\u00b000' W",
            bearing_azimuth_deg_from_north=270.0,
            distance_ft=100.0,
        ),
    ]
    from mp_verify import verify_closure

    result = verify_closure(calls)
    rm = RunMetadata(
        parser_version="1.0.0",
        llm_provider="openai",
        llm_model="gpt-5",
        prompt_hash="abc123",
        timestamp_utc=datetime.now(UTC),
        source_pdf="deed.pdf",
        cache_enabled=True,
    )
    ctx = AuditContext(run_metadata=rm)
    out = tmp_path / "deed.csv"
    export_verified_csv(calls, result, str(out), audit_context=ctx)

    verified_path = tmp_path / "deed_verified.csv"
    assert verified_path.exists()
    audit_json = tmp_path / "deed_verified.audit.json"
    assert audit_json.exists()
    audit_html = tmp_path / "deed_verified.audit.html"
    assert audit_html.exists()


def test_legacy_curved_row_notes_circular_assumption():
    """A 21-column row cannot state a spiral, so its circular reading is noted."""
    from mp_export.csv_writer import (
        LEGACY_CURVE_NOTE,
        LEGACY_FIELDNAMES,
        _call_to_row,
        csv_text_to_calls,
    )
    from mp_models import DeedCall

    curve = DeedCall(
        course=1,
        direction_text="along a spiral curve to the right",
        distance_ft=49.5,
        curve_type="spiral",
        curve_dir="right",
        radius_ft=100.0,
        arc_length_ft=50.0,
        notes="per plat",
    )
    line = DeedCall(
        course=2, direction_text="N 0 E", bearing_azimuth_deg_from_north=0.0, distance_ft=10.0
    )
    lines = [",".join(LEGACY_FIELDNAMES)]
    for call in (curve, line):
        row = _call_to_row(call)
        lines.append(",".join(f'"{row[name]}"' for name in LEGACY_FIELDNAMES))
    loaded = csv_text_to_calls("\n".join(lines) + "\n")
    assert loaded[0].curve_type is None
    assert loaded[0].notes == f"per plat; {LEGACY_CURVE_NOTE}"
    assert loaded[1].notes is None
