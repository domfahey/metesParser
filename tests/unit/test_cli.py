from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from metesparser import cli
from metesparser.models import ClosureResult, DeedCall, LegalDescription, Point


def _verified_result() -> ClosureResult:
    return ClosureResult(
        misclosure_x_ft=0.0,
        misclosure_y_ft=0.0,
        misclosure_ft=0.0,
        area_sq_ft=100.0,
        area_acres=100.0 / 43560.0,
        perimeter_ft=50.0,
        closure_passed=True,
        angle_check_passed=True,
        curve_consistency_passed=True,
        warnings=[],
        points=[Point(x=0.0, y=0.0), Point(x=10.0, y=0.0), Point(x=10.0, y=10.0)],
    )


def _not_verified_result() -> ClosureResult:
    return ClosureResult(
        misclosure_x_ft=3.0,
        misclosure_y_ft=4.0,
        misclosure_ft=5.0,
        area_sq_ft=25.0,
        area_acres=25.0 / 43560.0,
        perimeter_ft=20.0,
        closure_passed=False,
        angle_check_passed=False,
        curve_consistency_passed=False,
        warnings=["Needs review"],
        points=[Point(x=0.0, y=0.0), Point(x=2.0, y=0.0), Point(x=2.0, y=2.0)],
    )


def test_main_with_no_command_exits_gracefully(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["metesparser"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "usage:" in (captured.out + captured.err)


def test_main_with_unknown_command_exits_with_error(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["metesparser", "unknown"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert "invalid choice" in (captured.out + captured.err)


def test_main_dispatches_extract(monkeypatch, tmp_path):
    pdf = tmp_path / "input.pdf"
    pdf.write_text("pdf")

    called: list[tuple[str, str | None, str | None]] = []
    monkeypatch.setattr(
        "metesparser.cli.extract_command",
        lambda pdf_path, output=None, llm_provider=None: called.append(
            (pdf_path, output, llm_provider)
        ),
    )

    monkeypatch.setattr(
        sys, "argv", ["metesparser", "extract", str(pdf), "--llm-provider", "openai"]
    )
    cli.main()

    assert called == [(str(pdf), None, "openai")]


def test_main_dispatches_verify(monkeypatch, tmp_path):
    csv = tmp_path / "calls.csv"
    csv.write_text("course,direction_text,distance_ft\n")

    called: list[tuple[str, float | None]] = []
    monkeypatch.setattr(
        "metesparser.cli.verify_command",
        lambda csv_path, area=None: called.append((csv_path, area)),
    )

    monkeypatch.setattr(sys, "argv", ["metesparser", "verify", str(csv), "-a", "2500"])
    cli.main()

    assert called == [(str(csv), 2500.0)]


def test_main_rejects_export_command(monkeypatch, tmp_path, capsys):
    csv = tmp_path / "calls.csv"
    csv.write_text("course,direction_text,distance_ft\n")

    monkeypatch.setattr(sys, "argv", ["metesparser", "export", str(csv)])
    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert "invalid choice" in (captured.out + captured.err)


def test_extract_command_handles_missing_pdf_path():
    with pytest.raises(SystemExit) as exc:
        cli.extract_command("missing.pdf")
    assert exc.value.code == 1


def test_extract_command_exports_verified_csv(monkeypatch, tmp_path):
    pdf = tmp_path / "deed.pdf"
    pdf.write_text("pdf")
    output = tmp_path / "out.csv"
    legal_desc = LegalDescription(
        calls=[
            DeedCall(
                course=1,
                direction_text="N 90° E",
                bearing_azimuth_deg_from_north=90.0,
                distance_ft=10.0,
            )
        ],
        source_doc="deed.pdf",
    )

    export_calls: list[tuple] = []
    verified = _verified_result()

    monkeypatch.setattr(
        "metesparser.pdf_processor.PDFProcessor",
        lambda provider=None: SimpleNamespace(process_deed_pdf=lambda _: legal_desc),
    )
    monkeypatch.setattr(
        "metesparser.closure_checker.ClosureChecker.verify_closure", lambda calls: verified
    )
    monkeypatch.setattr(
        "metesparser.closure_checker.ClosureChecker.get_closure_summary", lambda result: "VERIFIED"
    )
    monkeypatch.setattr(
        "metesparser.csv_builder.CSVBuilder.export_verified_csv",
        lambda calls, closure_result, output_path, legal_desc_obj: export_calls.append(
            (calls, closure_result, output_path, legal_desc_obj)
        ),
    )

    cli.extract_command(str(pdf), output=str(output))

    assert export_calls == [(legal_desc.calls, verified, str(output), legal_desc)]


def test_extract_command_defaults_output_path_to_csv(monkeypatch, tmp_path):
    pdf = tmp_path / "deed.pdf"
    pdf.write_text("pdf")
    legal_desc = LegalDescription(
        calls=[
            DeedCall(
                course=1,
                direction_text="N 90° E",
                bearing_azimuth_deg_from_north=90.0,
                distance_ft=10.0,
            )
        ],
        source_doc="deed.pdf",
    )
    exported: list[tuple] = []
    verified = _verified_result()

    monkeypatch.setattr(
        "metesparser.pdf_processor.PDFProcessor",
        lambda provider=None: SimpleNamespace(process_deed_pdf=lambda _: legal_desc),
    )
    monkeypatch.setattr(
        "metesparser.closure_checker.ClosureChecker.verify_closure", lambda calls: verified
    )
    monkeypatch.setattr(
        "metesparser.closure_checker.ClosureChecker.get_closure_summary", lambda result: "VERIFIED"
    )
    monkeypatch.setattr(
        "metesparser.csv_builder.CSVBuilder.export_verified_csv",
        lambda calls, closure_result, output_path, legal_desc_obj: exported.append((output_path,)),
    )

    cli.extract_command(str(pdf))

    assert exported == [(str(tmp_path / "deed.csv"),)]


def test_extract_command_errors_on_processing_failure(monkeypatch, tmp_path):
    pdf = tmp_path / "deed.pdf"
    pdf.write_text("pdf")
    monkeypatch.setattr(
        "metesparser.pdf_processor.PDFProcessor",
        lambda provider=None: SimpleNamespace(
            process_deed_pdf=lambda _: (_ for _ in ()).throw(RuntimeError("boom"))
        ),
    )

    with pytest.raises(SystemExit) as exc:
        cli.extract_command(str(pdf))
    assert exc.value.code == 1


def test_extract_command_exports_unverified_csv(monkeypatch, tmp_path):
    pdf = tmp_path / "deed.pdf"
    pdf.write_text("pdf")
    output = tmp_path / "out.csv"
    legal_desc = LegalDescription(
        calls=[
            DeedCall(
                course=1,
                direction_text="N 90° E",
                bearing_azimuth_deg_from_north=90.0,
                distance_ft=10.0,
            )
        ],
        source_doc="deed.pdf",
    )

    export_calls: list[tuple] = []
    unverified = _not_verified_result()

    monkeypatch.setattr(
        "metesparser.pdf_processor.PDFProcessor",
        lambda provider=None: SimpleNamespace(process_deed_pdf=lambda _: legal_desc),
    )
    monkeypatch.setattr(
        "metesparser.closure_checker.ClosureChecker.verify_closure", lambda calls: unverified
    )
    monkeypatch.setattr(
        "metesparser.closure_checker.ClosureChecker.get_closure_summary",
        lambda result: "UNVERIFIED",
    )
    monkeypatch.setattr(
        "metesparser.csv_builder.CSVBuilder.legal_description_to_csv",
        lambda legal_description, output_path: export_calls.append(
            (legal_description, output_path)
        ),
    )

    cli.extract_command(str(pdf), output=str(output))

    assert export_calls == [(legal_desc, str(output))]


def test_verify_command_success_and_failure(monkeypatch, tmp_path):
    csv = tmp_path / "calls.csv"
    csv.write_text("course,direction_text,distance_ft\n")
    calls = [
        DeedCall(
            course=1,
            direction_text="N 90° E",
            bearing_azimuth_deg_from_north=90.0,
            distance_ft=10.0,
        )
    ]

    monkeypatch.setattr("metesparser.csv_builder.CSVBuilder.csv_to_calls", lambda _: calls)
    monkeypatch.setattr(
        "metesparser.closure_checker.ClosureChecker.get_closure_summary", lambda result: "VERIFIED"
    )
    monkeypatch.setattr(
        "metesparser.closure_checker.ClosureChecker.verify_closure",
        lambda calls, area=0.0: _verified_result(),
    )

    cli.verify_command(str(csv))

    calls[0].distance_ft = 20.0
    monkeypatch.setattr(
        "metesparser.closure_checker.ClosureChecker.verify_closure",
        lambda calls, area=0.0: _not_verified_result(),
    )

    with pytest.raises(SystemExit) as exc:
        cli.verify_command(str(csv))
    assert exc.value.code == 1


def test_verify_command_forwards_stated_area(monkeypatch, tmp_path):
    csv = tmp_path / "calls.csv"
    csv.write_text("course,direction_text,distance_ft\n")
    calls = [
        DeedCall(
            course=1,
            direction_text="N 90° E",
            bearing_azimuth_deg_from_north=90.0,
            distance_ft=10.0,
        )
    ]

    observed_areas: list[float] = []

    def _verify(calls_arg: list[DeedCall], area: float = 0.0) -> ClosureResult:
        observed_areas.append(area)
        return _verified_result()

    monkeypatch.setattr("metesparser.csv_builder.CSVBuilder.csv_to_calls", lambda _: calls)
    monkeypatch.setattr(
        "metesparser.closure_checker.ClosureChecker.get_closure_summary", lambda result: "VERIFIED"
    )
    monkeypatch.setattr("metesparser.closure_checker.ClosureChecker.verify_closure", _verify)

    cli.verify_command(str(csv), stated_area=2500.0)

    assert observed_areas == [2500.0]


def test_verify_command_errors_on_csv_load_failure(monkeypatch, tmp_path):
    csv = tmp_path / "calls.csv"
    csv.write_text("course,direction_text,distance_ft\n")
    monkeypatch.setattr(
        "metesparser.csv_builder.CSVBuilder.csv_to_calls",
        lambda _: (_ for _ in ()).throw(RuntimeError("load failed")),
    )

    with pytest.raises(SystemExit) as exc:
        cli.verify_command(str(csv))
    assert exc.value.code == 1


def test_verify_command_missing_csv_exits():
    with pytest.raises(SystemExit) as exc:
        cli.verify_command("missing.csv")
    assert exc.value.code == 1


def test_export_command_is_not_implemented():
    with pytest.raises(SystemExit) as exc:
        cli.export_command("calls.csv")
    assert exc.value.code == 1


def test_main_configures_logging_from_cli_flags(monkeypatch, tmp_path):
    pdf = tmp_path / "input.pdf"
    pdf.write_text("pdf")

    observed: list[tuple[str, str, bool]] = []

    def _configure_logging(*, level: str, log_format: str, debug: bool) -> None:
        observed.append((level, log_format, debug))

    monkeypatch.setattr("metesparser.cli.configure_logging", _configure_logging)
    monkeypatch.setattr(
        "metesparser.cli.extract_command",
        lambda pdf_path, output=None, llm_provider=None: None,
    )

    monkeypatch.setattr(
        sys,
        "argv",
        ["metesparser", "--debug", "--log-format", "json", "extract", str(pdf)],
    )
    cli.main()

    assert observed == [("DEBUG", "json", True)]


def test_main_rejects_invalid_log_level(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["metesparser", "--log-level", "VERBOSE"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert "Invalid log level" in (captured.out + captured.err)
