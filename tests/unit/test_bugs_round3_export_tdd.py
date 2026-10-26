"""Regression tests for verified CSV export provenance and sidecar replacement."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from mp_export import calls_to_csv as package_calls_to_csv
from mp_export import export_verified_csv as package_export_verified_csv
from mp_models import AuditContext as PackageAuditContext
from mp_models import DeedCall as PackageCall
from mp_models import LegalDescription as PackageLegalDescription
from mp_models import RunMetadata as PackageRunMetadata
from mp_verify import verify_closure as verify_package

from metesparser.closure_checker import ClosureChecker
from metesparser.csv_builder import CSVBuilder
from metesparser.models import AuditContext, DeedCall, LegalDescription, RunMetadata


def _square(call_type):
    return [
        call_type(
            course=i + 1,
            direction_text="boundary",
            bearing_azimuth_deg_from_north=azimuth,
            distance_ft=100,
        )
        for i, azimuth in enumerate((0, 90, 180, 270))
    ]


@pytest.fixture(params=["package", "monolith"])
def api(request):
    if request.param == "package":
        return (
            PackageCall,
            PackageLegalDescription,
            verify_package,
            package_export_verified_csv,
            package_calls_to_csv,
            PackageAuditContext,
            PackageRunMetadata,
        )
    return (
        DeedCall,
        LegalDescription,
        ClosureChecker.verify_closure,
        CSVBuilder.export_verified_csv,
        CSVBuilder.calls_to_csv,
        AuditContext,
        RunMetadata,
    )


def _audit_types(api, source_pdf="source-a.pdf"):
    audit_type, run_type = api[5:]
    run = run_type(
        parser_version="1.0.0",
        llm_provider="openai",
        llm_model="test-model",
        prompt_hash="test",
        timestamp_utc=datetime.now(UTC),
        source_pdf=source_pdf,
        cache_enabled=True,
    )
    return audit_type(run_metadata=run)


def test_verified_export_rejects_legal_description_with_different_calls(api, tmp_path):
    call_type, legal_type, verify, export = api[:4]
    calls = _square(call_type)
    result = verify(calls)
    changed = legal_type(calls=[calls[0]])
    output = tmp_path / "deed.csv"

    with pytest.raises(ValueError, match="calls do not match|selected calls|verification"):
        export(calls, result, str(output), legal_desc=changed)

    assert not (tmp_path / "deed_verified.csv").exists()
    assert not (tmp_path / "deed_verified.verification.txt").exists()


def test_verified_export_rejects_stale_result_for_different_closed_calls(api, tmp_path):
    call_type, _, verify, export = api[:4]
    original = _square(call_type)
    result = verify(original)
    # This is another closed 100 by 100 parcel, with the same area/perimeter.
    changed = [
        call_type(
            course=i + 1,
            direction_text="boundary",
            bearing_azimuth_deg_from_north=azimuth,
            distance_ft=100,
        )
        for i, azimuth in enumerate((90, 180, 270, 0))
    ]

    with pytest.raises(ValueError, match="match|selected calls|verification"):
        export(changed, result, str(tmp_path / "different.csv"))

    assert not (tmp_path / "different_verified.csv").exists()


def test_failed_preflight_preserves_existing_verified_artifacts(api, tmp_path):
    call_type, legal_type, verify, export = api[:4]
    calls = _square(call_type)
    output = tmp_path / "deed.csv"
    export(
        calls,
        verify(calls),
        str(output),
        legal_desc=legal_type(calls=calls, source_doc="existing.pdf"),
        audit_context=_audit_types(api),
    )
    artifact_paths = [
        tmp_path / "deed_verified.csv",
        tmp_path / "deed_verified.metadata.txt",
        tmp_path / "deed_verified.verification.txt",
        tmp_path / "deed_verified.audit.json",
        tmp_path / "deed_verified.audit.html",
    ]
    before = {path: path.read_bytes() for path in artifact_paths}

    with pytest.raises(ValueError, match="calls do not match"):
        export(calls, verify(calls), str(output), legal_desc=legal_type(calls=[calls[0]]))

    assert {path: path.read_bytes() for path in artifact_paths} == before


def test_verified_export_replaces_owned_sidecars_when_inputs_omitted(api, tmp_path):
    call_type, legal_type, verify, export = api[:4]
    calls = _square(call_type)
    first = legal_type(calls=calls, source_doc="source-a.pdf")
    output = tmp_path / "deed.csv"
    export(calls, verify(calls), str(output), legal_desc=first, audit_context=_audit_types(api))
    verified = tmp_path / "deed_verified.csv"
    sidecars = [
        tmp_path / "deed_verified.metadata.txt",
        tmp_path / "deed_verified.audit.json",
        tmp_path / "deed_verified.audit.html",
    ]
    assert all(path.exists() for path in sidecars)
    neighbor = tmp_path / "deed_verified.keep"
    neighbor.write_text("preserve")

    export(calls, verify(calls), str(output))

    assert not any(path.exists() for path in sidecars)
    assert neighbor.read_text() == "preserve"
    assert verified.exists()


def test_verified_export_sidecars_are_current_when_new_inputs_supplied(api, tmp_path):
    call_type, legal_type, verify, export = api[:4]
    calls = _square(call_type)
    output = tmp_path / "deed.csv"
    export(
        calls,
        verify(calls),
        str(output),
        legal_desc=legal_type(calls=calls, source_doc="old.pdf"),
        audit_context=_audit_types(api, "old-source.pdf"),
    )
    updated_calls = [
        call.model_copy(update={"direction_text": "updated boundary"}) for call in calls
    ]
    export(
        updated_calls,
        verify(updated_calls),
        str(output),
        legal_desc=legal_type(calls=updated_calls, source_doc="new.pdf"),
        audit_context=_audit_types(api, "new-source.pdf"),
    )

    metadata = (tmp_path / "deed_verified.metadata.txt").read_text()
    audit = json.loads((tmp_path / "deed_verified.audit.json").read_text())
    exported_calls = (tmp_path / "deed_verified.csv").read_text()
    assert "new.pdf" in metadata
    assert audit["run_metadata"]["source_pdf"] == "new-source.pdf"
    assert "updated boundary" in exported_calls
    assert (tmp_path / "deed_verified.audit.html").exists()


def test_direct_calls_to_csv_rewrite_cleans_exact_sidecars(api, tmp_path):
    call_type, legal_type, verify, export, calls_to_csv = api[:5]
    calls = _square(call_type)
    output = tmp_path / "deed.csv"
    export(
        calls,
        verify(calls),
        str(output),
        legal_desc=legal_type(calls=calls, source_doc="old.pdf"),
        audit_context=_audit_types(api),
    )
    neighbor = tmp_path / "deed_verified.keep"
    neighbor.write_text("preserve")
    updated_calls = [call.model_copy(update={"direction_text": "raw rewrite"}) for call in calls]

    calls_to_csv(updated_calls, str(tmp_path / "deed_verified.csv"))

    assert "raw rewrite" in (tmp_path / "deed_verified.csv").read_text()
    for suffix in (".metadata.txt", ".verification.txt", ".audit.json", ".audit.html"):
        assert not (tmp_path / f"deed_verified{suffix}").exists()
    assert neighbor.read_text() == "preserve"


def test_direct_calls_to_csv_rewrite_removes_stale_metadata(api, tmp_path):
    call_type, _, _, _, calls_to_csv = api[:5]
    calls = _square(call_type)
    output = tmp_path / "deed.csv"
    calls_to_csv(calls, str(output), {"source_doc": "old.pdf"})
    metadata = tmp_path / "deed.metadata.txt"
    assert metadata.exists()

    calls_to_csv(calls, str(output))

    assert not metadata.exists()
