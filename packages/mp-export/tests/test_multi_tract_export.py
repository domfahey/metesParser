"""Tests for multi-tract CSV export."""

from __future__ import annotations

from pathlib import Path

import pytest
from mp_export.csv_writer import csv_to_calls, export_verified_csv
from mp_models import ClosureResult, DeedCall, Tract, TractType


def _square_calls(size: float = 100.0) -> list[DeedCall]:
    return [
        DeedCall(
            course=1,
            direction_text="N 45\u00b000' E",
            bearing_quadrant="N 45\u00b000' E",
            bearing_azimuth_deg_from_north=45.0,
            distance_ft=size,
        ),
        DeedCall(
            course=2,
            direction_text="S 45\u00b000' E",
            bearing_quadrant="S 45\u00b000' E",
            bearing_azimuth_deg_from_north=135.0,
            distance_ft=size,
        ),
        DeedCall(
            course=3,
            direction_text="S 45\u00b000' W",
            bearing_quadrant="S 45\u00b000' W",
            bearing_azimuth_deg_from_north=225.0,
            distance_ft=size,
        ),
        DeedCall(
            course=4,
            direction_text="N 45\u00b000' W",
            bearing_quadrant="N 45\u00b000' W",
            bearing_azimuth_deg_from_north=315.0,
            distance_ft=size,
        ),
    ]


def _good_closure(area: float = 10000.0) -> ClosureResult:
    from mp_verify import verify_tract

    return verify_tract(_square_calls(area**0.5))


def _bad_closure() -> ClosureResult:
    return ClosureResult(
        misclosure_x_ft=5.0,
        misclosure_y_ft=5.0,
        misclosure_ft=7.07,
        area_sq_ft=2500.0,
        area_acres=2500.0 / 43560.0,
        perimeter_ft=200.0,
        closure_passed=False,
        angle_check_passed=True,
        curve_consistency_passed=True,
        warnings=["Closure failed"],
    )


class TestMultiTractExport:
    def test_single_tract_returns_verified_path_and_writes_calls(self, tmp_path: Path) -> None:
        result = export_verified_csv(
            _square_calls(),
            _good_closure(),
            str(tmp_path / "deed.csv"),
        )
        expected = tmp_path / "deed_verified.csv"
        assert result == [expected]
        assert expected.exists()
        assert len(csv_to_calls(str(expected))) == 4

    def test_multi_tract_writes_one_verified_csv_per_boundary_tract(self, tmp_path: Path) -> None:
        t1 = Tract(
            label="Tract 1",
            tract_type=TractType.MAIN,
            role_basis="heading",
            calls=_square_calls(100.0),
        )
        # Exception/easement tracts are never exported (see test_pr60_r52_*).
        t2 = Tract(
            label="Addition 1",
            tract_type=TractType.ADDITION,
            role_basis="heading",
            calls=_square_calls(50.0),
        )
        paths = export_verified_csv(
            _square_calls(),
            _good_closure(),
            str(tmp_path / "deed.csv"),
            tract_results=[(t1, _good_closure(10000)), (t2, _good_closure(2500))],
        )
        assert paths == [
            tmp_path / "deed_verified_tract1.csv",
            tmp_path / "deed_verified_tract2.csv",
        ]
        assert [len(csv_to_calls(str(p))) for p in paths] == [4, 4]
        assert [c.distance_ft for c in csv_to_calls(str(paths[0]))] == [100.0] * 4
        assert [c.distance_ft for c in csv_to_calls(str(paths[1]))] == [50.0] * 4

    def test_failed_tract_skipped_and_listed_in_not_verified_summary(self, tmp_path: Path) -> None:
        """Tracts that fail verification get no CSV and are separated in the verification summary."""
        t1 = Tract(
            label="Tract 1",
            tract_type=TractType.MAIN,
            role_basis="heading",
            calls=_square_calls(100.0),
        )
        t2 = Tract(
            label="Tract 2",
            tract_type=TractType.MAIN,
            role_basis="heading",
            calls=_square_calls(50.0),
        )
        result = export_verified_csv(
            _square_calls(),
            _good_closure(),
            str(tmp_path / "deed.csv"),
            tract_results=[(t1, _good_closure(10000)), (t2, _bad_closure())],
        )
        assert result == [tmp_path / "deed_verified_tract1.csv"]
        assert (tmp_path / "deed_verified_tract1.csv").exists()
        assert not (tmp_path / "deed_verified_tract2.csv").exists()

        summary = (tmp_path / "deed_verified.verification.txt").read_text(encoding="utf-8")
        header = "Not verified (no CSV written):"
        verified_part, sep, not_verified_part = summary.partition(header)
        assert sep == header
        assert "Tract 1" in verified_part
        assert "Tract 2" not in verified_part
        assert "Tract 2" in not_verified_part
        assert "7.0700 ft" in not_verified_part
        assert "Closure failed" in not_verified_part


class TestMultiTractGate:
    def test_no_verified_tract_raises_and_writes_nothing(self, tmp_path: Path) -> None:
        t1 = Tract(
            label="Tract 1",
            tract_type=TractType.MAIN,
            role_basis="heading",
            calls=_square_calls(100.0),
        )
        with pytest.raises(ValueError, match="no tract passed verification"):
            export_verified_csv(
                _square_calls(),
                _good_closure(),
                str(tmp_path / "deed.csv"),
                tract_results=[(t1, _bad_closure())],
            )
        assert list(tmp_path.iterdir()) == []
