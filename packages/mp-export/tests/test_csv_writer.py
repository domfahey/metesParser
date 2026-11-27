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


def test_csv_fieldnames_canonical_schema_and_order():
    """FIELDNAMES must declare the exact 22-column canonical CSV schema in order."""
    from mp_export.csv_writer import FIELDNAMES

    expected = [
        "course",
        "direction_text",
        "bearing_quadrant",
        "bearing_azimuth_deg_from_north",
        "distance_ft",
        "curve_dir",
        "radius_ft",
        "delta_deg",
        "arc_length_ft",
        "chord_bearing",
        "chord_length_ft",
        "along",
        "to",
        "monument_type",
        "monument_status",
        "is_exception",
        "is_meander",
        "is_tie_in",
        "non_tangent",
        "radial_bearing",
        "notes",
        "curve_type",
    ]
    assert FIELDNAMES == expected
    assert len(FIELDNAMES) == 22


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


def test_calls_to_csv_empty_optional_fields(tmp_path):
    """Optional fields should be written as empty strings when None."""
    from mp_export.csv_writer import calls_to_csv
    from mp_models import DeedCall

    call = DeedCall(
        course=1,
        direction_text="North",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=100.0,
    )
    out = tmp_path / "optional.csv"
    calls_to_csv([call], str(out))
    with open(out, encoding="utf-8") as f:
        [row] = list(csv.DictReader(f))
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


def test_legacy_curved_row_notes_circular_assumption(tmp_path):
    """A 21-column row cannot state a spiral, so its circular reading is noted."""
    import io

    from mp_export.csv_writer import (
        LEGACY_CURVE_NOTE,
        LEGACY_FIELDNAMES,
        calls_to_csv,
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
    full_csv = tmp_path / "full.csv"
    calls_to_csv([curve, line], str(full_csv))
    legacy_buf = io.StringIO()
    with open(full_csv, encoding="utf-8") as src:
        writer = csv.DictWriter(
            legacy_buf, fieldnames=LEGACY_FIELDNAMES, extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(csv.DictReader(src))
    loaded = csv_text_to_calls(legacy_buf.getvalue())
    assert loaded[0].curve_type is None
    assert loaded[0].notes == f"per plat; {LEGACY_CURVE_NOTE}"
    assert loaded[1].notes is None


def _square_calls(side: float = 100.0) -> list:
    from mp_models import DeedCall

    return [
        DeedCall(
            course=1,
            direction_text="North",
            bearing_quadrant="N 00\u00b000' E",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=side,
        ),
        DeedCall(
            course=2,
            direction_text="East",
            bearing_quadrant="N 90\u00b000' E",
            bearing_azimuth_deg_from_north=90.0,
            distance_ft=side,
        ),
        DeedCall(
            course=3,
            direction_text="South",
            bearing_quadrant="S 00\u00b000' E",
            bearing_azimuth_deg_from_north=180.0,
            distance_ft=side,
        ),
        DeedCall(
            course=4,
            direction_text="West",
            bearing_quadrant="N 90\u00b000' W",
            bearing_azimuth_deg_from_north=270.0,
            distance_ft=side,
        ),
    ]


def test_csv_header_validation_rejects_missing_unexpected_and_reordered_columns():
    from mp_export.csv_writer import FIELDNAMES, csv_text_to_calls

    with pytest.raises(ValueError, match="missing columns"):
        csv_text_to_calls("")

    with pytest.raises(ValueError, match="missing columns"):
        csv_text_to_calls("course,direction_text\n")

    with pytest.raises(ValueError, match="unexpected columns"):
        csv_text_to_calls(",".join([*FIELDNAMES, "extra_col"]) + "\n")

    reordered = list(reversed(FIELDNAMES))
    with pytest.raises(ValueError, match="duplicated or out of order"):
        csv_text_to_calls(",".join(reordered) + "\n")


def test_csv_text_to_calls_blank_lines_spirals_width_errors_and_malformed_csv(tmp_path):
    from mp_export.csv_writer import FIELDNAMES, calls_to_csv, csv_text_to_calls
    from mp_models import DeedCall

    header = ",".join(FIELDNAMES)
    spiral = DeedCall(
        course=1,
        direction_text="along a spiral curve to the right",
        distance_ft=None,
        curve_type="spiral",
        curve_dir="right",
        radius_ft=100.0,
        delta_deg=30.0,
    )
    spiral_csv = tmp_path / "spiral.csv"
    calls_to_csv([spiral], str(spiral_csv))
    spiral_row = spiral_csv.read_text(encoding="utf-8").splitlines()[1]

    # BOM prefix and blank lines are handled; spiral with blank distance_ft is accepted.
    loaded = csv_text_to_calls(f"\ufeff{header}\n\n{spiral_row}\n\n")
    assert len(loaded) == 1
    assert loaded[0].curve_type == "spiral"
    assert loaded[0].distance_ft is None

    # Non-spiral with blank distance_ft fails strict import and records in non-strict mode.
    non_spiral_row = ",".join(["1", "North", "", "0.0", "", *([""] * (len(FIELDNAMES) - 5))])
    with pytest.raises(ValueError, match="invalid CSV row 2"):
        csv_text_to_calls(f"{header}\n{non_spiral_row}\n", strict=True)

    # Row width mismatch fails strict import with cell count detail and is captured non-strictly.
    short_row = "1,North"
    with pytest.raises(ValueError, match="expected 22 cells, got 2"):
        csv_text_to_calls(f"{header}\n{short_row}\n", strict=True)
    rejected: list[tuple[int, str]] = []
    assert csv_text_to_calls(f"{header}\n{short_row}\n", strict=False, rejected_rows=rejected) == []
    assert rejected[0][0] == 2 and "expected 22 cells" in rejected[0][1]

    # Unclosed quote triggers csv.Error -> ValueError with malformed CSV context.
    with pytest.raises(ValueError, match="malformed CSV"):
        csv_text_to_calls(f'{header}\n1,"unterminated quote\n')


def test_calls_to_csv_cleans_up_stale_verified_sidecars(tmp_path):
    from mp_export.csv_writer import calls_to_csv

    out = tmp_path / "parcel_verified.csv"
    stale_sidecars = [
        out.with_suffix(".metadata.txt"),
        out.with_suffix(".verification.txt"),
        out.with_suffix(".audit.json"),
        out.with_suffix(".audit.html"),
    ]
    for path in stale_sidecars:
        path.write_text("stale content", encoding="utf-8")

    calls_to_csv(_square_calls(), str(out))
    for path in stale_sidecars:
        assert not path.exists()


def test_legal_description_to_csv_tract_attribution_fallbacks_and_role_marks(tmp_path):
    from mp_export.csv_writer import csv_to_calls, legal_description_to_csv
    from mp_models import (
        DESCRIPTION_ROLES_NOTE,
        DeedCall,
        LegalDescription,
        Tract,
        TractType,
        non_boundary_marks,
    )

    main_calls = _square_calls(100.0)
    exc_calls = _square_calls(20.0)
    eas_calls = _square_calls(10.0)

    # 1. Calls match a sole boundary tract verbatim (with a distinct easement tract) -> stays unmarked.
    ld_sole = LegalDescription(
        calls=main_calls,
        tracts=[
            Tract(
                label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=main_calls
            ),
            Tract(
                label="Easement 1",
                tract_type=TractType.EASEMENT,
                role_basis="heading",
                calls=eas_calls,
            ),
        ],
    )
    out_sole = tmp_path / "sole.csv"
    legal_description_to_csv(ld_sole, str(out_sole))
    loaded_sole = csv_to_calls(str(out_sole))
    assert not non_boundary_marks(loaded_sole)

    # 2. Combined flat calls across MAIN + EXCEPTION + EASEMENT -> attributes & marks non-boundary.
    ld_mixed = LegalDescription(
        calls=[*main_calls, *exc_calls, *eas_calls],
        tracts=[
            Tract(
                label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=main_calls
            ),
            Tract(
                label="Exception 1",
                tract_type=TractType.EXCEPTION,
                role_basis="heading",
                calls=exc_calls,
            ),
            Tract(
                label="Easement 1",
                tract_type=TractType.EASEMENT,
                role_basis="heading",
                calls=eas_calls,
            ),
        ],
    )
    out_mixed = tmp_path / "mixed.csv"
    legal_description_to_csv(ld_mixed, str(out_mixed))
    loaded_mixed = csv_to_calls(str(out_mixed))
    assert not non_boundary_marks(loaded_mixed[:4])
    assert all(c.is_exception for c in loaded_mixed[4:8])
    assert "exception" in non_boundary_marks(loaded_mixed[4:8])
    assert "easement" in non_boundary_marks(loaded_mixed[8:12])

    # 3. Ambiguous partial subset shared across boundary & non-boundary tracts fails closed
    #    to the non-boundary slot (including via course-number-insensitive fallback matching).
    shared_course = DeedCall(
        course=1, direction_text="North", bearing_azimuth_deg_from_north=0.0, distance_ft=50.0
    )
    renumbered_copy = shared_course.model_copy(update={"course": 9})
    ld_ambiguous = LegalDescription(
        calls=[renumbered_copy],
        tracts=[
            Tract(
                label="Tract 1",
                tract_type=TractType.MAIN,
                role_basis="heading",
                calls=[shared_course],
            ),
            Tract(
                label="Easement 1",
                tract_type=TractType.EASEMENT,
                role_basis="heading",
                calls=[shared_course.model_copy()],
            ),
        ],
    )
    out_ambig = tmp_path / "ambig.csv"
    legal_description_to_csv(ld_ambiguous, str(out_ambig))
    assert "easement" in non_boundary_marks(csv_to_calls(str(out_ambig)))

    # 4. Non-boundary-only tracts + an extra unattributed flat call falls back to exception marks.
    extra_call = DeedCall(
        course=99, direction_text="East", bearing_azimuth_deg_from_north=90.0, distance_ft=15.0
    )
    ld_exc_only = LegalDescription(
        calls=[extra_call],
        tracts=[
            Tract(
                label="Exception 1",
                tract_type=TractType.EXCEPTION,
                role_basis="heading",
                calls=exc_calls,
            )
        ],
    )
    out_exc_only = tmp_path / "exc_only.csv"
    legal_description_to_csv(ld_exc_only, str(out_exc_only))
    loaded_exc_only = csv_to_calls(str(out_exc_only))
    assert loaded_exc_only[0].is_exception is True
    assert "exception" in non_boundary_marks(loaded_exc_only)

    # 5. Empty flat calls with populated tracts exports tracts directly with marks;
    #    inferred multi-tract roles stamp DESCRIPTION_ROLES_NOTE on every call (both with and
    #    without flat calls).
    ld_inferred_flat = LegalDescription(
        calls=main_calls,
        tracts=[
            Tract(
                label="Tract 1", tract_type=TractType.MAIN, role_basis="inferred", calls=main_calls
            ),
            Tract(
                label="Easement 1",
                tract_type=TractType.EASEMENT,
                role_basis="inferred",
                calls=eas_calls,
            ),
        ],
    )
    out_inf_flat = tmp_path / "inferred_flat.csv"
    legal_description_to_csv(ld_inferred_flat, str(out_inf_flat))
    assert all(DESCRIPTION_ROLES_NOTE in (c.notes or "") for c in csv_to_calls(str(out_inf_flat)))

    ld_tracts_only = LegalDescription(
        calls=[],
        tracts=[
            Tract(
                label="Tract 1", tract_type=TractType.MAIN, role_basis="inferred", calls=main_calls
            ),
            Tract(
                label="Exception 1",
                tract_type=TractType.EXCEPTION,
                role_basis="inferred",
                calls=exc_calls,
            ),
        ],
    )
    out_tracts = tmp_path / "tracts_only.csv"
    legal_description_to_csv(ld_tracts_only, str(out_tracts))
    loaded_tracts = csv_to_calls(str(out_tracts))
    assert len(loaded_tracts) == 8
    assert all(DESCRIPTION_ROLES_NOTE in (c.notes or "") for c in loaded_tracts)
    assert all(c.is_exception for c in loaded_tracts[4:])

    # 6. Completely empty LegalDescription writes header-only CSV.
    out_empty = tmp_path / "empty.csv"
    legal_description_to_csv(LegalDescription(), str(out_empty))
    assert csv_to_calls(str(out_empty)) == []


def test_export_verified_csv_gate_enforces_fresh_verification_roles_and_results_match(tmp_path):
    from mp_export.csv_writer import _validate_export_geometry, export_verified_csv
    from mp_models import (
        CheckResult,
        ClosureResult,
        LegalDescription,
        SkippedCourse,
        Tract,
        TractType,
        mark_non_boundary,
    )
    from mp_verify import verify_closure

    calls = _square_calls(100.0)
    fresh = verify_closure(calls)

    # 1. Forged passing ClosureResult on an open traverse is rejected by fresh verification.
    open_calls = [*calls[:-1], calls[-1].model_copy(update={"distance_ft": 50.0})]
    with pytest.raises(ValueError, match="selected calls failed fresh verification"):
        export_verified_csv(open_calls, fresh, str(tmp_path / "open.csv"))

    # 2. Tampered ClosureResult metrics / checks on closed calls are rejected.
    with pytest.raises(ValueError, match="closure result does not match selected calls"):
        export_verified_csv(
            calls, fresh.model_copy(update={"perimeter_ft": 999.0}), str(tmp_path / "tampered.csv")
        )
    with pytest.raises(ValueError, match="closure result does not match selected calls"):
        export_verified_csv(
            calls,
            fresh.model_copy(update={"checks": fresh.checks[:-1]}),
            str(tmp_path / "short_checks.csv"),
        )
    tampered_checks = [
        c.model_copy(update={"detail": "forged"}) if c.name == "traverse_closure" else c
        for c in fresh.checks
    ]
    with pytest.raises(ValueError, match="closure result does not match selected calls"):
        export_verified_csv(
            calls,
            fresh.model_copy(update={"checks": tampered_checks}),
            str(tmp_path / "forged_check.csv"),
        )

    # 3. Historical ClosureResult (without checks/source_review_status in model_fields_set) exports.
    historical_payload = fresh.model_dump(
        exclude={"checks", "source_review_status", "confidence_score"}
    )
    historical = ClosureResult(**historical_payload)
    assert not ({"checks", "source_review_status"} & historical.model_fields_set)
    written_hist = export_verified_csv(calls, historical, str(tmp_path / "hist.csv"))
    assert written_hist[0].exists()

    # 4. External passing double_entry check is accepted when double_entry_calls=None,
    #    and rejected if a mismatched double_entry result is forged when double_entry_calls is passed.
    de_result = verify_closure(calls, double_entry_calls=calls)
    written_de = export_verified_csv(calls, de_result, str(tmp_path / "de.csv"))
    assert written_de[0].exists()
    bad_de_checks = [
        CheckResult(
            name="double_entry", status="passed", passed=True, reason="check_passed", detail="ok"
        )
        if c.name == "double_entry"
        else c
        for c in fresh.checks
    ]
    # When double_entry_calls is explicitly passed as None-equivalent (mismatched vs calls), fresh fails.
    with pytest.raises(ValueError, match="closure result does not match selected calls"):
        export_verified_csv(
            calls,
            fresh.model_copy(
                update={
                    "checks": [
                        c.model_copy(update={"detail": "different detail"})
                        if c.name == "double_entry"
                        else c
                        for c in bad_de_checks
                    ]
                }
            ),
            str(tmp_path / "de_mismatch.csv"),
            double_entry_calls=calls,
        )

    # 5. LegalDescription.calls mismatch & _validate_export_geometry stated_area_sq_ft fallback.
    ld_mismatch = LegalDescription(calls=_square_calls(50.0))
    with pytest.raises(ValueError, match="calls do not match LegalDescription.calls"):
        export_verified_csv(calls, fresh, str(tmp_path / "mismatch.csv"), legal_desc=ld_mismatch)

    ld_area = LegalDescription(calls=calls, stated_area_sq_ft=10000.0)
    res_area = verify_closure(calls, stated_area_sq_ft=10000.0)
    sel_calls, fresh_area = _validate_export_geometry(calls, res_area, ld_area)
    assert len(sel_calls) == 4 and fresh_area.is_fully_verified()

    # 6. Calls carrying non-boundary marks or role-review marks are rejected in single-tract mode.
    marked = mark_non_boundary(calls, TractType.EASEMENT)
    with pytest.raises(ValueError, match="easement"):
        export_verified_csv(marked, fresh, str(tmp_path / "marked.csv"))

    # 7. Single-tract mode with LegalDescription.tracts enforces tract role & area consistency.
    inferred_ld = LegalDescription(
        calls=calls,
        tracts=[
            Tract(label="Tract 1", tract_type=TractType.MAIN, role_basis="inferred", calls=calls),
            Tract(
                label="Easement 1",
                tract_type=TractType.EASEMENT,
                role_basis="inferred",
                calls=_square_calls(10.0),
            ),
        ],
    )
    with pytest.raises(ValueError, match="description roles need review"):
        export_verified_csv(calls, fresh, str(tmp_path / "inferred.csv"), legal_desc=inferred_ld)

    easement_only_ld = LegalDescription(
        calls=calls,
        tracts=[
            Tract(
                label="Easement 1", tract_type=TractType.EASEMENT, role_basis="heading", calls=calls
            )
        ],
    )
    with pytest.raises(ValueError, match="no parcel boundary tract"):
        export_verified_csv(
            calls, fresh, str(tmp_path / "eas_only.csv"), legal_desc=easement_only_ld
        )

    two_boundary_ld = LegalDescription(
        calls=calls,
        tracts=[
            Tract(label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=calls),
            Tract(
                label="Addition 1",
                tract_type=TractType.ADDITION,
                role_basis="heading",
                calls=_square_calls(50.0),
            ),
        ],
    )
    with pytest.raises(ValueError, match="multiple boundary tracts require multi-tract"):
        export_verified_csv(
            calls, fresh, str(tmp_path / "two_bound.csv"), legal_desc=two_boundary_ld
        )

    exc_ld = LegalDescription(
        calls=calls,
        tracts=[
            Tract(label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=calls),
            Tract(
                label="Exception 1",
                tract_type=TractType.EXCEPTION,
                role_basis="heading",
                calls=_square_calls(10.0),
            ),
        ],
    )
    with pytest.raises(ValueError, match="exception tracts require multi-tract"):
        export_verified_csv(calls, fresh, str(tmp_path / "exc_single.csv"), legal_desc=exc_ld)

    wrong_calls_ld = LegalDescription(
        calls=calls,
        tracts=[
            Tract(
                label="Tract 1",
                tract_type=TractType.MAIN,
                role_basis="heading",
                calls=_square_calls(50.0),
            )
        ],
    )
    with pytest.raises(ValueError, match="calls do not match the boundary tract"):
        export_verified_csv(
            calls, fresh, str(tmp_path / "wrong_tract_calls.csv"), legal_desc=wrong_calls_ld
        )

    area_conflict_ld = LegalDescription(
        calls=calls,
        stated_area_sq_ft=10000.0,
        tracts=[
            Tract(
                label="Tract 1",
                tract_type=TractType.MAIN,
                role_basis="heading",
                calls=calls,
                stated_area_sq_ft=2500.0,
            )
        ],
    )
    with pytest.raises(ValueError, match="conflicts with boundary tract stated_area_sq_ft"):
        export_verified_csv(
            calls, res_area, str(tmp_path / "area_conflict.csv"), legal_desc=area_conflict_ld
        )

    # Tract-level skipped_courses blocks single-tract export via fresh verification.
    skipped_ld = LegalDescription(
        calls=calls,
        tracts=[
            Tract(
                label="Tract 1",
                tract_type=TractType.MAIN,
                role_basis="heading",
                calls=calls,
                skipped_courses=[
                    SkippedCourse(
                        course=5,
                        source_course=5,
                        tract_label="Tract 1",
                        source_excerpt="garbled",
                        error_type="ValueError",
                        error="bad course",
                    )
                ],
            )
        ],
    )
    with pytest.raises(ValueError, match="selected calls failed fresh verification"):
        export_verified_csv(calls, fresh, str(tmp_path / "skipped.csv"), legal_desc=skipped_ld)


def test_export_verified_csv_multi_tract_validation_area_inheritance_and_marked_calls(tmp_path):
    from mp_export.csv_writer import export_verified_csv
    from mp_models import (
        LegalDescription,
        SkippedCourse,
        Tract,
        TractType,
        mark_non_boundary,
    )
    from mp_verify import verify_closure, verify_tract

    c1 = _square_calls(100.0)
    c2 = _square_calls(50.0)
    t1 = Tract(label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=c1)
    t2 = Tract(label="Tract 2", tract_type=TractType.ADDITION, role_basis="heading", calls=c2)
    r1 = verify_tract(c1)
    r2 = verify_tract(c2)

    # 1. Supplied tract missing from legal_desc.tracts raises ValueError.
    ld_t1_only = LegalDescription(tracts=[t1])
    with pytest.raises(ValueError, match="is not in legal_desc.tracts"):
        export_verified_csv(
            [],
            r1,
            str(tmp_path / "missing_tract.csv"),
            legal_desc=ld_t1_only,
            tract_results=[(t1, r1), (t2, r2)],
        )

    # 2. Supplied tract conflicting with same-label tract in legal_desc.tracts raises ValueError.
    t1_mutated = t1.model_copy(update={"calls": c2})
    with pytest.raises(ValueError, match="conflicts with legal_desc.tracts"):
        export_verified_csv(
            [],
            r2,
            str(tmp_path / "conflict_tract.csv"),
            legal_desc=ld_t1_only,
            tract_results=[(t1_mutated, r2)],
        )

    # 3. Duplicate label in legal_desc.tracts partially supplied raises conflict.
    t1_dup = Tract(label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=c2)
    ld_dup = LegalDescription(tracts=[t1, t1_dup])
    with pytest.raises(ValueError, match="conflicts with legal_desc.tracts"):
        export_verified_csv(
            [],
            r1,
            str(tmp_path / "dup_label.csv"),
            legal_desc=ld_dup,
            tract_results=[(t1, r1)],
        )

    # 4. Omitted tract in legal_desc.tracts stays in _known_tracts so its skip does not block t1.
    ld_two = LegalDescription(tracts=[t1, t2])
    skip_on_t2 = SkippedCourse(
        course=9,
        source_course=9,
        tract_label="Tract 2",
        source_excerpt="bad line",
        error_type="ValueError",
        error="unparseable",
    )
    written_omit = export_verified_csv(
        [],
        r1,
        str(tmp_path / "omitted_ok.csv"),
        legal_desc=ld_two,
        tract_results=[(t1, r1)],
        skipped_courses=[skip_on_t2],
    )
    assert [p.name for p in written_omit] == ["omitted_ok_verified_tract1.csv"]

    # 5. Multi-tract deed-level stated_area_sq_ft conflicts vs inherits for a sole boundary tract.
    eas = Tract(label="Easement 1", tract_type=TractType.EASEMENT, role_basis="heading", calls=c2)
    t1_with_area = t1.model_copy(update={"stated_area_sq_ft": 2500.0})
    ld_area_conflict = LegalDescription(stated_area_sq_ft=10000.0, tracts=[t1_with_area, eas])
    with pytest.raises(ValueError, match="conflicts with boundary tract stated_area_sq_ft"):
        export_verified_csv(
            [],
            r1,
            str(tmp_path / "mt_area_conflict.csv"),
            legal_desc=ld_area_conflict,
            tract_results=[
                (t1_with_area, r1),
                (eas, verify_closure([], tracts=[t1_with_area, eas])[1]),
            ],
        )

    ld_area_inherit = LegalDescription(stated_area_sq_ft=10000.0, tracts=[t1, eas])
    r1_area = verify_tract(c1, stated_area_sq_ft=10000.0)
    written_inherit = export_verified_csv(
        [],
        r1_area,
        str(tmp_path / "mt_area_inherit.csv"),
        legal_desc=ld_area_inherit,
        tract_results=[(t1, r1_area), (eas, verify_closure([], tracts=[t1, eas])[1])],
    )
    assert [p.name for p in written_inherit] == ["mt_area_inherit_verified_tract1.csv"]

    # 6. Double-entry call count mismatch in multi-tract mode raises ValueError.
    with pytest.raises(ValueError, match="Double-entry call count mismatch"):
        export_verified_csv(
            [],
            r1,
            str(tmp_path / "mt_de_mismatch.csv"),
            tract_results=[(t1, r1), (t2, r2)],
            double_entry_calls=c1,
        )

    # 7. MAIN tract carrying calls with non-boundary marks is skipped and reports its mark reason.
    marked_calls = mark_non_boundary(c2, TractType.EASEMENT)
    marked_main = Tract(
        label="Tainted Main", tract_type=TractType.MAIN, role_basis="heading", calls=marked_calls
    )
    marked_res = verify_tract(marked_calls)
    written_marked = export_verified_csv(
        [],
        r1,
        str(tmp_path / "marked_mt.csv"),
        tract_results=[(t1, r1), (marked_main, marked_res)],
    )
    assert [p.name for p in written_marked] == ["marked_mt_verified_tract1.csv"]
    summary = (tmp_path / "marked_mt_verified.verification.txt").read_text(encoding="utf-8")
    assert "Tainted Main" in summary and "easement" in summary
