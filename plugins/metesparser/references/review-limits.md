# Review scope and output

MetesParser is text-first. The bundled review engine accepts supplied text and structured data; it does not inspect PDF page images or perform OCR. A scanned deed therefore needs a user-provided transcription before review.

The engine parses and checks only the conditions implemented by its deterministic rules. A `checks_passed` status is not a legal opinion, title determination, survey, boundary certification, or guarantee that source wording was interpreted correctly. Human review remains necessary for ambiguous or incomplete descriptions and for topology or monument questions not represented in the input.

Bearings that contain only cardinal wording remain unknown. Do not infer a numeric azimuth, fill missing calls, or treat a closure adjustment as a source fact. Keep the distinction between verbatim deed language and parser-derived fields clear.

The launcher returns engine JSON on standard output. Statuses are `checks_passed` (exit 0), `needs_review` (exit 1), and `error` (exit 2). Report errors and generated artifact paths exactly as returned; do not claim artifact creation if no path is listed.
