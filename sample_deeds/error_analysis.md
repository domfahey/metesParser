# Error Analysis: GT vs MD Failures

**Date**: 2026-02-16 (updated after fixes)
**Total deeds**: 63 | **Pass**: 54 | **Fail**: 9

## Fixes Applied

### Fix 3: Abbreviated cardinal direction matching
`call_extractor.py` now recognizes LLM-abbreviated cardinals (NW, SW, NE, SE) in both
`_CARDINAL_ONLY_PATTERN` and `extract_direction()`. Previously, when `PDFProcessor.normalize_legal_description()` (LLM-based) abbreviated "NORTHWEST" to "NW", the call extractor couldn't match the direction and rejected the call.

### Fix 1 + Fix 4: Audit script multi-tract and dense paragraph support
`scripts/audit_gt_vs_md.py` now:
- Extracts ALL BEGINNING...closure blocks (multi-tract support)
- Matches "BEGINNING in" in addition to "BEGINNING at"
- Matches "point of beginning" in addition to "place of BEGINNING"
- Handles inline numbered calls `(1)` in dense paragraphs
- Processes pre-numbered thence-split segments before numbered sections

**Result**: 3 multi-tract Euclid Ave deeds now pass (10763-969, 11792-01193, 8577-1165).

## Remaining Failures (9 deeds)

### Category 1: Multi-Description Deeds (2 deeds)

**100 Haddon Ave (4317-236)**
Two separate legal descriptions: cardinal-only (page 1) and survey with quadrant bearings (page 2). Audit extracts both (8 calls) vs GT's 4 from the survey only.

**8 Kings Highway W (7535-929)**
Two separate lot descriptions with 4 calls each. Audit correctly finds 8 calls; GT only captured the first lot (4 calls). Previously a false pass.

### Category 2: Interior Angle Notation — GT Needs Regeneration (2 deeds)

**100 Haddon Ave (4658-859)** and **(4658-863)**
GT pipeline rejected cardinal-only calls, yielding GT=3 instead of 4. Fix 3 (abbreviated cardinal matching) should allow GT regeneration to produce 4 calls. MD correctly shows 4 calls.

### Category 3: OCR Quality in Multi-Tract Deed (1 deed)

**15 E Euclid Ave (7433-466)**
Multi-block extraction works (6 calls found = GT count), but LlamaParse OCR produced "8o" (letter o) instead of "80" and "142 rest" instead of "142 feet". Call count matches; distance values don't due to OCR corruption.

### Category 4: LLM OCR Digit Ambiguity (1 deed)

**75 Haddon Ave (4924-448)**
GT LLM: 187.31 ft vs LlamaParse: 87.31 ft (leading "1" ambiguity). Needs manual verification.

### Category 5: Severely Degraded Scan (1 deed)

**75 Haddon Ave (4924-452)**
Garbled OCR: "BEGINNiNn e onas invesa7.6". Too poor for any OCR engine.

### Category 6: Pre-Existing Failures (2 deeds)

**38 Birchall Dr (10054-595)** and **8 Kings Highway W (7535-933)** — missing BEGINNING keyword in MD.

## Summary

| Category | Count | Status |
|---|---|---|
| Multi-description deed (audit extracts both) | 2 | GT limitation — would need multi-description GT |
| Interior angle notation (GT needs regen) | 2 | Actionable — regenerate GT with Fix 3 |
| OCR quality in multi-tract deed | 1 | LlamaParse OCR limitation |
| LLM OCR digit ambiguity | 1 | Manual verification required |
| Severely degraded scan | 1 | Re-scan at higher resolution |
| Pre-existing failures (no BEGINNING in MD) | 2 | Already known |

**Improvement**: 52/63 (83%) → 54/63 (86%) pass rate. 3 multi-tract deeds fixed.
