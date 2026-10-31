"""PR #60 round 54: the not-exported reason derives from the exported tract itself."""

from __future__ import annotations

from pathlib import Path

from mp_export.csv_writer import export_verified_csv
from mp_models import DeedCall, Tract, TractType
from mp_verify import verify_closure


def _square(side: float = 100.0) -> list[DeedCall]:
    return [
        DeedCall(course=i + 1, direction_text=d, bearing_azimuth_deg_from_north=a, distance_ft=side)
        for i, (d, a) in enumerate((("N", 0.0), ("E", 90.0), ("S", 180.0), ("W", 270.0)))
    ]


def _summary(tmp_path: Path) -> str:
    return (tmp_path / "deed_verified.verification.txt").read_text()


def test_foreign_easement_result_is_a_mismatch_not_a_duplicate(tmp_path: Path) -> None:
    main = Tract(label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=_square())
    e1 = Tract(
        label="Easement 1", tract_type=TractType.EASEMENT, role_basis="heading", calls=_square(10.0)
    )
    e2 = Tract(
        label="Easement 2", tract_type=TractType.EASEMENT, role_basis="heading", calls=_square(20.0)
    )
    results = verify_closure([], tracts=[main, e1, e2])
    export_verified_csv(
        [],
        results[0],
        str(tmp_path / "deed.csv"),
        tract_results=[(main, results[0]), (e1, results[2])],
    )
    line = next(x for x in _summary(tmp_path).splitlines() if x.startswith("Easement 1:"))
    assert "does not belong to this tract" in line
    assert "Easement 2" not in line


def test_main_tract_with_easement_result_is_blocked_as_mismatch(tmp_path: Path) -> None:
    main = Tract(label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=_square())
    main2 = Tract(
        label="Tract 2", tract_type=TractType.MAIN, role_basis="heading", calls=_square(50.0)
    )
    e1 = Tract(
        label="Easement 1", tract_type=TractType.EASEMENT, role_basis="heading", calls=_square(10.0)
    )
    results = verify_closure([], tracts=[main, main2, e1])
    written = export_verified_csv(
        [],
        results[0],
        str(tmp_path / "deed.csv"),
        tract_results=[(main, results[0]), (main2, results[2])],
    )
    assert [p.name for p in written] == ["deed_verified_tract1.csv"]
    line = next(x for x in _summary(tmp_path).splitlines() if x.startswith("Tract 2:"))
    assert "does not belong to this tract" in line
    assert "not a parcel boundary" not in line


def test_own_result_reason_is_single_and_grammatical(tmp_path: Path) -> None:
    main = Tract(label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=_square())
    e1 = Tract(
        label="Easement 1", tract_type=TractType.EASEMENT, role_basis="heading", calls=_square(10.0)
    )
    results = verify_closure([], tracts=[main, e1])
    export_verified_csv(
        [],
        results[0],
        str(tmp_path / "deed.csv"),
        tract_results=list(zip([main, e1], results, strict=True)),
    )
    line = next(x for x in _summary(tmp_path).splitlines() if x.startswith("Easement 1:"))
    assert line.count("Easement 1 is an easement tract") == 1
    assert "a easement" not in line
