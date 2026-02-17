"""Tests for multi-tract CSV export."""

from pathlib import Path

from mp_models import ClosureResult, DeedCall, Tract, TractType
from mp_export.csv_writer import export_verified_csv


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
    return ClosureResult(
        misclosure_x_ft=0.0,
        misclosure_y_ft=0.0,
        misclosure_ft=0.0,
        area_sq_ft=area,
        area_acres=area / 43560.0,
        perimeter_ft=400.0,
        closure_passed=True,
        angle_check_passed=True,
        curve_consistency_passed=True,
        warnings=[],
    )


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
        t2 = Tract(
            label="Exception 1", tract_type=TractType.EXCEPTION, calls=_square_calls(50.0)
        )
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
