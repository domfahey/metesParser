# Plot a corridor

Use [plot-corridor](SKILL.md) for an explicitly described easement or right-of-way ribbon. It preserves centerline line/arc calls, source references, ordered endpoint widths, step/taper rules, joins and caps; it produces advisory geometry within a declared error budget.

Copy the [synthetic request](references/example.json) to a new local file for a software example:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" analyze-corridor REQUEST.json --output-dir NEW_DIR
```

The [generated schema](references/request.schema.json) comes from `mp_models.corridor.CorridorRequest`. Replace example values only with supported source evidence. An unsupported result remains `needs_review` and has no complete polygon. On success, retain `boundary_origin_in_centerline_frame` when reusing the normalized boundary plot. Neither a corridor polygon nor its closed drawing verifies the open centerline as a parcel.
