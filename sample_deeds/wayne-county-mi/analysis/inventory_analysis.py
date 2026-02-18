#!/usr/bin/env python3
"""Analyze Wayne County MI ground truth JSON files for metes and bounds content.

Categorizes each document as:
  - metes_and_bounds: Has bearings and distances (actual traverse calls)
  - lot_block_only: Has lot/block/subdivision but no traverse
  - no_legal: No meaningful legal description

Outputs:
  - Summary statistics to stdout
  - CSV inventory to legal_description_inventory.csv
"""

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

GT_DIR = Path(__file__).resolve().parent.parent / "gt"
OUTPUT_CSV = GT_DIR.parent / "analysis" / "legal_description_inventory.csv"

# --- Detection patterns ---

# Bearing patterns: "N 45 degrees 30 minutes E", "North 89 degrees 32 minutes 10 seconds West",
# "S 56°40'30\" W", "N45°30'E", etc.
BEARING_PATTERNS = [
    # Spelled out: "North 89 degrees 32 minutes 10 seconds West"
    r"(?:North|South)\s+\d+\s+degrees?\s+\d+\s+minutes?",
    # DMS with symbols: N 45°30'20" E
    r"[NS]\s*\d+\s*[°]\s*\d+",
    # Abbreviated quadrant: "N 45 deg 30 min E", "S 56 degrees 40 minutes W"
    r"[NS]\s+\d+\s+deg(?:rees?)?\s+\d+\s+min(?:utes?)?",
    # Common shortened: "N45°30'E"
    r"[NS]\d+[°]\d+",
    # Tax-record abbreviation: "N 88D 25M 31S E", "N89DEG 06M W", "N0D 07M E"
    r"[NS]\s*\d+\s*D(?:EG)?\s+\d+\s*M",
    # Compact tax-record: "N89DEG06M", "S01D41M46SE"
    r"[NS]\d+D(?:EG)?\d+M",
    # Spelled out direction with DMS symbols: "South 00°44'00" W"
    r"(?:North|South)\s+\d+\s*[°]\s*\d+",
]

# Distance patterns: "210.00 feet", "1432.62 ft", "329.84 feet", "330.00 FT"
DISTANCE_PATTERNS = [
    r"\d+\.\d+\s+feet",
    r"\d+\.\d+\s+ft\.?\b",
    r"\d+\s+feet\b",
    # Compact: "330.00FT", "60FT" (no space)
    r"\d+\.\d+FT\b",
    r"\d+FT\b",
]

# "thence" is the classic metes and bounds transition word; also "TH " in abbreviated form
THENCE_PATTERN = r"\bthence\b|\bTH\s+[NS]"

# "beginning" / "point of beginning" / "point of commencement"
POB_PATTERN = r"\b(?:point\s+of\s+beginning|beginning\s+at|described\s+as\s+beginning)\b"

# Lot/block/subdivision indicators
LOT_BLOCK_PATTERNS = [
    r"\bLOT\s+\d+",
    r"\bBLOCK\s+\d+",
    r"\bSUBDIVISION\b",
    r"\bSUB\s*DIVISION\b",
    r"\bPLAT\b",
    r"\bCONDOMINIUM\b",
    r"\bCONDO\b",
    r"\bUNIT\s+\d+",
    r"\bLIBER\s+\d+",
]


def has_match(text: str, patterns: list[str], flags: int = re.IGNORECASE) -> bool:
    """Return True if any pattern matches in text."""
    return any(re.search(p, text, flags) for p in patterns)


def count_matches(text: str, patterns: list[str], flags: int = re.IGNORECASE) -> int:
    """Return total match count across all patterns."""
    total = 0
    for p in patterns:
        total += len(re.findall(p, text, flags))
    return total


def categorize_legal_description(full_legal: str) -> dict:
    """Categorize a legal description and return indicator flags."""
    if not full_legal or full_legal.strip().upper() == "NA":
        return {
            "category": "no_legal",
            "has_bearings": False,
            "has_distances": False,
            "has_thence": False,
            "has_pob": False,
            "has_lot_block": False,
            "bearing_count": 0,
            "distance_count": 0,
            "thence_count": 0,
        }

    text = full_legal

    has_bearings = has_match(text, BEARING_PATTERNS)
    has_distances = has_match(text, DISTANCE_PATTERNS)
    has_thence = bool(re.search(THENCE_PATTERN, text, re.IGNORECASE))
    has_pob = bool(re.search(POB_PATTERN, text, re.IGNORECASE))
    has_lot_block = has_match(text, LOT_BLOCK_PATTERNS)

    bearing_count = count_matches(text, BEARING_PATTERNS)
    distance_count = count_matches(text, DISTANCE_PATTERNS)
    thence_count = len(re.findall(THENCE_PATTERN, text, re.IGNORECASE))

    # Classification logic:
    # metes_and_bounds: Must have bearings AND distances (the core of a traverse)
    # Also classify as M&B if there are multiple "thence" with distances (even if
    # bearing detection misses due to unusual formatting)
    if has_bearings and has_distances:
        category = "metes_and_bounds"
    elif thence_count >= 2 and has_distances:
        # Multiple "thence" with distances strongly suggests M&B even if bearing
        # regex didn't catch the format
        category = "metes_and_bounds"
    elif has_lot_block:
        category = "lot_block_only"
    elif full_legal.strip().upper() != "NA" and len(full_legal.strip()) > 10:
        # Has some legal text but no M&B indicators and no lot/block
        # Could be a section/township description or other format
        category = "lot_block_only"
    else:
        category = "no_legal"

    return {
        "category": category,
        "has_bearings": has_bearings,
        "has_distances": has_distances,
        "has_thence": has_thence,
        "has_pob": has_pob,
        "has_lot_block": has_lot_block,
        "bearing_count": bearing_count,
        "distance_count": distance_count,
        "thence_count": thence_count,
    }


def main():
    json_files = sorted(GT_DIR.glob("*.json"))
    if not json_files:
        print(f"ERROR: No JSON files found in {GT_DIR}", file=sys.stderr)
        sys.exit(1)

    print(f"Scanning {len(json_files)} ground truth JSON files in:\n  {GT_DIR}\n")

    rows = []
    errors = []

    for jf in json_files:
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            errors.append((jf.name, str(e)))
            continue

        # Extract document type
        doc_type = "UNKNOWN"
        header = data.get("Header", {})
        if isinstance(header, dict):
            doc_type = header.get("Document_Type", "UNKNOWN")
            if not doc_type or doc_type == "":
                doc_type = header.get("Document_Title", "UNKNOWN")

        # Extract full legal description
        full_legal = data.get("Full_Legal_Description", "")
        if full_legal is None:
            full_legal = ""

        # Categorize
        result = categorize_legal_description(full_legal)

        # Preview (first 200 chars, clean up newlines for CSV)
        preview = full_legal[:200].replace("\n", " ").replace("\r", " ").strip()

        rows.append({
            "filename": jf.name,
            "document_type": doc_type,
            "legal_desc_category": result["category"],
            "has_bearings": result["has_bearings"],
            "has_distances": result["has_distances"],
            "has_thence": result["has_thence"],
            "full_legal_description_preview": preview,
        })

    # Write CSV
    fieldnames = [
        "filename",
        "document_type",
        "legal_desc_category",
        "has_bearings",
        "has_distances",
        "has_thence",
        "full_legal_description_preview",
    ]
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"CSV inventory written to:\n  {OUTPUT_CSV}\n")

    # --- Summary Statistics ---
    total = len(rows)
    cat_counts = Counter(r["legal_desc_category"] for r in rows)
    doc_type_counts = Counter(r["document_type"] for r in rows)

    print("=" * 70)
    print("SUMMARY: Legal Description Categories")
    print("=" * 70)
    for cat in ["metes_and_bounds", "lot_block_only", "no_legal"]:
        count = cat_counts.get(cat, 0)
        pct = (count / total * 100) if total > 0 else 0
        print(f"  {cat:<20s}: {count:>4d}  ({pct:5.1f}%)")
    print(f"  {'TOTAL':<20s}: {total:>4d}")
    print()

    # M&B sub-analysis
    mb_rows = [r for r in rows if r["legal_desc_category"] == "metes_and_bounds"]
    if mb_rows:
        print("=" * 70)
        print("METES & BOUNDS DOCUMENTS (parseable by metesParser)")
        print("=" * 70)
        for r in mb_rows:
            indicators = []
            if r["has_bearings"]:
                indicators.append("bearings")
            if r["has_distances"]:
                indicators.append("distances")
            if r["has_thence"]:
                indicators.append("thence")
            print(f"  {r['filename']}")
            print(f"    Document Type: {r['document_type']}")
            print(f"    Indicators: {', '.join(indicators)}")
            print(f"    Preview: {r['full_legal_description_preview'][:120]}...")
            print()

    # Document types that have M&B
    print("=" * 70)
    print("DOCUMENT TYPE BREAKDOWN")
    print("=" * 70)
    print(f"  {'Document Type':<35s} {'Total':>6s} {'M&B':>5s} {'Lot/Blk':>8s} {'No Legal':>9s}")
    print(f"  {'-'*35} {'-'*6} {'-'*5} {'-'*8} {'-'*9}")

    # Build cross-tab
    doc_type_x_cat = {}
    for r in rows:
        dt = r["document_type"]
        cat = r["legal_desc_category"]
        if dt not in doc_type_x_cat:
            doc_type_x_cat[dt] = Counter()
        doc_type_x_cat[dt][cat] += 1

    for dt in sorted(doc_type_x_cat.keys(), key=lambda x: -sum(doc_type_x_cat[x].values())):
        cats = doc_type_x_cat[dt]
        tot = sum(cats.values())
        mb = cats.get("metes_and_bounds", 0)
        lb = cats.get("lot_block_only", 0)
        nl = cats.get("no_legal", 0)
        mb_flag = " <-- HAS M&B" if mb > 0 else ""
        print(f"  {dt:<35s} {tot:>6d} {mb:>5d} {lb:>8d} {nl:>9d}{mb_flag}")

    print()

    # Errors
    if errors:
        print("=" * 70)
        print(f"ERRORS ({len(errors)} files could not be parsed)")
        print("=" * 70)
        for fname, err in errors:
            print(f"  {fname}: {err}")
        print()

    # Final tally
    print("=" * 70)
    print("KEY FINDING")
    print("=" * 70)
    mb_count = cat_counts.get("metes_and_bounds", 0)
    pct = (mb_count / total * 100) if total > 0 else 0
    print(f"  {mb_count} of {total} documents ({pct:.1f}%) contain metes & bounds")
    print(f"  legal descriptions with bearings and distances that could be parsed")
    print(f"  by the metesParser pipeline.")
    print()

    # List M&B document types
    mb_doc_types = Counter()
    for r in mb_rows:
        mb_doc_types[r["document_type"]] += 1
    if mb_doc_types:
        print("  Document types with metes & bounds:")
        for dt, cnt in mb_doc_types.most_common():
            print(f"    - {dt}: {cnt}")


if __name__ == "__main__":
    main()
