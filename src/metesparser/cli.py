"""Command-line interface for metesparser."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import structlog

from .logging_config import configure_logging, get_log_format

logger = structlog.get_logger(__name__)


def _emit_closure_summary(summary: str, command_logger: structlog.stdlib.BoundLogger) -> None:
    if get_log_format() == "json":
        command_logger.info("Closure summary", summary=summary)
        return

    print()
    print(summary)
    print()


def extract_command(
    pdf_path: str, output: str | None = None, llm_provider: str | None = None
) -> None:
    """Extract legal description from PDF and save to CSV.

    Args:
        pdf_path: Path to input PDF file
        output: Output CSV path (default: derived from input filename)
        llm_provider: Optional LLM provider override
    """
    from .closure_checker import ClosureChecker
    from .csv_builder import CSVBuilder
    from .pdf_processor import PDFProcessor

    pdf_file = Path(pdf_path)
    if not pdf_file.exists():
        logger.error("PDF file not found", path=pdf_path)
        sys.exit(1)

    if not output:
        output = str(pdf_file.with_suffix(".csv"))

    command_logger = logger.bind(command="extract", input_pdf=pdf_path, output_csv=output)
    command_logger.info("Processing deed PDF")

    try:
        processor = PDFProcessor(provider=llm_provider)
        legal_desc = processor.process_deed_pdf(pdf_path)

        command_logger.info("Verifying closure")
        closure_result = ClosureChecker.verify_closure(legal_desc.calls)

        summary = ClosureChecker.get_closure_summary(closure_result)
        _emit_closure_summary(summary, command_logger)

        if closure_result.is_fully_verified():
            command_logger.info("Exporting verified CSV")
            CSVBuilder.export_verified_csv(legal_desc.calls, closure_result, output, legal_desc)
        else:
            command_logger.warning("Verification did not pass completely; exporting unverified CSV")
            CSVBuilder.legal_description_to_csv(legal_desc, output)
            command_logger.info("Exported unverified CSV")

    except Exception:
        command_logger.exception("Failed to process PDF")
        sys.exit(1)


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

    command_logger = logger.bind(command="verify", input_csv=csv_path)
    command_logger.info("Verifying calls from CSV")

    try:
        calls = CSVBuilder.csv_to_calls(csv_path)
        command_logger.info("Loaded calls", count=len(calls))

        closure_result = ClosureChecker.verify_closure(calls, stated_area or 0.0)

        summary = ClosureChecker.get_closure_summary(closure_result)
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

    verify_parser = subparsers.add_parser("verify", help="Verify a CSV file of calls")
    verify_parser.add_argument("csv", help="Path to CSV file")
    verify_parser.add_argument(
        "-a", "--area", type=float, help="Stated area in square feet (for comparison)"
    )

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
        extract_command(args.pdf, args.output, args.llm_provider)
    elif args.command == "verify":
        verify_command(args.csv, args.area)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
