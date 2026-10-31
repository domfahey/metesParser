---
name: plot-metes-and-bounds
description: Plots the requested tract from a deed, survey, PDF, image, whole document text, isolated description, or structured calls as a standalone display plot, without automatic closure verification or a dashboard. Use when the user asks to plot, draw or sketch a deed or boundary, see what a description looks like, or whether a description can be plotted. Not for closure or verification (use review-metes-and-bounds or verify-traverse), a dashboard (use deed-closure-dashboard), an online map (use render-online-map) or an easement corridor (use plot-corridor).
metadata:
  version: "0.1.0"
---

# Plot metes and bounds

For "Plot the boundary in this deed" or "Can this description be plotted?", work through these steps:

1. Identify the requested tract. Reuse unchanged acquisition and selection artifacts.
2. If the source is an image or PDF without usable text, delegate native document reading to [convert-document-to-text](../convert-document-to-text/SKILL.md). Whole document text needs selection, not a fabricated conversion; never feed a whole document to the text plot command.
3. Delegate selection of the tract to [extract-metes-and-bounds](../extract-metes-and-bounds/SKILL.md) when locating it is part of the task, and ask the user only if tract selection stays ambiguous. Follow the [intake and coverage procedure](../../references/source-preparation.md#intake-and-source-coverage), retaining rejected and unresolved passages even if the surviving calls close.
4. Plot one description per run. The `plot` command rejects several descriptions (error, exit 2), so run it once per tract with separate plot identities; see [multiple descriptions](../../references/review-limits.md#multiple-descriptions) and the [status and exit codes](../../references/review-limits.md#status-and-exit-codes).
5. Treat a plottability question as a request for an assessment: report supported or blocked geometry and missing input, and create a plot only when requested or clearly implied.

Choose the input:

- A matching existing structured call artifact, when the source is unchanged.
- An already-isolated UTF-8 plain-text description with no calls: use `--input-format text`, which must be requested explicitly (`auto` keeps structured-file detection). Shared deterministic preparation normalizes notation, extracts POC/POB, and marks commencement-to-POB calls as tie-ins before preparing display geometry. This is parsing for display, not canonical verification. Unresolved commencement is rejected and needs clarification; incomplete bearings remain unresolved in the plot.
- Never infer bearings from closure or neighboring calls, and preserve the actual source text and available source references.

Check the [runtime prerequisites](../../references/usage.md#runtime-prerequisites), then run from the intended project root with a new output directory:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" plot INPUT --output-dir NEW_DIR --input-format auto
```

`--input-format` accepts `auto`, `calls`, `relative`, `plot`, or `text`. The package command is `uv run metes-review plot INPUT --output-dir NEW_DIR --input-format auto`; the Python entry point is `mp_review.plot_file(INPUT, NEW_DIR, input_format="text")`. Accepted structured data are strict CSV, a calls-list or `LegalDescription` JSON object, `RelativeDescription` JSON, or `PlotRequest` JSON. For PlotRequest fields, see [artifact handoffs](../../references/artifact-handoffs.md) and the authoritative `mp_models`/`mp_review` APIs.

For relative-angle inputs, read the [relative-analysis contract and example](../deed-closure-dashboard/references/relative-analysis.md). Keep computed local headings separate from recorded bearings.

Preserve every source value and verbatim call; leave cardinal-only or otherwise incomplete bearings unresolved. The plot command creates `source.csv`, `source.json`, or `source.txt` as an exact-byte source copy, `plot-input.json`, `plot-geometry.json`, `plot.html`, and `plot-manifest.json`. Text plots retain all parsed calls, including tie-ins, and actual source quotations; geometry excludes tie-ins. If normalization prevents confident matching to an individual verbatim call, the quotation retains the full supplied description. Its top-level status is `needs_review`: the plot is a display deliverable, not verification, and it does not create a verified CSV or claim document reading.

Return the requested plot artifacts and stop. Do not run canonical verification, repeat valid reading/selection, prepare map layers, or build a dashboard unless the user requested those additional tasks. Return the compact intake and source coverage alongside the plot; a partial display cannot establish a complete boundary. See [artifact handoffs](../../references/artifact-handoffs.md) for identity, status, and resume rules.

A later requested online map routes to [render-online-map](../render-online-map/SKILL.md), reusing valid plot inputs, actual source records, and supplied geographic evidence through the [online handoff](../../references/artifact-handoffs.md#optional-online-map-handoff). This standalone plot supplies neither geographic placement nor verified status. Assemble a dashboard only when the user also requests one.
