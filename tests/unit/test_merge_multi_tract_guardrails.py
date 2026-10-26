"""Keep hardened verification/export gates when integrating multi-tract support."""

import pytest
from mp_export import export_verified_csv
from mp_models import DeedCall, Tract, TractType
from mp_verify import verify_closure, verify_tract

from metesparser.closure_checker import ClosureChecker
from metesparser.csv_builder import CSVBuilder


def square(size=100):
    return [
        DeedCall(
            course=i + 1, direction_text=str(a), bearing_azimuth_deg_from_north=a, distance_ft=size
        )
        for i, a in enumerate((0, 90, 180, 270))
    ]


@pytest.mark.parametrize("verify", [verify_tract, ClosureChecker.verify_tract])
def test_multi_tract_verification_rejects_crossing_boundaries(verify):
    calls = [
        DeedCall(
            course=i + 1, direction_text=str(a), bearing_azimuth_deg_from_north=a, distance_ft=d
        )
        for i, (a, d) in enumerate(
            ((45, 2**0.5 * 100), (270, 100), (135, 2**0.5 * 100), (270, 100))
        )
    ]
    result = verify(calls)
    assert not result.is_fully_verified()
    assert any("intersect" in w.lower() for w in result.warnings)


@pytest.mark.parametrize("export", [export_verified_csv, CSVBuilder.export_verified_csv])
def test_multi_tract_export_rechecks_result_against_selected_calls(export, tmp_path):
    calls = square()
    result = verify_closure(calls)
    changed = calls[:-1] + [calls[-1].model_copy(update={"distance_ft": 150})]
    if export == CSVBuilder.export_verified_csv:
        from metesparser.models import DeedCall as LegacyCall
        from metesparser.models import Tract as LegacyTract
        from metesparser.models import TractType as LegacyTractType

        calls = [LegacyCall.model_validate(c.model_dump()) for c in calls]
        changed = [LegacyCall.model_validate(c.model_dump()) for c in changed]
        result = ClosureChecker.verify_closure(calls)
        tract = LegacyTract(label="Tract A", tract_type=LegacyTractType.MAIN, calls=changed)
    else:
        tract = Tract(label="Tract A", tract_type=TractType.MAIN, calls=changed)
    with pytest.raises(ValueError, match="fresh verification|does not match"):
        export(calls, result, str(tmp_path / "calls.csv"), tract_results=[(tract, result)])
    assert not list(tmp_path.iterdir())
