#!/usr/bin/env python3
"""Normalize all date fields in GT JSON files to ISO format (YYYY-MM-DD)."""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

# Standard output format
OUTPUT_FORMAT = "%Y-%m-%d"  # ISO 8601

# Month name mappings (including abbreviations and typos)
MONTH_CORRECTIONS = {
    "JAN": "January", "FEB": "February", "MAR": "March", "APR": "April",
    "MAY": "May", "JUN": "June", "JUL": "July", "AUG": "August",
    "SEP": "September", "SEPT": "September", "OCT": "October",
    "NOV": "November", "DEC": "December",
    # Common typos
    "OCTOMBER": "October", "SEPTEMEBER": "September", "FEBUARY": "February",
    "JANURARY": "January", "DECEMEBER": "December",
}

# Date patterns to parse
DATE_PATTERNS = [
    # DD-Month-YYYY (e.g., "10-May-2013", "17-AUG-2012")
    (r"^(\d{1,2})-([A-Za-z]+)-(\d{4})$", "DMY"),
    # DDth Month YYYY (e.g., "2nd February 2013")
    (r"^(\d{1,2})(?:st|nd|rd|th)\s+([A-Za-z]+)\s+(\d{4})$", "DMY_ORD"),
    # DD Month YYYY (e.g., "13 September 2012")
    (r"^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$", "DMY_SPACE"),
    # Month DD, YYYY (e.g., "May 10, 2013")
    (r"^([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})$", "MDY"),
    # Month-DD-YYYY (e.g., "JUNE-01-2043")
    (r"^([A-Za-z]+)-(\d{1,2})-(\d{4})$", "M-D-Y"),
    # DD-Month YYYY (e.g., "7-December 2012")
    (r"^(\d{1,2})-([A-Za-z]+)\s+(\d{4})$", "DMY_MIXED"),
    # MM/DD/YYYY
    (r"^(\d{1,2})/(\d{1,2})/(\d{4})$", "NUMERIC_SLASH"),
    # MM/DD/YY (2-digit year)
    (r"^(\d{1,2})/(\d{1,2})/(\d{2})$", "NUMERIC_SLASH_2Y"),
    # YYYY-MM-DD
    (r"^(\d{4})-(\d{1,2})-(\d{1,2})$", "ISO"),
    # DD-Month-YYYY HH:MM:SS AM/PM
    (r"^(\d{1,2})-([A-Za-z]+)-(\d{4})\s+\d{1,2}:\d{2}:\d{2}\s*(?:AM|PM)?$", "DMY_TIME"),
]

# Fields to normalize (field path -> normalized field name suffix)
DATE_FIELD_MAPPINGS = {
    # Header fields
    "Recording_Date_And_Time": "Recording_Date_Normalized",
    "Dated_Date": "Dated_Date_Normalized",
    "Loan_Term_End_Date": "Loan_Term_End_Date_Normalized",
    "Judgement_Entered_Date": "Judgement_Entered_Date_Normalized",
    "Lien_Entered_Date": "Lien_Entered_Date_Normalized",
    # Legal description
    "Map_Date": "Map_Date_Normalized",
    # Prior document
    "Primary_Or_Prior_Document_Date": "Primary_Or_Prior_Document_Date_Normalized",
}


def normalize_month(month_str: str) -> str | None:
    """Normalize month name, handling abbreviations and typos."""
    month_upper = month_str.upper()

    if month_upper in MONTH_CORRECTIONS:
        return MONTH_CORRECTIONS[month_upper]

    try:
        dt = datetime.strptime(month_str.title(), "%B")
        return dt.strftime("%B")
    except ValueError:
        return None


def parse_and_normalize_date(date_str: str) -> str | None:
    """
    Parse a date string and return normalized ISO format (YYYY-MM-DD).

    Returns None for NA/empty values or unparseable dates.
    """
    if not date_str or date_str.strip().upper() in ("NA", "N/A", "NONE", ""):
        return None

    date_str = date_str.strip()

    for pattern, pattern_type in DATE_PATTERNS:
        match = re.match(pattern, date_str, re.IGNORECASE)
        if match:
            groups = match.groups()
            try:
                if pattern_type in ("DMY", "DMY_ORD", "DMY_SPACE", "DMY_MIXED", "DMY_TIME"):
                    day = int(groups[0])
                    month_str = normalize_month(groups[1])
                    year = int(groups[2])

                    if not month_str:
                        return None

                    month = datetime.strptime(month_str, "%B").month
                    dt = datetime(year, month, day)
                    return dt.strftime(OUTPUT_FORMAT)

                elif pattern_type in ("MDY", "M-D-Y"):
                    month_str = normalize_month(groups[0])
                    day = int(groups[1])
                    year = int(groups[2])

                    if not month_str:
                        return None

                    month = datetime.strptime(month_str, "%B").month
                    dt = datetime(year, month, day)
                    return dt.strftime(OUTPUT_FORMAT)

                elif pattern_type == "NUMERIC_SLASH":
                    month, day, year = int(groups[0]), int(groups[1]), int(groups[2])
                    dt = datetime(year, month, day)
                    return dt.strftime(OUTPUT_FORMAT)

                elif pattern_type == "NUMERIC_SLASH_2Y":
                    month, day, year = int(groups[0]), int(groups[1]), int(groups[2])
                    year = 2000 + year if year < 50 else 1900 + year
                    dt = datetime(year, month, day)
                    return dt.strftime(OUTPUT_FORMAT)

                elif pattern_type == "ISO":
                    year, month, day = int(groups[0]), int(groups[1]), int(groups[2])
                    dt = datetime(year, month, day)
                    return dt.strftime(OUTPUT_FORMAT)

            except ValueError:
                return None

    return None


def add_normalized_field(obj: Any, raw_field: str, normalized_field: str) -> bool:
    """Add a normalized date field next to the raw field. Returns True if added."""
    if not isinstance(obj, dict):
        return False

    if raw_field not in obj:
        return False

    raw_value = obj[raw_field]
    normalized = parse_and_normalize_date(raw_value) if isinstance(raw_value, str) else None

    # Add normalized field right after the raw field
    if normalized:
        obj[normalized_field] = normalized
        return True
    else:
        # Add NA for unparseable/NA values
        obj[normalized_field] = "NA"
        return False


def normalize_gt_file(data: dict) -> tuple[dict, int]:
    """
    Normalize all date fields in a GT JSON structure.

    Returns (modified_data, count_of_normalized_dates)
    """
    normalized_count = 0

    # Header fields
    header = data.get("Header", {})

    if add_normalized_field(header, "Recording_Date_And_Time", "Recording_Date_Normalized"):
        normalized_count += 1

    if add_normalized_field(header, "Dated_Date", "Dated_Date_Normalized"):
        normalized_count += 1

    # Loan details
    loan = header.get("Loan_Details", {})
    if add_normalized_field(loan, "Loan_Term_End_Date", "Loan_Term_End_Date_Normalized"):
        normalized_count += 1

    # Judgement details (array)
    for judgement in header.get("Judgement_Details", []):
        added = add_normalized_field(
            judgement, "Judgement_Entered_Date", "Judgement_Entered_Date_Normalized"
        )
        if added:
            normalized_count += 1

    # Lien details (array)
    for lien in header.get("Lien_Details", []):
        added = add_normalized_field(
            lien, "Lien_Entered_Date", "Lien_Entered_Date_Normalized"
        )
        if added:
            normalized_count += 1

    # Legal descriptions
    for legal in data.get("Legal_Descriptions", []):
        for attr in legal.get("Legal_Description_Attributes", []):
            if add_normalized_field(attr, "Map_Date", "Map_Date_Normalized"):
                normalized_count += 1

    # Prior document details
    for prior in data.get("Primary_Or_Prior_Document_Details", []):
        added = add_normalized_field(
            prior, "Primary_Or_Prior_Document_Date", "Primary_Or_Prior_Document_Date_Normalized"
        )
        if added:
            normalized_count += 1

    return data, normalized_count


def normalize_all_gt_files(gt_dir: Path, dry_run: bool = False) -> dict:
    """
    Normalize all GT JSON files in the directory.

    Args:
        gt_dir: Path to GT directory
        dry_run: If True, don't write changes

    Returns:
        Report dictionary
    """
    report = {
        "files_processed": 0,
        "files_modified": 0,
        "dates_normalized": 0,
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
            report["dates_normalized"] += count

            if not dry_run:
                with open(json_file, "w", encoding="utf-8") as f:
                    json.dump(modified_data, f, indent=2, ensure_ascii=False)
                    f.write("\n")

    return report


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Normalize dates in GT JSON files")
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
    print("NORMALIZATION REPORT")
    print("=" * 60)
    print(f"Files processed:    {report['files_processed']}")
    print(f"Files modified:     {report['files_modified']}")
    print(f"Dates normalized:   {report['dates_normalized']}")

    if report["errors"]:
        print(f"\nErrors ({len(report['errors'])}):")
        for file_name, error in report["errors"]:
            print(f"  {file_name}: {error}")

    if args.dry_run:
        print("\n[DRY RUN] No files were modified. Run without --dry-run to apply changes.")

    return 0


if __name__ == "__main__":
    exit(main())
