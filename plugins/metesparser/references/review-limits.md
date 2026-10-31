# Review scope and output

The bundled review engine accepts selected text and structured data; it does not inspect PDF page images or perform OCR. The plugin uses Claude's native document/image reading to prepare text from images and PDFs, then locates the intended metes-and-bounds description before deterministic review. No separate OCR provider or conversion dependency is added. If native reading cannot access a source, disclose that limitation and request an accessible source.

The engine parses and checks only the conditions implemented by its deterministic rules. A `checks_passed` status is not a legal opinion, title determination, survey, boundary certification, or guarantee that source wording was interpreted correctly. Human review remains necessary for ambiguous or incomplete descriptions and for topology or monument questions not represented in the input.

Bearings that contain only cardinal wording remain unknown. Do not infer a numeric azimuth, fill missing calls, or treat a closure adjustment as a source fact. Keep the distinction between verbatim deed language and parser-derived fields clear.

Boundary intersection checks include straight segments and circular arcs, using actual finite arc sweeps rather than chords. Crossings, overlaps, and nonadjacent touches block verification; legitimate shared endpoints of neighboring courses are allowed. Unknown or inconsistent circular geometry and unsupported spiral curves produce warnings and require review. These planar checks do not establish source completeness, ownership, or the correctness of a supplied coordinate system.

## Multiple descriptions

Each description in a deed becomes a tract with a role: main (parcel), addition, exception, or easement. Verified export of a multi-description deed requires every tract's role to come from an explicit plain heading such as `PARCEL ONE:` or `TRACT 2:`. A role inferred from wording blocks verified export for every tract in that deed. Easement and exception tracts are never eligible for verified export. An ordinary single description is not affected, but one introduced by grant, exception or reservation wording (other than rights-only reservations such as mineral rights) is treated as an inferred role and blocked.

Text review accepts one description per review. A text that contains several descriptions, whether or not they are headed, returns `error` (exit 2); plain headings do not lift this rule. Ask the user which tract to review, or have them supply one description per run.

## Verified-export eligibility

`checks_passed` is not verified-export eligibility. Eligibility additionally requires closure below 0.01 ft, no warnings, and an eligible tract role (never easement or exception; in a multi-description deed, roles from explicit headings). Source review status is a separate assessment that eligibility does not establish.

## Status and exit codes

| Status | Exit code | Meaning |
| --- | --- | --- |
| `checks_passed` | 0 | Implemented deterministic checks passed. Not a legal opinion or source-accuracy finding. |
| `needs_review` | 1 | Completed result with unresolved checks or review items. |
| `error` | 2 | Invalid input or configuration, or no result. |

Advisory and derived-view commands (plot, map composition and rendering, `validate-source`, `inspect-artifacts`, `diagnose-closure`, `compare-descriptions`, `analyze-relative`, `derive-plss`) return `needs_review` (exit 1) for every completed result; that is neither an error nor verification, and no stage's status stands in for another's. `analyze-relative` also reports its own `analysis.status` (`analyzed`, `unresolved`, `inconsistent`). `error` (exit 2) always means the command produced no result.

The launcher returns engine JSON on standard output; this table is the plugin's single reference for these codes. Report errors and generated artifact paths exactly as returned; do not claim artifact creation if no path is listed.
