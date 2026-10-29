"""Relative geometry stays separate from canonical bearings and verified export."""

from pathlib import Path

import pytest

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "plugins/metesparser/skills/deed-closure-dashboard/references/relative-rectangle.json"
)


def test_documented_example_matches_package_and_legacy_facade() -> None:
    from mp_verify import analyze_relative as package_analyze

    from metesparser import analyze_relative
    from metesparser.relative import RelativeDescription

    description = RelativeDescription.model_validate_json(FIXTURE.read_bytes())
    before = description.model_dump()
    result = analyze_relative(description)

    assert analyze_relative is package_analyze
    assert result.model_dump() == package_analyze(description).model_dump()
    assert result.status == "analyzed"
    assert result.misclosure_ft == pytest.approx(0, abs=1e-10)
    assert result.area_sq_ft == pytest.approx(5000)
    assert result.perimeter_ft == pytest.approx(300)
    assert result.stated_angle_sum_deg == pytest.approx(360)
    assert result.engine_verified is False
    assert result.verified_export_eligible is False
    assert description.model_dump() == before
    assert all(c.recorded_bearing_azimuth_deg_from_north is None for c in description.courses)


@pytest.mark.parametrize("legacy", [False, True], ids=["package", "monolith"])
def test_relative_analysis_cannot_promote_canonical_export(tmp_path: Path, legacy: bool) -> None:
    from metesparser.relative import RelativeDescription, analyze_relative

    if legacy:
        from metesparser import ClosureChecker, CSVBuilder
        from metesparser.models import DeedCall

        verify = ClosureChecker.verify_closure
        export = CSVBuilder.export_verified_csv
    else:
        from mp_export import export_verified_csv as export
        from mp_models import DeedCall
        from mp_verify import verify_closure as verify

    directions = ["Northerly", "Easterly", "Southerly", "Westerly"]
    distances = [100, 50, 100, 50]
    calls = [
        DeedCall(
            course=i + 1,
            direction_text=direction,
            distance_ft=distance,
            notes="incomplete bearing - cardinal only",
        )
        for i, (direction, distance) in enumerate(zip(directions, distances, strict=True))
    ]
    before = [c.model_dump() for c in calls]
    local = analyze_relative(RelativeDescription.model_validate_json(FIXTURE.read_bytes()))
    assert local.status == "analyzed"
    canonical = verify(calls)
    assert not canonical.is_fully_verified()
    with pytest.raises(ValueError, match="Cannot export verified CSV"):
        export(calls, canonical, str(tmp_path / "record.csv"))

    # A successful result for another traverse must not bypass fresh verification.
    known = [
        DeedCall(
            course=i + 1,
            direction_text=f"Azimuth {i * 90}",
            distance_ft=distance,
            bearing_azimuth_deg_from_north=i * 90,
        )
        for i, distance in enumerate(distances)
    ]
    passed = verify(known)
    assert passed.is_fully_verified()
    with pytest.raises(ValueError):
        export(calls, passed, str(tmp_path / "substituted.csv"))
    assert not list(tmp_path.iterdir())
    assert [c.model_dump() for c in calls] == before
