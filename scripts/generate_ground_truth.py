#!/usr/bin/env python3
"""Generate ground truth JSON files for all sample PDFs."""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker
from metesparser.pdf_processor import PDFProcessor
from metesparser.text_parser import TextParser

# Deed metadata (from test files and visual inspection)
DEED_METADATA = {
    "18 Pennbrook Dr - Deed Image (11985 - 00829).pdf": {
        "address": "18 Pennbrook Drive",
        "city": "Haddonfield",
        "state": "NJ",
        "book": "11985",
        "page": "00829",
        "parcel_shape": "Rectangle",
        "dimensions": "60 ft × 125 ft",
    },
    "24 Pennbrook Dr - Deed Image (11793 - 00217).pdf": {
        "address": "24 Pennbrook Drive",
        "city": "Haddonfield",
        "state": "NJ",
        "book": "11793",
        "page": "00217",
        "parcel_shape": "Irregular polygon",
        "dimensions": "Multiple calls with curves",
    },
    "31 Pennbrook Dr - Deed Image (4618 - 717).pdf": {
        "address": "31 Pennbrook Drive",
        "city": "Haddonfield",
        "state": "NJ",
        "book": "4618",
        "page": "717",
        "parcel_shape": "Polygon",
        "dimensions": "5-sided parcel",
    },
    "31 Pennbrook Dr - Deed Image (9777 - 1354).pdf": {
        "address": "31 Pennbrook Drive",
        "city": "Haddonfield",
        "state": "NJ",
        "book": "9777",
        "page": "1354",
        "parcel_shape": "Polygon",
        "dimensions": "Chain of title deed",
    },
    "31 Pennbrook Dr - Deed Image (10989 - 916).pdf": {
        "address": "31 Pennbrook Drive",
        "city": "Haddonfield",
        "state": "NJ",
        "book": "10989",
        "page": "916",
        "parcel_shape": "Polygon",
        "dimensions": "Chain of title deed",
    },
    "31 Pennbrook Dr - Deed Image (11191 - 01716).pdf": {
        "address": "31 Pennbrook Drive",
        "city": "Haddonfield",
        "state": "NJ",
        "book": "11191",
        "page": "01716",
        "parcel_shape": "Polygon",
        "dimensions": "Chain of title deed (newest)",
    },
}


def generate_ground_truth(pdf_path: Path, processor: PDFProcessor) -> dict:
    """Generate ground truth data for a PDF."""
    print(f"\n{'=' * 80}")
    print(f"Processing: {pdf_path.name}")
    print("=" * 80)

    # Get metadata
    metadata = DEED_METADATA.get(
        pdf_path.name,
        {
            "address": "Unknown",
            "city": "Unknown",
            "state": "NJ",
            "book": "Unknown",
            "page": "Unknown",
        },
    )

    # Extract text
    print("Step 1/5: Extracting raw text from PDF...")
    raw_text = processor.extract_text_from_pdf(str(pdf_path))

    # Extract legal description
    print("Step 2/5: Extracting legal description...")
    legal_desc_text = processor.extract_legal_description(str(pdf_path))

    # Normalize
    print("Step 3/5: Normalizing text...")
    normalized_text = processor.normalize_legal_description(legal_desc_text)

    # Extract POB/POC
    print("Step 4/5: Extracting POB/POC...")
    poc, pob = TextParser.extract_poc_and_pob(normalized_text)

    # Extract calls
    print("Step 5/5: Extracting calls...")
    calls = CallExtractor.extract_calls(normalized_text)
    calls = CallExtractor.enrich_calls_with_azimuths(calls)

    print(f"  ✓ Extracted {len(calls)} calls")

    # Verify closure if we have calls
    closure_data = {}
    if calls:
        result = ClosureChecker.verify_closure(calls)
        closure_data = {
            "misclosure_ft": round(result.misclosure_ft, 4),
            "area_sq_ft": round(result.area_sq_ft, 2) if result.area_available else None,
            "area_acres": round(result.area_acres, 4) if result.area_available else None,
            "area_available": result.area_available,
            "perimeter_ft": round(result.perimeter_ft, 2) if result.perimeter_available else None,
            "perimeter_available": result.perimeter_available,
            "closure_passed": result.closure_passed,
        }
        print(f"  ✓ Misclosure: {result.misclosure_ft:.4f} ft")
        area_text = (
            f"{result.area_sq_ft:.2f} sq ft ({result.area_acres:.4f} acres)"
            if result.area_available
            else "not determined"
        )
        print(f"  ✓ Area: {area_text}")

    # Convert calls to dict
    expected_calls = []
    for call in calls:
        expected_calls.append(
            {
                "course": call.course,
                "direction_text": call.direction_text,
                "bearing_quadrant": call.bearing_quadrant,
                "bearing_azimuth_deg_from_north": call.bearing_azimuth_deg_from_north,
                "distance_ft": call.distance_ft,
                "curve_dir": call.curve_dir,
                "radius_ft": call.radius_ft,
                "delta_deg": call.delta_deg,
                "arc_length_ft": call.arc_length_ft,
                "along": call.along,
                "to": call.to,
                "monument_type": call.monument_type,
                "notes": call.notes,
            }
        )

    # Build ground truth
    ground_truth = {
        "deed_info": metadata,
        "raw_ocr_text": raw_text[:1000] + "..."
        if len(raw_text) > 1000
        else raw_text,  # Truncate for size
        "expected_legal_description": legal_desc_text,
        "expected_normalized_text": normalized_text,
        "expected_poc": poc if poc else None,
        "expected_pob": pob,
        "expected_calls": expected_calls,
        "expected_closure": closure_data,
        "critical_assertions": {
            "num_calls": {
                "expected": len(calls),
                "operator": "==",
                "description": f"MUST extract exactly {len(calls)} calls",
            },
        },
        "notes": f"Ground truth generated at {datetime.now(UTC).isoformat()}",
    }

    return ground_truth


def main():
    """Generate ground truth for all PDFs."""
    sample_deeds_dir = Path(__file__).parent.parent / "sample_deeds"
    pdfs = sorted(sample_deeds_dir.glob("*.pdf"))

    print(f"Found {len(pdfs)} PDFs to process")

    processor = PDFProcessor()

    for pdf_path in pdfs:
        # Check if ground truth already exists
        output_path = pdf_path.with_suffix(".ground_truth.json")

        if output_path.exists():
            print(f"\n⏭️  Skipping {pdf_path.name} (ground truth already exists)")
            continue

        try:
            ground_truth = generate_ground_truth(pdf_path, processor)

            # Write JSON
            with open(output_path, "w") as f:
                json.dump(ground_truth, f, indent=2, ensure_ascii=False)

            print(f"  ✅ Saved to: {output_path.name}")

        except Exception as e:
            print(f"  ❌ Error: {e}")
            import traceback

            traceback.print_exc()

    print(f"\n{'=' * 80}")
    print("Ground truth generation complete!")
    print(f"{'=' * 80}\n")

    # Summary
    ground_truth_files = list(sample_deeds_dir.glob("*.ground_truth.json"))
    print(f"Total ground truth files: {len(ground_truth_files)}")
    for gt_file in sorted(ground_truth_files):
        print(f"  ✓ {gt_file.name}")


if __name__ == "__main__":
    main()
