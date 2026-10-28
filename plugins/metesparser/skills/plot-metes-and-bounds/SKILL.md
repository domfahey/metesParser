---
name: plot-metes-and-bounds
description: Creates a standalone plot from supplied structured calls or an already-isolated description when the user asks to plot a metes-and-bounds traverse. Does not select text from documents, verify closure, or build a dashboard.
---

# Plot metes and bounds

Use a matching existing structured call artifact when the source is unchanged. If the user supplies an already-isolated plain-text description but no calls, use the rule-based `mp_parse.extract_calls()` API (and `enrich_calls_with_azimuths()` for supported bearing conversions) only to prepare structured plot input. This is parsing for display; do not run canonical verification as a side effect. Preserve the actual source text and available source references. Never infer bearings from closure or neighboring calls. If the parser returns multiple tracts, the intended tract is ambiguous, or a call cannot be interpreted safely, ask for tract selection/clarification or leave the affected geometry unresolved.

The standalone `plot` CLI accepts structured files only. This skill does not select a description from a whole document: use an existing selection handoff, or invoke description extraction only when locating the requested tract is part of the task.

Check the [runtime prerequisites](../../references/usage.md#runtime-prerequisites), then run from the intended project root with a new output directory:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" plot INPUT --output-dir NEW_DIR --input-format auto
```

`--input-format` accepts `auto`, `calls`, `relative`, or `plot`. The package command is `uv run metes-review plot INPUT --output-dir NEW_DIR --input-format auto`. Accepted data are strict CSV, a calls-list or `LegalDescription` JSON object, `RelativeDescription` JSON, or `PlotRequest` JSON. For PlotRequest fields, see [artifact handoffs](../../references/artifact-handoffs.md) and the authoritative `mp_models`/`mp_review` APIs.

For relative-angle inputs, read the [relative-analysis contract and example](../deed-closure-dashboard/references/relative-analysis.md). Keep computed local headings separate from recorded bearings.

Preserve every source value and verbatim call; leave cardinal-only or otherwise incomplete bearings unresolved. The plot command creates `source.csv` or `source.json` as an exact-byte source copy, `plot-input.json`, `plot-geometry.json`, `plot.html`, and `plot-manifest.json`. Its top-level status is `needs_review`: the plot is a display deliverable, not verification, and it does not create a verified CSV or claim document reading.

Return the requested plot artifacts and stop. Do not run canonical verification, reread a PDF, select a description, prepare map layers, or build a dashboard unless the user requested those additional tasks. See [artifact handoffs](../../references/artifact-handoffs.md) for identity, status, and resume rules.

A later requested online map routes to [render-online-map](../render-online-map/SKILL.md), reusing valid plot inputs, actual source records, and supplied geographic evidence through the [online handoff](../../references/artifact-handoffs.md#optional-online-map-handoff). This standalone plot supplies neither geographic placement nor verified status. Assemble a dashboard only when the user also requests one.
