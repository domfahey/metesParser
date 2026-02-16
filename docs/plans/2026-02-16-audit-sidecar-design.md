# Audit Sidecar Design: Transparency by Design

**Date**: 2026-02-16
**Status**: Approved
**Goal**: Every pipeline run produces a `.audit.json` sidecar + `.audit.html` report so surveyors can trace every CSV value back to source text.

## Audience & Problem

Primary audience: **end users / surveyors** reviewing CSV output. The biggest trust gap is the LLM extraction step — an AI reads the PDF, and there is currently no record of what it extracted or how the structured output was derived.

Surveyors need:
1. **Side-by-side comparison** — original deed text alongside structured extraction
2. **Transformation log** — raw text -> normalized -> parsed -> structured, step by step
3. **Confidence annotations** — which values to double-check

## Approach: Audit Sidecar

JSON as canonical store, HTML as presentation layer. No changes to existing CSV schema or DeedCall model.

Output files per run:
```
deed.csv                # structured calls (unchanged)
deed_verified.csv       # verified calls (unchanged)
deed.metadata.txt       # deed metadata (unchanged)
deed.verification.txt   # closure report (unchanged)
deed.audit.json         # NEW: full audit trail
deed.audit.html         # NEW: human-readable report
```

---

## Section 1: Data Model

New Pydantic models in `models.py` (frozen, extra=forbid):

```
AuditContext
├── run_metadata
│   ├── parser_version: str          # "0.2.0"
│   ├── llm_provider: str            # "openai" / "gemini"
│   ├── llm_model: str               # "gpt-5.2"
│   ├── prompt_hash: str             # SHA256 of prompt template used
│   ├── timestamp_utc: datetime
│   ├── source_pdf: str              # filename
│   ├── cache_hit: bool              # was LLM response from cache?
│   └── config_snapshot: dict        # tolerances, flags, distance unit
│
├── extraction_record
│   ├── raw_llm_response: str        # verbatim LLM output
│   ├── normalized_text: str         # after TextParser.normalize
│   └── llm_confidence: float | None # heuristic score (see Section 4)
│
├── call_audits: list[CallAudit]     # one per DeedCall, indexed by course #
│   ├── course: int
│   ├── source_excerpt: str          # exact text span parsed (see Section 3)
│   ├── transformations: list[Transformation]
│   │   ├── step: str               # "normalize", "extract_bearing", etc.
│   │   ├── input: str
│   │   ├── output: str
│   │   └── rule: str | None        # regex pattern or method that matched
│   ├── decisions: list[Decision]
│   │   ├── field: str              # "monument_type", "bearing_azimuth", etc.
│   │   ├── value: str
│   │   ├── reason: str             # "matched pattern: iron\s*(pin|rod)"
│   │   ├── alternatives: list[str] # other possible values considered
│   │   └── confidence: float       # 0.0-1.0
│   └── flags: list[str]            # "incomplete_bearing", "indefinite", etc.
│
└── verification_audit
    ├── checks: list[CheckResult]
    │   ├── name: str               # "traverse_closure", "curve_consistency"
    │   ├── passed: bool
    │   ├── detail: str             # "misclosure: 0.0032 ft < 0.01 ft tolerance"
    │   └── inputs: dict            # actual values used in the check
    └── closure_summary: dict        # misclosure, precision, area, confidence
```

Key decisions:
- Pydantic models (frozen, extra=forbid) — consistent with project patterns
- Indexed by course number — surveyors think in courses, not array indices
- `source_excerpt` is the most important field — the "show me where this came from" answer
- `alternatives` on decisions captures "what else could this have been?"

---

## Section 2: Pipeline Threading

`AuditContext` gets threaded through the pipeline via an optional parameter.

```
PDFProcessor.process_deed_pdf()
  │
  ├─ Creates AuditContext(run_metadata=...)    # born here
  │
  ├─ LLM extraction
  │   └─ ctx.extraction_record = ...           # raw LLM response captured
  │
  ├─ TextParser.normalize_legal_description(text, ctx)
  │   └─ ctx.extraction_record.normalized_text = ...
  │
  ├─ CallExtractor.extract_calls(text, ctx)
  │   └─ ctx.call_audits.append(CallAudit(...))  # one per call
  │
  ├─ BearingConverter.enrich_calls_with_azimuths(calls, ctx)
  │   └─ ctx.call_audits[i].transformations.append(...)
  │
  ├─ MonumentClassifier.classify_monument(to_text, ctx, course)
  │   └─ ctx.call_audits[i].decisions.append(...)
  │
  ├─ ClosureChecker.verify_closure(calls, ctx)
  │   └─ ctx.verification_audit = ...
  │
  └─ Returns (LegalDescription, AuditContext)   # both returned
```

Design rules:
1. **`ctx` is always optional** — `ctx: AuditContext | None = None`. Methods check `if ctx:` before writing. Zero behavior change when auditing is off; existing tests pass untouched.
2. **PDFProcessor owns the lifecycle** — creates, passes down, serializes. No other module creates or serializes.
3. **Modules only append, never read** — one-directional coupling.
4. **Course number is the join key** — CallAudit.course matches DeedCall.course (the CSV `course` column).

Serialization:
```python
if ctx:
    audit_path = output_path.with_suffix(".audit.json")
    audit_path.write_text(ctx.model_dump_json(indent=2))
```

What does NOT change:
- No changes to `DeedCall`, `LegalDescription`, or `ClosureResult` models
- No changes to CSV schema
- No changes to existing method signatures (ctx is optional with default None)
- All existing tests pass without modification

---

## Section 3: Source Excerpt Capture

`CallExtractor.extract_calls()` uses regex to split legal description text into individual call strings, then parses each one. The raw call strings are currently consumed during parsing. We preserve them.

Strategy — capture at split time:
```
Full normalized text
  │
  ├─ CallExtractor splits into call_texts: list[str]
  │   e.g. ["thence South 56°40'30\" West, 150.00 feet to an iron pin found", ...]
  │
  ├─ For each (i, call_text):
  │   ├─ Parse into DeedCall (existing logic, unchanged)
  │   └─ Create CallAudit(course=i+1, source_excerpt=call_text)
  │
  └─ source_excerpt = exact string fed into the parser
```

Why this works:
- `call_text` already exists as a loop variable — just save it instead of discarding it
- It's verbatim — no transformation applied yet at this point
- It's per-call — each course maps to exactly one source excerpt

Full traceability chain:
```
CSV row → source_excerpt (what was parsed)
       → normalized_text (full context)
       → raw_llm_response (what the AI actually said)
```

Edge cases:
- Tie-in calls: same treatment, `is_tie_in` in audit flags
- Exception clauses: split happens before call extraction; exception text in `extraction_record`
- Failed parses: `source_excerpt` still captured with `flags=["parse_failed"]`
- Multi-line calls: full multi-line string preserved (regex captures across line breaks)

---

## Section 4: Confidence Scoring

Two layers — LLM extraction confidence and per-field parse confidence.

### Layer 1: LLM Extraction Confidence

Post-extraction heuristic scoring (not model-reported confidence):

| Signal | Weight | Check |
|--------|--------|-------|
| Has POB statement | +0.20 | Fundamental to any deed |
| Has 3+ bearing calls | +0.20 | Looks like a real legal description |
| Has closure language | +0.15 | "to the point of beginning" |
| Has distance values | +0.15 | Numeric feet/chains/etc |
| Text length reasonable | +0.10 | Not suspiciously short/long |
| Has PLSS metadata | +0.10 | Section/township/range |
| No garbled characters | +0.10 | OCR quality signal |

Advisory only — does not gate any processing.

### Layer 2: Per-Field Parse Confidence

| Classification | Confidence | Reasoning |
|----------------|-----------|-----------|
| Exact regex match (bearing) | 0.95 | Unambiguous pattern |
| Monument classification (specific keyword) | 0.90 | Clear keyword like "iron pin" |
| Monument classification (generic fallback) | 0.60 | Ambiguous like "marker" |
| Cardinal-only bearing | 0.40 | Direction known, degrees unknown |
| Inferred values (unit heuristic) | 0.50 | Educated guess |
| Missing/defaulted values | 0.0 | No data |

Confidence lives only in the audit trail — no new fields on DeedCall.

---

## Section 5: `.audit.json` Schema

```json
{
  "schema_version": "1.0.0",
  "run_metadata": {
    "parser_version": "0.2.0",
    "llm_provider": "openai",
    "llm_model": "gpt-5.2",
    "prompt_hash": "a3f2c8...",
    "timestamp_utc": "2026-02-16T14:30:00Z",
    "source_pdf": "18_pennbrook.pdf",
    "cache_hit": false,
    "config": {
      "closure_tolerance_ft": 0.01,
      "distance_unit": "feet",
      "log_level": "INFO"
    }
  },
  "extraction_record": {
    "raw_llm_response": "BEGINNING at an iron pin found in the...",
    "normalized_text": "BEGINNING at an iron pin found in the...",
    "llm_confidence": 0.85,
    "confidence_signals": {
      "has_pob": true,
      "has_bearing_calls": true,
      "has_closure_language": true,
      "has_distances": true,
      "text_length_reasonable": true,
      "has_plss": false,
      "no_garbled_chars": true
    }
  },
  "call_audits": [
    {
      "course": 1,
      "source_excerpt": "thence South 56 degrees 40 minutes 30 seconds West, 150.00 feet to an iron pin found",
      "transformations": [
        {
          "step": "extract_bearing",
          "input": "South 56 degrees 40 minutes 30 seconds West",
          "output": "S 56°40'30\" W",
          "rule": "BEARING_PATTERN (call_extractor.py:87)"
        },
        {
          "step": "compute_azimuth",
          "input": "S 56°40'30\" W",
          "output": "236.675",
          "rule": "quadrant_to_azimuth: 180 + 56.675"
        },
        {
          "step": "extract_distance",
          "input": "150.00 feet",
          "output": "150.0",
          "rule": "DISTANCE_PATTERN (call_extractor.py:92)"
        },
        {
          "step": "classify_monument",
          "input": "to an iron pin found",
          "output": "iron_pin",
          "rule": "iron\\s*pin (call_extractor.py:134)"
        }
      ],
      "decisions": [
        {
          "field": "bearing_azimuth_deg_from_north",
          "value": "236.675",
          "reason": "S quadrant: 180 + 56.675 = 236.675",
          "alternatives": [],
          "confidence": 0.95
        },
        {
          "field": "monument_type",
          "value": "iron_pin",
          "reason": "matched pattern: iron\\s*pin",
          "alternatives": ["iron_rod"],
          "confidence": 0.90
        },
        {
          "field": "monument_status",
          "value": "found",
          "reason": "matched keyword: found",
          "alternatives": ["set"],
          "confidence": 0.95
        }
      ],
      "flags": []
    }
  ],
  "verification_audit": {
    "checks": [
      {
        "name": "traverse_closure",
        "passed": true,
        "detail": "misclosure: 0.0032 ft < 0.01 ft tolerance",
        "inputs": {
          "misclosure_x_ft": 0.0021,
          "misclosure_y_ft": 0.0024,
          "misclosure_total_ft": 0.0032,
          "tolerance_ft": 0.01
        }
      }
    ],
    "closure_summary": {
      "misclosure_ft": 0.0032,
      "precision_ratio": "1:46875",
      "area_sq_ft": 7543.21,
      "area_acres": 0.1732,
      "perimeter_ft": 600.12,
      "confidence_score": 0.92,
      "status": "EXCELLENT"
    }
  }
}
```

Schema decisions:
- `schema_version` at top — allows future evolution
- `prompt_hash` not full prompt — avoids bloating
- `raw_llm_response` stored verbatim — ground truth for surveyor comparison
- `rule` includes file:line — shows parsing is deterministic
- `inputs` on verification checks — surveyors can independently verify the math

---

## Section 6: HTML Audit Report

Generated from `.audit.json` via new module `audit_reporter.py`. Single-file HTML with embedded CSS, no external dependencies.

### Layout
- **Header**: PDF name, timestamp, parser version, LLM model, overall confidence
- **LLM Extraction** (collapsible): side-by-side raw vs normalized text, confidence bar
- **Call-by-Call Summary Table**: course | source excerpt | parsed values | confidence dots | flags
- **Course Detail** (click to expand per row): full transformation log, decisions with alternatives, reasoning
- **Verification** (collapsible): per-check pass/fail table with detail and inputs, closure summary

### UX Decisions
- Color coding: green (>=0.8), yellow (0.5-0.8), red (<0.5) on confidence
- Red rows jump out — surveyors immediately see which values need manual verification
- Self-contained HTML — no JS frameworks, no external requests, works offline
- Collapsible sections — scan summary first, drill into flagged courses only

### Implementation
- `AuditReporter.generate_html(ctx: AuditContext) -> str`
- `AuditReporter.write_report(ctx: AuditContext, path: Path) -> None`
- Python string templates (no Jinja dependency)
- Called from `PDFProcessor` after `.audit.json` is written

---

## What Does NOT Change

- `DeedCall`, `LegalDescription`, `ClosureResult` models — untouched
- CSV schema (21 fields) — untouched
- Existing method signatures — `ctx` parameter is optional with default `None`
- All ~790 existing tests pass without modification
- `.metadata.txt` and `.verification.txt` output — still produced as before

## New Modules

| Module | Purpose |
|--------|---------|
| `models.py` (additions) | `AuditContext`, `CallAudit`, `Transformation`, `Decision`, `CheckResult`, `RunMetadata`, `ExtractionRecord`, `VerificationAudit` |
| `audit_reporter.py` (new) | HTML report generation from AuditContext |

## Deliverables (Incremental)

1. **Phase A**: Data model + pipeline threading + JSON serialization
2. **Phase B**: Source excerpt capture + confidence scoring
3. **Phase C**: HTML report generation
