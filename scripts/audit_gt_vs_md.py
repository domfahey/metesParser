#!/usr/bin/env python3
"""Audit ground truth JSON files against LlamaParse markdown for each sample deed.

Reads each .md and .ground_truth.json pair, extracts bearings/distances from
the markdown text, and flags discrepancies with the GT expected_calls.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample_deeds"

# Regex patterns for extracting metes & bounds data from markdown text
BEARING_PATTERN = re.compile(
    r"([NS])\s*(?:orth|outh)?\s*(\d{1,3})\s*(?:degrees?|°|deg\.?)[,\s]*"
    r"(\d{1,2})\s*(?:minutes?|\'|min\.?)[,\s]*"
    r"(?:(\d{1,2})\s*(?:seconds?|\"|sec\.?)[,\s]*)?"
    r"([EW])\s*(?:ast|est)?",
    re.IGNORECASE,
)

DISTANCE_PATTERN = re.compile(
    r"(?:a?\s*distance\s+of\s+|,\s*)?(\d+(?:\.\d+)?)\s*(?:feet|ft\.?|foot)",
    re.IGNORECASE,
)

# "passing over stone 15.83 feet ... total distance of 336.25 feet": the total is the course length
TOTAL_DISTANCE_PATTERN = re.compile(
    r"\b(?:a\s+)?total\s+distance\s+(?:of\s+)?(\d+(?:\.\d+)?)\s*(?:feet|ft\.?|foot)",
    re.IGNORECASE,
)

# "158 feet 8 inches", "92 feet, 4 inches"
INCHES_AFTER_FEET_PATTERN = re.compile(
    r"\s*,?\s*(?:and\s+)?(\d+(?:\.\d+)?)\s*inch(?:es)?\b", re.IGNORECASE
)

# "10 feet wide alley" or "distant 10 feet Northeastwardly": not the course length
WIDTH_AFTER_PATTERN = re.compile(r"\s+wide\b", re.IGNORECASE)
OFFSET_BEFORE_PATTERN = re.compile(r"\bdistant\s+$", re.IGNORECASE)
OFFSET_AFTER_PATTERN = re.compile(r"\s+(?:north|south|east|west)", re.IGNORECASE)

THENCE_PATTERN = re.compile(r"\bthence\b", re.IGNORECASE)
BEGINNING_PATTERN = re.compile(r"\*{0,2}\bBEGINNING\b\*{0,2}\s+(?:at|in)\b", re.IGNORECASE)
# Block openings also include "BEGINNING on" (not "place of beginning on the lands") and
# "STARTING at" (a tie line precedes the POB)
BLOCK_START_PATTERN = re.compile(
    r"\*{0,2}\b(?:BEGINNING\b\*{0,2}\s+(?:at|in)|(?<!of\s)BEGINNING\b\*{0,2}\s+on"
    r"|STARTING\b\*{0,2}\s+at)\b",
    re.IGNORECASE,
)

# Cardinal-only pattern (no DMS) — mirrors _CARDINAL_ONLY_PATTERN from call_extractor.py
CARDINAL_ONLY_PATTERN = re.compile(
    r"\b(north|south|east|west|northeast|northwest|southeast|southwest|NE|NW|SE|SW)(?:erly|wardly)?\b",
    re.IGNORECASE,
)


def dms_to_decimal(deg: str | int, minutes: str | int, seconds: str | int | None = 0) -> float:
    """Convert DMS to decimal degrees."""
    return float(deg) + float(minutes) / 60.0 + float(seconds or 0) / 3600.0


def bearing_to_azimuth(quadrant1: str, angle_decimal: float, quadrant2: str) -> float | None:
    """Convert quadrant bearing to azimuth."""
    q1 = quadrant1.upper()
    q2 = quadrant2.upper()
    if q1 == "N" and q2 == "E":
        return angle_decimal
    elif q1 == "S" and q2 == "E":
        return 180.0 - angle_decimal
    elif q1 == "S" and q2 == "W":
        return 180.0 + angle_decimal
    elif q1 == "N" and q2 == "W":
        return 360.0 - angle_decimal
    return None


# "TRACT #1", "TRACT #2B": two or more mark separate tracts, not duplicate descriptions
TRACT_MARKER_PATTERN = re.compile(r"\bTRACT\s*#?\s*\d+[A-Z]?\b", re.IGNORECASE)

# Exhibit A / Schedule C section markers; the letter is a whole word ("SCHEDULE City" is not)
EXHIBIT_PATTERN = re.compile(
    r"(?:EXHIBIT\s*[\"']?\s*[\"']?A\b[\"']?|SCHEDULE\s+C\b)",
    re.IGNORECASE,
)

# "place of BEGINNING" or "point of beginning" closure marker
POB_CLOSE_PATTERN = re.compile(
    r"(?:point|place)\s+(?:and\s+place\s+)?of\s+BEGINNING|\bto\s+BEGINNING\b",
    re.IGNORECASE,
)

# "which last mentioned point is the place of beginning": a tie line ends here, the description goes on
# "which last mentioned point is the place of beginning" (a tie line ends here) or
# "said point of beginning being also distant ..." (a preamble reference): not closures.
# "to said point of beginning" still closes.
RESTATED_POB_BEFORE_PATTERN = re.compile(
    r"(?:\blast\s+mentioned\s+point\s+is\s+(?:the\s+)?|(?<!\bto\s)\bsaid\s+)$", re.IGNORECASE
)

# Numbered call starters: "1. " or "(1) " at start of line OR inline
CALL_NUM_PATTERN = re.compile(
    r"(?:^|\n)\s*(?:\d+\.\s|\(\d+\)\s|\([A-Za-z]\)\s)",
)

# A point of beginning reached by a tie course is followed by more courses:
# "...to a point and place of beginning, thence;" or "...place of beginning.\n\n(1) South..."
COURSES_FOLLOW_PATTERN = re.compile(
    r"\s*[,;.]?\s*(?:thence\b|\(\d+\)\s|\([A-Za-z]\)\s)", re.IGNORECASE
)

# Inline numbered calls in dense paragraphs: "(1) " anywhere in text
INLINE_NUM_PATTERN = re.compile(
    r"\(\d+\)\s",
)


def find_preferred_text(md_text: str) -> str:
    """Return text from Exhibit A / Schedule C section, or full text if none."""
    matches = list(EXHIBIT_PATTERN.finditer(md_text))
    if matches:
        return md_text[matches[0].start() :]
    return md_text


def find_block_close(text: str, start: int) -> re.Match[str] | None:
    """Find the closure ending a block, skipping restated or referenced points of beginning
    and points of beginning that more courses follow."""
    for match in POB_CLOSE_PATTERN.finditer(text, start):
        if RESTATED_POB_BEFORE_PATTERN.search(text, 0, match.start()):
            continue
        if COURSES_FOLLOW_PATTERN.match(text, match.end()):
            continue
        return match
    return None


def extract_distance(segment: str) -> float | None:
    """Return the course length in feet, preferring a stated total over widths and offsets."""
    total = TOTAL_DISTANCE_PATTERN.search(segment)
    if total:
        return float(total.group(1))
    matches = list(DISTANCE_PATTERN.finditer(segment))
    if not matches:
        return None

    def is_reference(m: re.Match[str]) -> bool:
        after = segment[m.end() :]
        return bool(
            WIDTH_AFTER_PATTERN.match(after)
            or (
                OFFSET_BEFORE_PATTERN.search(segment, 0, m.start(1))
                and OFFSET_AFTER_PATTERN.match(after)
            )
        )

    match = next((m for m in matches if not is_reference(m)), matches[0])
    value = float(match.group(1))
    inches = INCHES_AFTER_FEET_PATTERN.match(segment, match.end())
    if inches:
        value += float(inches.group(1)) / 12
    return value


def extract_all_legal_blocks(text: str) -> list[str]:
    """Extract all BEGINNING...point/place of BEGINNING blocks from text."""
    blocks = []
    search_start = 0

    while True:
        begin_match = BLOCK_START_PATTERN.search(text, search_start)
        if not begin_match:
            break

        start = begin_match.start()
        close_match = find_block_close(text, start + 10)
        if close_match:
            blocks.append(text[start : close_match.end()])
            search_start = close_match.end()
        else:
            # No closure after BEGINNING — check for closure BEFORE it
            # (handles MD files where PDF pages appear in reversed order).
            # Find the LAST closure before BEGINNING (closest to it),
            # not the first — there may be earlier false-positive matches.
            all_closes = list(POB_CLOSE_PATTERN.finditer(text[:start]))
            close_before = all_closes[-1] if all_closes else None
            if close_before:
                # Page wrap: [BEGINNING→end of file] + [start of file→closure]
                wrapped = text[start:] + "\n" + text[: close_before.end()]
                blocks.append(wrapped)
            else:
                # No closure found anywhere — take to next TRACT marker or end
                next_tract = re.search(r"\bTRACT\s*#?\d+", text[start + 10 :], re.IGNORECASE)
                if next_tract:
                    blocks.append(text[start : start + 10 + next_tract.start()])
                else:
                    blocks.append(text[start:])
            break

    return blocks


def extract_calls_from_block(block_text: str) -> list[dict[str, object]]:
    """Extract bearing/distance pairs from a single legal description block."""
    calls = []

    # Try numbered call detection first (handles semicolons between calls)
    num_matches = list(CALL_NUM_PATTERN.finditer(block_text))

    # Also check for inline numbered calls like "(1) " in dense paragraphs
    if len(num_matches) < 2:
        inline_matches = list(INLINE_NUM_PATTERN.finditer(block_text))
        if len(inline_matches) >= 2:
            num_matches = inline_matches

    if len(num_matches) >= 2:
        segments = []

        # Include pre-numbered text as thence-split segments
        pre_text = block_text[: num_matches[0].start()]
        if THENCE_PATTERN.search(pre_text):
            pre_segments = re.split(r"\bthence\b", pre_text, flags=re.IGNORECASE)[1:]
            segments.extend(pre_segments)

        for j, m in enumerate(num_matches):
            seg_start = m.start()
            seg_end = num_matches[j + 1].start() if j + 1 < len(num_matches) else len(block_text)
            segments.append(block_text[seg_start:seg_end])
    else:
        # Fall back to thence splitting. When courses end with "thence" ("...483.13 feet
        # to a point thence;"), the first course is the last sentence before it.
        preamble, *segments = re.split(r"\bthence\b", block_text, flags=re.IGNORECASE)
        last_sentence = re.split(r"[.;:]\s+|\n", preamble.strip())[-1]
        if segments and BEARING_PATTERN.match(last_sentence):
            segments.insert(0, last_sentence)

    for i, segment in enumerate(segments, 1):
        bearing_match = BEARING_PATTERN.search(segment)
        distance_ft = extract_distance(segment)

        call_data = {"call_num": i, "segment": segment[:200].strip()}

        if bearing_match:
            q1, deg, mins, secs, q2 = bearing_match.groups()
            angle = dms_to_decimal(deg, mins, secs)
            azimuth = bearing_to_azimuth(q1, angle, q2)
            call_data["bearing"] = f"{q1.upper()} {deg}°{mins}'{secs or '00'}\" {q2.upper()}"
            call_data["azimuth"] = azimuth
        else:
            cardinal_match = CARDINAL_ONLY_PATTERN.search(segment[:100])
            if cardinal_match:
                call_data["bearing"] = f"cardinal-only: {cardinal_match.group()}"
                call_data["azimuth"] = None

        if distance_ft is not None:
            call_data["distance_ft"] = distance_ft

        if "bearing" in call_data or "distance_ft" in call_data:
            calls.append(call_data)

    return calls


def extract_calls_from_md(
    md_text: str, n_gt: int | None = None, n_gt_calls: list[dict[str, object]] | None = None
) -> list[dict[str, object]]:
    """Extract bearing/distance pairs from markdown text.

    Prefers Exhibit A / Schedule C sections over deed body text.
    Extracts all complete BEGINNING...point/place of BEGINNING blocks.
    Uses numbered call patterns, falling back to thence splitting.

    When n_gt is provided and the total across all blocks doesn't match,
    tries to find a single block whose count matches the GT (handles PDFs
    that physically contain schedules from multiple deeds).
    """
    # Step 1: Prefer Exhibit A / Schedule C section
    search_text = find_preferred_text(md_text)

    # Step 2: Find all legal description blocks (multi-tract support)
    blocks = extract_all_legal_blocks(search_text)

    if not blocks and search_text != md_text:
        # No block in exhibit section — try full text
        blocks = extract_all_legal_blocks(md_text)

    if not blocks:
        # Step 2b (fallback): If no BEGINNING block found but closure language
        # exists (e.g., garbled OCR of BEGINNING like "BEGINNiNn"), anchor to
        # the first "thence" keyword and extract up to the closure marker.
        # This avoids including preamble text that could produce false matches.
        source = search_text
        close_match = POB_CLOSE_PATTERN.search(source)
        if not close_match and source != md_text:
            source = md_text
            close_match = POB_CLOSE_PATTERN.search(source)
        if close_match:
            first_thence = THENCE_PATTERN.search(source)
            if first_thence:
                block_start = first_thence.start()
            else:
                block_start = 0
            block_text = source[block_start : close_match.end()]
            return extract_calls_from_block(block_text)
        return []

    # Step 3: Extract calls from all blocks. A block repeating an earlier one word for word
    # is a second copy of the description (e.g. inside an attached certification), not a tract.
    seen: set[str] = set()
    unique_blocks = []
    for block in blocks:
        key = " ".join(block.split()).lower()
        if key not in seen:
            seen.add(key)
            unique_blocks.append(block)
    block_calls = [extract_calls_from_block(block) for block in unique_blocks]

    # Step 4: If some blocks have DMS bearings and others are cardinal-only,
    # drop the cardinal-only blocks (duplicate descriptions of the same parcel),
    # unless the deed is multi-tract: marked tracts, or all blocks together match the GT count.
    dms_blocks = [
        calls for calls in block_calls if any(c.get("azimuth") is not None for c in calls)
    ]
    total_calls = sum(len(calls) for calls in block_calls)
    multi_tract = len(TRACT_MARKER_PATTERN.findall(search_text)) >= 2 or total_calls == n_gt
    if dms_blocks and len(dms_blocks) < len(block_calls) and not multi_tract:
        block_calls = dms_blocks

    all_calls = []
    for calls in block_calls:
        all_calls.extend(calls)

    # Step 5: If total doesn't match GT but individual blocks do, use the
    # best-matching block. Handles PDFs containing schedules from multiple deeds.
    if n_gt is not None and len(all_calls) != n_gt and len(block_calls) > 1:
        matching = [calls for calls in block_calls if len(calls) == n_gt]
        if len(matching) == 1:
            return matching[0]
        if len(matching) > 1 and n_gt_calls is not None:
            # Multiple blocks match count — pick best by distance agreement
            best, best_score = matching[0], -1
            for candidate in matching:
                score = sum(
                    1
                    for i in range(n_gt)
                    if (
                        candidate[i].get("distance_ft") is not None
                        and n_gt_calls[i].get("distance_ft") is not None
                        and abs(candidate[i]["distance_ft"] - n_gt_calls[i]["distance_ft"]) < 0.1
                    )
                )
                if score > best_score:
                    best, best_score = candidate, score
            return best

    return all_calls


def audit_deed(pdf_base: str) -> dict[str, object]:
    """Audit a single deed's GT against its markdown."""
    md_path = SAMPLE_DIR / f"{pdf_base}.md"
    gt_path = SAMPLE_DIR / f"{pdf_base}.ground_truth.json"

    if not md_path.exists() or not gt_path.exists():
        return {"name": pdf_base, "status": "SKIP", "issues": ["Missing md or gt file"]}

    md_text = md_path.read_text()
    with open(gt_path) as f:
        gt = json.load(f)

    gt_calls = gt.get("expected_calls", [])
    issues = []

    # Extract calls from markdown (pass GT for best-block selection)
    md_calls = extract_calls_from_md(md_text, n_gt=len(gt_calls), n_gt_calls=gt_calls)

    # 1. Call count comparison
    n_gt = len(gt_calls)
    n_md = len(md_calls)

    # Count thence occurrences in markdown as a secondary check
    thence_count = len(THENCE_PATTERN.findall(md_text))

    if n_gt != n_md and n_gt > 0:
        issues.append(f"CALL_COUNT: GT={n_gt}, MD extracted={n_md}, thence count={thence_count}")
    elif n_gt == 0 and n_md > 0:
        # An empty GT would otherwise pass every comparison below
        issues.append(f"EMPTY_GT: GT has no calls but MD extracted={n_md}")

    # 2. Compare individual calls
    for i in range(min(n_gt, n_md)):
        gc = gt_calls[i]
        mc = md_calls[i]

        # Compare azimuth
        gt_az = gc.get("bearing_azimuth_deg_from_north")
        md_az = mc.get("azimuth")

        if gt_az is not None and md_az is not None:
            diff = abs(gt_az - md_az)
            if diff > 0.05:
                issues.append(
                    f"BEARING_C{i + 1}: GT={gt_az:.4f}°, MD={md_az:.4f}° "
                    f"(diff={diff:.4f}°) | MD text: {mc.get('bearing', '?')}"
                )
        elif gt_az is not None and md_az is None:
            # GT has azimuth but MD shows cardinal-only — check if MD text actually has bearing
            issues.append(
                f"BEARING_C{i + 1}: GT has azimuth {gt_az:.4f}° but MD shows cardinal-only | "
                f"MD: {mc.get('bearing', 'none')}"
            )

        # Compare distance
        gt_dist = gc.get("distance_ft")
        md_dist = mc.get("distance_ft")

        if gt_dist is not None and md_dist is not None:
            diff = abs(gt_dist - md_dist)
            if diff > 0.05:
                issues.append(
                    f"DISTANCE_C{i + 1}: GT={gt_dist:.2f}ft, MD={md_dist:.2f}ft (diff={diff:.2f}ft)"
                )
        elif gt_dist is not None and md_dist is None:
            issues.append(f"DISTANCE_MISSING_C{i + 1}: GT={gt_dist:.2f}ft, not found in MD")

    # 3. Check if BEGINNING is present in markdown.
    # Only flag when no calls were extracted (n_md == 0) — the Step 2b
    # fallback may recover calls via thence-splitting even without BEGINNING.
    if not BEGINNING_PATTERN.search(md_text):
        if n_gt > 0 and n_md == 0:
            issues.append("NO_BEGINNING: MD has no BEGINNING keyword but GT expects calls")

    # 4. Check GT raw_ocr_text vs MD content (rough similarity)
    gt_ocr = gt.get("raw_ocr_text", "")
    if gt_ocr and len(gt_ocr) > 50:
        # Check if key phrases from GT OCR appear in MD
        # Extract first bearing from GT OCR
        gt_bearing_match = BEARING_PATTERN.search(gt_ocr)
        if gt_bearing_match:
            # Check if similar bearing exists in MD
            if not BEARING_PATTERN.search(md_text):
                issues.append("OCR_BEARING_ABSENT: GT OCR has bearings but MD has none")

    # 5. Check POB consistency
    gt_pob = gt.get("expected_pob", "")
    if gt_pob:
        # Check if key POB terms appear in MD
        pob_keywords = [w for w in gt_pob.split() if len(w) > 4][:5]
        md_lower = md_text.lower()
        missing_kw = [kw for kw in pob_keywords if kw.lower() not in md_lower]
        if len(missing_kw) > len(pob_keywords) // 2:
            issues.append(f"POB_MISMATCH: GT POB keywords not found in MD: {missing_kw}")

    status = "PASS" if not issues else "FAIL"
    return {"name": pdf_base, "status": status, "issues": issues, "n_gt": n_gt, "n_md": n_md}


def main() -> None:
    pdf_files = sorted(SAMPLE_DIR.glob("*.pdf"))
    print(f"Auditing {len(pdf_files)} deeds: GT vs Markdown\n")

    results = []
    for pdf_path in pdf_files:
        base = pdf_path.stem
        result = audit_deed(base)
        results.append(result)

    # Summary
    pass_count = sum(1 for r in results if r["status"] == "PASS")
    fail_count = sum(1 for r in results if r["status"] == "FAIL")
    skip_count = sum(1 for r in results if r["status"] == "SKIP")

    print("=" * 90)
    print(
        f"GT AUDIT: {pass_count} PASS / {fail_count} FAIL / {skip_count} SKIP out of {len(results)}"
    )
    print("=" * 90)

    # Error type summary
    error_types = {}
    for r in results:
        for issue in r.get("issues", []):
            etype = issue.split(":")[0]
            if etype.startswith("BEARING_C"):
                etype = "BEARING_MISMATCH"
            elif etype.startswith("DISTANCE_C"):
                etype = "DISTANCE_MISMATCH"
            elif etype.startswith("DISTANCE_MISSING"):
                etype = "DISTANCE_MISSING"
            error_types.setdefault(etype, []).append((r["name"], issue))

    if error_types:
        print("\n--- ISSUE TYPE SUMMARY ---")
        for etype, instances in sorted(error_types.items(), key=lambda x: -len(x[1])):
            print(f"  {etype}: {len(instances)} occurrences")

    print("\n--- DETAILED ISSUES ---")
    for r in results:
        if r["status"] == "FAIL":
            print(f"\n  FAIL | {r['name']}")
            print(f"         GT calls: {r.get('n_gt', '?')}, MD extracted: {r.get('n_md', '?')}")
            for issue in r["issues"]:
                print(f"         - {issue}")

    print("\n--- PASSING DEEDS ---")
    for r in results:
        if r["status"] == "PASS":
            print(f"  PASS | {r['name']} (GT={r.get('n_gt', '?')}, MD={r.get('n_md', '?')} calls)")

    # Property summary
    print("\n--- PROPERTY SUMMARY ---")
    properties = {}
    for r in results:
        parts = r["name"].split(" - Deed Image")
        prop = parts[0] if parts else r["name"]
        properties.setdefault(prop, {"pass": 0, "fail": 0, "skip": 0, "total": 0})
        properties[prop]["total"] += 1
        properties[prop][r["status"].lower()] += 1

    for prop, counts in sorted(properties.items()):
        p = counts["pass"]
        t = counts["total"]
        f = counts["fail"]
        s = counts["skip"]
        pct = p / t * 100 if t > 0 else 0
        print(f"  {prop}: {p}/{t} pass ({pct:.0f}%) | {f} fail | {s} skip")


if __name__ == "__main__":
    main()
