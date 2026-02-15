import csv
from pathlib import Path

import pytest
from pydantic import ValidationError

from metesparser.csv_builder import CSVBuilder
from metesparser.models import DeedCall, LegalDescription


def test_deedcall_rejects_incomplete_curve_geometry():
    with pytest.raises(ValidationError):
        DeedCall(
            course=1,
            direction_text="North",
            distance_ft=100.0,
            curve_dir="right",
            radius_ft=50.0,
        )


def test_deedcall_rejects_invalid_course_and_legaldescription_rejects_invalid_page():
    with pytest.raises(ValidationError):
        DeedCall(
            course=0,
            direction_text="North",
            distance_ft=100.0,
            bearing_azimuth_deg_from_north=0.0,
        )

    with pytest.raises(ValidationError):
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

    with pytest.raises(ValidationError):
        DeedCall(
            course=2,
            direction_text="North",
            distance_ft=100.0,
            is_exception="maybe",
        )


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
        writer = csv.DictWriter(
            f,
            fieldnames=[
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
            ],
        )
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
        writer = csv.DictWriter(
            f,
            fieldnames=[
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
            ],
        )
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


def test_legaldescription_rejects_non_int_page_number():
    with pytest.raises(ValidationError, match="page"):
        LegalDescription(page="1")
