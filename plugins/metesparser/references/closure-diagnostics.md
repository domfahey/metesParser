# Closure diagnosis

Commands below use the plugin root that the invoking skill printed; substitute it for `${CLAUDE_PLUGIN_ROOT}`.

Use diagnosis when the user asks which recorded line or supported circular arc may explain a closure residual, or when a failed check needs a sensitivity explanation. It analyzes an existing identity-bound `ClosureDiagnosticRequest`; it does not reread a document, choose source values, amend calls, rerun canonical verification, or authorize verified export.

The packaged [request JSON schema](closure-diagnostics/request.schema.json) is generated from `mp_models.diagnostics.ClosureDiagnosticRequest`; the runtime additionally enforces cross-field identities and supported geometry. The [synthetic request fixture](closure-diagnostics/request.json) shows a complete request. It binds the ordered canonical calls and source references with `input_sha256`; `frame` explicitly declares recorded bearings, feet, and the foot definition (`international_ft`, `us_survey_ft`, or `unknown_ft`). Keep call IDs, source quotes, occurrences, pages, and uncertainties attached. Unknown source identity fields stay null. Optional precision assumptions require explicit nearest-rounding increments and evidence; do not guess them.

Run the request into a new directory:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" diagnose-closure REQUEST.json --output-dir NEW_DIR
```

The package equivalent is `uv run metes-review diagnose-closure REQUEST.json --output-dir NEW_DIR`. A completed result is `needs_review` (exit 1), whether diagnosis is `supported`, `incomplete`, or `unsupported`; invalid input or an existing output directory is `error` (exit 2). Output contains exact request bytes as `request.json`, `diagnostics.json`, and `diagnostics-manifest.json`. Report `availability`, residual, sensitivities, exclusions, limitations, and optional conservative quantization bound as returned. Sensitivity ranks identify mathematical influence under the recorded geometry, not likely error or a correction recommendation. A quantization bound is deterministic, not an error probability or confidence score.

Standalone diagnosis supports complete straight and supported circular boundaries, including semicircles and major arcs below a full turn. Marked tie-ins are excluded and listed. Conflicting redundant measurements or orientation evidence are rejected. Full/multi-revolution arcs, spirals, ambiguous radial conventions, meanders, exceptions and indefinite/missing geometry remain incomplete/unsupported. Curve sensitivities use radius, sweep and starting tangent as independent parameters with explicit fixed constraints; their units/ranks are separate from line distance/bearing sensitivities. Straight-call quantization assumptions cannot establish a curve error bound. No case changes canonical check results or `verified_export_eligible=false`.

Recompute a retained result if its stored `algorithm_version` differs from the one in a freshly produced result. Browser scenario diagnosis currently handles complete straight boundaries, while recorded results and the standalone engine support the stated arcs.

The dashboard may show a separate diagnosis panel when the source bundle provides supported inputs; scenario diagnosis is recomputed independently from the unchanged baseline. Its `diagnostic_request_from_dashboard` adapter returns the same public request contract used by the standalone command, so identical requests use the same deterministic engine. Candidate selection reuses the matching call's source page/crop/occurrence controls. Reset and presentation controls do not write files or alter the recorded calls, placement, or canonical result. Use standalone diagnosis for a requested report/file; a dashboard request remains a separate deliverable. See [artifact handoffs](artifact-handoffs.md) for status boundaries.
