# Plot a supplied PLSS reference

Use [plot-plss-reference](SKILL.md) to derive a requested rectangular aliquot from an identified supplied section dataset. It never manufactures a nominal section from township/range/section wording.

The [synthetic request](references/example.json) contains actual invented reference bytes, named corners and projected units; the [generated schema](references/request.schema.json) is authoritative for structure.

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" derive-plss REQUEST.json --output-dir NEW_DIR
```

Computed output includes `prepared-layer.json` for later map composition, plus retained request/result and provenance hashes. It does not create an HTML viewer or establish legal subdivision. Missing references and unsupported subdivision evidence stay explicit; map placement and deed verification remain separate.

Completed schema-valid analyses return `needs_review` (exit 1), including `unsupported` results. Malformed requests, duplicate or ambiguous dataset section/reference identities, and invalid output paths return `error` (exit 2); they are not completed unsupported analyses.
