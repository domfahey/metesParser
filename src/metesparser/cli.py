"""Command-line interface for metesparser."""

from __future__ import annotations

import inspect
import math
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
import structlog.contextvars

from .logging_config import configure_logging, get_log_format

logger = structlog.get_logger(__name__)

RUNS_DIR = Path("output/runs")


def _unwrap_llm_model(processor: object) -> str:
    """Resolve the underlying model identifier through any CachedLLMClient wrappers."""
    client: Any = getattr(processor, "client", None)
    seen: set[int] = set()
    while client is not None and id(client) not in seen:
        seen.add(id(client))
        model = getattr(client, "model", None)
        if isinstance(model, str) and model:
            return model
        client = getattr(client, "_client", None)
    return "unknown"


def _verify_closure_compat(
    verify_fn: Any,
    calls: list[Any],
    *,
    stated_area_sq_ft: float,
    tracts: list[Any] | None = None,
) -> Any:
    """Call ClosureChecker.verify_closure while remaining compatible with 2-arg mocks."""
    params = inspect.signature(verify_fn).parameters
    accepts_var_kw = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
    kwargs: dict[str, Any] = {}
    if "tracts" in params or accepts_var_kw:
        kwargs["tracts"] = tracts
    if "stated_area_sq_ft" in params or accepts_var_kw:
        kwargs["stated_area_sq_ft"] = stated_area_sq_ft
        return verify_fn(calls, **kwargs)
    return verify_fn(calls, stated_area_sq_ft, **kwargs)


def _get_closure_summary_compat(
    summary_fn: Any, result: Any, calls: list[Any] | None = None
) -> str:
    """Call ClosureChecker.get_closure_summary while remaining compatible with 1-arg mocks."""
    params = inspect.signature(summary_fn).parameters
    accepts_var_kw = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
    if "calls" in params or accepts_var_kw:
        return str(summary_fn(result, calls=calls))
    return str(summary_fn(result))


def _aggregate_tract_closure(tract_results: list[tuple[Any, Any]]) -> Any:
    """Summarize per-tract ClosureResult objects into a single RunResults-compatible ClosureResult."""
    from mp_models import is_boundary_tract

    from .models import ClosureResult

    if not tract_results:
        return ClosureResult(
            misclosure_x_ft=0.0,
            misclosure_y_ft=0.0,
            misclosure_ft=0.0,
            area_sq_ft=0.0,
            area_acres=0.0,
            perimeter_ft=0.0,
            misclosure_available=False,
            area_available=False,
            perimeter_available=False,
            closure_passed=False,
            angle_check_passed=False,
            curve_consistency_passed=False,
            confidence_score=0.0,
            warnings=["No tracts verified"],
        )
    boundary = [r for t, r in tract_results if is_boundary_tract(t.tract_type)]
    selected = boundary or [r for _, r in tract_results]
    all_warnings = [w for _, r in tract_results for w in r.warnings]
    misclosure_avail = all(r.misclosure_available for r in selected)
    area_avail = all(r.area_available for r in selected)
    perimeter_avail = all(r.perimeter_available for r in selected)
    confidences = [r.confidence_score for r in selected if r.confidence_score is not None]
    return ClosureResult(
        misclosure_x_ft=selected[0].misclosure_x_ft if len(selected) == 1 else 0.0,
        misclosure_y_ft=selected[0].misclosure_y_ft if len(selected) == 1 else 0.0,
        misclosure_ft=max(
            (r.misclosure_ft for r in selected if r.misclosure_available), default=0.0
        ),
        area_sq_ft=sum(r.area_sq_ft for r in selected) if area_avail else 0.0,
        area_acres=sum(r.area_acres for r in selected) if area_avail else 0.0,
        perimeter_ft=sum(r.perimeter_ft for r in selected) if perimeter_avail else 0.0,
        misclosure_available=misclosure_avail,
        area_available=area_avail,
        perimeter_available=perimeter_avail,
        closure_passed=(
            all(r.closure_passed for r in selected) and all(r.is_fully_verified() for r in selected)
        ),
        angle_check_passed=all(r.angle_check_passed for r in selected),
        curve_consistency_passed=all(r.curve_consistency_passed for r in selected),
        confidence_score=min(confidences) if confidences else 0.0,
        warnings=all_warnings,
    )


def _emit_closure_summary(summary: str, command_logger: structlog.stdlib.BoundLogger) -> None:
    command_logger.info("Closure summary", summary=summary)
    if get_log_format() != "json":
        print()
        print(summary)
        print()


def extract_command(
    pdf_path: str,
    output: str | None = None,
    llm_provider: str | None = None,
    *,
    no_cache: bool = False,
) -> None:
    """Extract legal description from PDF and save to CSV.

    Args:
        pdf_path: Path to input PDF file
        output: Output CSV path (default: derived from input filename)
        llm_provider: Optional LLM provider override
    """
    from mp_models import mark_roles_review, roles_need_review, roles_review_detail

    from .closure_checker import ClosureChecker
    from .csv_builder import CSVBuilder
    from .pdf_processor import PDFProcessor

    pdf_file = Path(pdf_path)
    if not pdf_file.exists():
        logger.error("PDF file not found", path=pdf_path)
        sys.exit(1)

    if not output:
        output = str(pdf_file.with_suffix(".csv"))

    run_id = str(uuid.uuid4())
    ctx = {"command": "extract", "input_pdf": pdf_path, "output_csv": output, "run_id": run_id}
    structlog.contextvars.bind_contextvars(**ctx)
    command_logger = logger.bind(**ctx)
    command_logger.info("Processing deed PDF")

    try:
        processor = PDFProcessor(provider=llm_provider, cache=not no_cache)
        result = processor.process_deed_pdf(pdf_path)
        assert not isinstance(result, tuple)  # audit=False (default)
        legal_desc = result

        # Guessed description roles (several descriptions, a role inferred from
        # wording) are never verified or exported, whatever the flat geometry: the
        # calls carry the role-review mark, so the unverified CSV fails `verify` too.
        role_review = roles_need_review(legal_desc.tracts, legal_desc.calls)
        if role_review:
            command_logger.warning(roles_review_detail(role_review))
            legal_desc = legal_desc.model_copy(
                update={
                    "calls": mark_roles_review(legal_desc.calls),
                    "tracts": [
                        t.model_copy(update={"calls": mark_roles_review(t.calls)})
                        for t in legal_desc.tracts
                    ],
                }
            )

        from mp_models import is_boundary_tract

        tracts_arg = legal_desc.tracts or None
        calls_for_verify = legal_desc.all_calls if tracts_arg else legal_desc.calls

        command_logger.info("Verifying closure")
        closure_result = _verify_closure_compat(
            ClosureChecker.verify_closure,
            calls_for_verify,
            stated_area_sq_ft=legal_desc.stated_area_sq_ft or 0.0,
            tracts=tracts_arg,
        )

        if isinstance(closure_result, list):
            tract_results = list(zip(legal_desc.tracts, closure_result, strict=True))
            summary = "\n\n".join(
                f"--- {tract.label} ---\n"
                + _get_closure_summary_compat(
                    ClosureChecker.get_closure_summary, tract_res, calls=tract.calls
                )
                for tract, tract_res in tract_results
            )
            _emit_closure_summary(summary, command_logger)
            any_exportable = not role_review and any(
                is_boundary_tract(tract.tract_type) and tract_res.is_fully_verified()
                for tract, tract_res in tract_results
            )
            if any_exportable:
                command_logger.info("Exporting verified CSV")
                CSVBuilder.export_verified_csv(
                    calls_for_verify,
                    closure_result[0],
                    output,
                    legal_desc,
                    tract_results=tract_results,
                )
            else:
                command_logger.warning(
                    "Verification did not pass completely; exporting unverified CSV"
                )
                CSVBuilder.legal_description_to_csv(legal_desc, output)
                command_logger.info("Exported unverified CSV")
            manifest_closure = _aggregate_tract_closure(tract_results)
        else:
            summary = _get_closure_summary_compat(
                ClosureChecker.get_closure_summary, closure_result, calls=calls_for_verify
            )
            _emit_closure_summary(summary, command_logger)

            if closure_result.is_fully_verified() and not role_review:
                command_logger.info("Exporting verified CSV")
                CSVBuilder.export_verified_csv(legal_desc.calls, closure_result, output, legal_desc)
            else:
                command_logger.warning(
                    "Verification did not pass completely; exporting unverified CSV"
                )
                CSVBuilder.legal_description_to_csv(legal_desc, output)
                command_logger.info("Exported unverified CSV")
            manifest_closure = closure_result

        # Write run manifest (never fails the main extract flow)
        try:
            import metesparser

            from .run_registry import (
                RunManifest,
                RunResults,
                get_prompt_versions,
                write_run_manifest,
            )

            prompt_versions = get_prompt_versions(processor.prompts_dir)
            manifest = RunManifest(
                run_id=run_id,
                timestamp_utc=datetime.now(UTC),
                source_pdf=pdf_file.name,
                llm_provider=llm_provider or os.getenv("METESPARSER_LLM_PROVIDER") or "openai",
                llm_model=_unwrap_llm_model(processor),
                cache_enabled=not no_cache,
                prompt_versions=prompt_versions,
                results=RunResults.from_closure(manifest_closure, len(calls_for_verify)),
                parser_version=metesparser.__version__,
            )
            write_run_manifest(manifest, RUNS_DIR)
        except Exception:
            command_logger.warning("Failed to write run manifest", exc_info=True)

    except Exception:
        command_logger.exception("Failed to process PDF")
        sys.exit(1)
    finally:
        structlog.contextvars.clear_contextvars()


def verify_command(csv_path: str, stated_area: float | None = None) -> None:
    """Verify a CSV file of calls.

    Args:
        csv_path: Path to CSV file
        stated_area: Optional stated area in sq ft for comparison
    """
    from .closure_checker import ClosureChecker
    from .csv_builder import CSVBuilder

    csv_file = Path(csv_path)
    if not csv_file.exists():
        logger.error("CSV file not found", path=csv_path)
        sys.exit(1)

    if stated_area is not None and (not math.isfinite(stated_area) or stated_area <= 0):
        logger.error("Stated area must be finite and positive", stated_area=stated_area)
        sys.exit(1)

    command_logger = logger.bind(command="verify", input_csv=csv_path)
    command_logger.info("Verifying calls from CSV")

    try:
        calls = CSVBuilder.csv_to_calls(csv_path)
        command_logger.info("Loaded calls", count=len(calls))

        closure_result = _verify_closure_compat(
            ClosureChecker.verify_closure,
            calls,
            stated_area_sq_ft=stated_area or 0.0,
        )

        summary = _get_closure_summary_compat(
            ClosureChecker.get_closure_summary, closure_result, calls=calls
        )
        _emit_closure_summary(summary, command_logger)

        if closure_result.is_fully_verified():
            command_logger.info("All verification checks passed")
        else:
            command_logger.warning("Some verification checks did not pass")
            sys.exit(1)

    except Exception:
        command_logger.exception("Failed to verify CSV")
        sys.exit(1)


def export_command(csv_path: str, format: str = "geojson", output: str | None = None) -> None:
    """Export calls to GeoJSON or KML (currently not implemented).

    Args:
        csv_path: Path to CSV file
        format: Output format (geojson or kml)
        output: Output file path (default: derived from input)
    """
    logger.error("Export functionality not yet implemented")
    sys.exit(1)


def compare_runs_command(runs_dir: str | None = None, pdf_filter: str | None = None) -> None:
    """Compare extraction runs across prompt versions."""
    from .run_registry import format_comparison_table, load_run_manifests

    resolved_dir = Path(runs_dir) if runs_dir else RUNS_DIR
    command_logger = logger.bind(command="compare-runs", runs_dir=str(resolved_dir))
    command_logger.info("Comparing runs")

    try:
        manifests = load_run_manifests(resolved_dir)
        command_logger.info("Loaded run manifests", count=len(manifests))
        output = format_comparison_table(manifests, pdf_filter=pdf_filter)
        print(output)
    except Exception:
        command_logger.exception("Failed to compare runs")
        sys.exit(1)


def main() -> None:
    """Main CLI entry point."""
    import argparse

    from dotenv import load_dotenv

    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Metes & Bounds Deed Parser - Extract and verify legal descriptions"
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("METESPARSER_LOG_LEVEL", "INFO"),
        help="Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )
    parser.add_argument(
        "--log-format",
        choices=["console", "json"],
        default=os.getenv("METESPARSER_LOG_FORMAT", "console"),
        help="Log output format",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging with callsite metadata",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    extract_parser = subparsers.add_parser("extract", help="Extract legal description from PDF")
    extract_parser.add_argument("pdf", help="Path to PDF file")
    extract_parser.add_argument(
        "-o", "--output", help="Output CSV file path (default: derived from input)"
    )
    extract_parser.add_argument(
        "--llm-provider",
        choices=["openai", "gemini"],
        help="LLM provider to use (overrides METESPARSER_LLM_PROVIDER env var)",
    )
    extract_parser.add_argument(
        "--no-cache",
        action="store_true",
        default=False,
        help="Disable LLM response caching (re-query the LLM for every call)",
    )

    verify_parser = subparsers.add_parser("verify", help="Verify a CSV file of calls")
    verify_parser.add_argument("csv", help="Path to CSV file")
    verify_parser.add_argument(
        "-a", "--area", type=float, help="Stated area in square feet (for comparison)"
    )

    compare_parser = subparsers.add_parser("compare-runs", help="Compare extraction runs")
    compare_parser.add_argument(
        "--runs-dir", help="Directory containing run manifests (default: output/runs/)"
    )
    compare_parser.add_argument("--pdf", help="Filter by PDF name (substring match)")

    args = parser.parse_args()

    try:
        configured_level = "DEBUG" if args.debug else args.log_level
        configure_logging(
            level=configured_level,
            log_format=args.log_format,
            debug=args.debug,
            take_over_root=True,
        )
        logger.debug(
            "Logging configured",
            level=configured_level,
            format=args.log_format,
            debug=args.debug,
        )
    except ValueError as exc:
        parser.error(str(exc))

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "extract":
        extract_command(args.pdf, args.output, args.llm_provider, no_cache=args.no_cache)
    elif args.command == "verify":
        if args.area is not None and (not math.isfinite(args.area) or args.area <= 0):
            parser.error("--area must be a finite positive number")
        verify_command(args.csv, args.area)
    elif args.command == "compare-runs":
        compare_runs_command(args.runs_dir, args.pdf)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
