"""File adapters preserve source bytes and reject ambiguous structured input."""

import hashlib
import json
from pathlib import Path

import pytest
from mp_review.plot import plot_file


def calls():
    return [
        {
            "course": i,
            "direction_text": "supplied",
            "distance_ft": 100,
            "bearing_azimuth_deg_from_north": a,
        }
        for i, a in enumerate([0, 90, 180, 270], 1)
    ]


def test_json_plot_roundtrip_and_hashes(tmp_path):
    source = tmp_path / "calls.json"
    raw = json.dumps(calls(), indent=4).encode()
    source.write_bytes(raw)
    out = tmp_path / "out"
    result = plot_file(source, out)
    assert result["status"] == "needs_review"
    assert result["verified_export_eligible"] is False
    assert result["source_review_complete"] is False
    assert (out / "source.json").read_bytes() == raw
    assert not list(out.glob("*.csv"))
    manifest = json.loads((out / "plot-manifest.json").read_text())
    assert manifest["source_sha256"] == hashlib.sha256(raw).hexdigest()
    assert manifest["source_name"] == "calls.json"
    assert manifest["input_format"] == "auto"
    assert manifest["replay_version"] == "plot-input-replay-1"
    rerun = plot_file(out / "plot-input.json", tmp_path / "second")
    assert rerun["status"] == "needs_review"
    assert json.loads((out / "plot-geometry.json").read_text()) == json.loads(
        (tmp_path / "second" / "plot-geometry.json").read_text()
    )


@pytest.mark.parametrize(
    "raw",
    [
        "[]",
        '{"calls":[],"calls":[]}',
        "[NaN]",
        '[{"course":1,"distance_ft":1,"direction_text":"x","extra":2}]',
        "{",
        '[{"course":1,"distance_ft":1e999,"direction_text":"x"}]',
    ],
)
def test_rejects_invalid_input_without_creating_artifacts(tmp_path, raw):
    path = tmp_path / "input.json"
    path.write_text(raw)
    out = tmp_path / "out"
    result = plot_file(path, out)
    assert result["status"] == "error"
    assert not out.exists()


def test_existing_output_is_preserved(tmp_path):
    source = tmp_path / "calls.json"
    source.write_text(json.dumps(calls()))
    out = tmp_path / "out"
    out.mkdir()
    marker = out / "plot.html"
    marker.write_text("untouched")
    assert plot_file(source, out)["status"] == "error"
    assert marker.read_text() == "untouched"


def test_relative_adapter_preserves_sources_without_recorded_bearings(tmp_path):
    fixture = json.loads((Path(__file__).parent / "fixtures/dashboard-relative.json").read_text())
    relative = fixture["calculations"][0]["relative"]
    path = tmp_path / "relative.json"
    path.write_text(json.dumps(relative))
    out = tmp_path / "relative-plot"
    result = plot_file(path, out)
    assert result["status"] == "needs_review"
    request = json.loads((out / "plot-input.json").read_text())
    from mp_models import RelativeDescription

    assert request["relative"] == RelativeDescription.model_validate(relative).model_dump(
        mode="json"
    )
    assert all(c["call"]["bearing_azimuth_deg_from_north"] is None for c in request["calls"])
    assert all(c["page_id"] is None for c in request["calls"])
    assert request["calls"][0]["quote"] == relative["courses"][0]["source"]["quote"]
    assert result["geometry"]["completeness"] == "complete"


def test_strict_csv_roundtrip_and_reject_short_row(tmp_path):
    from mp_export.csv_writer import calls_to_csv
    from mp_models import DeedCall

    path = tmp_path / "calls.csv"
    calls_to_csv([DeedCall.model_validate(c) for c in calls()], str(path))
    source = path.read_bytes()
    result = plot_file(path, tmp_path / "csv-plot")
    assert result["status"] == "needs_review"
    assert (tmp_path / "csv-plot/source.csv").read_bytes() == source
    path.write_bytes(source + b"5,north\n")
    assert plot_file(path, tmp_path / "bad-csv")["status"] == "error"
    assert not (tmp_path / "bad-csv").exists()


def test_legal_description_retains_original_metadata(tmp_path):
    data = {"calls": calls(), "source_doc": "Book 3, page 4", "datum": "supplied datum"}
    path = tmp_path / "legal.json"
    path.write_text(json.dumps(data))
    result = plot_file(path, tmp_path / "legal")
    assert result["status"] == "needs_review"
    assert json.loads((tmp_path / "legal/source.json").read_text()) == data


@pytest.mark.parametrize(
    "source_kind,requested_format",
    [
        ("plot", "calls"),
        ("relative", "calls"),
        ("plot", "relative"),
        ("calls", "relative"),
        ("calls", "plot"),
        ("relative", "plot"),
    ],
)
def test_explicit_input_format_rejects_other_schemas(tmp_path, source_kind, requested_format):
    from mp_models import DeedCall, PlotCall, PlotRequest

    relative = json.loads((Path(__file__).parent / "fixtures/dashboard-relative.json").read_text())[
        "calculations"
    ][0]["relative"]
    plot = PlotRequest(
        title="supplied",
        calls=tuple(
            PlotCall(id=f"call-{i}", call=DeedCall.model_validate(call))
            for i, call in enumerate(calls(), 1)
        ),
    ).model_dump(mode="json")
    data = {"calls": calls(), "plot": plot, "relative": relative}[source_kind]
    source = tmp_path / "source.json"
    source.write_text(json.dumps(data))
    assert plot_file(source, tmp_path / "auto")["status"] == "needs_review"
    out = tmp_path / "explicit"
    result = plot_file(source, out, input_format=requested_format)
    assert result["status"] == "error"
    assert not out.exists()


@pytest.mark.parametrize("requested_format", ["csv", "json", "pdf", "", "CALLS"])
def test_direct_api_rejects_unsupported_input_format(tmp_path, requested_format):
    source = tmp_path / "source.json"
    source.write_text(json.dumps(calls()))
    out = tmp_path / "out"
    result = plot_file(source, out, input_format=requested_format)
    assert result["status"] == "error"
    assert "auto, calls, relative or plot" in result["errors"][0]["message"]
    assert not out.exists()
