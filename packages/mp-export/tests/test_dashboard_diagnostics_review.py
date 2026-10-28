"""Independent B review regressions for finite browser sensitivity math."""

import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest
from mp_models.deed_call import DeedCall
from mp_models.diagnostics import (
    ClosureDiagnosticRequest,
    DiagnosticCall,
    DiagnosticFrame,
    diagnostic_input_hash,
)
from mp_verify.diagnostics import diagnose_closure

SCRIPT = Path(__file__).resolve().parents[1] / "src/mp_export/dashboard_assets/dashboard.js"


def diagnoses(distances):
    calls = tuple(
        DiagnosticCall(
            call_id=f"c{i}",
            call=DeedCall(
                course=i,
                direction_text="Explicit synthetic straight course",
                distance_ft=distance,
                bearing_azimuth_deg_from_north=angle,
            ),
        )
        for i, (distance, angle) in enumerate(zip(distances, (90, 180, 270, 0), strict=True), 1)
    )
    request = ClosureDiagnosticRequest(
        request_id="independent-browser-check",
        input_id="rectangle",
        calls=calls,
        input_sha256=diagnostic_input_hash(calls),
        frame=DiagnosticFrame(name="Explicit synthetic local bearings"),
    )
    expected = diagnose_closure(request)
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node unavailable for independent browser math")
    payload = {
        "calculation": {"method": "canonical", "occurrence_id": "occ"},
        "calls": [
            {"id": c.call_id, "occurrence_id": "occ", "call": c.call.model_dump(mode="json")}
            for c in calls
        ],
    }
    source = "const math=require(process.argv[1]); const i=JSON.parse(require('fs').readFileSync(0,'utf8')); process.stdout.write(JSON.stringify(math.diagnoseScenario(i.calculation,i.calls)));"
    completed = subprocess.run(
        [node, "-e", source, str(SCRIPT)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
    )
    return expected, json.loads(completed.stdout)


@pytest.mark.parametrize("scale", [1e155, 1e200, 1e300])
def test_finite_angle_projections_normalize_residual_before_multiplication(scale):
    expected, actual = diagnoses((1.005 * scale, scale, scale, scale))
    assert expected.availability == actual["availability"] == "supported"
    assert expected.ranking_available and actual["ranking_available"]
    for browser, python in zip(actual["sensitivities"], expected.sensitivities, strict=True):
        assert browser["angle_projection_abs_per_arcsecond"] == pytest.approx(
            python.angle_projection_abs_per_arcsecond, rel=1e-10
        )
        assert browser["angle_rank"] == python.angle_rank


def test_binary_ulp_threshold_matches_python_just_below_power_of_two():
    base = 128.0
    north_south = math.nextafter(math.nextafter(base, 0), 0)
    expected, actual = diagnoses((base + 1e-12, north_south, base - 1e-12, north_south))
    perimeter = math.fsum((base + 1e-12, north_south, base - 1e-12, north_south))
    assert perimeter < 512
    assert expected.numerical_zero_threshold_ft == 32 * math.ulp(perimeter)
    assert actual["numerical_zero_threshold_ft"] == expected.numerical_zero_threshold_ft
    assert actual["ranking_available"] == expected.ranking_available
