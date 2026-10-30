"""PR #60 round 18: a curve's radius is never its course distance; an unstated length stays unknown.

A spiral stated only by radius and delta has no determinable length (its arc is not
R * delta), so its distance is recorded as not determined (``distance_ft=None``):
the course is neither given an invented distance (such as the radius) nor dropped,
and verification treats it as unpositioned.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from types import SimpleNamespace

import mp_models
import pytest
from mp_export.csv_writer import FIELDNAMES
from mp_export.csv_writer import _call_to_row as package_call_to_row
from mp_export.csv_writer import csv_text_to_calls as package_csv_text_to_calls
from mp_export.revision_html import _selected as _revision_selected
from mp_models.plot_request import PlotCall, PlotRequest
from mp_parse.calls import extract_calls as package_extract_calls
from mp_parse.calls import extract_single_call as package_extract_single_call
from mp_verify.checks import check_distance_reasonableness, compare_double_entry
from mp_verify.closure import calculate_perimeter
from mp_verify.closure import verify_closure as package_verify
from mp_verify.plot import prepare_plot
from pydantic import ValidationError

from metesparser import models as monolith_models
from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker
from metesparser.csv_builder import CSVBuilder

SPIRAL_COURSE = (
    "along a spiral curve to the right having a radius of 1000.00 feet and a delta angle "
    "of 5°43'46\" to a point"
)
SPIRAL_DEED = (
    "BEGINNING at a pin; thence N 0° E 100 feet; thence "
    + SPIRAL_COURSE
    + "; thence S 0° E 100 feet; thence S 90° W 100 feet to the point of beginning."
)
CIRCULAR_COURSE = (
    "along a curve to the right having a radius of 1000 feet, arc length of 100 feet to a point"
)
STRAIGHT_COURSE = "N 45° E 125.50 feet to an iron pin"
NOT_DETERMINED_NOTE = "spiral length not stated - course distance not determined"


def _package_calls(text: str, strict: bool) -> list[mp_models.DeedCall]:
    return package_extract_calls(text, strict=strict)[0]


def _monolith_calls(text: str, strict: bool) -> list[monolith_models.DeedCall]:
    return CallExtractor.extract_calls(text, strict=strict)


EXTRACT_CALLS = {"package": _package_calls, "monolith": _monolith_calls}
EXTRACT_SINGLE = {
    "package": package_extract_single_call,
    "monolith": CallExtractor.extract_single_call,
}
VERIFY = {"package": package_verify, "monolith": ClosureChecker.verify_closure}
MODELS = {"package": mp_models, "monolith": monolith_models}


@pytest.mark.parametrize("strict", [True, False], ids=["strict", "non-strict"])
@pytest.mark.parametrize("impl", EXTRACT_CALLS)
def test_spiral_without_length_is_kept_with_undetermined_distance(impl, strict):
    calls = EXTRACT_CALLS[impl](SPIRAL_DEED, strict)
    assert [c.course for c in calls] == [1, 2, 3, 4]
    spiral = calls[1]
    assert spiral.curve_type == "spiral"
    assert spiral.radius_ft == pytest.approx(1000.0)
    assert spiral.distance_ft is None
    assert spiral.distance_ft != 1000.0
    assert NOT_DETERMINED_NOTE in (spiral.notes or "")
    assert [c.distance_ft for c in calls[::2]] == [100.0, 100.0]


@pytest.mark.parametrize("strict", [True, False], ids=["strict", "non-strict"])
@pytest.mark.parametrize("impl", EXTRACT_CALLS)
def test_spiral_without_length_blocks_closure(impl, strict):
    calls = EXTRACT_CALLS[impl](SPIRAL_DEED, strict)
    result = VERIFY[impl](calls)
    assert not result.closure_passed
    assert not result.misclosure_available
    assert not result.area_available
    assert not result.perimeter_available
    assert any(w.startswith("Course 2:") for w in result.warnings)


@pytest.mark.parametrize("impl", EXTRACT_SINGLE)
def test_single_spiral_without_length_never_takes_radius(impl):
    call = EXTRACT_SINGLE[impl](SPIRAL_COURSE, 1)
    assert call is not None
    assert call.distance_ft is None
    assert NOT_DETERMINED_NOTE in (call.notes or "")


@pytest.mark.parametrize("impl", EXTRACT_SINGLE)
def test_spiral_stated_length_is_the_course_distance_not_the_radius(impl):
    text = (
        "along a spiral curve to the right having a radius of 1000.00 feet, a delta angle "
        "of 5\u00b043'46\" and a length of 300.00 feet to a point"
    )
    call = EXTRACT_SINGLE[impl](text, 1)
    assert call is not None
    assert call.distance_ft == pytest.approx(300.0)


@pytest.mark.parametrize("impl", EXTRACT_SINGLE)
def test_circular_curve_with_stated_arc_keeps_arc_distance(impl):
    call = EXTRACT_SINGLE[impl](CIRCULAR_COURSE, 1)
    assert call is not None
    assert call.distance_ft == pytest.approx(100.0)
    assert call.radius_ft == pytest.approx(1000.0)


@pytest.mark.parametrize("impl", EXTRACT_SINGLE)
def test_straight_course_distance_unchanged(impl):
    call = EXTRACT_SINGLE[impl](STRAIGHT_COURSE, 1)
    assert call is not None
    assert call.distance_ft == pytest.approx(125.5)
    assert call.radius_ft is None


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"curve_dir": "right", "radius_ft": 1000.0, "delta_deg": 5.0},
        {
            "curve_dir": "right",
            "radius_ft": 1000.0,
            "delta_deg": 5.0,
            "curve_type": "spiral",
            "arc_length_ft": 300.0,
        },
        {
            "curve_dir": "right",
            "radius_ft": 1000.0,
            "delta_deg": 5.0,
            "curve_type": "spiral",
            "chord_bearing": "N 10° E",
            "chord_length_ft": 99.0,
        },
    ],
    ids=["straight", "circular", "spiral-with-arc", "spiral-with-chord"],
)
@pytest.mark.parametrize("impl", MODELS)
def test_distance_may_be_undetermined_only_for_spiral_without_length(impl, overrides):
    with pytest.raises(ValidationError, match="distance_ft"):
        MODELS[impl].DeedCall(course=1, direction_text="x", distance_ft=None, **overrides)


@pytest.mark.parametrize("impl", MODELS)
def test_distance_key_is_still_required(impl):
    with pytest.raises(ValidationError):
        MODELS[impl].DeedCall(course=1, direction_text="N 0 E")


@pytest.mark.parametrize("impl", EXTRACT_CALLS)
def test_csv_leaves_undetermined_distance_blank(impl):
    calls = EXTRACT_CALLS[impl](SPIRAL_DEED, False)
    to_row = package_call_to_row if impl == "package" else CSVBuilder._call_to_row
    row = to_row(calls[1])
    assert list(row) == FIELDNAMES
    assert row["distance_ft"] == ""
    assert row["radius_ft"] == "1000.00"


def _undetermined_spiral(course: int = 2) -> mp_models.DeedCall:
    return mp_models.DeedCall(
        course=course,
        direction_text="spiral",
        distance_ft=None,
        curve_dir="right",
        curve_type="spiral",
        radius_ft=1000.0,
        delta_deg=5.0,
    )


def _line(course: int, azimuth: float, distance: float) -> mp_models.DeedCall:
    return mp_models.DeedCall(
        course=course,
        direction_text="line",
        bearing_azimuth_deg_from_north=azimuth,
        distance_ft=distance,
    )


def test_distance_checks_skip_undetermined_distance():
    calls = [_line(1, 0.0, 100.0), _undetermined_spiral(), _line(3, 180.0, 100.0)]
    assert check_distance_reasonableness(calls) == []
    assert compare_double_entry(calls, calls) == []
    other = [*calls[:1], _line(2, 90.0, 50.0), calls[2]]
    assert "Course 2: Distance presence mismatch" in compare_double_entry(calls, other)
    with pytest.raises(ValueError, match="distance not determined"):
        calculate_perimeter(calls)


def test_plot_leaves_undetermined_spiral_unresolved():
    calls = (_line(1, 0.0, 100.0), _undetermined_spiral(), _line(3, 180.0, 100.0))
    request = PlotRequest(
        title="t", calls=tuple(PlotCall(id=f"c{c.course}", call=c) for c in calls)
    )
    geometry = prepare_plot(request).geometry
    assert [u.call_id for u in geometry.unresolved][:1] == ["c2"]
    assert all(p.call_id != "c2" for p in geometry.primitives)


def test_revision_detail_reports_undetermined_distance():
    record = SimpleNamespace(call=_undetermined_spiral())
    assert "Distance: not determined" in _revision_selected(record)


@pytest.mark.parametrize("impl", MODELS)
def test_audit_records_distance_not_determined(impl):
    models = MODELS[impl]
    ctx = models.AuditContext(
        run_metadata=models.RunMetadata(
            parser_version="t",
            llm_provider="t",
            llm_model="t",
            prompt_hash="t",
            timestamp_utc=datetime.now(UTC),
            source_pdf="t.pdf",
            cache_enabled=False,
        )
    )
    if impl == "package":
        package_extract_calls(SPIRAL_DEED, audit_context=ctx)
    else:
        CallExtractor.extract_calls(SPIRAL_DEED, audit_context=ctx)
    audit = ctx.call_audits[1]
    step = next(t for t in audit.transformations if t.step == "extract_distance")
    assert step.output == "not determined"
    assert "1000" not in step.output
    assert "spiral" in (step.rule or "")
    assert "distance_not_determined" in audit.flags


@pytest.mark.parametrize("impl", EXTRACT_CALLS)
def test_csv_import_reads_blank_spiral_distance_back_as_a_spiral(impl):
    calls = EXTRACT_CALLS[impl](SPIRAL_DEED, False)
    to_row = package_call_to_row if impl == "package" else CSVBuilder._call_to_row
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, FIELDNAMES)
    writer.writeheader()
    for call in calls:
        writer.writerow(to_row(call))
    reader = package_csv_text_to_calls if impl == "package" else CSVBuilder.csv_text_to_calls
    # curve_type is exported (round 19), so the blank distance is read back as a spiral.
    loaded = reader(buffer.getvalue())
    assert [c.model_dump() for c in loaded] == [c.model_dump() for c in calls]
    assert loaded[1].curve_type == "spiral"
    assert loaded[1].distance_ft is None
