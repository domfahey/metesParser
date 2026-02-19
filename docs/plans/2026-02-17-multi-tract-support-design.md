# Multi-Tract Support Design

**Date**: 2026-02-17
**Status**: Approved
**Approach**: Tract wrapper model (Approach A)

## Problem

The system handles exactly one closed polygon per deed. Multi-tract deeds — which represent ~36% of sample deeds (31/87) — either fail closure verification or have secondary tracts silently dropped.

### Failing patterns

| Pattern | Example deeds | Current behavior |
|---------|--------------|-----------------|
| TRACT #1 / #2 markers | 101-111 Kings Hwy E | Not detected; calls merged into one flat list |
| Multiple BEGINNING blocks | 219 Berlin Rd, 1 Walnut St | Second block merged or missed |
| ALSO additive parcels | 2 Walnut St | Merged with `is_exception=False`; closure fails |
| EXCEPT exclusions | 36 Kresson Rd | Partially works (area subtracted) but exception traverse not independently verified |

### Layers affected

Every layer assumes single-tract: LLM prompt drops secondary descriptions, `extract_calls()` uses one course counter, `LegalDescription` has one flat `calls` list, `verify_closure()` runs one traverse, CSV export writes one file.

## Design Decisions

1. **All multi-tract patterns supported**: TRACT/PARCEL markers, multiple BEGINNING blocks, ALSO additive parcels, EXCEPT exclusions.
2. **One CSV per tract**: `deed_verified_tract1.csv`, `deed_verified_tract2.csv`, etc. Existing single-tract output unchanged.
3. **Rule-based splitting only**: No LLM prompt changes. `mp-parse` detects tract boundaries deterministically.
4. **Zero breaking changes**: Single-tract deeds behave identically. Multi-tract behavior only activates when `tracts` is non-empty.

## Architecture

### 1. New `Tract` model (mp-models)

```python
class TractType(str, Enum):
    MAIN = "main"           # Primary parcel
    EXCEPTION = "exception"  # EXCEPT/LESS AND EXCEPT (subtracted from area)
    ADDITION = "addition"    # ALSO/INCLUDING (additive parcel)
    EASEMENT = "easement"    # Easement tract


class Tract(_Model):
    label: str                              # "Tract 1", "Parcel A", "Exception 1"
    tract_type: TractType
    calls: list[DeedCall]
    pob_description: str | None = None
    stated_area_sq_ft: float | None = None
    closure_result: ClosureResult | None = None  # Populated by mp-verify
```

`LegalDescription` gains:

```python
tracts: list[Tract] = Field(default_factory=list)
```

Backward-compatible `all_calls` property merges all tracts:

```python
@property
def all_calls(self) -> list[DeedCall]:
    """Flat list of all calls across all tracts."""
    return [c for t in self.tracts for c in t.calls] if self.tracts else self.calls
```

Single-tract deeds continue using `calls` directly. `tracts` stays empty unless the parser detects multi-tract patterns.

### 2. Tract splitting in mp-parse

New `split_into_tracts()` function replaces `split_exception_clauses()` as the top-level text splitter. Detection in priority order:

1. **Explicit markers**: `TRACT #N`, `TRACT A`, `PARCEL N`, `PARCEL A` (regex)
2. **Independent BEGINNING blocks**: Multiple `BEGINNING at/in` markers, each with its own POB closure
3. **EXCEPT/ALSO clauses**: Existing `split_exception_clauses()` logic, reused as fallback

```python
def split_into_tracts(text: str) -> list[tuple[str, str, TractType]]:
    """Split legal description text into tract segments.

    Returns: list of (tract_text, label, tract_type)
    """
    # 1. Try explicit TRACT/PARCEL markers
    tract_markers = find_tract_markers(text)
    if tract_markers:
        return split_on_markers(text, tract_markers)

    # 2. Try multiple BEGINNING blocks
    beginning_blocks = find_beginning_blocks(text)
    if len(beginning_blocks) > 1:
        return label_beginning_blocks(beginning_blocks)

    # 3. Fall back to EXCEPT/ALSO splitting
    clauses = split_exception_clauses(text)
    return [(t, auto_label(i, is_exc),
             TractType.EXCEPTION if is_exc else TractType.MAIN)
            for i, (t, is_exc) in enumerate(clauses)]
```

In `extract_calls()`: calls `split_into_tracts()` and builds a `Tract` per segment. Course numbering resets per tract. `split_exception_clauses()` remains as a lower-level utility.

### 3. Verification changes (mp-verify)

New function for single-tract verification:

```python
def verify_tract(
    calls: list[DeedCall],
    audit_context: AuditContext | None = None,
) -> ClosureResult:
    """Verify one tract's closure. Runs the 8 checks, no exception splitting."""
```

Updated `verify_closure()` gains optional `tracts` parameter:

```python
def verify_closure(
    calls: list[DeedCall],
    tracts: list[Tract] | None = None,
    audit_context: AuditContext | None = None,
) -> ClosureResult | list[ClosureResult]:
    """Verify closure — multi-tract aware.

    If tracts provided: verify each independently, return list[ClosureResult].
    If no tracts (backward compat): existing single-traverse behavior.
    """
```

Net area computation:

```
net_area = sum(main tract areas) - sum(exception tract areas) + sum(addition tract areas)
```

Each tract gets its own `ClosureResult` with independent misclosure, area, and all 8 verification checks. Exception tracts are now properly closure-verified.

### 4. Export changes (mp-export)

One CSV per tract:

```
deed_verified.csv              # single-tract (backward compat)
deed_verified_tract1.csv       # multi-tract: main parcel
deed_verified_tract2.csv       # multi-tract: exception
deed_verified_tract3.csv       # multi-tract: addition
```

21-field CSV schema unchanged. Each file is self-contained.

```python
def export_verified_csv(
    legal_desc: LegalDescription,
    closure_result: ClosureResult,
    output_path: Path,
    *,
    tract_results: list[tuple[Tract, ClosureResult]] | None = None,
    audit_context: AuditContext | None = None,
) -> list[Path]:  # was single Path
```

Audit sidecar (`.audit.json`, `.audit.html`) gains a `tracts` array with per-tract closure summaries, call tables, and confidence scores, plus a top-level `net_area`.

### 5. Pipeline changes

Return type stays the same for backward compat:

```python
def run(self, pdf_path: Path) -> ClosureResult | tuple[ClosureResult, AuditContext]:
```

For multi-tract deeds, the returned `ClosureResult` is a summary (net area, combined pass/fail). Per-tract results live on `legal_desc.tracts[i].closure_result`.

Pipeline flow:

```
PDF → PDFProcessor (unchanged) → LegalDescription
  → split_into_tracts() → populate legal_desc.tracts
  → for each tract: verify_tract() → tract.closure_result
  → compute summary ClosureResult (net area, combined pass/fail)
  → export: one CSV per verified tract + combined audit sidecar
```

### 6. Monolith sync

All changes to packages must be mirrored in the monolith:
- `mp-models` changes → `src/metesparser/models.py`
- `mp-parse` changes → `src/metesparser/call_extractor.py`, `text_parser.py`
- `mp-verify` changes → `src/metesparser/closure_checker.py`
- `mp-export` changes → `src/metesparser/csv_builder.py`

## Backward Compatibility

| Layer | Single-tract deed behavior | Change? |
|-------|---------------------------|---------|
| `LegalDescription.calls` | Still populated directly | No |
| `LegalDescription.tracts` | Empty list (default) | New field, inert |
| `verify_closure(calls)` | Same as today | No |
| `export_verified_csv()` | One `_verified.csv` | No |
| `Pipeline.run()` return type | Same `ClosureResult` | No |
| CSV schema | 21 fields | No |

## Testing Strategy

- Unit tests per tract type (MAIN, EXCEPTION, ADDITION, EASEMENT)
- Multi-tract splitting tests with real deed text from failing samples
- Independent closure verification per tract
- Net area = main - exception + addition
- Backward compat: all existing ~994 tests pass unchanged
- Integration: re-run audit script, expect improvement on multi-tract failures

## Sample Deed Coverage

31 of 87 sample deeds have multi-tract indicators:
- 25 deeds with multiple BEGINNING blocks
- 15 deeds with TRACT markers
- 8 deeds with PARCEL markers
- Currently 5 audit failures directly caused by multi-tract limitations
