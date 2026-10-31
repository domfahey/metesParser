# Relative-angle analysis

Commands below use the plugin root that the invoking skill printed; substitute it for `${CLAUDE_PLUGIN_ROOT}`.

Use this deterministic analysis when straight courses have relative angles but lack recorded compass bearings. Prepare the input after reviewing the source; the module does not transcribe documents or infer angles from prose. Canonical review and its export gate remain separate.

## Run a reproducible example

The [synthetic rectangle](../skills/deed-closure-dashboard/references/relative-rectangle.json) describes a clockwise 100 × 50 ft rectangle with four stated 90° interior angles. Its expected perimeter is 300 ft, area 5,000 sq ft, and gap zero within floating-point precision. It contains no property records.

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" analyze-relative "${CLAUDE_PLUGIN_ROOT}/skills/deed-closure-dashboard/references/relative-rectangle.json" --output-dir relative-demo
```

For repository development, use `uv run metes-review analyze-relative INPUT.json --output-dir NEW_DIRECTORY`.

```python
from pathlib import Path
from mp_models import RelativeDescription
from mp_verify import analyze_relative

description = RelativeDescription.model_validate_json(Path("INPUT.json").read_bytes())
analysis = analyze_relative(description)
print(analysis.model_dump_json(indent=2))
```

The same types and function are available through `metesparser.relative`. Input models are immutable. `recorded_bearing_azimuth_deg_from_north` remains `None` when absent; the solver puts computed values in separate `local_azimuth_deg` fields.

## Input contract, version 1.0

Supply one ordered boundary ring, with at least three straight courses. Distances and coordinates are in feet; angles are numeric decimal degrees. Convert DMS explicitly after checking its minutes and seconds; do not pass packed DMS, text, nonfinite values, or booleans as numbers.

| Field | Required content |
| --- | --- |
| `schema_version` | `"1.0"` |
| `frame` | `name`, `first_azimuth_deg`, `origin: [x, y]`, and `orientation: "cw"` or `"ccw"`. The first azimuth is clockwise from an arbitrary local positive-y axis. Name its basis; it is not recorded north. |
| `courses` | Ordered objects with unique `course_id`, positive `distance_ft`, and `source`. An optional `recorded_bearing_azimuth_deg_from_north` preserves an existing source value but does not establish alignment or constrain this local-only solver. |
| `constraints` | Objects with unique `constraint_id`, `kind`, `from_course`, `to_course`, and `source`, plus the interpretation fields below. References must name existing courses. |
| Every `source` | Nonblank `reference` and verbatim `quote`. Include document, page, occurrence, and course/corner identity in the reference. Whitespace in source text is preserved. |
| Optional constraint `interpretation` | Explain a chosen turn, inferred relationship, or exterior convention separately from the original quotation. |

Unknown fields and malformed geometry fail validation. No curves, disconnected tracts, tie calls, or exceptions may be silently flattened into this ring. Analyze each selected boundary separately.

| Constraint `kind` | Additional fields and meaning |
| --- | --- |
| `interior` | `angle_deg` between 0 and 360, exclusive; `from_course` is the incoming leg and `to_course` the immediately following outgoing leg. Orientation determines the signed turn. Reflex angles exceed 180°. |
| `exterior` | `angle_deg` and `exterior_convention: "interior_complement"` explicitly authorize the conversion to interior `360 − angle_deg`. Missing convention is unresolved. Exterior deflection angles need a separately justified conversion, not this convention. |
| `perpendicular` | `turn: "left"` or `"right"` specifies the signed 90° rotation from the referenced course's forward heading to the target course's forward heading. Missing turn is unresolved. |
| `parallel` | `parallel_direction: "same"` or `"opposite"` specifies a 0° or 180° heading difference. Missing direction is unresolved. Parallel headings alone do not assert collinearity or shared endpoints. |

Interior/exterior constraints apply only to consecutive courses, including the closing last-to-first pair. Perpendicular/parallel constraints may reference nonadjacent courses. Their references are directed travel headings, not undirected infinite lines. A closing constraint checks the heading at the POB; it does not force positional closure. Missing closing-angle evidence must stay absent.

`frame.orientation` supplies the sign convention for interior/exterior angles and the computed closing angle. Explicit perpendicular turns and parallel directions determine their own heading differences; the module does not independently certify the ring's winding. For a complete stated interior/exterior ring, an angle sum different from `(n − 2) × 180°` is contradictory even when its headings agree modulo 360°.

Angular consistency uses a fixed `1e-8` degree arithmetic tolerance, not a survey tolerance. Translated points must retain offsets and course vectors within the smaller of `1e-6` ft and one part per million of the shortest course. Unrepresentable geometry returns `numerical_range` with no points or area; reduce the arbitrary origin rather than silently publishing collapsed coordinates.

## Read the result

The CLI's top-level `status` is always `needs_review` (exit 1) for valid descriptions. `error` (exit 2) means malformed input, settings, or an I/O failure. The separate `analysis.status` means:

- `analyzed`: every course heading is determined and the supplied constraints are consistent. The positional gap may still be large. This does not assert a valid surveyed boundary or run the canonical eight checks.
- `unresolved`: a turn, angle, convention, or connection to the first-course axis is missing. Issues identify the affected course/constraint; geometry is withheld.
- `inconsistent`: constraints contradict one another. Geometry is withheld; recheck the source without selecting whichever reading closes better.

Every result carries `method: "local_angle_analysis"`, `engine_verified: false`, and `verified_export_eligible: false`. Results include the original description and source evidence. The output directory contains `source.json`, `analysis.json`, `audit.json`, and an escaped `review.html`; no verified CSV is produced. Input hashing identifies the exact JSON analyzed, not an independently verified original deed image.

For analyzed geometry, report local points, local headings and deltas, perimeter, gap components/magnitude, and provisional area. `area_basis: "implicit_closing_segment"` discloses how open endpoints are treated. `stated_angle_sum_deg` requires a complete ring of explicit interior/exterior angle constraints, including the closing angle; it remains unavailable when angles are missing or only implied by parallel/perpendicular relationships. Compare it with `expected_angle_sum_deg` only with those qualifications.

Rotation and translation change coordinates, not closure magnitude or area. Do not mix unrotated deltas with rotated bearings. Local analysis does not resolve geographic alignment, source legibility, self-intersections, title priority, or survey accuracy. Retain canonical verification and its source-review limitations alongside these results.
