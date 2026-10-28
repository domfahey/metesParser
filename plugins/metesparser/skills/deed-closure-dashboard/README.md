# Deed Closure Dashboard

Build an offline dashboard for source-grounded description review, record-only geometric findings, and clearly separated sensitivity scenarios.

## Example request

> Review the descriptions in this deed packet and prepare a dashboard showing the source pages, transcription uncertainties, record-value closure findings, and an editable scenario workbench. Keep source readings and any hypothetical edits separate.

## Inputs and outputs

**Inputs:** A request for an interactive dashboard plus the source packet and/or valid source-review/selection records and JSON bundle. Reuse records that match the unchanged source.

**Output:** A self-contained offline HTML dashboard plus JSON snapshots of the source review, deterministic calculations, and stage manifest. The dashboard presents indexed source pages and evidence crops when supplied. It is a review aid; it does not establish source completeness, legal authority, or a survey certification.

## Run the renderer

After completing native source review and preparing a bundle, run from the project root with an unused output directory:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" dashboard bundle.json --output-dir dashboard-new --cache-dir dashboard-cache
```

The equivalent package command is `uv run metes-review dashboard bundle.json --output-dir dashboard-new --cache-dir dashboard-cache`. A valid bundle is reported as `needs_review` (exit 1); inspect its JSON `artifacts`, `errors`, `source_review_complete`, and calculation statuses. Outputs are `source.json`, `dashboard.html`, `source-review.json`, `calculations.json`, `stage-manifest.json`, and `render-manifest.json`. The command does not perform native reading or write the engine's verified CSV. Explicit placements and named-point comparisons are supported; automatic matching is not.

## Documentation

- [Skill instructions](SKILL.md)
- [Source review and dashboard playbook](references/playbook.md)
- [Bundle schema and stage semantics](references/dashboard-bundle.md)
- [Relative-angle input reference](references/relative-analysis.md)
- [Plot and placement reference](references/plot-and-overlays.md)
- [Artifact handoffs](../../references/artifact-handoffs.md)
- [Prepare parcel overlay](../prepare-parcel-overlay/SKILL.md)
- [Shared plugin usage](../../references/usage.md)
- [Plugin changelog](../../CHANGELOG.md)

## Optional online view

When requested alongside the dashboard, delegate the Mapbox view to [render-online-map](../render-online-map/README.md) after assembling source-linked geometry and explicit placement evidence. The dashboard owns source composition; the renderer owns the local viewer or requested in-chat MCP preview. Keep the offline dashboard and report geographic availability separately from source review and verification.
