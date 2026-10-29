---
name: plot-metes-and-bounds
description: Plots the requested boundary from a deed, survey, PDF, image, whole document text, isolated description, or structured calls. Coordinates native conversion and tract selection when needed, then creates a standalone plot without automatic closure verification or a dashboard.
---

# Plot metes and bounds

For “Plot the boundary in this deed” or “Can this description be plotted?”, identify the requested tract first. Reuse unchanged acquisition/selection artifacts; otherwise delegate native document reading to [convert-document-to-text](../convert-document-to-text/SKILL.md) when needed, then selection to [extract-metes-and-bounds](../extract-metes-and-bounds/SKILL.md). Whole document text needs selection, not a fabricated conversion. Do not feed a whole document to the text plot command. For several explicitly identified tracts, use one acquisition and separate candidate/plot identities; ask only when tract selection remains ambiguous. Follow the [intake and coverage procedure](../../references/source-preparation.md#intake-and-source-coverage), retaining rejected and unresolved passages even if the surviving calls close. A plottability question requests an assessment; report supported/blocked geometry and missing input, and create a plot only when requested or clearly implied.

Use a matching existing structured call artifact when the source is unchanged. If the user supplies an already-isolated UTF-8 plain-text description but no calls, use the `plot` command with `--input-format text`. Its shared deterministic preparation normalizes notation, extracts POC/POB, and marks commencement-to-POB calls as tie-ins before preparing display geometry. This is parsing for display; do not run canonical verification as a side effect. Preserve the actual source text and available source references. Never infer bearings from closure or neighboring calls. Multiple tracts or unresolved commencement are rejected and require selection/clarification; incomplete bearings remain unresolved in the plot.

Text input must be requested explicitly; `auto` keeps its structured-file detection. Selection from a whole document belongs to the extraction capability above; invoke it as a prerequisite only when locating the requested tract is part of the plot task.

Check the [runtime prerequisites](../../references/usage.md#runtime-prerequisites), then run from the intended project root with a new output directory:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" plot INPUT --output-dir NEW_DIR --input-format auto
```

`--input-format` accepts `auto`, `calls`, `relative`, `plot`, or explicit `text`. The package command is `uv run metes-review plot INPUT --output-dir NEW_DIR --input-format auto`; use `--input-format text` for an already-isolated description. The Python entry point is `mp_review.plot_file(INPUT, NEW_DIR, input_format="text")`. Accepted structured data are strict CSV, a calls-list or `LegalDescription` JSON object, `RelativeDescription` JSON, or `PlotRequest` JSON. For PlotRequest fields, see [artifact handoffs](../../references/artifact-handoffs.md) and the authoritative `mp_models`/`mp_review` APIs.

For relative-angle inputs, read the [relative-analysis contract and example](../deed-closure-dashboard/references/relative-analysis.md). Keep computed local headings separate from recorded bearings.

Preserve every source value and verbatim call; leave cardinal-only or otherwise incomplete bearings unresolved. The plot command creates `source.csv`, `source.json`, or `source.txt` as an exact-byte source copy, `plot-input.json`, `plot-geometry.json`, `plot.html`, and `plot-manifest.json`. Text plots retain all parsed calls, including tie-ins, and actual source quotations; geometry excludes tie-ins. If normalization prevents confident matching to an individual verbatim call, the quotation retains the full supplied description. Its top-level status is `needs_review`: the plot is a display deliverable, not verification, and it does not create a verified CSV or claim document reading.

Return the requested plot artifacts and stop. Do not run canonical verification, repeat valid reading/selection, prepare map layers, or build a dashboard unless the user requested those additional tasks. Return the compact intake and source coverage alongside the plot; a partial display cannot establish a complete boundary. See [artifact handoffs](../../references/artifact-handoffs.md) for identity, status, and resume rules.

A later requested online map routes to [render-online-map](../render-online-map/SKILL.md), reusing valid plot inputs, actual source records, and supplied geographic evidence through the [online handoff](../../references/artifact-handoffs.md#optional-online-map-handoff). This standalone plot supplies neither geographic placement nor verified status. Assemble a dashboard only when the user also requests one.
