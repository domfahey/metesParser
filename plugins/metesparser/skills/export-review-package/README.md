# Export a review package

Use [export-review-package](SKILL.md) to freeze an identified published revision into requested SVG/PDF/DXF/geographic GeoJSON and audit sidecars. It retains selected layer membership and coordinate/presentation policies without canonical verification.

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" export-review BUNDLE.json --revision-dir REVISION_DIR --request REQUEST.json --output-dir NEW_DIR
```

The [request schema](references/request.schema.json), [synthetic request](references/example.json), [matching bundle](references/bundle-example.json) and [revision definition](references/revision-example.json) illustrate the contract. A revision JSON must be published by the revision store before delivery; copying it into a folder does not establish publication. For executable synthetic inputs, use `scripts/skill_evals.py materialize export-published-revision-package` from a source checkout with separate candidate/evaluator directories.

Check the final manifest and format omissions. An unresolved current draft, stale placement or unsupported required appearance blocks output. Raster/label omissions in CAD/GIS stay explicit; geographic coordinates require supplied evidence. No HTML or verified CSV is promised.

`calls.json` contains the actual selected drawing inputs. `revision-calls.json` is separately labeled `selected_revision_evidence`, with the drawing geometry mode and revision ID/generation. It retains alternative values, raw drafts and original source records for context; when recorded geometry is requested, those hypothetical values do not replace the drawing inputs.
