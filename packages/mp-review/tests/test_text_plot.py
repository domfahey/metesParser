"""Isolated text plots prepare calls without verifying or inventing a boundary."""

import json

import pytest
from mp_review.plot import plot_file

SQUARE = (
    "THENCE N 0° E 100 feet; THENCE N 90° E 100 feet; "
    "THENCE S 0° E 100 feet; THENCE N 90° W 100 feet to the POINT OF BEGINNING."
)
COMMENCEMENT = "COMMENCING at a stone; THENCE N 0° E 50 feet to the POINT OF BEGINNING; " + SQUARE


def test_text_plot_separates_tie_in_and_preserves_source(tmp_path, monkeypatch):
    import mp_review.api
    import mp_verify

    def forbidden(*args, **kwargs):
        raise AssertionError("Plotting must not run canonical verification")

    monkeypatch.setattr(mp_review.api, "verify_closure", forbidden)
    monkeypatch.setattr(mp_verify, "verify_closure", forbidden)
    source = tmp_path / "selected.txt"
    source.write_bytes(COMMENCEMENT.encode("utf-8"))
    out = tmp_path / "plot"
    result = plot_file(source, out, input_format="text")
    assert result["status"] == "needs_review", result["errors"]
    geometry = result["geometry"]
    assert len(geometry["primitives"]) == 4
    assert geometry["perimeter_ft"] == pytest.approx(400)
    assert geometry["misclosure_ft"] == pytest.approx(0, abs=1e-10)
    assert (out / "source.txt").read_bytes() == source.read_bytes()
    request = json.loads((out / "plot-input.json").read_text())
    assert len(request["calls"]) == 5
    assert request["calls"][0]["call"]["is_tie_in"] is True
    assert "50 feet" in request["calls"][0]["quote"]
    assert all(c["quote"] in COMMENCEMENT for c in request["calls"])
    assert all(c["source_reference"].startswith("selected.txt:") for c in request["calls"])
    assert result["engine_verified"] is False
    assert result["verified_export_eligible"] is False
    assert not list(out.glob("*.csv"))


def test_text_plot_preserves_unknown_bearing(tmp_path):
    text = "BEGINNING at a stone; THENCE southwesterly 100 feet; " + SQUARE
    source = tmp_path / "selected.txt"
    source.write_text(text)
    out = tmp_path / "plot"
    result = plot_file(source, out, input_format="text")
    assert result["status"] == "needs_review", result["errors"]
    request = json.loads((out / "plot-input.json").read_text())
    assert request["calls"][0]["call"]["bearing_azimuth_deg_from_north"] is None
    assert "incomplete bearing" in request["calls"][0]["call"]["notes"]
    assert result["geometry"]["primitives"] == []
    assert result["geometry"]["unresolved"]


@pytest.mark.parametrize(
    "text",
    [
        "TRACT 1: BEGINNING at a stone; " + SQUARE + " TRACT 2: BEGINNING at a stone; " + SQUARE,
        "Parcel A: BEGINNING at a stone; " + SQUARE + " Parcel B: BEGINNING at a stone; " + SQUARE,
        "COMMENCING at a stone; THENCE N 0° E 50 feet; THENCE N 90° E 100 feet;",
        "POINT OF COMMENCEMENT at a stone; THENCE N 0° E 50 feet; THENCE N 90° E 100 feet;",
        "POC at a stone; THENCE N 0° E 50 feet; THENCE N 90° E 100 feet;",
        "COMMENCING at a stone; BEGINNING at a pin; THENCE N 0° E 100 feet;",
        "COMMENCING at a stone; THENCE N 0° E 50 feet to the POINT OF BEGINNING;",
    ],
)
def test_text_plot_rejects_ambiguous_or_unresolved_boundary(tmp_path, text):
    source = tmp_path / "selected.txt"
    source.write_text(text)
    out = tmp_path / "plot"
    result = plot_file(source, out, input_format="text")
    assert result["status"] == "error"
    assert not out.exists()


def test_text_format_is_explicit(tmp_path):
    source = tmp_path / "selected.txt"
    source.write_text(COMMENCEMENT)
    assert plot_file(source, tmp_path / "auto")["status"] == "error"


def test_normalization_preserves_original_quotations(tmp_path):
    text = (
        "BEGINNING at an IPF; THENCE North 0 degrees East 100 feet to an IPS; "
        "THENCE North 90 degrees East 100 feet along the Southerly line of Pennbrook Drive; "
        "THENCE South 0 degrees East 100 feet; "
        "THENCE North 90 degrees West 100 feet to the POINT OF BEGINNING."
    )
    source = tmp_path / "selected.txt"
    source.write_text(text)
    out = tmp_path / "plot"
    result = plot_file(source, out, input_format="text")
    assert result["status"] == "needs_review", result["errors"]
    request = json.loads((out / "plot-input.json").read_text())
    assert request["calls"][0]["quote"] == "North 0 degrees East 100 feet to an IPS"
    assert "IPS" in request["calls"][0]["quote"]
    assert request["calls"][0]["call"]["bearing_azimuth_deg_from_north"] == 0
    assert (out / "source.txt").read_text() == text


@pytest.mark.parametrize("text", ["", "No geometric calls.", "THENCE N 0° E distance unknown;"])
def test_empty_or_malformed_text_fails_closed(tmp_path, text):
    source = tmp_path / "selected.txt"
    source.write_text(text)
    out = tmp_path / "plot"
    assert plot_file(source, out, input_format="text")["status"] == "error"
    assert not out.exists()
