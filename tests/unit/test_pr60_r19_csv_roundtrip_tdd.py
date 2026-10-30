"""PR #60 round 19: CSV export and import preserve spirals and never drop a course silently.

``curve_type`` is the 22nd (last) CSV column, so a spiral read back from CSV stays a
spiral instead of becoming a circular arc. A blank distance reads back exactly when
``DeedCall`` allows it (a spiral with no stated length). Legacy 21-column CSVs still
import (``curve_type`` absent -> None). Non-strict import records each rejected row
in a caller-supplied list and otherwise refuses; it never drops a row invisibly.
"""

from __future__ import annotations

import csv
import importlib.util
import io
import sys
from pathlib import Path

import mp_models
import pytest
from mp_export.csv_writer import FIELDNAMES, LEGACY_FIELDNAMES
from mp_export.csv_writer import _call_to_row as package_call_to_row
from mp_export.csv_writer import csv_text_to_calls as package_csv_text_to_calls
from mp_review.api import replay_review
from mp_review.plot import _request as plot_request
from mp_verify.closure import verify_closure as package_verify

from metesparser import models as monolith_models
from metesparser.closure_checker import ClosureChecker
from metesparser.csv_builder import CSVBuilder

ROOT = Path(__file__).resolve().parents[2]

ORIGINAL_21 = [
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
    "monument_status",
    "is_exception",
    "is_meander",
    "is_tie_in",
    "non_tangent",
    "radial_bearing",
    "notes",
]

IMPLS = {
    "package": (
        mp_models,
        package_call_to_row,
        package_csv_text_to_calls,
        package_verify,
        FIELDNAMES,
    ),
    "monolith": (
        monolith_models,
        CSVBuilder._call_to_row,
        CSVBuilder.csv_text_to_calls,
        ClosureChecker.verify_closure,
        CSVBuilder.FIELDNAMES,
    ),
}

CHORD = 49.5
LEG = CHORD * 0.5**0.5


def _spiral_parcel(m):
    return [
        m.DeedCall(
            course=1,
            direction_text="along a spiral curve to the right",
            distance_ft=CHORD,
            curve_type="spiral",
            curve_dir="right",
            radius_ft=100.0,
            arc_length_ft=50.0,
            chord_bearing="N 45°00'00\" E",
            chord_length_ft=CHORD,
        ),
        m.DeedCall(
            course=2,
            direction_text="S 0° E",
            bearing_azimuth_deg_from_north=180.0,
            distance_ft=LEG,
        ),
        m.DeedCall(
            course=3,
            direction_text="S 90° W",
            bearing_azimuth_deg_from_north=270.0,
            distance_ft=LEG,
        ),
    ]


def _undetermined_spiral_parcel(m):
    calls = _spiral_parcel(m)
    calls[0] = m.DeedCall(
        course=1,
        direction_text="along a spiral curve to the right",
        distance_ft=None,
        curve_type="spiral",
        curve_dir="right",
        radius_ft=1000.0,
        delta_deg=5.0,
    )
    return calls


def _write(rows, fieldnames) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()


@pytest.mark.parametrize("impl", IMPLS)
def test_curve_type_is_appended_as_last_column(impl):
    *_, fieldnames = IMPLS[impl]
    assert fieldnames[:21] == ORIGINAL_21
    assert fieldnames[21:] == ["curve_type"]
    assert LEGACY_FIELDNAMES == ORIGINAL_21


@pytest.mark.parametrize("impl", IMPLS)
def test_spiral_round_trips_with_identical_verification(impl):
    m, to_row, read, verify, fieldnames = IMPLS[impl]
    calls = _spiral_parcel(m)
    text = _write([to_row(c) for c in calls], fieldnames)
    loaded = read(text)
    assert [c.curve_type for c in loaded] == ["spiral", None, None]
    assert [c.model_dump() for c in loaded] == [c.model_dump() for c in calls]
    assert verify(loaded).model_dump() == verify(calls).model_dump()


@pytest.mark.parametrize("impl", IMPLS)
def test_spiral_without_length_round_trips_blank_distance(impl):
    m, to_row, read, verify, fieldnames = IMPLS[impl]
    calls = _undetermined_spiral_parcel(m)
    rows = [to_row(c) for c in calls]
    assert rows[0]["distance_ft"] == ""
    assert rows[0]["curve_type"] == "spiral"
    loaded = read(_write(rows, fieldnames))
    assert loaded[0].distance_ft is None
    assert loaded[0].curve_type == "spiral"
    assert [c.model_dump() for c in loaded] == [c.model_dump() for c in calls]
    assert verify(loaded).model_dump() == verify(calls).model_dump()


@pytest.mark.parametrize("impl", IMPLS)
def test_blank_distance_still_rejected_for_non_spiral(impl):
    m, to_row, read, _, fieldnames = IMPLS[impl]
    rows = [to_row(c) for c in _spiral_parcel(m)]
    rows[1]["distance_ft"] = ""
    with pytest.raises(ValueError, match="invalid CSV row 3"):
        read(_write(rows, fieldnames))
    rows = [to_row(c) for c in _undetermined_spiral_parcel(m)]
    rows[0]["curve_type"] = ""
    with pytest.raises(ValueError, match="invalid CSV row 2"):
        read(_write(rows, fieldnames))


@pytest.mark.parametrize("impl", IMPLS)
def test_legacy_21_column_csv_still_imports(impl):
    m, to_row, read, _, _ = IMPLS[impl]
    rows = [to_row(c) for c in _spiral_parcel(m)]
    loaded = read(_write(rows, ORIGINAL_21))
    assert len(loaded) == 3
    assert all(c.curve_type is None for c in loaded)


def test_review_and_plot_accept_current_and_legacy_headers():
    calls = _spiral_parcel(mp_models)
    rows = [package_call_to_row(c) for c in calls]
    current = _write(rows, FIELDNAMES).encode()
    legacy = _write(rows, ORIGINAL_21).encode()

    result = replay_review(current, input_kind="csv", source_name="calls.csv")
    assert not [e for e in result["errors"] if e["code"] == "invalid_input"], result["errors"]
    assert result["calls"][0]["curve_type"] == "spiral"
    assert result["verification"] == package_verify(calls).model_dump(mode="json")

    legacy_result = replay_review(legacy, input_kind="csv", source_name="calls.csv")
    assert not [e for e in legacy_result["errors"] if e["code"] == "invalid_input"]
    assert legacy_result["calls"][0]["curve_type"] is None

    request, kind = plot_request(current, "calls.csv", "calls")
    assert kind == "csv"
    assert request.calls[0].call.curve_type == "spiral"
    legacy_request, _ = plot_request(legacy, "calls.csv", "calls")
    assert legacy_request.calls[0].call.curve_type is None


@pytest.mark.parametrize("impl", IMPLS)
def test_non_strict_import_never_drops_a_row_silently(impl):
    m, to_row, read, _, fieldnames = IMPLS[impl]
    rows = [to_row(c) for c in _spiral_parcel(m)]
    rows[1]["distance_ft"] = "abc"
    text = _write(rows, fieldnames)

    with pytest.raises(ValueError, match="invalid CSV row 3"):
        read(text, strict=False)

    rejected: list[tuple[int, str]] = []
    loaded = read(text, strict=False, rejected_rows=rejected)
    assert [c.course for c in loaded] == [1, 3]
    assert [number for number, _ in rejected] == [3]
    assert rejected[0][1]


def _load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_r19_{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_extraction_report_handles_undetermined_spiral_distance(tmp_path):
    script = _load_script("extract_sample_deeds")
    calls = _undetermined_spiral_parcel(monolith_models)
    legal = monolith_models.LegalDescription(calls=calls, source_doc="spiral.pdf")
    out = tmp_path / "report.txt"
    script.create_extraction_report(legal, ClosureChecker.verify_closure(calls), out)
    report = out.read_text()
    assert "Distance:        not determined" in report
    assert "1000.00 feet" not in report
