import hashlib
import json

import pytest
from mp_models.deed_call import DeedCall
from mp_models.diagnostics import (
    ClosureDiagnosticRequest,
    DiagnosticCall,
    DiagnosticFrame,
    diagnostic_input_hash,
)
from mp_review.diagnostics import diagnose_closure_file
from mp_verify.diagnostics import diagnose_closure


def source_bytes():
    calls = tuple(
        DiagnosticCall(
            call_id=f"c{i}",
            call=DeedCall(
                course=i,
                direction_text="verbatim",
                bearing_azimuth_deg_from_north=angle,
                distance_ft=distance,
            ),
        )
        for i, (angle, distance) in enumerate(((90, 100.5), (180, 100), (270, 100), (0, 100)), 1)
    )
    req = ClosureDiagnosticRequest(
        request_id="r1",
        input_id="parcel",
        calls=calls,
        input_sha256=diagnostic_input_hash(calls),
        frame=DiagnosticFrame(name="Recorded"),
    )
    return (" \n" + json.dumps(req.model_dump(mode="json"), indent=4) + "\n").encode()


def test_retains_exact_bytes_manifest_and_advisory_no_exports(tmp_path):
    data = source_bytes()
    path = tmp_path / "input.json"
    path.write_bytes(data)
    output = tmp_path / "out"
    result = diagnose_closure_file(path, output)
    assert result["status"] == "needs_review"
    assert result["verified_export_eligible"] is False
    assert result["engine_verified"] is False
    assert (output / "request.json").read_bytes() == data
    expected = diagnose_closure(ClosureDiagnosticRequest.model_validate_json(data))
    assert json.loads((output / "diagnostics.json").read_text()) == expected.model_dump(mode="json")
    manifest = json.loads((output / "diagnostics-manifest.json").read_text())
    assert manifest["source_sha256"] == hashlib.sha256(data).hexdigest()
    assert (
        manifest["diagnostics_sha256"]
        == hashlib.sha256((output / "diagnostics.json").read_bytes()).hexdigest()
    )
    assert manifest["input_sha256"] == expected.input_sha256
    assert manifest["request_sha256"] == expected.request_sha256
    assert sorted(p.name for p in output.iterdir()) == [
        "diagnostics-manifest.json",
        "diagnostics.json",
        "request.json",
    ]
    assert diagnose_closure_file(path, output)["status"] == "error"
    assert path.read_bytes() == data


def test_invalid_input_leaves_no_output(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"calls":[],"calls":[]}')
    assert diagnose_closure_file(path, tmp_path / "out")["status"] == "error"
    assert not (tmp_path / "out").exists()


def test_unknown_course_is_completed_advisory(tmp_path):
    data = json.loads(source_bytes())
    data["calls"][0]["call"]["bearing_azimuth_deg_from_north"] = None
    calls = tuple(DiagnosticCall.model_validate(c) for c in data["calls"])
    data["input_sha256"] = diagnostic_input_hash(calls)
    path = tmp_path / "in.json"
    path.write_text(json.dumps(data))
    result = diagnose_closure_file(path, tmp_path / "out")
    assert result["status"] == "needs_review"
    assert result["diagnostics"]["availability"] == "incomplete"


def test_committed_synthetic_fixture_uses_public_identity_contract(tmp_path):
    from pathlib import Path

    path = Path(__file__).parent / "fixtures/diagnostics/request.json"
    request = ClosureDiagnosticRequest.model_validate_json(path.read_bytes())
    result = diagnose_closure_file(path, tmp_path / "fixture-out")
    assert result["status"] == "needs_review"
    assert request.input_sha256 == diagnostic_input_hash(request.calls)
    assert result["diagnostics"]["residual"]["magnitude_ft"] == pytest.approx(0.5, abs=1e-10)
