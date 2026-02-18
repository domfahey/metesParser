#!/usr/bin/env python3
"""Normalize book/page fields in GT JSON files.

For page ranges (e.g., "249-252"), extracts the starting page.
For decimal values (e.g., "4081.0"), converts to integer.
For trailing punctuation (e.g., "50709."), removes it.
Preserves original raw values and adds *_Normalized fields.
"""

import json
import re
from pathlib import Path
from typing import Any


def clean_value(value: str) -> str:
    """
    Clean a value by:
    - Stripping leading/trailing whitespace
    - Collapsing multiple whitespaces to single space
    - Trimming trailing punctuation (., ;, :, etc.)
    """
    value = str(value).strip()
    # Collapse multiple whitespaces
    value = re.sub(r'\s+', ' ', value)
    # Trim trailing punctuation
    value = re.sub(r'[.,;:!?]+$', '', value)
    return value.strip()


def normalize_book_number(value: str) -> str | None:
    """
    Normalize a book number to a clean integer string.

    Handles:
    - Regular numbers: "50709" -> "50709"
    - Trailing punctuation: "50709." -> "50709"
    - Decimal values: "50709.0" -> "50709"
    - Liber references: "L48939" -> "48939" (extracts numeric part)
    - Complex refs: "3/D/280" -> None (too complex, skip)
    - Whitespace cleanup

    Returns None for NA or unparseable values.
    """
    if not value or str(value).strip().upper() in ("NA", "N/A", "NONE", ""):
        return None

    value = clean_value(value)

    # Handle decimal (e.g., "50709.0")
    if '.' in value:
        try:
            value = str(int(float(value)))
        except ValueError:
            pass

    # If it's now a clean number, return it
    if re.match(r'^\d+$', value):
        return value

    # Handle Liber references (L followed by numbers)
    liber_match = re.match(r'^L(\d+)$', value, re.IGNORECASE)
    if liber_match:
        return liber_match.group(1)

    # Complex references like "3/D/280" - can't normalize cleanly
    return None


def normalize_page_number(value: str) -> str | None:
    """
    Normalize a page number to a clean integer string.

    Handles:
    - Regular numbers: "969" -> "969"
    - Page ranges: "249-252" -> "249" (starting page)
    - Decimal values: "4081.0" -> "4081"
    - Leading zeros: "00969" -> "969"
    - Trailing punctuation: "969." -> "969"
    - Whitespace cleanup

    Returns None for NA or unparseable values.
    """
    if not value or str(value).strip().upper() in ("NA", "N/A", "NONE", ""):
        return None

    value = clean_value(value)

    # Handle page ranges (e.g., "249-252", "11-19", "906-906")
    range_match = re.match(r'^(\d+)\s*[-–—]\s*\d+$', value)
    if range_match:
        return str(int(range_match.group(1)))  # Return starting page, strip leading zeros

    # Handle decimal (e.g., "4081.0")
    if '.' in value:
        try:
            return str(int(float(value)))
        except ValueError:
            pass

    # If it's a clean number (possibly with leading zeros)
    if re.match(r'^\d+$', value):
        return str(int(value))  # Strip leading zeros

    return None


def add_normalized_field(obj: Any, raw_field: str, normalized_field: str, normalizer) -> bool:
    """Add a normalized field next to the raw field. Returns True if a valid value was added."""
    if not isinstance(obj, dict):
        return False

    if raw_field not in obj:
        return False

    raw_value = obj[raw_field]
    normalized = normalizer(raw_value) if isinstance(raw_value, str) else None

    if normalized:
        obj[normalized_field] = normalized
        return True
    else:
        obj[normalized_field] = "NA"
        return False


def normalize_gt_file(data: dict) -> tuple[dict, int]:
    """
    Normalize all book/page fields in a GT JSON structure.

    Returns (modified_data, count_of_normalized_fields)
    """
    normalized_count = 0

    # Header fields
    header = data.get("Header", {})

    added = add_normalized_field(
        header, "Recording_Book_Number", "Recording_Book_Normalized", normalize_book_number
    )
    if added:
        normalized_count += 1
    elif "Recording_Book_Number" in header:
        header["Recording_Book_Normalized"] = "NA"

    added = add_normalized_field(
        header, "Recording_Page_Number", "Recording_Page_Normalized", normalize_page_number
    )
    if added:
        normalized_count += 1
    elif "Recording_Page_Number" in header:
        header["Recording_Page_Normalized"] = "NA"

    # Legal descriptions - Map Book/Page
    for legal in data.get("Legal_Descriptions", []):
        for attr in legal.get("Legal_Description_Attributes", []):
            if isinstance(attr, dict):
                added = add_normalized_field(
                    attr, "Map_Book_Or_Condo_Book", "Map_Book_Normalized", normalize_book_number
                )
                if added:
                    normalized_count += 1
                elif "Map_Book_Or_Condo_Book" in attr:
                    attr["Map_Book_Normalized"] = "NA"

                added = add_normalized_field(
                    attr, "Map_Page_Or_Condo_Page", "Map_Page_Normalized", normalize_page_number
                )
                if added:
                    normalized_count += 1
                elif "Map_Page_Or_Condo_Page" in attr:
                    attr["Map_Page_Normalized"] = "NA"

    # Prior document details
    for prior in data.get("Primary_Or_Prior_Document_Details", []):
        added = add_normalized_field(
            prior, "Primary_Or_Prior_Book_Number", "Prior_Book_Normalized", normalize_book_number
        )
        if added:
            normalized_count += 1
        elif "Primary_Or_Prior_Book_Number" in prior:
            prior["Prior_Book_Normalized"] = "NA"

        added = add_normalized_field(
            prior, "Primary_Or_Prior_Page_Number", "Prior_Page_Normalized", normalize_page_number
        )
        if added:
            normalized_count += 1
        elif "Primary_Or_Prior_Page_Number" in prior:
            prior["Prior_Page_Normalized"] = "NA"

    return data, normalized_count


def normalize_all_gt_files(gt_dir: Path, dry_run: bool = False) -> dict:
    """
    Normalize all GT JSON files in the directory.

    Returns report dictionary.
    """
    report = {
        "files_processed": 0,
        "files_modified": 0,
        "fields_normalized": 0,
        "errors": [],
    }

    json_files = sorted(gt_dir.glob("*.json"))

    for json_file in json_files:
        report["files_processed"] += 1

        try:
            with open(json_file, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            report["errors"].append((json_file.name, f"JSON parse error: {e}"))
            continue

        modified_data, count = normalize_gt_file(data)

        if count > 0:
            report["files_modified"] += 1
            report["fields_normalized"] += count

        if not dry_run:
            with open(json_file, "w", encoding="utf-8") as f:
                json.dump(modified_data, f, indent=2, ensure_ascii=False)
                f.write("\n")

    return report


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Normalize book/page fields in GT JSON files")
    parser.add_argument("--dry-run", action="store_true", help="Don't write changes")
    parser.add_argument("--gt-dir", type=Path, default=Path(__file__).parent / "gt",
                        help="Path to GT directory")
    args = parser.parse_args()

    if not args.gt_dir.exists():
        print(f"Error: GT directory not found at {args.gt_dir}")
        return 1

    mode = "DRY RUN" if args.dry_run else "NORMALIZING"
    print(f"[{mode}] Processing GT files in: {args.gt_dir}")
    print()

    report = normalize_all_gt_files(args.gt_dir, dry_run=args.dry_run)

    print("=" * 60)
    print("BOOK/PAGE NORMALIZATION REPORT")
    print("=" * 60)
    print(f"Files processed:      {report['files_processed']}")
    print(f"Files modified:       {report['files_modified']}")
    print(f"Fields normalized:    {report['fields_normalized']}")

    if report["errors"]:
        print(f"\nErrors ({len(report['errors'])}):")
        for file_name, error in report["errors"]:
            print(f"  {file_name}: {error}")

    if args.dry_run:
        print("\n[DRY RUN] No files were modified. Run without --dry-run to apply changes.")

    return 0


if __name__ == "__main__":
    exit(main())
