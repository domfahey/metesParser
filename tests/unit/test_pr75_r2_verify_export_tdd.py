"""Red-Green TDD regression tests for PR #75 Track 2 (mp-verify & mp-export)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest
from mp_bearing.azimuth import degree_of_curvature_to_radius
from mp_bearing.curves import calculate_chord_bearing, calculate_missing_curve_elements
from mp_export.csv_writer import csv_to_calls, export_verified_csv, legal_description_to_csv
from mp_models import DeedCall, LegalDescription, Tract, TractType
from mp_verify import get_closure_summary, verify_closure

from metesparser.bearing_converter import BearingConverter
from metesparser.closure_checker import ClosureChecker
from metesparser.csv_builder import CSVBuilder
from metesparser.models import DeedCall as MonoDeedCall


def _line(course: int, azimuth: float, distance: float, **extra: Any) -> DeedCall:
    return DeedCall(
        course=course,
        direction_text=f"az {azimuth}",
        bearing_azimuth_deg_from_north=azimuth,
        distance_ft=distance,
        **extra,
    )


def _square(size: float = 100.0, course_start: int = 1, **extra: Any) -> list[DeedCall]:
    return [
        _line(course_start + i, az, size, **extra) for i, az in enumerate((0.0, 90.0, 180.0, 270.0))
    ]


def _mono_square(size: float = 100.0) -> list[MonoDeedCall]:
    return [
        MonoDeedCall(
            course=i + 1,
            direction_text=f"az {az}",
            bearing_azimuth_deg_from_north=az,
            distance_ft=size,
        )
        for i, az in enumerate((0.0, 90.0, 180.0, 270.0))
    ]


# ---------------------------------------------------------------------------
# Item 1 (#2b): export_verified_csv(..., tract_results=None) bypasses
# ---------------------------------------------------------------------------


def test_export_verified_csv_rejects_empty_main_tract_with_exception_calls(tmp_path: Path) -> None:
    exc_calls = _square(50.0)
    empty_main = Tract(label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=[])
    exc_tract = Tract(
        label="Exception 1",
        tract_type=TractType.EXCEPTION,
        role_basis="heading",
        calls=exc_calls,
    )
    legal = LegalDescription(calls=exc_calls, tracts=[empty_main, exc_tract])
    closing = verify_closure(exc_calls)

    with pytest.raises(ValueError, match="no parcel boundary tract"):
        export_verified_csv(exc_calls, closing, str(tmp_path / "deed.csv"), legal_desc=legal)
    assert list(tmp_path.iterdir()) == []


def test_export_verified_csv_rejects_main_plus_exception_without_tract_results(
    tmp_path: Path,
) -> None:
    main_calls = _square(100.0)
    exc_calls = _square(20.0)
    main_tract = Tract(
        label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=main_calls
    )
    exc_tract = Tract(
        label="Exception 1",
        tract_type=TractType.EXCEPTION,
        role_basis="heading",
        calls=exc_calls,
    )
    legal = LegalDescription(calls=main_calls, tracts=[main_tract, exc_tract])
    closing = verify_closure(main_calls)

    with pytest.raises(ValueError, match="exception tracts require multi-tract verification"):
        export_verified_csv(main_calls, closing, str(tmp_path / "deed.csv"), legal_desc=legal)
    assert list(tmp_path.iterdir()) == []


def test_export_verified_csv_rejects_multiple_boundary_tracts_without_tract_results(
    tmp_path: Path,
) -> None:
    main_calls = _square(100.0)
    add_calls = _square(50.0)
    main_tract = Tract(
        label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=main_calls
    )
    add_tract = Tract(
        label="Addition 1", tract_type=TractType.ADDITION, role_basis="heading", calls=add_calls
    )
    legal = LegalDescription(calls=main_calls, tracts=[main_tract, add_tract])
    closing = verify_closure(main_calls)

    with pytest.raises(ValueError, match="multiple boundary tracts require multi-tract"):
        export_verified_csv(main_calls, closing, str(tmp_path / "deed.csv"), legal_desc=legal)
    assert list(tmp_path.iterdir()) == []


def test_export_verified_csv_rejects_calls_mismatching_sole_boundary_tract(tmp_path: Path) -> None:
    main_calls = _square(100.0)
    other_calls = _square(50.0)
    main_tract = Tract(
        label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=main_calls
    )
    legal = LegalDescription(calls=other_calls, tracts=[main_tract])
    closing = verify_closure(other_calls)

    with pytest.raises(ValueError, match="calls do not match the boundary tract"):
        export_verified_csv(other_calls, closing, str(tmp_path / "deed.csv"), legal_desc=legal)
    assert list(tmp_path.iterdir()) == []


def test_export_verified_csv_allows_headed_main_plus_headed_easement_when_calls_match_main(
    tmp_path: Path,
) -> None:
    main_calls = _square(100.0)
    easement_calls = _square(20.0)
    main_tract = Tract(
        label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=main_calls
    )
    easement_tract = Tract(
        label="Easement 1",
        tract_type=TractType.EASEMENT,
        role_basis="heading",
        calls=easement_calls,
    )
    legal = LegalDescription(calls=main_calls, tracts=[main_tract, easement_tract])
    closing = verify_closure(main_calls)

    written = export_verified_csv(main_calls, closing, str(tmp_path / "deed.csv"), legal_desc=legal)
    assert written == [tmp_path / "deed_verified.csv"]
    loaded = csv_to_calls(str(written[0]))
    assert len(loaded) == 4
    assert all(c.distance_ft == 100.0 for c in loaded)


# ---------------------------------------------------------------------------
# Item 2 (#5): Unstated-radius (delta_deg, arc_length_ft) curves fail closed
# ---------------------------------------------------------------------------


def test_unstated_radius_curve_is_rejected_and_blocked_without_tautological_pass() -> None:
    from pydantic import ValidationError

    arc = 100.0 * math.pi / 2.0
    with pytest.raises(ValidationError, match="Curve geometry requires radius_ft"):
        DeedCall(
            course=1,
            direction_text="N 0°00' E",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=arc,
            curve_dir="right",
            radius_ft=None,
            delta_deg=90.0,
            arc_length_ft=arc,
        )

    bypassed = DeedCall.model_construct(
        course=1,
        direction_text="N 0°00' E",
        bearing_quadrant="N 0°00' E",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=arc,
        curve_dir="right",
        radius_ft=None,
        delta_deg=90.0,
        arc_length_ft=arc,
        curve_type=None,
    )
    result = verify_closure([bypassed, _line(2, 180.0, 100.0), _line(3, 270.0, 100.0)])
    checks = {c.name: c for c in result.checks}
    assert checks["curve_consistency"].status == "blocked"
    assert not checks["curve_consistency"].passed
    assert not result.is_fully_verified()


# ---------------------------------------------------------------------------
# Item 3 (#6): export_verified_csv with double-entry-verified deeds
# ---------------------------------------------------------------------------


def test_export_verified_csv_accepts_double_entry_single_tract_with_and_without_param(
    tmp_path: Path,
) -> None:
    calls = _square(100.0)
    de = _square(100.0)
    result = verify_closure(calls, double_entry_calls=de)
    assert any(c.name == "double_entry" and c.status == "passed" for c in result.checks)

    # Explicit double_entry_calls= replays and passes
    out1 = tmp_path / "explicit" / "deed.csv"
    written1 = export_verified_csv(calls, result, str(out1), double_entry_calls=de)
    assert written1 == [tmp_path / "explicit" / "deed_verified.csv"]

    # Omitting double_entry_calls= also works for existing callers when geometry matches exactly
    out2 = tmp_path / "implicit" / "deed.csv"
    written2 = export_verified_csv(calls, result, str(out2))
    assert written2 == [tmp_path / "implicit" / "deed_verified.csv"]

    # Monolith CSVBuilder facade forwards double_entry_calls cleanly
    mono_calls = _mono_square(100.0)
    mono_de = _mono_square(100.0)
    mono_res = ClosureChecker.verify_closure(mono_calls, double_entry_calls=mono_de)
    out3 = tmp_path / "mono" / "deed.csv"
    written3 = CSVBuilder.export_verified_csv(
        mono_calls, mono_res, str(out3), double_entry_calls=mono_de
    )
    assert written3 == [tmp_path / "mono" / "deed_verified.csv"]


def test_export_verified_csv_rejects_double_entry_discrepancy_and_mismatch(tmp_path: Path) -> None:
    calls = _square(100.0)
    good_de = _square(100.0)
    bad_de = list(_square(100.0))
    bad_de[0] = bad_de[0].model_copy(update={"distance_ft": 105.0})

    result_with_de = verify_closure(calls, double_entry_calls=good_de)
    with pytest.raises(ValueError, match="selected calls failed fresh verification"):
        export_verified_csv(
            calls, result_with_de, str(tmp_path / "bad.csv"), double_entry_calls=bad_de
        )

    # Result computed WITHOUT double_entry must not match when double_entry_calls IS provided
    result_without_de = verify_closure(calls)
    with pytest.raises(ValueError, match="closure result does not match selected calls"):
        export_verified_csv(
            calls, result_without_de, str(tmp_path / "mismatch.csv"), double_entry_calls=good_de
        )
    assert list(tmp_path.iterdir()) == []


def test_export_verified_csv_multi_tract_double_entry_and_length_mismatch(tmp_path: Path) -> None:
    exc_calls = _square(20.0, course_start=1)
    main_calls = _square(100.0, course_start=5)
    add_calls = _square(50.0, course_start=9)
    # Put non-boundary tract FIRST to verify per-tract offset slicing skips it accurately
    tracts = [
        Tract(
            label="Easement 1", tract_type=TractType.EASEMENT, role_basis="heading", calls=exc_calls
        ),
        Tract(label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=main_calls),
        Tract(
            label="Addition 1", tract_type=TractType.ADDITION, role_basis="heading", calls=add_calls
        ),
    ]
    de_all = [*exc_calls, *main_calls, *add_calls]
    results = verify_closure(
        [*exc_calls, *main_calls, *add_calls], tracts=tracts, double_entry_calls=de_all
    )
    pairs = list(zip(tracts, results, strict=True))

    # Explicit double_entry_calls replays each tract slice
    out1 = tmp_path / "mt_explicit" / "deed.csv"
    written1 = export_verified_csv(
        [], results[1], str(out1), tract_results=pairs, double_entry_calls=de_all
    )
    assert [p.name for p in written1] == ["deed_verified_tract2.csv", "deed_verified_tract3.csv"]

    # Omitting double_entry_calls also succeeds when every other check/geometry matches
    out2 = tmp_path / "mt_implicit" / "deed.csv"
    written2 = export_verified_csv([], results[1], str(out2), tract_results=pairs)
    assert [p.name for p in written2] == ["deed_verified_tract2.csv", "deed_verified_tract3.csv"]

    # Total length mismatch in multi-tract double_entry_calls must fail closed
    bad_len_dir = tmp_path / "mt_bad_len"
    bad_len_dir.mkdir()
    with pytest.raises(ValueError, match="failed fresh verification"):
        export_verified_csv(
            [],
            results[1],
            str(bad_len_dir / "deed.csv"),
            tract_results=pairs,
            double_entry_calls=[*de_all, main_calls[0]],
        )
    assert list(bad_len_dir.iterdir()) == []

    # Discrepancy in Tract 1 slice must fail closed
    bad_slice_dir = tmp_path / "mt_bad_slice"
    bad_slice_dir.mkdir()
    bad_de_all = list(de_all)
    bad_de_all[4] = bad_de_all[4].model_copy(update={"distance_ft": 101.0})
    with pytest.raises(ValueError, match="failed fresh verification"):
        export_verified_csv(
            [],
            results[1],
            str(bad_slice_dir / "deed.csv"),
            tract_results=pairs,
            double_entry_calls=bad_de_all,
        )
    assert list(bad_slice_dir.iterdir()) == []


# ---------------------------------------------------------------------------
# Item 4 (#12): area_available=False when exception_area_sq_ft > main_area_sq_ft
# ---------------------------------------------------------------------------


def test_exception_exceeding_main_area_sets_area_available_false_and_summary_not_determined() -> (
    None
):
    main = _square(100.0, course_start=1)  # 10,000 sq ft
    big_exc = _square(200.0, course_start=5, is_exception=True)  # 40,000 sq ft

    result = verify_closure([*main, *big_exc], stated_area_sq_ft=10000.0)

    assert result.area_available is False
    assert result.area_sq_ft == 0.0
    assert result.area_acres == 0.0
    assert any("exceeds main" in w.lower() for w in result.warnings)

    summary = get_closure_summary(result)
    assert "Area: not determined" in summary
    assert "0.00 sq ft" not in summary

    area_check = next(c for c in result.checks if c.name == "area_reasonableness")
    assert area_check.status == "blocked"
    assert area_check.inputs["area_available"] is False


# ---------------------------------------------------------------------------
# Item 5 (#13c): legal_description_to_csv empty CSV on easement-only deeds
# ---------------------------------------------------------------------------


def test_legal_description_to_csv_exports_easement_only_tracts_calls(tmp_path: Path) -> None:
    easement_calls = _square(30.0)
    legal = LegalDescription(
        calls=[],
        tracts=[
            Tract(
                label="Easement 1",
                tract_type=TractType.EASEMENT,
                role_basis="heading",
                calls=easement_calls,
            )
        ],
    )
    out = tmp_path / "easement.csv"
    legal_description_to_csv(legal, str(out))

    loaded = csv_to_calls(str(out))
    assert len(loaded) == 4
    assert all(c.distance_ft == 30.0 for c in loaded)


# ---------------------------------------------------------------------------
# Item 7 (#20): Negative-path tests for mp-bearing & monolith BearingConverter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "missing_fn",
    [calculate_missing_curve_elements, BearingConverter.calculate_missing_curve_elements],
    ids=["mp_bearing", "monolith"],
)
@pytest.mark.parametrize(
    ("chord_length_ft", "delta_deg"),
    [(0.0, 30.0), (100.0, 360.0)],
)
def test_calculate_missing_curve_elements_rejects_degenerate_chord_delta(
    missing_fn: Any, chord_length_ft: float, delta_deg: float
) -> None:
    with pytest.raises(ValueError, match="zero chord length or 360-degree delta"):
        missing_fn(chord_length_ft=chord_length_ft, delta_deg=delta_deg)


@pytest.mark.parametrize(
    "chord_fn",
    [calculate_chord_bearing, BearingConverter.calculate_chord_bearing],
    ids=["mp_bearing", "monolith"],
)
@pytest.mark.parametrize("bad_val", [True, False, float("nan"), float("inf"), float("-inf")])
def test_calculate_chord_bearing_rejects_bool_nan_inf(chord_fn: Any, bad_val: Any) -> None:
    with pytest.raises(ValueError, match="tangent_azimuth must be finite"):
        chord_fn(bad_val, 30.0, "right")
    with pytest.raises(ValueError, match="delta_deg must be finite"):
        chord_fn(45.0, bad_val, "left")


@pytest.mark.parametrize(
    "deg_fn",
    [degree_of_curvature_to_radius, BearingConverter.degree_of_curvature_to_radius],
    ids=["mp_bearing", "monolith"],
)
@pytest.mark.parametrize("bad_val", [True, False, float("nan"), float("inf"), float("-inf")])
def test_degree_of_curvature_to_radius_rejects_bool_nan_inf(deg_fn: Any, bad_val: Any) -> None:
    with pytest.raises(ValueError, match="positive and non-zero"):
        deg_fn(bad_val)
