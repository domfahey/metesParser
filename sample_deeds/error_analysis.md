# Error Analysis: GT vs MD Failures (11 deeds)

**Date**: 2026-02-16
**Total deeds**: 63 | **Pass**: 52 | **Fail**: 11 | **New deed failures**: 7 of 23 (30%)

## Category 1: Multi-Description Deeds (1 deed)

**100 Haddon Ave (4317-236)**

The deed contains **two separate legal descriptions** for the same parcel:
- **Description 1** (page 1): Uses cardinal directions + interior angles ("Northwest along... 129 feet; thence Southwest, forming an interior angle of 89°43'30"...")
- **Description 2** (page 2): A proper survey with quadrant bearings ("North 34 degrees 02' 00" West 129.00 feet to a found iron pipe")

The GT pipeline correctly found Description 2 and extracted 4 calls with proper azimuths. The audit script's regex matched the cardinal-only Description 1 first, reporting bearing mismatches. **Not a real error** — just an artifact of the deed having two descriptions and the audit heuristic matching the wrong one.

## Category 2: Interior Angle Notation — No Quadrant Bearings (2 deeds)

**100 Haddon Ave (4658-859)** and **(4658-863)** (same property, different recordings)

The legal description uses only cardinal directions with interior angles:
> "NORTHWEST ALONG THE SOUTHWEST LINE OF HADDON AVENUE 129 FEET; THENCE SOUTHWEST, FORMING AN INTERIOR ANGLE OF 89 DEGREES 43 MINUTES 30 SECONDS..."

The GT pipeline **rejected call 2** ("Rejecting bearingless non-curve call") because it had no standard bearing — yielding GT=3 calls. But the MD correctly shows 4 calls. The GT also reordered the remaining calls, causing distance mismatches (GT C2=129ft vs MD C2=200ft).

**Root cause**: The `call_extractor.py` rejection heuristic drops valid calls that use interior-angle notation. The deed is geometrically complete (4 calls forming a rectangle), but the parser can't derive bearings from interior angles alone.

## Category 3: Multi-Tract Deeds (4 deeds)

**15 E Euclid Ave (10763-969)**, **(11792-01193)**, **(7433-466)**, **(8577-1165)**

All 4 are recordings of the same property with two tracts:

- **Tract #1**: Archaic notation — "80 feet in width or breadth; thence Northwestwardly between parallel lines, parallel with Turnley Avenue 142 feet in length or depth." No numbered courses, no explicit bearings.
- **Tract #2**: 4 numbered courses with cardinal directions and interior angles ("Westwardly along said Northerly line of Euclid Avenue the distance of 10 feet")

The GT pipeline extracted **6 calls** (2 from Tract #1 + 4 from Tract #2). The audit script's regex only found **4 calls** (the numbered ones from Tract #2) because Tract #1 uses "width or breadth"/"length or depth" notation that doesn't match the `DISTANCE_PATTERN` regex.

For (8577-1165), the exhibit combines both tracts in a single dense paragraph, and the audit found **0 calls** — the compact format defeated the regex patterns entirely.

**Root cause**: Archaic "width/breadth/depth" notation and dense paragraph formatting aren't handled by the audit script's extraction regex.

## Category 4: LLM OCR Digit Ambiguity (1 deed)

**75 Haddon Ave (4924-448)**

| Field | GT (LLM OCR) | MD (LlamaParse) | Likely Correct |
|---|---|---|---|
| Course 1 distance | 187.31 ft | 87.31 ft | Needs manual verification |
| Course 2 total distance | 707.52 ft | 307.52 ft | Needs manual verification |

The GT LLM extracted "187.31" while LlamaParse got "87.31" — a leading "1" ambiguity. Similarly "707.52" vs "307.52" — a "7" vs "3" confusion. Both are plausible OCR misreads from a low-resolution 1997 scan. The deed (4924-452) of the same property is even worse — page 1 is nearly illegible.

**Root cause**: Low-resolution scan causes digit ambiguity. Neither OCR result can be trusted without manual verification against the original.

## Category 5: Severely Degraded Scan (1 deed)

**75 Haddon Ave (4924-452)**

Page 1 of the MD shows garbled text: `"BEGINNiNn e onas invesa7.6"` — nearly illegible. The GT extracted 1 call; the audit found 0. Page 2 is readable but the audit script requires a `BEGINNING` keyword match that the garbled page 1 can't provide.

**Root cause**: Original scan quality is too poor for any OCR engine.

## Category 6: Pre-Existing Failures (2 deeds — not new)

**38 Birchall Dr (10054-595)** and **8 Kings Highway W (7535-933)** — these existed before the new batch and have the same patterns (missing BEGINNING keyword in MD).

## Summary

| Category | Count | Actionable? |
|---|---|---|
| Multi-description deed (audit matched wrong one) | 1 | Fix audit script to prefer survey description over cardinal-only |
| Interior angle notation (no quadrant bearing) | 2 | Parser limitation — would need interior-angle-to-bearing solver |
| Multi-tract / archaic notation | 4 | Fix audit regex for "width/breadth/depth" patterns |
| LLM OCR digit ambiguity | 1 | Manual verification required |
| Severely degraded scan | 1 | Re-scan at higher resolution |
| Pre-existing failures | 2 | Already known |

**7 of 23 new deeds failed** (30%). Of these, only 1 requires manual data correction (OCR ambiguity). The other 6 are parser/audit limitations with archaic deed notation styles.
