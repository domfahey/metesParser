from __future__ import annotations

import io
import json
import sys
from types import SimpleNamespace

import pytest
import structlog

from metesparser import cli
from metesparser.logging_config import configure_logging
from metesparser.models import ClosureResult, DeedCall, LegalDescription, Point

pytestmark = pytest.mark.usefixtures("isolate_logging_state")


def _json_log_lines(payload: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in payload.splitlines() if line.strip()]


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
        lambda pdf_path, output=None, llm_provider=None, **kwargs: called.append(
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
        lambda provider=None, **kwargs: SimpleNamespace(process_deed_pdf=lambda _: legal_desc),
    )
    monkeypatch.setattr(
        "metesparser.closure_checker.ClosureChecker.verify_closure",
        lambda calls, stated_area_sq_ft=0.0, **kwargs: verified,
    )
    monkeypatch.setattr(
        "metesparser.closure_checker.ClosureChecker.get_closure_summary",
        lambda result, **kwargs: "VERIFIED",
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
        lambda provider=None, **kwargs: SimpleNamespace(process_deed_pdf=lambda _: legal_desc),
    )
    monkeypatch.setattr(
        "metesparser.closure_checker.ClosureChecker.verify_closure",
        lambda calls, stated_area_sq_ft=0.0, **kwargs: verified,
    )
    monkeypatch.setattr(
        "metesparser.closure_checker.ClosureChecker.get_closure_summary",
        lambda result, **kwargs: "VERIFIED",
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
        lambda provider=None, **kwargs: SimpleNamespace(
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
        lambda provider=None, **kwargs: SimpleNamespace(process_deed_pdf=lambda _: legal_desc),
    )
    monkeypatch.setattr(
        "metesparser.closure_checker.ClosureChecker.verify_closure",
        lambda calls, stated_area_sq_ft=0.0, **kwargs: unverified,
    )
    monkeypatch.setattr(
        "metesparser.closure_checker.ClosureChecker.get_closure_summary",
        lambda result, **kwargs: "UNVERIFIED",
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
        "metesparser.closure_checker.ClosureChecker.get_closure_summary",
        lambda result, **kwargs: "VERIFIED",
    )
    monkeypatch.setattr(
        "metesparser.closure_checker.ClosureChecker.verify_closure",
        lambda calls, stated_area_sq_ft=0.0, **kwargs: _verified_result(),
    )

    cli.verify_command(str(csv))

    calls[0] = calls[0].model_copy(update={"distance_ft": 20.0})
    monkeypatch.setattr(
        "metesparser.closure_checker.ClosureChecker.verify_closure",
        lambda calls, stated_area_sq_ft=0.0, **kwargs: _not_verified_result(),
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

    def _verify(
        calls_arg: list[DeedCall], stated_area_sq_ft: float = 0.0, **kwargs: object
    ) -> ClosureResult:
        observed_areas.append(stated_area_sq_ft)
        return _verified_result()

    monkeypatch.setattr("metesparser.csv_builder.CSVBuilder.csv_to_calls", lambda _: calls)
    monkeypatch.setattr(
        "metesparser.closure_checker.ClosureChecker.get_closure_summary",
        lambda result, **kwargs: "VERIFIED",
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


def test_extract_command_json_mode_logs_summary_without_stdout(monkeypatch, tmp_path, capsys):
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

    log_stream = io.StringIO()
    configure_logging(level="INFO", log_format="json", stream=log_stream)

    monkeypatch.setattr(
        "metesparser.pdf_processor.PDFProcessor",
        lambda provider=None, **kwargs: SimpleNamespace(process_deed_pdf=lambda _: legal_desc),
    )
    monkeypatch.setattr(
        "metesparser.closure_checker.ClosureChecker.verify_closure",
        lambda calls, stated_area_sq_ft=0.0, **kwargs: _verified_result(),
    )
    monkeypatch.setattr(
        "metesparser.closure_checker.ClosureChecker.get_closure_summary",
        lambda result, **kwargs: "VERIFIED",
    )
    monkeypatch.setattr(
        "metesparser.csv_builder.CSVBuilder.export_verified_csv",
        lambda calls, closure_result, output_path, legal_desc_obj: None,
    )

    try:
        cli.extract_command(str(pdf))
    finally:
        configure_logging(level="INFO", log_format="console", stream=io.StringIO())

    captured = capsys.readouterr()
    assert captured.out == ""
    assert any(
        line.get("event") == "Closure summary" and line.get("summary") == "VERIFIED"
        for line in _json_log_lines(log_stream.getvalue())
    )


def test_extract_command_console_mode_logs_summary_and_stdout(monkeypatch, tmp_path, capsys):
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

    log_stream = io.StringIO()
    configure_logging(level="INFO", log_format="console", stream=log_stream)

    monkeypatch.setattr(
        "metesparser.pdf_processor.PDFProcessor",
        lambda provider=None, **kwargs: SimpleNamespace(process_deed_pdf=lambda _: legal_desc),
    )
    monkeypatch.setattr(
        "metesparser.closure_checker.ClosureChecker.verify_closure",
        lambda calls, stated_area_sq_ft=0.0, **kwargs: _verified_result(),
    )
    monkeypatch.setattr(
        "metesparser.closure_checker.ClosureChecker.get_closure_summary",
        lambda result, **kwargs: "VERIFIED",
    )
    monkeypatch.setattr(
        "metesparser.csv_builder.CSVBuilder.export_verified_csv",
        lambda calls, closure_result, output_path, legal_desc_obj: None,
    )

    try:
        cli.extract_command(str(pdf))
    finally:
        configure_logging(level="INFO", log_format="console", stream=io.StringIO())

    captured = capsys.readouterr()
    assert "VERIFIED" in captured.out
    assert "Closure summary" in log_stream.getvalue()
    assert "VERIFIED" in log_stream.getvalue()


def test_extract_command_propagates_contextvars_and_clears_after_completion(monkeypatch, tmp_path):
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

    log_stream = io.StringIO()
    configure_logging(level="INFO", log_format="json", stream=log_stream)

    def _process(_: str) -> LegalDescription:
        structlog.get_logger("metesparser.call_extractor").warning("downstream parse warning")
        return legal_desc

    monkeypatch.setattr(
        "metesparser.pdf_processor.PDFProcessor",
        lambda provider=None, **kwargs: SimpleNamespace(process_deed_pdf=_process),
    )
    monkeypatch.setattr(
        "metesparser.closure_checker.ClosureChecker.verify_closure",
        lambda calls, stated_area_sq_ft=0.0, **kwargs: _verified_result(),
    )
    monkeypatch.setattr(
        "metesparser.closure_checker.ClosureChecker.get_closure_summary",
        lambda result, **kwargs: "VERIFIED",
    )
    monkeypatch.setattr(
        "metesparser.csv_builder.CSVBuilder.export_verified_csv",
        lambda calls, closure_result, output_path, legal_desc_obj: None,
    )

    try:
        cli.extract_command(str(pdf))
        structlog.get_logger("metesparser.after").info("after command")
    finally:
        configure_logging(level="INFO", log_format="console", stream=io.StringIO())

    lines = _json_log_lines(log_stream.getvalue())
    downstream = next(line for line in lines if line.get("event") == "downstream parse warning")
    assert downstream["command"] == "extract"
    assert downstream["input_pdf"] == str(pdf)
    assert downstream["output_csv"] == str(pdf.with_suffix(".csv"))
    assert isinstance(downstream.get("run_id"), str)
    assert downstream["run_id"]

    after = next(line for line in lines if line.get("event") == "after command")
    assert "command" not in after
    assert "input_pdf" not in after
    assert "run_id" not in after


def test_verify_command_json_mode_logs_summary_without_stdout(monkeypatch, tmp_path, capsys):
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

    log_stream = io.StringIO()
    configure_logging(level="INFO", log_format="json", stream=log_stream)

    monkeypatch.setattr("metesparser.csv_builder.CSVBuilder.csv_to_calls", lambda _: calls)
    monkeypatch.setattr(
        "metesparser.closure_checker.ClosureChecker.verify_closure",
        lambda calls, stated_area_sq_ft=0.0, **kwargs: _verified_result(),
    )
    monkeypatch.setattr(
        "metesparser.closure_checker.ClosureChecker.get_closure_summary",
        lambda result, **kwargs: "VERIFIED",
    )

    try:
        cli.verify_command(str(csv))
    finally:
        configure_logging(level="INFO", log_format="console", stream=io.StringIO())

    captured = capsys.readouterr()
    assert captured.out == ""
    assert any(
        line.get("event") == "Closure summary" and line.get("summary") == "VERIFIED"
        for line in _json_log_lines(log_stream.getvalue())
    )


def test_main_configures_logging_from_cli_flags(monkeypatch, tmp_path):
    pdf = tmp_path / "input.pdf"
    pdf.write_text("pdf")

    observed: list[tuple[str, str, bool, bool]] = []

    def _configure_logging(
        *, level: str, log_format: str, debug: bool, take_over_root: bool
    ) -> None:
        observed.append((level, log_format, debug, take_over_root))

    monkeypatch.setattr("metesparser.cli.configure_logging", _configure_logging)
    monkeypatch.setattr(
        "metesparser.cli.extract_command",
        lambda pdf_path, output=None, llm_provider=None, **kwargs: None,
    )

    monkeypatch.setattr(
        sys,
        "argv",
        ["metesparser", "--debug", "--log-format", "json", "extract", str(pdf)],
    )
    cli.main()

    assert observed == [("DEBUG", "json", True, True)]


def test_main_rejects_invalid_log_level(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["metesparser", "--log-level", "VERBOSE"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert "Invalid log level" in (captured.out + captured.err)


class TestCompareRunsCommand:
    def test_compare_runs_logs_with_structlog(self, monkeypatch, tmp_path, capsys):
        """compare-runs should use structured logging like other commands."""
        log_stream = io.StringIO()
        configure_logging(level="INFO", log_format="json", stream=log_stream)

        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()

        try:
            cli.compare_runs_command(runs_dir=str(runs_dir))
        finally:
            configure_logging(level="INFO", log_format="console", stream=io.StringIO())

        lines = _json_log_lines(log_stream.getvalue())
        assert any(line.get("command") == "compare-runs" for line in lines), (
            f"Expected structlog entry with command='compare-runs', got: {lines}"
        )

    def test_compare_runs_exits_on_error(self, monkeypatch, tmp_path):
        """compare-runs should sys.exit(1) on unexpected errors, not raise."""
        monkeypatch.setattr(
            "metesparser.run_registry.load_run_manifests",
            lambda _: (_ for _ in ()).throw(RuntimeError("disk error")),
        )

        with pytest.raises(SystemExit) as exc:
            cli.compare_runs_command(runs_dir=str(tmp_path))
        assert exc.value.code == 1

    def test_compare_runs_outputs_table_to_stdout(self, monkeypatch, tmp_path, capsys):
        """compare-runs should still print the table to stdout."""
        monkeypatch.setattr("metesparser.run_registry.load_run_manifests", lambda _: [])
        monkeypatch.setattr(
            "metesparser.run_registry.format_comparison_table",
            lambda manifests, pdf_filter=None: "No runs found.",
        )

        cli.compare_runs_command(runs_dir=str(tmp_path))

        captured = capsys.readouterr()
        assert "No runs found." in captured.out

    def test_main_dispatches_compare_runs_command(self, monkeypatch, tmp_path):
        """CLI main() parses compare-runs flags and dispatches to compare_runs_command."""
        dispatched: list[tuple[str | None, str | None]] = []
        monkeypatch.setattr(
            "metesparser.cli.compare_runs_command",
            lambda runs_dir, pdf_filter: dispatched.append((runs_dir, pdf_filter)),
        )
        monkeypatch.setattr(
            sys,
            "argv",
            ["metesparser", "compare-runs", "--runs-dir", str(tmp_path), "--pdf", "pennbrook"],
        )

        cli.main()

        assert dispatched == [(str(tmp_path), "pennbrook")]


class TestExtractRunManifest:
    def test_extract_writes_run_manifest(self, monkeypatch, tmp_path):
        """Extract command should write a run manifest to runs/ directory."""
        from metesparser.run_registry import load_run_manifests

        pdf = tmp_path / "test.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        output = tmp_path / "out.csv"
        runs_dir = tmp_path / "runs"

        legal_desc = LegalDescription(
            calls=[
                DeedCall(
                    course=1,
                    direction_text="N 0° E",
                    bearing_quadrant="N 0° E",
                    bearing_azimuth_deg_from_north=0.0,
                    distance_ft=100.0,
                ),
                DeedCall(
                    course=2,
                    direction_text="S 90° E",
                    bearing_quadrant="N 90° E",
                    bearing_azimuth_deg_from_north=90.0,
                    distance_ft=100.0,
                ),
                DeedCall(
                    course=3,
                    direction_text="S 0° W",
                    bearing_quadrant="S 0° W",
                    bearing_azimuth_deg_from_north=180.0,
                    distance_ft=100.0,
                ),
                DeedCall(
                    course=4,
                    direction_text="N 90° W",
                    bearing_quadrant="N 90° W",
                    bearing_azimuth_deg_from_north=270.0,
                    distance_ft=100.0,
                ),
            ],
            source_doc="test.pdf",
        )

        verified = _verified_result()

        monkeypatch.setattr(
            "metesparser.pdf_processor.PDFProcessor",
            lambda **_kw: SimpleNamespace(
                process_deed_pdf=lambda _: legal_desc,
                prompts_dir=tmp_path,
                client=SimpleNamespace(model="gpt-5.2"),
            ),
        )
        monkeypatch.setattr(
            "metesparser.closure_checker.ClosureChecker.verify_closure",
            lambda calls, stated_area_sq_ft=0.0, **kwargs: verified,
        )
        monkeypatch.setattr(
            "metesparser.closure_checker.ClosureChecker.get_closure_summary",
            lambda result, **kwargs: "VERIFIED",
        )
        monkeypatch.setattr(
            "metesparser.csv_builder.CSVBuilder.export_verified_csv",
            lambda calls, closure_result, output_path, legal_desc_obj: None,
        )
        monkeypatch.setattr("metesparser.cli.RUNS_DIR", runs_dir)

        cli.extract_command(str(pdf), output=str(output))

        manifests = load_run_manifests(runs_dir)
        assert len(manifests) == 1
        assert manifests[0].source_pdf == "test.pdf"
        assert manifests[0].results.call_count == 4

    def test_extract_openrouter_unwraps_model_and_writes_manifest(self, monkeypatch, tmp_path):
        """CLI _unwrap_llm_model and extract_command record OpenRouter provider and model."""
        from metesparser.llm_cache import CachedLLMClient
        from metesparser.llm_clients import OpenRouterClient
        from metesparser.run_registry import load_run_manifests

        client = OpenRouterClient(api_key="or-offline", model="anthropic/claude-haiku-5.5")
        cached_client = CachedLLMClient(client, cache_dir=tmp_path / "cache")
        assert cli._unwrap_llm_model(SimpleNamespace(client=cached_client)) == (
            "anthropic/claude-haiku-5.5"
        )

        pdf = tmp_path / "deed.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        output = tmp_path / "out.csv"
        runs_dir = tmp_path / "runs"

        legal_desc = LegalDescription(
            calls=[
                DeedCall(
                    course=1,
                    direction_text="N 90° E",
                    bearing_quadrant="N 90° E",
                    bearing_azimuth_deg_from_north=90.0,
                    distance_ft=10.0,
                )
            ],
            source_doc="deed.pdf",
        )
        verified = _verified_result()

        seen_providers: list[str | None] = []

        def fake_processor(*, provider=None, cache=True):
            seen_providers.append(provider)
            return SimpleNamespace(
                process_deed_pdf=lambda _: legal_desc,
                prompts_dir=tmp_path,
                client=cached_client,
            )

        monkeypatch.setattr("metesparser.pdf_processor.PDFProcessor", fake_processor)
        monkeypatch.setattr(
            "metesparser.closure_checker.ClosureChecker.verify_closure",
            lambda calls, stated_area_sq_ft=0.0, **kwargs: verified,
        )
        monkeypatch.setattr(
            "metesparser.closure_checker.ClosureChecker.get_closure_summary",
            lambda result, **kwargs: "VERIFIED",
        )
        monkeypatch.setattr(
            "metesparser.csv_builder.CSVBuilder.export_verified_csv",
            lambda calls, closure_result, output_path, legal_desc_obj: None,
        )
        monkeypatch.setattr("metesparser.cli.RUNS_DIR", runs_dir)

        cli.extract_command(str(pdf), output=str(output), llm_provider="openrouter")

        assert seen_providers == ["openrouter"]
        manifests = load_run_manifests(runs_dir)
        assert len(manifests) == 1
        assert manifests[0].llm_provider == "openrouter"
        assert manifests[0].llm_model == "anthropic/claude-haiku-5.5"


class TestExtractAuditAndEscalationFlags:
    """CLI --audit and --escalate-* flag parsing, validation, and Pipeline wiring."""

    _CLOSED_SQUARE = (
        "BEGINNING at a point; "
        "THENCE N 0°00'00\" E 100.00 feet to a point; "
        "THENCE S 90°00'00\" E 100.00 feet to a point; "
        "THENCE S 0°00'00\" W 100.00 feet to a point; "
        "THENCE N 90°00'00\" W 100.00 feet to the point of beginning."
    )
    _BROKEN_SQUARE = (
        "BEGINNING at a point; "
        "THENCE N 0°00'00\" E 100.00 feet to a point; "
        "THENCE S 90°00'00\" E 100.00 feet to a point; "
        "THENCE S 0°00'00\" W 100.00 feet to a point; "
        "THENCE N 90°00'00\" W 99.00 feet to the point of beginning."
    )
    _TWO_TRACT_CLOSED = (
        "TRACT #1: BEGINNING at a point; "
        "THENCE N 0°00'00\" E 100.00 feet; "
        "THENCE S 90°00'00\" E 100.00 feet; "
        "THENCE S 0°00'00\" W 100.00 feet; "
        "THENCE N 90°00'00\" W 100.00 feet to the point of beginning. "
        "TRACT #2: BEGINNING at a point; "
        "THENCE N 0°00'00\" E 50.00 feet; "
        "THENCE S 90°00'00\" E 50.00 feet; "
        "THENCE S 0°00'00\" W 50.00 feet; "
        "THENCE N 90°00'00\" W 50.00 feet to the point of beginning."
    )
    _TWO_TRACT_BROKEN = (
        "TRACT #1: BEGINNING at a point; "
        "THENCE N 0°00'00\" E 100.00 feet; "
        "THENCE S 90°00'00\" E 100.00 feet; "
        "THENCE S 0°00'00\" W 100.00 feet; "
        "THENCE N 90°00'00\" W 98.00 feet to the point of beginning. "
        "TRACT #2: BEGINNING at a point; "
        "THENCE N 0°00'00\" E 50.00 feet; "
        "THENCE S 90°00'00\" E 50.00 feet; "
        "THENCE S 0°00'00\" W 50.00 feet; "
        "THENCE N 90°00'00\" W 48.00 feet to the point of beginning."
    )

    @staticmethod
    def _make_fake_client_cls(
        *,
        model: str,
        text: str,
        locate_json: str = '{"pages": [1]}',
    ):
        from metesparser.llm_clients import BaseLLMClient

        class _FakeClient(BaseLLMClient):
            def __init__(self, api_key: str | None = None, **_kwargs: object) -> None:
                self.api_key = api_key
                self.model = model

            def generate_text_with_pdf(
                self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
            ) -> str:
                return text

            def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
                return text

            def generate_text_with_images(
                self, prompt: str, image_paths: object, *, response_mime_type: str | None = None
            ) -> str:
                if response_mime_type == "application/json":
                    return locate_json
                return text

        return _FakeClient

    def test_main_dispatches_audit_and_escalation_flags(self, monkeypatch, tmp_path):
        pdf = tmp_path / "input.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        out = tmp_path / "out.csv"

        recorded: list[tuple[tuple[object, ...], dict[str, object]]] = []
        monkeypatch.setattr(
            "metesparser.cli.extract_command",
            lambda *args, **kwargs: recorded.append((args, kwargs)),
        )

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "metesparser",
                "extract",
                str(pdf),
                "-o",
                str(out),
                "--llm-provider",
                "openrouter",
                "--no-cache",
                "--audit",
                "--escalate-policy",
                "closure_failed",
                "--escalate-provider",
                "gemini",
                "--escalate-dpi",
                "400",
            ],
        )
        cli.main()

        assert recorded == [
            (
                (str(pdf), str(out), "openrouter"),
                {
                    "no_cache": True,
                    "audit": True,
                    "escalate_policy": "closure_failed",
                    "escalate_provider": "gemini",
                    "escalate_dpi": 400,
                },
            )
        ]

        recorded.clear()
        monkeypatch.setattr(sys, "argv", ["metesparser", "extract", str(pdf)])
        cli.main()
        assert recorded == [((str(pdf), None, None), {"no_cache": False})]

    @pytest.mark.parametrize(
        "extra_args",
        [
            ["--escalate-policy", "always"],
            ["--escalate-policy", "closure_failed", "--escalate-provider", "anthropic"],
            ["--escalate-policy", "never", "--escalate-provider", "gemini"],
            ["--escalate-policy", "never", "--escalate-dpi", "400"],
            ["--escalate-policy", "closure_failed", "--escalate-dpi", "0"],
            ["--escalate-policy", "closure_failed", "--escalate-dpi", "601"],
        ],
    )
    def test_main_rejects_inconsistent_and_out_of_range_escalation_flags(
        self, monkeypatch, tmp_path, capsys, extra_args
    ):
        pdf = tmp_path / "input.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")

        monkeypatch.setattr(
            sys,
            "argv",
            ["metesparser", "extract", str(pdf), *extra_args],
        )
        with pytest.raises(SystemExit) as exc:
            cli.main()

        assert exc.value.code == 2
        captured = capsys.readouterr()
        assert captured.err

    def test_extract_command_rejects_invalid_escalation_args_and_missing_api_key(
        self, monkeypatch, tmp_path
    ):
        pdf = tmp_path / "deed.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        monkeypatch.setattr("metesparser.cli.RUNS_DIR", tmp_path / "runs")
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.setattr(
            "metesparser.pdf_processor.PDFProcessor",
            lambda **_kw: pytest.fail("PDFProcessor must not run on invalid escalation config"),
        )

        invalid_calls = [
            {"escalate_policy": "always"},
            {"escalate_policy": "never", "escalate_dpi": 400},
            {"escalate_policy": "closure_failed", "escalate_provider": "bogus"},
            {"escalate_policy": "closure_failed", "escalate_provider": "gemini"},
        ]
        for kwargs in invalid_calls:
            with pytest.raises(SystemExit) as exc:
                cli.extract_command(str(pdf), output=str(tmp_path / "out.csv"), **kwargs)
            assert exc.value.code == 1

    def test_extract_command_audit_writes_verified_audit_sidecars(self, monkeypatch, tmp_path):
        monkeypatch.setattr("metesparser.cli.RUNS_DIR", tmp_path / "runs")

        # Single-tract verified
        pdf_single = tmp_path / "single.pdf"
        pdf_single.write_bytes(b"%PDF-1.4\n")
        out_single = tmp_path / "single.csv"
        monkeypatch.setattr(
            "metesparser.pdf_processor.OpenAIClient",
            self._make_fake_client_cls(model="gpt-5.2", text=self._CLOSED_SQUARE),
        )
        cli.extract_command(
            str(pdf_single),
            output=str(out_single),
            llm_provider="openai",
            no_cache=True,
            audit=True,
        )

        verified_csv = tmp_path / "single_verified.csv"
        audit_json = tmp_path / "single_verified.audit.json"
        audit_html = tmp_path / "single_verified.audit.html"
        assert verified_csv.exists()
        assert audit_json.exists()
        assert audit_html.exists()
        payload = json.loads(audit_json.read_text(encoding="utf-8"))
        assert payload["run_metadata"]["llm_provider"] == "openai"
        assert payload["verification_audit"] is not None
        assert "<!DOCTYPE html>" in audit_html.read_text(encoding="utf-8")

        # Multi-tract verified
        pdf_multi = tmp_path / "multi.pdf"
        pdf_multi.write_bytes(b"%PDF-1.4\n")
        out_multi = tmp_path / "multi.csv"
        monkeypatch.setattr(
            "metesparser.pdf_processor.OpenAIClient",
            self._make_fake_client_cls(model="gpt-5.2", text=self._TWO_TRACT_CLOSED),
        )
        cli.extract_command(
            str(pdf_multi),
            output=str(out_multi),
            llm_provider="openai",
            no_cache=True,
            audit=True,
        )

        assert (tmp_path / "multi_verified_tract1.csv").exists()
        assert (tmp_path / "multi_verified_tract2.csv").exists()
        multi_json = tmp_path / "multi_verified.audit.json"
        multi_html = tmp_path / "multi_verified.audit.html"
        assert multi_json.exists()
        assert multi_html.exists()
        multi_payload = json.loads(multi_json.read_text(encoding="utf-8"))
        assert len(multi_payload["tract_verification_audits"]) == 2
        assert "<!DOCTYPE html>" in multi_html.read_text(encoding="utf-8")

    def test_extract_command_audit_writes_unverified_audit_sidecars_without_verified_suffix(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setattr("metesparser.cli.RUNS_DIR", tmp_path / "runs")

        # Single-tract unverified
        single_dir = tmp_path / "single"
        single_dir.mkdir()
        pdf_single = single_dir / "bad.pdf"
        pdf_single.write_bytes(b"%PDF-1.4\n")
        out_single = single_dir / "out.csv"
        monkeypatch.setattr(
            "metesparser.pdf_processor.OpenAIClient",
            self._make_fake_client_cls(model="gpt-5.2", text=self._BROKEN_SQUARE),
        )
        cli.extract_command(
            str(pdf_single),
            output=str(out_single),
            llm_provider="openai",
            no_cache=True,
            audit=True,
        )

        assert out_single.exists()
        assert (single_dir / "out.audit.json").exists()
        assert (single_dir / "out.audit.html").exists()
        assert list(single_dir.glob("*_verified*")) == []
        assert "<!DOCTYPE html>" in (single_dir / "out.audit.html").read_text(encoding="utf-8")

        # Multi-tract unverified
        multi_dir = tmp_path / "multi"
        multi_dir.mkdir()
        pdf_multi = multi_dir / "bad_multi.pdf"
        pdf_multi.write_bytes(b"%PDF-1.4\n")
        out_multi = multi_dir / "multi_out.csv"
        monkeypatch.setattr(
            "metesparser.pdf_processor.OpenAIClient",
            self._make_fake_client_cls(model="gpt-5.2", text=self._TWO_TRACT_BROKEN),
        )
        cli.extract_command(
            str(pdf_multi),
            output=str(out_multi),
            llm_provider="openai",
            no_cache=True,
            audit=True,
        )

        assert out_multi.exists()
        assert (multi_dir / "multi_out.audit.json").exists()
        assert (multi_dir / "multi_out.audit.html").exists()
        assert list(multi_dir.glob("*_verified*")) == []

    def test_extract_command_escalation_policy_runs_through_pipeline_and_fails_closed_on_disagreement(
        self, monkeypatch, tmp_path
    ):
        import base64

        from pypdf import PdfWriter

        monkeypatch.setattr("metesparser.cli.RUNS_DIR", tmp_path / "runs")
        secret_key = "secret-gemini-api-key-never-persist"
        monkeypatch.setenv("GEMINI_API_KEY", secret_key)

        pdf = tmp_path / "esc.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        writer.add_blank_page(width=612, height=792)
        with pdf.open("wb") as handle:
            writer.write(handle)

        png = tmp_path / "page.png"
        png.write_bytes(
            base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC"
            )
        )

        monkeypatch.setattr(
            "metesparser.pdf_processor.OpenAIClient",
            self._make_fake_client_cls(
                model="gpt-primary", text=self._BROKEN_SQUARE, locate_json='{"pages": [1]}'
            ),
        )
        monkeypatch.setattr(
            "metesparser.pdf_processor.GeminiClient",
            self._make_fake_client_cls(
                model="gemini-esc", text=self._CLOSED_SQUARE, locate_json='{"pages": [1]}'
            ),
        )
        monkeypatch.setattr(
            "mp_ocr.preprocess_pdf_pages_for_ocr",
            lambda _pdf, _out, *, pages=None, **_kw: [png] * (len(pages) if pages else 2),
        )

        out = tmp_path / "esc.csv"
        cli.extract_command(
            str(pdf),
            output=str(out),
            llm_provider="openai",
            no_cache=True,
            audit=True,
            escalate_policy="closure_failed",
            escalate_provider="gemini",
            escalate_dpi=300,
        )

        assert out.exists()
        assert list(tmp_path.glob("*_verified*")) == []
        audit_json = tmp_path / "esc.audit.json"
        audit_html = tmp_path / "esc.audit.html"
        assert audit_json.exists()
        assert audit_html.exists()
        raw_json = audit_json.read_text(encoding="utf-8")
        raw_html = audit_html.read_text(encoding="utf-8")
        assert secret_key not in raw_json
        assert secret_key not in raw_html
        payload = json.loads(raw_json)
        cfg = payload["run_metadata"]["config"]
        assert cfg["escalation_policy"] == "closure_failed"
        assert cfg["escalation_triggered"] is True
        assert cfg["escalation_selected"] == "escalated"
        assert cfg["escalation_agrees"] is False
        assert cfg["escalation_disagreement_count"] == 1
        assert "<!DOCTYPE html>" in raw_html

    def test_extract_command_respects_metesparser_llm_provider_env_when_flag_omitted(
        self, monkeypatch, tmp_path
    ):
        from metesparser.run_registry import load_run_manifests

        pdf = tmp_path / "env_provider.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        out = tmp_path / "out.csv"
        runs_dir = tmp_path / "runs"
        monkeypatch.setattr("metesparser.cli.RUNS_DIR", runs_dir)
        monkeypatch.setenv("METESPARSER_LLM_PROVIDER", "gemini")

        legal_desc = LegalDescription(
            calls=[
                DeedCall(
                    course=1,
                    direction_text="N 90° E",
                    bearing_quadrant="N 90° E",
                    bearing_azimuth_deg_from_north=90.0,
                    distance_ft=10.0,
                )
            ],
            source_doc="env_provider.pdf",
        )
        seen_providers: list[str | None] = []

        def _fake_processor(*, provider=None, cache=True):
            seen_providers.append(provider)
            return SimpleNamespace(
                process_deed_pdf=lambda _: legal_desc,
                prompts_dir=tmp_path,
                model_name="gemini-test",
            )

        monkeypatch.setattr("metesparser.pdf_processor.PDFProcessor", _fake_processor)
        monkeypatch.setattr(
            "metesparser.closure_checker.ClosureChecker.verify_closure",
            lambda calls, stated_area_sq_ft=0.0, **kwargs: _verified_result(),
        )
        monkeypatch.setattr(
            "metesparser.closure_checker.ClosureChecker.get_closure_summary",
            lambda result, **kwargs: "VERIFIED",
        )
        monkeypatch.setattr(
            "metesparser.csv_builder.CSVBuilder.export_verified_csv",
            lambda calls, closure_result, output_path, legal_desc_obj: None,
        )

        cli.extract_command(str(pdf), output=str(out))

        assert seen_providers == ["gemini"]
        manifests = load_run_manifests(runs_dir)
        assert len(manifests) == 1
        assert manifests[0].llm_provider == "gemini"
        assert manifests[0].llm_model == "gemini-test"
