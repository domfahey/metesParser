# Deed Closure Dashboard

Build an offline dashboard for source-grounded description review, record-only geometric findings, and clearly separated sensitivity scenarios.

## Example request

> Review the descriptions in this deed packet and prepare a dashboard showing the source pages, transcription uncertainties, record-value closure findings, and an editable scenario workbench. Keep source readings and any hypothetical edits separate.

## Inputs and outputs

**Inputs:** The original deed or survey packet, source-review/selection notes, and a JSON bundle containing source/page records, description occurrences, extracted calls, calculations, and optional scenarios.

**Output:** A self-contained offline HTML dashboard plus JSON snapshots of the source review, deterministic calculations, and stage manifest. The dashboard presents indexed source pages and evidence crops when supplied. It is a review aid; it does not establish source completeness, legal authority, or a survey certification.

## Run the renderer

After completing native source review and preparing a bundle, run from the project root with an unused output directory:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" dashboard bundle.json --output-dir dashboard-new --cache-dir dashboard-cache
```

The equivalent package command is `uv run metes-review dashboard bundle.json --output-dir dashboard-new --cache-dir dashboard-cache`. A valid bundle is reported as `needs_review` (exit 1); inspect its JSON `artifacts`, `errors`, `source_review_complete`, and calculation statuses. Outputs are `source.json`, `dashboard.html`, `source-review.json`, `calculations.json`, `stage-manifest.json`, and `render-manifest.json`. The command does not perform native reading or write the engine's verified CSV.

## Documentation

- [Skill instructions](SKILL.md)
- [Source review and dashboard playbook](references/playbook.md)
- [Bundle schema and stage semantics](references/dashboard-bundle.md)
- [Relative-angle input reference](references/relative-analysis.md)
- [Shared plugin usage](../../references/usage.md)
- [Plugin changelog](../../CHANGELOG.md)
