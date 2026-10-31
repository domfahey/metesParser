---
name: plot-plss-reference
description: Derives computed aliquot reference geometry (for example the SE 1/4 of the NW 1/4) from a supplied, identified PLSS section dataset with named corners, projected CRS/units and a supported rectangular division rule. Use when the user asks to plot or compute a quarter section, "SE 1/4", a township and range reference, an aliquot or a PLSS reference. Not for plotting metes-and-bounds calls (plot-metes-and-bounds), a basemap view (render-online-map), or locating a section from a township/range recital alone.
metadata:
  version: "0.1.0"
---

# Plot a supplied PLSS reference

Plugin root: `${CLAUDE_PLUGIN_ROOT}`. Use this capability when a requested aliquot can be computed from supplied, identified reference geometry. A township/range/section recital alone is insufficient. Identify the missing dataset, exact principal meridian/section reference, corner coordinates, CRS, units or division rule; do not invent a nominal 640-acre section or silently fetch a substitute. Native reading and [description selection](../extract-metes-and-bounds/SKILL.md) can preserve PLSS wording while geometry remains unavailable.

Use a runtime with the geographic CRS dependencies available; disclose an unavailable runtime rather than guessing coordinates. Read [runtime prerequisites](../../references/usage.md#runtime-prerequisites), the generated [`PLSSDerivationRequest` schema](references/request.schema.json) and [synthetic complete example](references/example.json). Retain dataset/version/authority citation, exact section identity, selected dataset/reference IDs, source hash and available bytes, dates or explicit unknowns, named SW/SE/NE/NW corners and source IDs. Coordinates require an explicit projected grid CRS and compatible known units. Never infer the meridian, datum, foot definition, location or corner authority from a name or direction word.

The supported `rectangular_aliquot_v1` rule divides the supplied named SW→SE and SW→NW axes into equal fractions. Preserve aliquot step order: `SE4`, then `NW4` means the northwest quarter **of** the southeast quarter. The engine supports consistently ordered rectangles, including rotated rectangles. Schema-valid requests for irregular sections, excess/deficiency, government lots, inconsistent/missing corners, absent or mismatched selected references, or incompatible CRS/units return `unsupported`. Duplicate or ambiguous dataset section/reference identities are malformed input and return `error`, not a completed unsupported analysis. No nominal dimensions or alternate division method is substituted.

Copy this checklist and tick each prerequisite before running:

```
- [ ] Identified section dataset supplied (citation, version, authority, selected section/reference ID)
- [ ] Named SW/SE/NE/NW corners with source IDs
- [ ] Explicit projected CRS with known units
- [ ] Supported division rule (`rectangular_aliquot_v1`) and aliquot step order
```

If any item is missing, request that evidence from the user and retry; do not substitute a nominal section, fetch a dataset, or guess a CRS. Then run:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" derive-plss REQUEST.json --output-dir NEW_DIR
```

The source-checkout command is `uv run metes-review derive-plss REQUEST.json --output-dir NEW_DIR`; the adapter is `mp_review.plss.prepare_plss_file`. Statuses and exit codes follow [status and exit codes](../../references/review-limits.md#status-and-exit-codes) (advisory → `needs_review`); invalid request/schema/output, including duplicate section/reference identities, returns `error`.

Return the actual availability/reason, retained source/dataset/request hashes, rule and order, units, limitations and paths. Output retains exact `request.json`, `plss-result.json` and a manifest published last. A computed result adds `prepared-layer.json`, compatible with existing map composition. This adapter does not itself produce an HTML map. Stop at the prepared reference unless a later view is requested; route provider rendering to [render-online-map](../render-online-map/SKILL.md).

Label the result **computed reference geometry**, not a surveyed legal subdivision, established boundary or verified deed. Supplied source authority/corner accuracy is not independently established by calculation. Reusing the prepared layer does not place an unrelated deed: require separate sourced deed position/orientation and fresh geometry bindings. Preserve identities and explicit unknowns through later workflows under [artifact handoffs](../../references/artifact-handoffs.md).
