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
