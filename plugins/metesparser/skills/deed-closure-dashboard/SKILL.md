---
name: deed-closure-dashboard
description: This skill should be used when the user asks to "build a deed closure dashboard", "compare descriptions across the chain of title", "make an interactive closure workbench", or follow the "deed-closure-dashboard playbook". Builds an evidence-backed dashboard for deeds or other documents; use review-metes-and-bounds for a closure check without a dashboard.
metadata:
  version: "0.3.0"
---

# Deed closure dashboard

Read the [dashboard playbook](references/playbook.md) before building. Use its six sections as the review goals: record findings, disputed-figure evidence, interactive workbench, recorded descriptions and extracted courses, complete source-page copies, and method/limits/sources. Apply the workflow to any supplied document set, not only deeds. The bundled renderer covers per-occurrence findings, evidence, records/courses, source pages, and method notes; it does not implement shared parcel alignment or comparison. Report that limitation instead of implying those views were produced.

For the validated offline renderer, prepare the version 1.0 bundle described in [dashboard-bundle.md](references/dashboard-bundle.md), then run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" dashboard bundle.json --output-dir dashboard-new --cache-dir dashboard-cache` (or `uv run metes-review dashboard ...` in the development workspace). Native source reading and description selection remain prior, separate stages. The renderer accepts supplied JSON; it does not read PDFs or create a source-review log.

For optional reports, overlays, redlines, timelines, drafts, and review logs, consult [patterns from the supplied dashboard example](references/example-patterns.md). The HTML is a design example, not a dataset or runtime to reproduce.

## Coordinate bounded subagents

Use subagents for dashboard creation when the host supports them. Assign explicit file ownership and a shared data contract before parallel work. Avoid concurrent edits to the same source records or HTML file:

- Assign document indexing and evidence preparation by source document. Use a smaller model only when it supports the required native document/image reading and the scans are sufficiently clear. Escalate unreadable digits, ambiguous wording, missing pages, and conflicting descriptions to the coordinating agent or a stronger capable model.
- Assign a calculation worker the selected source-linked calls and explicit assumptions. Prefer a smaller capable model for bounded deterministic implementation and test execution; retain stronger review for angle interpretation, coordinate alignment, and numerical disagreements.
- Assign an interface worker the agreed record/scenario schema and Python reference results. Prefer integration and QA of the reusable renderer over reimplementing its HTML/CSS/JS and SVG; use a smaller capable model for bounded integration work when suitable.
- Assign independent QA to check calculations, record/scenario isolation, evidence coverage, copy controls, viewer navigation, and responsive light/dark layouts. Give raw source data and acceptance criteria rather than another agent's conclusions. Escalate discrepancies instead of editing figures to make results agree.

Keep final source interpretation and integration with the coordinating agent. Pass only relevant source excerpts and artifacts to each worker to avoid repeatedly converting all PDFs. Record the actual models and checks used when available; do not claim a cheaper model, delegation, or client test was used if it was not. If subagents or model selection are unavailable, follow the same stages sequentially and disclose the limitation.

## Prepare the source and calculations

Locate every description before calculating. Use [native text preparation](../convert-document-to-text/SKILL.md) and [description selection](../extract-metes-and-bounds/SKILL.md); inspect every supplied page and repeated description. Render/crop pages for visual evidence with available host tools without substituting an external OCR service for Claude's native reading. Preserve an untouched transcript; store any line-joining or dehyphenation as a separate, traceable display copy.

Run [deterministic review](../review-metes-and-bounds/SKILL.md) on each selected description. Keep engine status and artifacts. For angle-only records, preserve unknown recorded bearings and the engine's `needs_review` result. Use the [relative-angle JSON contract and `analyze-relative` command](references/relative-analysis.md) for reproducible local geometry; label inferred angles, turn choices, alignment, and direction checks as assumptions. Preserve unresolved/conflicting constraints without selecting a reading because it closes. Never copy arbitrary local headings into recorded bearing fields or issue an engine-verified CSV from dashboard calculations.

Treat matching angle sums as a consistency check, not proof that every angle is correct or that only distances can be wrong. Treat older versions, survey evidence, alternate digits, and closing versions as comparisons rather than automatic corrections or declarations of authority. Keep each description occurrence identifiable, including repeated copies within one instrument.

## Build, validate, and deliver

Freeze source-derived record data and make a separate editable working copy. Calculate findings cards solely from the record baseline, with ambiguous readings labeled conditional or unclear. Isolate each counterfactual and reset to its own record version; workbench edits must never alter record findings, transcripts, crops, or engine status.

Use the validated `dashboard` command to render the source bundle and its deterministic calculation stages. Keep source-derived record data immutable and scenario edits isolated. Inspect the generated HTML and JSON artifacts against the bundle, and do not silently omit missing evidence or invent assets. The browser workbench is advisory; its straight-course scenario edits do not alter record findings or engine status. The canonical baseline can process supported curves, but curve edits are not supported by the browser scenario calculator. Do not present a dashboard as verified CSV.

Deliver the local HTML and stage JSON artifacts. Do not publish or share them unless requested and the host's actual sharing controls are available. Identify tax-ID pages before any requested sharing and verify privacy rather than promising an Artifact is private by default. Report untested native-reading, browser, or publishing steps explicitly. No dashboard color band, scenario result, or successful closure constitutes a survey, title opinion, or boundary certification.
