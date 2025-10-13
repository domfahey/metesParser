"""Command-line interface for metesparser."""

import sys
from pathlib import Path

import structlog

logger = structlog.get_logger()


def extract_command(pdf_path: str, output: str | None = None) -> None:
    """Extract legal description from PDF and save to CSV.

    Args:
        pdf_path: Path to input PDF file
        output: Output CSV path (default: derived from input filename)
    """
    from .closure_checker import ClosureChecker
    from .csv_builder import CSVBuilder
    from .pdf_processor import PDFProcessor

    # Check if PDF exists
    pdf_file = Path(pdf_path)
    if not pdf_file.exists():
        logger.error("PDF file not found", path=pdf_path)
        sys.exit(1)

    # Determine output path
    if not output:
        output = str(pdf_file.with_suffix(".csv"))

    logger.info("Processing deed PDF", input=pdf_path, output=output)

    try:
        # Process PDF
        processor = PDFProcessor()
        legal_desc = processor.process_deed_pdf(pdf_path)

        # Verify closure
        logger.info("Verifying closure...")
        closure_result = ClosureChecker.verify_closure(legal_desc.calls)

        # Print closure summary
        print()
        print(ClosureChecker.get_closure_summary(closure_result))
        print()

        # Export CSV
        if closure_result.is_fully_verified():
            logger.info("Exporting verified CSV...")
            CSVBuilder.export_verified_csv(legal_desc.calls, closure_result, output, legal_desc)
        else:
            logger.warning("Verification did not pass completely. Exporting unverified CSV.")
            CSVBuilder.legal_description_to_csv(legal_desc, output)
            logger.info("Exported to", path=output)

    except Exception as e:
        logger.error("Failed to process PDF", error=str(e))
        sys.exit(1)


def verify_command(csv_path: str, stated_area: float | None = None) -> None:
    """Verify a CSV file of calls.

    Args:
        csv_path: Path to CSV file
        stated_area: Optional stated area in sq ft for comparison
    """
    from .closure_checker import ClosureChecker
    from .csv_builder import CSVBuilder

    # Check if CSV exists
    csv_file = Path(csv_path)
    if not csv_file.exists():
        logger.error("CSV file not found", path=csv_path)
        sys.exit(1)

    logger.info("Verifying calls from CSV", path=csv_path)

    try:
        # Load calls
        calls = CSVBuilder.csv_to_calls(csv_path)
        logger.info("Loaded calls", count=len(calls))

        # Verify closure
        closure_result = ClosureChecker.verify_closure(calls, stated_area or 0.0)

        # Print summary
        print()
        print(ClosureChecker.get_closure_summary(closure_result))
        print()

        if closure_result.is_fully_verified():
            logger.info("✓ All verification checks passed")
        else:
            logger.warning("Some verification checks did not pass")
            sys.exit(1)

    except Exception as e:
        logger.error("Failed to verify CSV", error=str(e))
        sys.exit(1)


def export_command(csv_path: str, format: str = "geojson", output: str | None = None) -> None:
    """Export calls to GeoJSON or KML.

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

    # Load environment variables
    load_dotenv()

    # Configure logging
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ]
    )

    parser = argparse.ArgumentParser(
        description="Metes & Bounds Deed Parser - Extract and verify legal descriptions"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Extract command
    extract_parser = subparsers.add_parser("extract", help="Extract legal description from PDF")
    extract_parser.add_argument("pdf", help="Path to PDF file")
    extract_parser.add_argument(
        "-o", "--output", help="Output CSV file path (default: derived from input)"
    )

    # Verify command
    verify_parser = subparsers.add_parser("verify", help="Verify a CSV file of calls")
    verify_parser.add_argument("csv", help="Path to CSV file")
    verify_parser.add_argument(
        "-a", "--area", type=float, help="Stated area in square feet (for comparison)"
    )

    # Export command
    export_parser = subparsers.add_parser("export", help="Export calls to GeoJSON or KML")
    export_parser.add_argument("csv", help="Path to CSV file")
    export_parser.add_argument(
        "-f",
        "--format",
        choices=["geojson", "kml"],
        default="geojson",
        help="Output format",
    )
    export_parser.add_argument(
        "-o", "--output", help="Output file path (default: derived from input)"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    # Route to command
    if args.command == "extract":
        extract_command(args.pdf, args.output)
    elif args.command == "verify":
        verify_command(args.csv, args.area)
    elif args.command == "export":
        export_command(args.csv, args.format, args.output)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
