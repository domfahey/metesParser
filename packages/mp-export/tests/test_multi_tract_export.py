"""Tests for multi-tract CSV export."""

from pathlib import Path

from mp_export.csv_writer import export_verified_csv
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


class TestMultiTractExport:
    def test_single_tract_returns_list(self, tmp_path: Path):
        result = export_verified_csv(
            _square_calls(),
            _good_closure(),
            str(tmp_path / "deed.csv"),
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert "_verified" in result[0].stem

    def test_multi_tract_returns_multiple_paths(self, tmp_path: Path):
        t1 = Tract(label="Tract 1", tract_type=TractType.MAIN, calls=_square_calls(100.0))
        # Exception/easement tracts are never exported (see test_pr60_r52_*).
        t2 = Tract(label="Addition 1", tract_type=TractType.ADDITION, calls=_square_calls(50.0))
        result = export_verified_csv(
            _square_calls(),
            _good_closure(),
            str(tmp_path / "deed.csv"),
            tract_results=[(t1, _good_closure(10000)), (t2, _good_closure(2500))],
        )
        assert isinstance(result, list)
        assert len(result) == 2
        assert "tract1" in result[0].stem
        assert "tract2" in result[1].stem

    def test_multi_tract_files_exist(self, tmp_path: Path):
        t1 = Tract(label="Tract 1", tract_type=TractType.MAIN, calls=_square_calls(100.0))
        t2 = Tract(label="Tract 2", tract_type=TractType.MAIN, calls=_square_calls(50.0))
        paths = export_verified_csv(
            _square_calls(),
            _good_closure(),
            str(tmp_path / "deed.csv"),
            tract_results=[(t1, _good_closure(10000)), (t2, _good_closure(2500))],
        )
        for p in paths:
            assert p.exists()

    def test_backward_compat_no_return_value(self, tmp_path: Path):
        """Existing callers that ignore return value still work."""
        export_verified_csv(
            _square_calls(),
            _good_closure(),
            str(tmp_path / "deed.csv"),
        )
        # Just verify no exception - callers that don't capture return are fine
        verified = tmp_path / "deed_verified.csv"
        assert verified.exists()

    def test_failed_tract_skipped(self, tmp_path: Path):
        """Tracts that fail verification are NOT exported."""
        t1 = Tract(label="Tract 1", tract_type=TractType.MAIN, calls=_square_calls(100.0))
        t2 = Tract(label="Tract 2", tract_type=TractType.MAIN, calls=_square_calls(50.0))
        bad_closure = ClosureResult(
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
        result = export_verified_csv(
            _square_calls(),
            _good_closure(),
            str(tmp_path / "deed.csv"),
            tract_results=[(t1, _good_closure(10000)), (t2, bad_closure)],
        )
        assert len(result) == 1
        assert "tract1" in result[0].stem


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


class TestMultiTractGate:
    def test_no_verified_tract_raises_and_writes_nothing(self, tmp_path: Path):
        import pytest

        t1 = Tract(label="Tract 1", tract_type=TractType.MAIN, calls=_square_calls(100.0))
        with pytest.raises(ValueError, match="Cannot export verified CSV"):
            export_verified_csv(
                _square_calls(),
                _good_closure(),
                str(tmp_path / "deed.csv"),
                tract_results=[(t1, _bad_closure())],
            )
        assert list(tmp_path.iterdir()) == []

    def test_mixed_summary_lists_unverified_tracts_separately(self, tmp_path: Path):
        t1 = Tract(label="Tract 1", tract_type=TractType.MAIN, calls=_square_calls(100.0))
        t2 = Tract(label="Tract 2", tract_type=TractType.MAIN, calls=_square_calls(50.0))
        export_verified_csv(
            _square_calls(),
            _good_closure(),
            str(tmp_path / "deed.csv"),
            tract_results=[(t1, _good_closure(10000)), (t2, _bad_closure())],
        )
        summary = (tmp_path / "deed_verified.verification.txt").read_text()
        verified_part, _, not_verified_part = summary.partition("Not verified (no CSV written):")
        assert "Tract 1" in verified_part
        assert "Tract 2" not in verified_part
        assert "Tract 2" in not_verified_part


class TestUnverifiedTractSummary:
    def test_unverified_tract_listed_in_not_verified_section(self, tmp_path: Path):
        t1 = Tract(label="Tract 1", tract_type=TractType.MAIN, calls=_square_calls(100.0))
        t2 = Tract(label="Tract 2", tract_type=TractType.MAIN, calls=_square_calls(50.0))
        export_verified_csv(
            _square_calls(),
            _good_closure(),
            str(tmp_path / "deed.csv"),
            tract_results=[(t1, _good_closure(10000)), (t2, _bad_closure())],
        )
        assert (tmp_path / "deed_verified_tract1.csv").exists()
        assert not (tmp_path / "deed_verified_tract2.csv").exists()

        summary = (tmp_path / "deed_verified.verification.txt").read_text()
        header = "Not verified (no CSV written):"
        verified_part, sep, not_verified_part = summary.partition(header)
        assert sep == header
        assert "Tract 1" in verified_part
        assert "Tract 2" not in verified_part
        assert "Tract 2" in not_verified_part
        assert "7.0700 ft" in not_verified_part
        assert "Closure failed" in not_verified_part
