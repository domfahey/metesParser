#!/usr/bin/env python3
"""Audit all date fields in GT JSON files for validity."""

import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

# Known date field paths in the GT JSON structure
DATE_FIELDS = [
    "Header.Recording_Date_And_Time",
    "Header.Dated_Date",
    "Header.Loan_Details.Loan_Term_End_Date",
    "Header.Judgement_Details[].Judgement_Entered_Date",
    "Header.Lien_Details[].Lien_Entered_Date",
    "Legal_Descriptions[].Legal_Description_Attributes[].Map_Date",
    "Primary_Or_Prior_Document_Details[].Primary_Or_Prior_Document_Date",
]

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

# Date patterns to try parsing
DATE_PATTERNS = [
    # DD-Month-YYYY (e.g., "10-May-2013", "17-AUG-2012")
    (r"^(\d{1,2})-([A-Za-z]+)-(\d{4})$", "DMY"),
    # DDth Month YYYY (e.g., "2nd February 2013")
    (r"^(\d{1,2})(?:st|nd|rd|th)\s+([A-Za-z]+)\s+(\d{4})$", "DMY_ORD"),
    # DD Month YYYY (e.g., "13 September 2012") - without ordinal
    (r"^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$", "DMY_SPACE"),
    # Month DD, YYYY (e.g., "May 10, 2013")
    (r"^([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})$", "MDY"),
    # Month-DD-YYYY (e.g., "JUNE-01-2043", "April-3-2013")
    (r"^([A-Za-z]+)-(\d{1,2})-(\d{4})$", "M-D-Y"),
    # DD-Month YYYY (e.g., "7-December 2012") - mixed format
    (r"^(\d{1,2})-([A-Za-z]+)\s+(\d{4})$", "DMY_MIXED"),
    # MM/DD/YYYY
    (r"^(\d{1,2})/(\d{1,2})/(\d{4})$", "NUMERIC_SLASH"),
    # MM/DD/YY (2-digit year)
    (r"^(\d{1,2})/(\d{1,2})/(\d{2})$", "NUMERIC_SLASH_2Y"),
    # YYYY-MM-DD
    (r"^(\d{4})-(\d{1,2})-(\d{1,2})$", "ISO"),
    # DD-Month-YYYY HH:MM:SS AM/PM (datetime with time)
    (r"^(\d{1,2})-([A-Za-z]+)-(\d{4})\s+\d{1,2}:\d{2}:\d{2}\s*(?:AM|PM)?$", "DMY_TIME"),
]


def normalize_month(month_str: str) -> str | None:
    """Normalize month name, handling abbreviations and typos."""
    month_upper = month_str.upper()

    # Check for corrections (abbreviations and typos)
    if month_upper in MONTH_CORRECTIONS:
        return MONTH_CORRECTIONS[month_upper]

    # Try parsing as full month name
    try:
        dt = datetime.strptime(month_str.title(), "%B")
        return dt.strftime("%B")
    except ValueError:
        pass

    return None


def parse_date(date_str: str) -> tuple[bool, str | None, str | None]:
    """
    Attempt to parse a date string and validate it.

    Returns:
        (is_valid, error_message, issue_type)
    """
    if not date_str or date_str.strip().upper() in ("NA", "N/A", "NONE", ""):
        return True, None, None  # NA values are considered valid (no date)

    date_str = date_str.strip()

    # Try each pattern
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
                        return False, f"Invalid month name: '{groups[1]}'", "invalid_month"

                    datetime(year, month_str and datetime.strptime(month_str, "%B").month, day)
                    return True, None, None

                elif pattern_type in ("MDY", "M-D-Y"):
                    month_str = normalize_month(groups[0])
                    day = int(groups[1])
                    year = int(groups[2])

                    if not month_str:
                        return False, f"Invalid month name: '{groups[0]}'", "invalid_month"

                    datetime(year, datetime.strptime(month_str, "%B").month, day)
                    return True, None, None

                elif pattern_type == "NUMERIC_SLASH":
                    month, day, year = int(groups[0]), int(groups[1]), int(groups[2])
                    datetime(year, month, day)
                    return True, None, None

                elif pattern_type == "NUMERIC_SLASH_2Y":
                    month, day, year = int(groups[0]), int(groups[1]), int(groups[2])
                    # Convert 2-digit year (00-99 -> 2000-2099 or 1900-1999)
                    year = 2000 + year if year < 50 else 1900 + year
                    datetime(year, month, day)
                    return True, None, None

                elif pattern_type == "ISO":
                    year, month, day = int(groups[0]), int(groups[1]), int(groups[2])
                    datetime(year, month, day)
                    return True, None, None

            except ValueError as e:
                return False, f"Invalid date components: {e}", "invalid_components"

    return False, f"Unrecognized date format: '{date_str}'", "unrecognized_format"


def extract_value_at_path(data: dict, path: str) -> list[tuple[str, Any]]:
    """
    Extract values at a given path, handling array notation.

    Returns list of (full_path, value) tuples.
    """
    results = []
    parts = path.split(".")

    def traverse(obj: Any, remaining_parts: list[str], current_path: str):
        if not remaining_parts:
            results.append((current_path, obj))
            return

        part = remaining_parts[0]
        rest = remaining_parts[1:]

        if part.endswith("[]"):
            # Array field
            field_name = part[:-2]
            if isinstance(obj, dict) and field_name in obj:
                arr = obj[field_name]
                if isinstance(arr, list):
                    for i, item in enumerate(arr):
                        if current_path:
                            new_path = f"{current_path}.{field_name}[{i}]"
                        else:
                            new_path = f"{field_name}[{i}]"
                        traverse(item, rest, new_path)
        else:
            if isinstance(obj, dict) and part in obj:
                new_path = f"{current_path}.{part}" if current_path else part
                traverse(obj[part], rest, new_path)

    traverse(data, parts, "")
    return results


def audit_gt_dates(gt_dir: Path) -> dict:
    """
    Audit all date fields in GT JSON files.

    Returns a report dictionary with:
        - total_files: number of files processed
        - total_dates: number of date fields checked
        - valid_dates: number of valid dates
        - invalid_dates: list of (file, field, value, error) tuples
        - na_dates: count of NA/empty dates
        - date_formats: dict of format -> count
    """
    report = {
        "total_files": 0,
        "total_dates": 0,
        "valid_dates": 0,
        "invalid_dates": [],
        "na_dates": 0,
        "date_formats": defaultdict(int),
        "unique_values": defaultdict(set),
    }

    json_files = sorted(gt_dir.glob("*.json"))
    report["total_files"] = len(json_files)

    for json_file in json_files:
        try:
            with open(json_file, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            err = (json_file.name, "FILE", "N/A", f"JSON parse error: {e}")
            report["invalid_dates"].append(err)
            continue

        for field_path in DATE_FIELDS:
            values = extract_value_at_path(data, field_path)

            for full_path, value in values:
                report["total_dates"] += 1

                is_na = value is None or (
                    isinstance(value, str) and value.upper() in ("NA", "N/A", "NONE", "")
                )
                if is_na:
                    report["na_dates"] += 1
                    report["valid_dates"] += 1
                    continue

                if not isinstance(value, str):
                    type_name = type(value).__name__
                    msg = f"Expected string, got {type_name}"
                    err = (json_file.name, full_path, str(value), msg)
                    report["invalid_dates"].append(err)
                    continue

                key = full_path.split("[")[0] if "[" in full_path else full_path
                report["unique_values"][key].add(value)

                is_valid, error, issue_type = parse_date(value)
                if is_valid:
                    report["valid_dates"] += 1
                    # Track format
                    for pattern, _ in DATE_PATTERNS:
                        if re.match(pattern, value.strip(), re.IGNORECASE):
                            report["date_formats"][pattern] += 1
                            break
                    else:
                        report["date_formats"]["other"] += 1
                else:
                    err = (json_file.name, full_path, value, error, issue_type)
                    report["invalid_dates"].append(err)

    # Convert defaultdicts and sets for JSON serialization
    report["date_formats"] = dict(report["date_formats"])
    report["unique_values"] = {k: list(v) for k, v in report["unique_values"].items()}

    return report


def print_report(report: dict) -> None:
    """Print a formatted audit report."""
    print("=" * 70)
    print("DATE AUDIT REPORT")
    print("=" * 70)
    print()

    print(f"Files processed:     {report['total_files']}")
    print(f"Total date fields:   {report['total_dates']}")
    print(f"Valid dates:         {report['valid_dates']}")
    print(f"NA/Empty dates:      {report['na_dates']}")
    print(f"Invalid dates:       {len(report['invalid_dates'])}")
    print()

    if report["invalid_dates"]:
        print("-" * 70)
        print("INVALID DATES:")
        print("-" * 70)
        for item in report["invalid_dates"]:
            file_name, field, value, error = item[:4]
            issue_type = item[4] if len(item) > 4 else "unknown"
            print(f"\n  File:  {file_name}")
            print(f"  Field: {field}")
            print(f"  Value: {value}")
            print(f"  Error: {error}")
            print(f"  Type:  {issue_type}")
        print()

    print("-" * 70)
    print("DATE FORMATS DETECTED:")
    print("-" * 70)
    for pattern, count in sorted(report["date_formats"].items(), key=lambda x: -x[1]):
        # Make pattern more readable
        readable = pattern.replace("\\d{1,2}", "D").replace("\\d{4}", "YYYY")
        readable = readable.replace("[A-Za-z]+", "Month").replace("\\s+", " ")
        readable = readable.replace("(?:st|nd|rd|th)", "th")
        readable = readable.replace("^", "").replace("$", "")
        print(f"  {readable}: {count}")
    print()

    # Show sample unique values for each field
    print("-" * 70)
    print("SAMPLE DATE VALUES BY FIELD:")
    print("-" * 70)
    for field, values in sorted(report["unique_values"].items()):
        non_na_values = [v for v in values if v.upper() not in ("NA", "N/A", "NONE", "")]
        if non_na_values:
            print(f"\n  {field}:")
            for v in sorted(non_na_values)[:5]:  # Show up to 5 samples
                print(f"    - {v}")
            if len(non_na_values) > 5:
                print(f"    ... and {len(non_na_values) - 5} more unique values")


def main():
    """Main entry point."""
    gt_dir = Path(__file__).parent / "gt"

    if not gt_dir.exists():
        print(f"Error: GT directory not found at {gt_dir}")
        return 1

    print(f"Auditing dates in: {gt_dir}")
    print()

    report = audit_gt_dates(gt_dir)
    print_report(report)

    # Return exit code based on results
    if report["invalid_dates"]:
        print(f"\n⚠️  Found {len(report['invalid_dates'])} invalid date(s)")
        return 1
    else:
        print("\n✅ All dates are valid!")
        return 0


if __name__ == "__main__":
    exit(main())
