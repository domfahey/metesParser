# Review scope and output

The bundled review engine accepts selected text and structured data; it does not inspect PDF page images or perform OCR. The plugin uses Claude's native document/image reading to prepare text from images and PDFs, then locates the intended metes-and-bounds description before deterministic review. No separate OCR provider or conversion dependency is added. If native reading cannot access a source, disclose that limitation and request an accessible source.

The engine parses and checks only the conditions implemented by its deterministic rules. A `checks_passed` status is not a legal opinion, title determination, survey, boundary certification, or guarantee that source wording was interpreted correctly. Human review remains necessary for ambiguous or incomplete descriptions and for topology or monument questions not represented in the input.

Bearings that contain only cardinal wording remain unknown. Do not infer a numeric azimuth, fill missing calls, or treat a closure adjustment as a source fact. Keep the distinction between verbatim deed language and parser-derived fields clear.

Boundary intersection checks include straight segments and circular arcs, using actual finite arc sweeps rather than chords. Crossings, overlaps, and nonadjacent touches block verification; legitimate shared endpoints of neighboring courses are allowed. Unknown or inconsistent circular geometry and unsupported spiral curves produce warnings and require review. These planar checks do not establish source completeness, ownership, or the correctness of a supplied coordinate system.

The launcher returns engine JSON on standard output. Statuses are `checks_passed` (exit 0), `needs_review` (exit 1), and `error` (exit 2). Report errors and generated artifact paths exactly as returned; do not claim artifact creation if no path is listed.
