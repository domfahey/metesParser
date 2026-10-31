"""PR #60 round 52: only MAIN/ADDITION tracts are verified-export candidates.

Easement and exception tracts are never written as verified CSVs, even when the
supplied result claims eligibility (a tract-unaware ``verify_tract`` result).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from mp_export.csv_writer import export_verified_csv
from mp_models import DeedCall, Tract, TractType
from mp_verify import verify_closure, verify_tract


def _square(side: float = 100.0) -> list[DeedCall]:
    return [
        DeedCall(
            course=i + 1,
            direction_text=d,
            bearing_azimuth_deg_from_north=a,
            distance_ft=side,
        )
        for i, (d, a) in enumerate((("N", 0.0), ("E", 90.0), ("S", 180.0), ("W", 270.0)))
    ]


@pytest.mark.parametrize("kind", [TractType.EASEMENT, TractType.EXCEPTION])
@pytest.mark.parametrize("forged", [False, True])
def test_non_boundary_only_export_is_refused(tmp_path: Path, kind: TractType, forged: bool) -> None:
    tract = Tract(label="Other 1", tract_type=kind, calls=_square())
    # A forged result comes from tract-unaware verification and claims eligibility.
    result = verify_tract(tract.calls) if forged else verify_closure([], tracts=[tract])[0]
    with pytest.raises(ValueError, match="no parcel boundary tract"):
        export_verified_csv([], result, str(tmp_path / "deed.csv"), tract_results=[(tract, result)])
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("kind", [TractType.EASEMENT, TractType.EXCEPTION])
@pytest.mark.parametrize("forged", [False, True])
def test_boundary_plus_non_boundary_exports_only_boundary(
    tmp_path: Path, kind: TractType, forged: bool
) -> None:
    main = Tract(label="Tract 1", tract_type=TractType.MAIN, calls=_square())
    other = Tract(label="Other 1", tract_type=kind, calls=_square(10.0))
    results = verify_closure([], tracts=[main, other])
    other_result = verify_tract(other.calls) if forged else results[1]

    written = export_verified_csv(
        [],
        results[0],
        str(tmp_path / "deed.csv"),
        tract_results=[(main, results[0]), (other, other_result)],
    )

    assert [p.name for p in written] == ["deed_verified_tract1.csv"]
    assert not (tmp_path / "deed_verified_tract2.csv").exists()
    summary = (tmp_path / "deed_verified.verification.txt").read_text()
    assert "Other 1" in summary
    assert "not a parcel boundary" in summary


def test_addition_tract_still_exports(tmp_path: Path) -> None:
    main = Tract(label="Tract 1", tract_type=TractType.MAIN, calls=_square())
    addition = Tract(label="Addition 1", tract_type=TractType.ADDITION, calls=_square(10.0))
    results = verify_closure([], tracts=[main, addition])
    written = export_verified_csv(
        [],
        results[0],
        str(tmp_path / "deed.csv"),
        tract_results=list(zip([main, addition], results, strict=True)),
    )
    assert [p.name for p in written] == ["deed_verified_tract1.csv", "deed_verified_tract2.csv"]
