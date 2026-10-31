# Using the metes-and-bounds skills

Contents: [Choose the entrypoint](#choose-the-entrypoint) · [Examples of composition](#examples-of-composition) · [Use in Claude](#use-in-claude) · [Source handoff](#source-handoff) · [Runtime prerequisites](#runtime-prerequisites) · [Run the selected text directly](#run-the-selected-text-directly) · [Intake, controls and resuming](#intake-controls-and-resuming) · [Interpret the result](#interpret-the-result) · [Documentation and changes](#documentation-and-changes) · [Requested Mapbox companion](#requested-mapbox-companion)

Commands below use the plugin root that the invoking skill printed; substitute it for `${CLAUDE_PLUGIN_ROOT}`.

Use a capability for one requested stage and stop at its deliverable. Use a workflow when the user requested the full review sequence or an interactive dashboard. The catalog in the [plugin README](../README.md#skills) links each skill and summarizes its purpose and output.

Start a closure request by locating the intended metes-and-bounds description. Any supplied source can contain it: a survey, plat, report, exhibit, title document, deed, email, image, or PDF.

## Choose the entrypoint

| Supplied input and request | Route | Stop point |
| --- | --- | --- |
| Image/PDF and “Check the closure of the boundary in this survey.” | `review-metes-and-bounds` coordinates native conversion → description selection → deterministic review. | Return review results and source records. |
| Complete document text and “Find the boundary description and check closure.” | `review-metes-and-bounds` coordinates selection → deterministic review. | Reuse the supplied text; do not invent a conversion stage. |
| Isolated description and “Does this close?” | `review-metes-and-bounds`, treating the supplied passage as selected. | Run the requested review. |
| Selected CSV/JSON calls and “Verify closure.” | Identify the intended call set, then `verify-traverse`. | Return verification only. |
| RelativeDescription JSON and “Analyze these relative angles.” | `verify-traverse` runs `analyze-relative`. | Return local analysis only; no canonical verification, plot, or dashboard. |
| PDF/image or whole document and “Plot the boundary in this deed.” | `plot-metes-and-bounds` composes native conversion when needed → description selection → standalone plot. | Return intake, source coverage and plot; no automatic verification/dashboard. |
| Document and “Can this description be plotted?” | Same source preparation, then assess supported/unresolved geometry. | State exact missing input; no automatic downstream deliverables. |
| Several explicitly identified tracts and “Review/plot A and B.” | Share acquisition, then separate selection and requested outputs per tract. | Combined inventory with independent results; retain blocked tracts and excluded historical descriptions. |
| Retained review and “Continue with this new scan.” | Read-only `inspect-artifacts` for the requested stage, then earliest invalid dependency. | Resume summary and only requested replacement outputs; preserve earlier runs. |
| Selected calls and “Plot these.” | `plot-metes-and-bounds`. | Return plot artifacts only; no closure verification. |
| Isolated prose and “Plot this description.” | `plot-metes-and-bounds` runs `plot --input-format text`. | Preserve tie-ins outside boundary geometry and unknown bearings; no verification side effect. |
| Supplied GeoJSON or scanned map and “Prepare this for later use.” | `prepare-parcel-overlay`. | Return prepared layer and provenance only. |
| Source material and explicit interactive dashboard/workbench request | `deed-closure-dashboard`; reuse valid acquisition, selection, and calculation handoffs. | Return local dashboard and stage artifacts. |
| Prepared geographically placed evidence and “Show this on a Mapbox basemap.” | `render-online-map` uses the [local viewer](../skills/render-online-map/references/local-viewer.md). | Return local map/display provenance; no dashboard, acquisition, verification, or inferred alignment. |
| Existing online-prepared map and “Show these vectors in chat using Mapbox MCP.” | `render-online-map` uses the [MCP handoff](../skills/render-online-map/references/mapbox-mcp.md). | Prepare exact vector arguments, inspect the connected tool schema, and call only if compatible; retain local raster/source review and report acceptance separately. |
| Several descriptions and “Does this property close?” without a tract selected | `review-metes-and-bounds` identifies candidates. | Ask which boundary to review before calculation. Text review takes one description per run; plain role headings matter only for verified export; see [multiple descriptions](review-limits.md#multiple-descriptions). |

`review-deed` is a manual slash-command alias for deed-specific requests (it is not selected automatically) and applies the same `review-metes-and-bounds` workflow.

Transcription, description extraction, traverse verification, plotting, overlay preparation, online map rendering, and description comparison are capabilities with separate deliverables. Stop after the requested capability; do not continue automatically to another stage. If a later stage is requested, reuse valid handoff artifacts for unchanged sources, conditionally using read-only `inspect-artifacts` when freshness or dependencies are unclear. Dashboard discovery is limited to explicit interactive dashboard/workbench requests; a request for a plot alone uses the plot capability. A two-description comparison uses `compare-descriptions` after the intended versions have been identified.

## Examples of composition

- **Document to closure review:** `review-metes-and-bounds` uses `convert-document-to-text` when needed, passes its full text and page map to `extract-metes-and-bounds`, then runs deterministic review. Carry acquisition and selection records forward; do not repeat valid stages.
- **Document to plot:** native conversion when needed → verbatim selection with source coverage → `plot --input-format text` on the selected file. Preserve rejected/unresolved material and separate tracts; the plot is local unless independent placement evidence is supplied.
- **Selected boundary to plot:** pass identified structured calls to `plot-metes-and-bounds`. For isolated prose, use explicit `--input-format text`; shared preparation handles commencement-to-POB tie-ins without canonical verification. A plot's `needs_review` status is not a verification result.
- **Prepared evidence to online map:** `render-online-map` uses `compose-map PLOT_DIR --layer PREPARED_LAYER.json --output-dir NEW_DIR` through the packaged launcher to retain intact plot/map inputs and fresh geometry hashes. Rendering still requires supplied geographic evidence for deed placement. It does not create a dashboard solely to render a map.
- **Prepared evidence to dashboard:** if a dashboard is explicitly requested, use `compose-dashboard BASE_BUNDLE.json --layer PREPARED_LAYER.json --output-dir NEW_DIR` through the same launcher. The base bundle must already contain actual source/page/call records. Composition retains source inputs, appends supported map arrays, and recomputes geometry; it does not infer deed alignment or attest source reading. Both composition commands return `needs_review` (exit 1), distinct from canonical verification.

The full accepted handoffs, status meanings, and invalidation rules are in [artifact handoffs](artifact-handoffs.md); see the [dashboard bundle reference](../skills/deed-closure-dashboard/references/dashboard-bundle.md#compose-existing-plot-and-map-artifacts) for the checked composition procedure.

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

## Runtime prerequisites

The Python launcher requires Python 3.11+ and `uv`; check `python3 --version` and `uv --version` before first use. Use an extracted plugin distribution: the source plugin directory does not contain its built runtime. First use provisions the locked runtime in the user's cache and needs access to pinned dependencies unless already cached. Report missing prerequisites without claiming an engine run. Optional geo/web-map operations require the appropriate distribution described in their capability references.

## Run the selected text directly

Run from the intended project root:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" review description-tract-a.txt --output-dir reviews/tract-a-new
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" verify calls.csv --output-dir reviews/calls-new
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" analyze-relative angles.json --output-dir reviews/angles-new
```

These commands accept prepared descriptions or identified call sets; they do not locate a description inside a PDF or arbitrary whole document. Output directories must be new. A configured output base can supply a fresh child when `--output-dir` is omitted. See [project settings](plugin-settings.md) for `.claude/metesparser.local.md`, CLI precedence, and per-run reload behavior.

For straight descriptions defined by relative angles, `analyze-relative` accepts a [source-linked JSON constraint description](relative-analysis.md). It calculates local geometry separately from canonical verification and always retains `needs_review` (exit 1) for valid inputs, including successful analysis. It preserves unknown recorded bearings and produces no verified CSV. Check `analysis.status` for `analyzed`, `unresolved`, or `inconsistent`.

## Intake, controls and resuming

Return the [compact intake and coverage accounting](source-preparation.md#intake-and-source-coverage) for a document task. For an explicitly requested dashboard, provide the [current controls guide](../skills/deed-closure-dashboard/references/playbook.md#current-controls-and-delivery). For a later continuation, use the [inspector and resume summary](artifact-handoffs.md#artifact-inspection-and-resume), reusing unchanged independent tracts and map registrations. Guided scan registration and separate deed placement use the [existing overlay procedure](../skills/prepare-parcel-overlay/references/overlay-preparation.md#guided-registration-and-separate-deed-placement).

## Interpret the result

Statuses and exit codes are listed in [review limits](review-limits.md#status-and-exit-codes). A multi-description deed without plain role headings is blocked from verified export; see [multiple descriptions](review-limits.md#multiple-descriptions). The selected source and any uncertainty remain part of the result, even when geometry closes.

For a processing error, inspect the diagnostic, correct supported configuration or source-grounded input formatting, and rerun in a fresh directory. For `needs_review`, retain the issue and consult the source; do not change a recorded value merely to obtain a passing result.

Missing exhibits, material illegibility, or unresolved tract selection must be resolved before issuing a verified result. Never infer a missing bearing or omit an exception to make a traverse close. Intersection checks cover straight segments and circular arcs; unsupported or incomplete curve geometry requires review. See [review scope](review-limits.md).

## Documentation and changes

Each skill directory has a human-facing `README.md` for examples and inputs/outputs, and `SKILL.md` for Claude's instructions. Keep detailed shared guidance in linked references. Record user-visible changes once in the [plugin changelog](../CHANGELOG.md); use the repository changelog for project-level announcements.

## Requested Mapbox companion

For a request to view prepared deed and map evidence over Mapbox, use [render-online-map](../skills/render-online-map/SKILL.md). Reuse valid reading/selection/import/registration outputs and validate geometry/placement bindings. The dashboard workflow assembles a source-grounded dashboard only when that deliverable is also requested, then delegates rendering. Follow the [online handoff](artifact-handoffs.md#optional-online-map-handoff) and [local viewer procedure](../skills/render-online-map/references/local-viewer.md). The ordinary dashboard remains offline. Local provider access starts only when the user clicks Connect; unavailable georeference/provider access never authorizes guessed placement or status promotion.

For a requested in-chat MCP preview, follow the [MCP procedure](../skills/render-online-map/references/mapbox-mcp.md). This vector-only option uses a configured Mapbox MCP connection and its authentication, rather than the local page's Connect field. It sends prepared geometry, opaque IDs, and provenance to that server only within the requested external-preview scope. Raster overlays and source-page review stay in the existing local views. Missing tools, incompatible schemas, or oversized arguments leave a reviewable local handoff and must not be reported as a successful interactive preview.
