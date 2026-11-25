#!/usr/bin/env python3
"""Extract and save deed call information from all sample PDFs.

This script processes each sample deed PDF and creates output files
showing the extraction results for human review.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mp_models import is_boundary_tract

from metesparser.cli import aggregate_tract_closure
from metesparser.closure_checker import ClosureChecker
from metesparser.csv_builder import CSVBuilder
from metesparser.models import ClosureResult, LegalDescription
from metesparser.pdf_processor import PDFProcessor

# Sample deed PDFs
SAMPLE_DEEDS_DIR = Path(__file__).resolve().parent.parent / "sample_deeds"
OUTPUT_DIR = Path(__file__).parent.parent / "output" / "extractions"

SAMPLE_PDFS = [
    ("18 Pennbrook Dr - Deed Image (11985 - 00829).pdf", "18_pennbrook"),
    ("24 Pennbrook Dr - Deed Image (11793 - 00217).pdf", "24_pennbrook"),
    ("31 Pennbrook Dr - Deed Image (4618 - 717).pdf", "31_pennbrook_4618_717"),
    ("31 Pennbrook Dr - Deed Image (9777 - 1354).pdf", "31_pennbrook_9777_1354"),
    ("31 Pennbrook Dr - Deed Image (10989 - 916).pdf", "31_pennbrook_10989_916"),
    ("31 Pennbrook Dr - Deed Image (11191 - 01716).pdf", "31_pennbrook_11191_01716"),
]


def create_extraction_report(
    legal_desc: LegalDescription, closure_result: ClosureResult, output_file: Path
) -> None:
    """Create a human-readable extraction report.

    Args:
        legal_desc: LegalDescription object
        closure_result: ClosureResult object
        output_file: Path to output text file
    """
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("=" * 80 + "\n")
        f.write("DEED EXTRACTION REPORT\n")
        f.write("=" * 80 + "\n\n")

        # Source info
        f.write(f"Source PDF: {legal_desc.source_doc}\n")
        f.write(f"Date Extracted: {datetime.now(UTC).isoformat()}\n\n")

        # Point of Commencement
        f.write("-" * 80 + "\n")
        f.write("POINT OF COMMENCEMENT (POC)\n")
        f.write("-" * 80 + "\n")
        if legal_desc.poc_description:
            f.write(f"{legal_desc.poc_description}\n\n")
        else:
            f.write("(None)\n\n")

        # Point of Beginning
        f.write("-" * 80 + "\n")
        f.write("POINT OF BEGINNING (POB)\n")
        f.write("-" * 80 + "\n")
        if legal_desc.pob_description:
            f.write(f"{legal_desc.pob_description}\n\n")
        else:
            f.write("(None)\n\n")

        # PLSS Metadata
        f.write("-" * 80 + "\n")
        f.write("PLSS METADATA\n")
        f.write("-" * 80 + "\n")
        f.write(f"Section: {legal_desc.section or '(None)'}\n")
        f.write(f"Township: {legal_desc.township or '(None)'}\n")
        f.write(f"Range: {legal_desc.range or '(None)'}\n")
        f.write(f"Principal Meridian: {legal_desc.principal_meridian or '(None)'}\n")
        f.write(f"Aliquot: {legal_desc.aliquot or '(None)'}\n\n")

        # Calls
        report_calls = legal_desc.calls or legal_desc.all_calls
        f.write("=" * 80 + "\n")
        f.write(f"EXTRACTED CALLS ({len(report_calls)} total)\n")
        f.write("=" * 80 + "\n\n")

        for i, call in enumerate(report_calls, 1):
            f.write(f"CALL #{i}\n")
            f.write("-" * 80 + "\n")
            f.write(f"Direction Text:  {call.direction_text}\n")
            f.write(f"Bearing:         {call.bearing_quadrant or '(incomplete)'}\n")
            f.write(
                f"Azimuth:         {f'{call.bearing_azimuth_deg_from_north:.2f}°' if call.bearing_azimuth_deg_from_north is not None else '(none)'}\n"
            )
            distance = (
                f"{call.distance_ft:.2f} feet" if call.distance_ft is not None else "not determined"
            )
            f.write(f"Distance:        {distance}\n")

            # Curve info if present
            if call.curve_dir:
                f.write(f"Curve Direction: {call.curve_dir}\n")
                f.write(
                    f"Radius:          {f'{call.radius_ft:.2f} ft' if call.radius_ft is not None else '(none)'}\n"
                )
                f.write(
                    f"Delta:           {f'{call.delta_deg:.4f}°' if call.delta_deg is not None else '(none)'}\n"
                )
                f.write(
                    f"Arc Length:      {f'{call.arc_length_ft:.2f} ft' if call.arc_length_ft is not None else '(none)'}\n"
                )

            f.write(f"Along:           {call.along or '(none)'}\n")
            f.write(f"To:              {call.to or '(none)'}\n")
            f.write(f"Monument Type:   {call.monument_type or '(none)'}\n")
            f.write(f"Is Exception:    {call.is_exception}\n")
            f.write(f"Notes:           {call.notes or '(none)'}\n")
            f.write("\n")

        # Closure verification
        f.write("=" * 80 + "\n")
        f.write("CLOSURE VERIFICATION\n")
        f.write("=" * 80 + "\n\n")

        if closure_result.misclosure_available:
            f.write(f"Misclosure (X):     {closure_result.misclosure_x_ft:10.4f} ft\n")
            f.write(f"Misclosure (Y):     {closure_result.misclosure_y_ft:10.4f} ft\n")
            f.write(f"Total Misclosure:   {closure_result.misclosure_ft:10.4f} ft\n")
        else:
            f.write("Total Misclosure:   not determined\n")
        f.write(
            f"Closure Status:     {'✓ CLOSED' if closure_result.closure_passed else '✗ OPEN'}\n\n"
        )

        if closure_result.area_available:
            f.write(f"Calculated Area:    {closure_result.area_sq_ft:10.2f} sq ft\n")
            f.write(f"                    {closure_result.area_acres:10.4f} acres\n")
        else:
            f.write("Calculated Area:    not determined\n")
        perimeter = (
            f"{closure_result.perimeter_ft:10.2f} ft"
            if closure_result.perimeter_available
            else "not determined"
        )
        f.write(f"Perimeter:          {perimeter}\n\n")

        f.write(
            f"Angle Check:        {'✓ PASSED' if closure_result.angle_check_passed else '✗ FAILED'}\n"
        )
        f.write(
            f"Curve Consistency:  {'✓ PASSED' if closure_result.curve_consistency_passed else '✗ FAILED'}\n\n"
        )

        # Warnings
        if closure_result.warnings:
            f.write("WARNINGS:\n")
            for warning in closure_result.warnings:
                f.write(f"  - {warning}\n")
            f.write("\n")

        # Closure status summary
        f.write("-" * 80 + "\n")
        f.write(f"OVERALL STATUS: {closure_result.get_closure_status()}\n")
        f.write("-" * 80 + "\n")


def main() -> None:
    """Process all sample PDFs and create extraction reports."""
    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Initialize processor
    print("Initializing PDF processor...")
    processor = PDFProcessor()

    print(f"\nProcessing {len(SAMPLE_PDFS)} sample deeds...\n")

    results: list[dict[str, Any]] = []

    for pdf_filename, output_name in SAMPLE_PDFS:
        pdf_path = SAMPLE_DEEDS_DIR / pdf_filename

        if not pdf_path.exists():
            print(f"⚠ SKIPPED: {pdf_filename} (not found)")
            continue

        print(f"Processing: {pdf_filename}")

        try:
            # Extract legal description
            print("  - Extracting from PDF...")
            legal_desc = processor.process_deed_pdf(str(pdf_path))
            assert not isinstance(legal_desc, tuple)

            # Verify closure
            print("  - Verifying closure...")
            tracts = legal_desc.tracts or None
            calls_for_verify = legal_desc.all_calls if tracts else legal_desc.calls
            verification = ClosureChecker.verify_closure(
                calls_for_verify,
                stated_area_sq_ft=legal_desc.stated_area_sq_ft or 0.0,
                tracts=tracts,
            )
            if isinstance(verification, list):
                tract_results = list(zip(legal_desc.tracts, verification, strict=True))
                closure_result = aggregate_tract_closure(tract_results)
                is_verified = any(
                    is_boundary_tract(tract.tract_type) and res.is_fully_verified()
                    for tract, res in tract_results
                )
                closes = closure_result.closure_passed
            else:
                tract_results = None
                closure_result = verification
                is_verified = closure_result.is_fully_verified()
                closes = closure_result.closure_passed

            # Create text report
            report_path = OUTPUT_DIR / f"{output_name}_extraction_report.txt"
            print(f"  - Creating report: {report_path.name}")
            create_extraction_report(legal_desc, closure_result, report_path)

            # Export CSV
            csv_path = OUTPUT_DIR / f"{output_name}.csv"
            print(f"  - Exporting CSV: {csv_path.name}")
            CSVBuilder.legal_description_to_csv(legal_desc, str(csv_path))

            # Try verified export if it passes
            if is_verified:
                verified_path = OUTPUT_DIR / f"{output_name}.csv"
                written_paths = CSVBuilder.export_verified_csv(
                    calls=calls_for_verify,
                    closure_result=closure_result,
                    output_path=str(verified_path),
                    legal_desc=legal_desc,
                    tract_results=tract_results,
                )
                written_names = (
                    ", ".join(Path(p).name for p in written_paths) if written_paths else "(none)"
                )
                print(f"  - Exported VERIFIED CSV(s): {written_names}")

            results.append(
                {
                    "pdf": pdf_filename,
                    "calls": legal_desc.num_calls(),
                    "closes": closes,
                    "verified": is_verified,
                    "area_sq_ft": closure_result.area_sq_ft
                    if closure_result.area_available
                    else None,
                    "misclosure_ft": closure_result.misclosure_ft
                    if closure_result.misclosure_available
                    else None,
                }
            )

            print(f"  ✓ Complete: {legal_desc.num_calls()} calls extracted\n")

        except Exception as e:
            print(f"  ✗ ERROR: {str(e)}\n")
            results.append(
                {
                    "pdf": pdf_filename,
                    "error": str(e),
                }
            )

    # Summary
    print("\n" + "=" * 80)
    print("EXTRACTION SUMMARY")
    print("=" * 80 + "\n")

    for r in results:
        if "error" in r:
            print(f"✗ {r['pdf']}")
            print(f"   ERROR: {r['error']}\n")
        else:
            status = "✓ VERIFIED" if r["verified"] else ("✓ CLOSES" if r["closes"] else "⚠ OPEN")
            print(f"{status} {r['pdf']}")
            area = (
                f"{r['area_sq_ft']:.2f} sq ft" if r["area_sq_ft"] is not None else "not determined"
            )
            misclosure = (
                f"{r['misclosure_ft']:.4f} ft"
                if r["misclosure_ft"] is not None
                else "not determined"
            )
            print(f"   Calls: {r['calls']}, Area: {area}, Misclosure: {misclosure}\n")

    print(f"\nAll reports saved to: {OUTPUT_DIR}/")
    print("\nReview the *_extraction_report.txt files for detailed results.")


if __name__ == "__main__":
    main()
