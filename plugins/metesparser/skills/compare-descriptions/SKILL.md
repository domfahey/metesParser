---
name: compare-descriptions
description: Compares two identified metes-and-bounds descriptions and reports, call by call, how their calls and geometry differ, as advisory output that never establishes a boundary. Use when the user asks how two legal descriptions differ, for a redline, or to compare these descriptions, an old deed against a new one, or a deed against a survey. Not for locating a description inside a document (use extract-metes-and-bounds), a single closure check (use review-metes-and-bounds) or a dashboard (use deed-closure-dashboard).
metadata:
  version: "0.1.0"
---

# Compare descriptions

Use this capability only when two intended descriptions or versions have been identified. If either description is inside a document and the intended tract or occurrence is unclear, route through [Extract Metes and Bounds](../extract-metes-and-bounds/SKILL.md) first. Do not compare an entire deed or silently pair the first matching-looking section.

Start from the [synthetic complete request](references/comparison-example.json). The [`ComparisonRequest` JSON schema](references/comparison-request.schema.json) is large (about 1,200 lines); consult it only for specific field definitions, for example with `grep` or `jq`, rather than reading it through. It is generated from `mp_models.comparison.ComparisonRequest`, and the packaged runtime also enforces cross-field identities and geometric rules. Supply separate left/right `PlotRequest` values with stable call IDs, source references, exact quotations, and occurrence identity where available; retain verbatim text. Add explicit call pairs only when the correspondence is supplied or otherwise unambiguous. Structural anchors, changed/unmatched calls, reordering, and split/merge candidates remain tentative; repeated motifs can be ambiguous.

Bearing basis, linear units, tolerances, and any right-to-left rigid transform require actual supporting source references. Never equate matching basis labels with matching bearing frames, infer a unit/foot definition, fit one description to the other, or invent a tolerance. A documented unknown basis may still permit structural text differences, while bearing/position comparisons remain `not_comparable` or `unavailable` with reasons. Curves and relative-description requests are unsupported for geometric comparison; preserve them as source evidence and report the limitation. See [comparison limits](../../references/comparison-limits.md).

Run the prepared request into a new directory:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" compare-descriptions REQUEST.json --output-dir NEW_DIR
```

The package command is `uv run metes-review compare-descriptions REQUEST.json --output-dir NEW_DIR`; the Python API is `mp_review.comparison.compare_descriptions_file(REQUEST, NEW_DIR)`. A completed operation returns `needs_review` and exit 1; invalid input or an existing output directory returns `error` and exit 2. It retains exact request bytes as `comparison-request.json`, the deterministic `comparison.json`, and `comparison-manifest.json` with request/result/input hashes and algorithm version.

Report component outcomes, structural differences, reasons, limitations, and artifact paths. Agreement is limited to supplied criteria and does not establish the same physical or legal boundary. The comparison cannot revise canonical verification, promote a tentative correspondence, or authorize verified CSV export. Stop after the requested comparison; build a dashboard only if separately requested.
