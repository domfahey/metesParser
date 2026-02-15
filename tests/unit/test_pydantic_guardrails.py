import csv
from pathlib import Path

import pytest
from pydantic import ValidationError

from metesparser.csv_builder import CSVBuilder
from metesparser.models import ClosureResult, DeedCall, LegalDescription, Point

CSV_FIELDNAMES: list[str] = [
    "course",
    "direction_text",
    "bearing_quadrant",
    "bearing_azimuth_deg_from_north",
    "distance_ft",
    "curve_dir",
    "radius_ft",
    "delta_deg",
    "arc_length_ft",
    "chord_bearing",
    "chord_length_ft",
    "along",
    "to",
    "monument_type",
    "is_exception",
    "notes",
]


def _base_csv_row(overrides: dict[str, str] | None = None) -> dict[str, str]:
    row: dict[str, str] = {
        "course": "1",
        "direction_text": "N 90° E",
        "bearing_quadrant": "N 90° E",
        "bearing_azimuth_deg_from_north": "90.0",
        "distance_ft": "100.0",
        "curve_dir": "",
        "radius_ft": "",
        "delta_deg": "",
        "arc_length_ft": "",
        "chord_bearing": "",
        "chord_length_ft": "",
        "along": "",
        "to": "",
        "monument_type": "",
        "is_exception": "false",
        "notes": "",
    }
    if overrides:
        row.update(overrides)
    return row


def test_deedcall_rejects_incomplete_curve_geometry():
    with pytest.raises(ValidationError, match="Curve geometry requires"):
        DeedCall(
            course=1,
            direction_text="North",
            distance_ft=100.0,
            curve_dir="right",
            radius_ft=50.0,
        )


def test_deedcall_requires_curve_direction_when_curve_measure_is_present():
    with pytest.raises(ValidationError, match="curve_dir is required"):
        DeedCall(
            course=1,
            direction_text="North",
            distance_ft=100.0,
            radius_ft=50.0,
            delta_deg=45.0,
        )


def test_deedcall_rejects_non_string_curve_or_monument_fields():
    with pytest.raises((TypeError, ValidationError), match="Curve/monument values must be strings"):
        DeedCall(
            course=1,
            direction_text="North",
            distance_ft=100.0,
            curve_dir=123,
        )


def test_deedcall_normalizes_curve_dir_and_monument_type():
    call = DeedCall(
        course=1,
        direction_text="North",
        distance_ft=100.0,
        curve_dir="  RIGHT  ",
        radius_ft=50.0,
        delta_deg=45.0,
        monument_type=" WOODEN_POST ",
    )

    assert call.curve_dir == "right"
    assert call.monument_type == "wooden_post"


def test_deedcall_rejects_invalid_course_and_legaldescription_rejects_invalid_page():
    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        DeedCall(
            course=0,
            direction_text="North",
            distance_ft=100.0,
            bearing_azimuth_deg_from_north=0.0,
        )

    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        LegalDescription(page=0)


def test_deedcall_rejects_non_int_course():
    with pytest.raises(ValidationError, match="course"):
        DeedCall(
            course="1",
            direction_text="North",
            distance_ft=100.0,
            bearing_azimuth_deg_from_north=45.0,
        )


def test_deedcall_rejects_extra_fields():
    with pytest.raises(ValidationError, match="extra"):
        DeedCall.model_validate(
            {
                "course": 1,
                "direction_text": "North",
                "distance_ft": 100.0,
                "bearing_azimuth_deg_from_north": 45.0,
                "unexpected_field": "oops",
            }
        )


def test_deedcall_normalizes_exception_flags():
    call = DeedCall(
        course=1,
        direction_text="North",
        distance_ft=100.0,
        is_exception="YES",
    )
    assert call.is_exception is True

    with pytest.raises(ValidationError, match="is_exception"):
        DeedCall(
            course=2,
            direction_text="North",
            distance_ft=100.0,
            is_exception="maybe",
        )


def test_deedcall_normalizes_int_exception_flag():
    true_call = DeedCall(
        course=1,
        direction_text="North",
        distance_ft=100.0,
        is_exception=1,
    )
    false_call = DeedCall(
        course=2,
        direction_text="North",
        distance_ft=100.0,
        is_exception=0,
    )

    assert true_call.is_exception is True
    assert false_call.is_exception is False


def test_deedcall_normalizes_azimuth_to_north_reference_range():
    wrapped_call = DeedCall(
        course=3,
        direction_text="North",
        distance_ft=100.0,
        bearing_azimuth_deg_from_north=450.0,
    )
    assert wrapped_call.bearing_azimuth_deg_from_north == 90.0

    negative_call = DeedCall(
        course=4,
        direction_text="South",
        distance_ft=100.0,
        bearing_azimuth_deg_from_north=-45.0,
    )
    assert negative_call.bearing_azimuth_deg_from_north == 315.0


def test_csv_row_to_call_skips_invalid_curve_row(tmp_path: Path):
    csv_path = tmp_path / "calls.csv"
    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerow(
            {
                "course": "1",
                "direction_text": "N 90° E",
                "bearing_quadrant": "N 90° E",
                "bearing_azimuth_deg_from_north": "90.0",
                "distance_ft": "100.0",
                "curve_dir": "",
                "radius_ft": "",
                "delta_deg": "",
                "arc_length_ft": "",
                "chord_bearing": "",
                "chord_length_ft": "",
                "along": "",
                "to": "",
                "monument_type": "",
                "is_exception": "false",
                "notes": "",
            }
        )
        writer.writerow(
            {
                "course": "2",
                "direction_text": "N 45° E",
                "bearing_quadrant": "N 45° E",
                "bearing_azimuth_deg_from_north": "45.0",
                "distance_ft": "100.0",
                "curve_dir": "right",
                "radius_ft": "50.0",
                "delta_deg": "",
                "arc_length_ft": "",
                "chord_bearing": "",
                "chord_length_ft": "",
                "along": "",
                "to": "",
                "monument_type": "",
                "is_exception": "false",
                "notes": "",
            }
        )

    calls = CSVBuilder.csv_to_calls(str(csv_path))

    assert len(calls) == 1
    assert calls[0].course == 1


def test_csv_row_to_call_default_false_for_blank_exception_flag(tmp_path: Path):
    csv_path = tmp_path / "calls.csv"
    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerow(
            {
                "course": "1",
                "direction_text": "N 90° E",
                "bearing_quadrant": "N 90° E",
                "bearing_azimuth_deg_from_north": "90.0",
                "distance_ft": "100.0",
                "curve_dir": "",
                "radius_ft": "",
                "delta_deg": "",
                "arc_length_ft": "",
                "chord_bearing": "",
                "chord_length_ft": "",
                "along": "",
                "to": "",
                "monument_type": "",
                "is_exception": " ",
                "notes": "",
            }
        )

    calls = CSVBuilder.csv_to_calls(str(csv_path))

    assert len(calls) == 1
    assert calls[0].is_exception is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"course": ""},
        {"course": "abc"},
        {"distance_ft": ""},
        {"distance_ft": "abc"},
        {"distance_ft": "-10.0"},
        {"is_exception": "maybe"},
        {"course": "0"},
    ],
    ids=[
        "missing_course",
        "non_numeric_course",
        "missing_distance",
        "non_numeric_distance",
        "negative_distance",
        "invalid_is_exception",
        "invalid_course_range",
    ],
)
def test_csv_row_to_call_skips_invalid_rows(tmp_path: Path, overrides: dict[str, str]):
    csv_path = tmp_path / "calls.csv"
    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerow(_base_csv_row(overrides))

    calls = CSVBuilder.csv_to_calls(str(csv_path))

    assert calls == []


def test_legaldescription_rejects_non_int_page_number():
    with pytest.raises(ValidationError, match="page"):
        LegalDescription(page="1")


def test_point_str_format():
    assert str(Point(x=1.0, y=2.5)) == "(1.00, 2.50)"


def test_legaldescription_incomplete_call_detection():
    legal_desc = LegalDescription(
        calls=[
            DeedCall(
                course=1,
                direction_text="North",
                distance_ft=100.0,
                bearing_azimuth_deg_from_north=0.0,
            ),
            DeedCall(
                course=2,
                direction_text="East",
                distance_ft=75.0,
                bearing_azimuth_deg_from_north=None,
            ),
        ]
    )

    assert legal_desc.has_incomplete_calls() is True

    complete = LegalDescription(
        calls=[
            DeedCall(
                course=1,
                direction_text="North",
                distance_ft=100.0,
                bearing_azimuth_deg_from_north=0.0,
            )
        ]
    )
    assert complete.has_incomplete_calls() is False


def test_closure_result_status_thresholds():
    assert (
        ClosureResult(
            misclosure_x_ft=0.0,
            misclosure_y_ft=0.0,
            misclosure_ft=0.05,
            area_sq_ft=1.0,
            area_acres=1.0 / 43560.0,
            perimeter_ft=1.0,
            closure_passed=True,
            angle_check_passed=True,
            curve_consistency_passed=True,
            warnings=[],
            points=[],
        ).get_closure_status()
        == "GOOD"
    )

    assert (
        ClosureResult(
            misclosure_x_ft=0.0,
            misclosure_y_ft=0.0,
            misclosure_ft=0.5,
            area_sq_ft=1.0,
            area_acres=1.0 / 43560.0,
            perimeter_ft=1.0,
            closure_passed=True,
            angle_check_passed=True,
            curve_consistency_passed=True,
            warnings=[],
            points=[],
        ).get_closure_status()
        == "ACCEPTABLE"
    )

    assert (
        ClosureResult(
            misclosure_x_ft=0.0,
            misclosure_y_ft=0.0,
            misclosure_ft=5.0,
            area_sq_ft=1.0,
            area_acres=1.0 / 43560.0,
            perimeter_ft=1.0,
            closure_passed=True,
            angle_check_passed=True,
            curve_consistency_passed=True,
            warnings=[],
            points=[],
        ).get_closure_status()
        == "POOR"
    )
