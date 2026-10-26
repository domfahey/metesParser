"""Verify source curve semantics and the actual serialized CSV boundary."""

import csv
from pathlib import Path

import pytest
from mp_export import calls_to_csv, csv_to_calls, export_verified_csv
from mp_models import DeedCall as PackageCall
from mp_verify import verify_closure

from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker
from metesparser.csv_builder import CSVBuilder
from metesparser.models import DeedCall as MonolithCall
from metesparser.pdf_processor import PDFProcessor
from metesparser.pipeline import Pipeline
from tests.fixtures.package_parser import extract_calls


@pytest.fixture(params=["package", "monolith"])
def api(request):
    if request.param == "package":
        return (
            PackageCall,
            extract_calls,
            verify_closure,
            calls_to_csv,
            csv_to_calls,
            export_verified_csv,
        )
    return (
        MonolithCall,
        CallExtractor.extract_calls,
        ClosureChecker.verify_closure,
        CSVBuilder.calls_to_csv,
        CSVBuilder.csv_to_calls,
        CSVBuilder.export_verified_csv,
    )


def _chord_curve(direction="right"):
    return (
        f"THENCE along a curve to the {direction}, radius of 100 feet, "
        "delta angle of 90 degrees, arc length of 157.0796327 feet, "
        "the chord of which bears N 45° E, 141.421356 feet; "
    )


@pytest.mark.parametrize("direction", ["left", "right"])
def test_chord_curve_text_closes_using_chord_direction(api, tmp_path, direction):
    _, parse, verify, _, load, export = api
    calls = parse(
        _chord_curve(direction)
        + "THENCE due South 100 feet; THENCE due West 100 feet to the point of beginning."
    )
    result = verify(calls)
    assert result.points[1].x == pytest.approx(100, abs=1e-6)
    assert result.points[1].y == pytest.approx(100, abs=1e-6)
    assert result.is_fully_verified()
    export(calls, result, str(tmp_path / "curve.csv"))
    assert verify(load(str(tmp_path / "curve_verified.csv"))).is_fully_verified()


def test_chord_curve_cannot_certify_a_different_tangent_path(api, tmp_path):
    _, parse, verify, _, _, export = api
    calls = parse(_chord_curve() + "THENCE due West 141.421356 feet to the point of beginning.")
    result = verify(calls)
    assert result.misclosure_ft == pytest.approx(108.23922, abs=1e-5)
    assert not result.is_fully_verified()
    with pytest.raises(ValueError, match="verification checks failed"):
        export(calls, result, str(tmp_path / "bad.csv"))
    assert not (tmp_path / "bad_verified.csv").exists()


def test_verified_export_remains_closed_after_loading(api, tmp_path):
    call_type, _, verify, _, load, export = api
    legs = [(0, 100), *[(90, 100.0049)] * 4, (180, 100), (270, 400.0196)]
    calls = [
        call_type(
            course=i + 1,
            direction_text="boundary",
            bearing_azimuth_deg_from_north=azimuth,
            distance_ft=distance,
        )
        for i, (azimuth, distance) in enumerate(legs)
    ]
    result = verify(calls)
    assert result.is_fully_verified()
    export(calls, result, str(tmp_path / "precision.csv"))
    loaded = load(str(tmp_path / "precision_verified.csv"))
    assert [c.distance_ft for c in loaded] == [c.distance_ft for c in calls]
    assert verify(loaded).is_fully_verified()


def test_csv_preserves_all_numeric_curve_geometry(api, tmp_path):
    call_type, _, _, write, load, _ = api
    call = call_type(
        course=1,
        direction_text="curve",
        bearing_azimuth_deg_from_north=12.345678912345,
        distance_ft=20.123456789,
        radius_ft=100.004912345,
        delta_deg=12.345678912345,
        arc_length_ft=20.123456789,
        chord_length_ft=20.0123456789,
        curve_dir="right",
    )
    path = tmp_path / "precise.csv"
    write([call], str(path))
    assert load(str(path)) == [call]


def _mixed_csv(api, tmp_path):
    call_type, _, _, write, _, _ = api
    calls = [
        call_type(
            course=i + 1,
            direction_text="boundary",
            distance_ft=100,
            bearing_azimuth_deg_from_north=a,
        )
        for i, a in enumerate([0, 90, 180, 270])
    ]
    path = tmp_path / "mixed.csv"
    write(calls, str(path))
    with path.open() as stream:
        rows = list(csv.DictReader(stream))
    bad = dict(rows[0], course="5", distance_ft="unreadable")
    with path.open("a", newline="") as stream:
        csv.DictWriter(stream, fieldnames=list(bad)).writerow(bad)
    return path


def test_csv_import_rejects_incomplete_parcel_by_default(api, tmp_path):
    _, _, _, _, load, _ = api
    path = _mixed_csv(api, tmp_path)
    with pytest.raises(ValueError, match="(?i)(invalid|row)"):
        load(str(path))


def test_partial_csv_recovery_must_be_explicit(api, tmp_path):
    _, _, _, _, load, _ = api
    path = _mixed_csv(api, tmp_path)
    calls = load(str(path), strict=False)
    assert len(calls) == 4


def test_cli_verification_rejects_a_csv_with_an_invalid_course(api, tmp_path):
    from metesparser.cli import verify_command

    path = _mixed_csv(api, tmp_path)
    with pytest.raises(SystemExit) as failure:
        verify_command(str(path))
    assert failure.value.code == 1


class _MalformedDeedClient:
    model = "test"
    text = (
        "THENCE due North 100 feet; THENCE due East 100 feet; "
        "THENCE due South 100 feet; THENCE due West 100 feet; "
        "THENCE N 12.5960° E 10 feet to a corner."
    )

    def generate_text(self, *_args, **_kwargs):
        return self.text

    def generate_text_with_pdf(self, *_args, **_kwargs):
        return self.text


@pytest.mark.parametrize("audit", [False, True])
def test_pipeline_rejects_malformed_source_instead_of_certifying_subset(monkeypatch, audit):
    processor = PDFProcessor(client=_MalformedDeedClient(), cache=False)
    monkeypatch.setattr("metesparser.pipeline.PDFProcessor", lambda **_: processor)
    with pytest.raises(ValueError, match="Malformed course 5"):
        Pipeline(audit=audit).run(Path("mocked.pdf"))


def test_cli_extraction_writes_no_csv_after_rejected_source_course(monkeypatch, tmp_path):
    from metesparser import cli

    processor = PDFProcessor(client=_MalformedDeedClient(), cache=False)
    monkeypatch.setattr("metesparser.pdf_processor.PDFProcessor", lambda **_: processor)
    monkeypatch.setattr(cli, "RUNS_DIR", tmp_path / "runs")
    pdf = tmp_path / "deed.pdf"
    pdf.write_bytes(b"mocked PDF")
    with pytest.raises(SystemExit) as failure:
        cli.extract_command(str(pdf), output=str(tmp_path / "out.csv"))
    assert failure.value.code == 1
    assert list(tmp_path.glob("*.csv")) == []
