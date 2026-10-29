# Using the metes-and-bounds skills

Start a closure request by locating the intended metes-and-bounds description. Any supplied source can contain it: a survey, plat, report, exhibit, title document, deed, email, image, or PDF.

## Choose the entrypoint

| Supplied input | Example request | Workflow |
| --- | --- | --- |
| Image or PDF | "Check the closure of the boundary in this survey." | `review-metes-and-bounds` → native conversion → description selection → deterministic review |
| Complete document text | "Find the boundary description in this report and check closure." | `review-metes-and-bounds` → description selection → deterministic review |
| Already isolated description | "Does this metes-and-bounds description close?" | Identify the supplied passage as the selected boundary, then deterministic review |
| Selected CSV/JSON calls | "Verify the closure of this call set." | Identify the intended boundary, then `verify-traverse` |
| Selected CSV/JSON calls, plot requested | "Plot these selected calls." | `plot-metes-and-bounds`; returns plot artifacts only |
| Supplied GeoJSON or scanned map, preparation requested | "Register/import this supplied map for later use." | `prepare-parcel-overlay`; returns prepared layer and provenance only |
| Prepared description and an explicit dashboard request | "Show the selected deed and parcel in an interactive workbench." | `deed-closure-dashboard`; reuse valid source and geometry artifacts |
| Several descriptions, no tract selected | "Does this property close?" | Locate candidates separately and clarify which boundary to check |

`review-deed` remains an entrypoint for deed-specific requests and follows the same shared workflow.

Transcription, description extraction, traverse verification, plotting, and overlay preparation are capabilities with separate deliverables. Stop after the requested capability; do not continue automatically to review, plotting, or dashboard creation. If a later stage is requested, reuse valid handoff artifacts for the unchanged source instead of rereading it. Dashboard discovery is limited to explicit interactive dashboard/workbench/source-comparison requests; a request for a plot alone uses the plot capability.

## Use in Claude

Load the extracted plugin using `claude --plugin-dir /absolute/path/to/plugin` for a local Claude Code session. Supply the document and ask the relevant question in natural language. The plugin instructions route conversion, selection, and review; native reading must be available in that session. Client installation and native reading support are separate from manifest validation.

Claude performs document/image conversion natively. No additional OCR service, provider credentials, or conversion software is introduced. If native reading cannot access the document, the skill reports the gap rather than silently choosing another provider.

## Source handoff

Preserve the original document, its full prepared text, and the selected description. Keep source locations and Claude's acquisition/selection records separate from the deterministic audit:

| Artifact | Meaning |
| --- | --- |
| `source-text.txt` | Full supplied text or Claude's native transcription |
| `source-acquisition.json` | Actual native-reading method, source identity, page coverage, instructions, and uncertainties, when conversion occurred |
| `description-<label>.txt` | Selected complete description, preserving source language |
| `description-selection.json` | Candidate identity, source ranges, rationale, and unresolved references |
| `review-<label>/` | New directory containing deterministic calls, verification results, audit, and report |

For already supplied text or calls, identify those as the source without inventing a native-conversion stage. See [source preparation](source-preparation.md) for record fields and uncertainty handling.

For stage-specific accepted inputs, output artifacts, status meanings, and invalidation rules, see [artifact handoffs](artifact-handoffs.md).

## Run the selected text directly

The Python launcher requires Python 3.11+ and `uv`. First use provisions the locked runtime in the user's cache. Run from the intended project root:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" review description-parcel-a.txt --output-dir reviews/parcel-a-new
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" verify calls.csv --output-dir reviews/calls-new
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" analyze-relative angles.json --output-dir reviews/angles-new
```

These commands accept prepared descriptions or identified call sets; they do not locate a description inside a PDF or arbitrary whole document. Output directories must be new. A configured output base can supply a fresh child when `--output-dir` is omitted. See [project settings](plugin-settings.md) for `.claude/metesparser.local.md`, CLI precedence, and per-run reload behavior.

For straight descriptions defined by relative angles, `analyze-relative` accepts a [source-linked JSON constraint description](../skills/deed-closure-dashboard/references/relative-analysis.md). It calculates local geometry separately from canonical verification and always retains `needs_review` (exit 1) for valid inputs, including successful analysis. It preserves unknown recorded bearings and produces no verified CSV. Check `analysis.status` for `analyzed`, `unresolved`, or `inconsistent`.

## Interpret the result

`checks_passed` (exit 0) means implemented deterministic checks passed; `needs_review` (exit 1) identifies unresolved checks; `error` (exit 2) reports a processing or configuration failure. The selected source and any uncertainty remain part of the result, even when geometry closes.

Missing exhibits, material illegibility, or unresolved tract selection must be resolved before issuing a verified result. Never infer a missing bearing or omit an exception to make a traverse close. Intersection checks cover straight segments and circular arcs; unsupported or incomplete curve geometry requires review. See [review scope](review-limits.md).

## Documentation and changes

Each skill directory has a human-facing `README.md` for examples and inputs/outputs, and `SKILL.md` for Claude's instructions. Keep detailed shared guidance in linked references. Record user-visible changes once in the [plugin changelog](../CHANGELOG.md); use the repository changelog for project-level announcements.
