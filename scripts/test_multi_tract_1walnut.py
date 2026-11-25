"""Quick integration test: 1 Walnut St multi-tract deed (3 tracts)."""

from __future__ import annotations

import re
from pathlib import Path

from mp_parse.calls import extract_calls
from mp_parse.normalizer import normalize_legal_description
from mp_parse.tracts import split_into_tracts
from mp_verify.closure import get_closure_summary, verify_tract


def main() -> None:
    md_path = (
        Path(__file__).resolve().parent.parent
        / "sample_deeds"
        / "1 Walnut St - Deed Image (12420 - 00902).md"
    )
    raw_text = md_path.read_text(encoding="utf-8")

    # Extract the actual Exhibit A content (starts with "# EXHIBIT A" header)
    # Use the line that starts the legal description text
    match = re.search(r"^# EXHIBIT A\s*$", raw_text, re.MULTILINE)
    if not match:
        print("ERROR: Could not find '# EXHIBIT A' header")
        return

    exhibit_b = raw_text.find("# EXHIBIT B", match.start())
    if exhibit_b == -1:
        print("ERROR: Could not find EXHIBIT B boundary")
        return

    legal_text = raw_text[match.start() : exhibit_b]

    # Strip markdown formatting (headers like ### TRACT NO. 1)
    legal_text = re.sub(r"^#{1,4}\s*", "", legal_text, flags=re.MULTILINE)

    print(f"Legal text length: {len(legal_text)} chars")
    print(f"Preview: {legal_text[:200]}...")
    print()

    # Normalize
    normalized = normalize_legal_description(legal_text)
    print(f"Normalized length: {len(normalized)} chars")
    print(f"Preview: {normalized[:200]}...")
    print()

    # Split into tracts
    tracts = split_into_tracts(normalized)
    print(f"Found {len(tracts)} tracts:")
    for text, label, ttype in tracts:
        print(f"  {label} ({ttype.value}): {len(text)} chars")
        print(f"    Preview: {text[:100]}...")
    print()

    # Extract calls and verify each tract
    for text, label, ttype in tracts:
        print(f"{'=' * 60}")
        print(f"  {label} ({ttype.value})")
        print(f"{'=' * 60}")

        calls, _legal_desc = extract_calls(text)
        print(f"  Extracted {len(calls)} calls:")
        for c in calls:
            tie = " [TIE-IN]" if c.is_tie_in else ""
            print(
                f"    Course {c.course}: {c.direction_text}  "
                f"dist={c.distance_ft:.2f} ft  "
                f"az={c.bearing_azimuth_deg_from_north}{tie}"
            )

        if len(calls) >= 3:
            result = verify_tract(calls)
            print()
            print(get_closure_summary(result, calls))
        else:
            print(f"  Only {len(calls)} calls — skipping verification")
        print()


if __name__ == "__main__":
    main()
