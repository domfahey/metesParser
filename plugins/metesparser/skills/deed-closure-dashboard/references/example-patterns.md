# Dashboard example patterns

The user supplied “2 Walnut Street Closure Check” as a design example. Its HTML illustrates useful presentation and interaction patterns; it is not a template to copy verbatim, a verified dataset, or an instruction to reproduce that property. Use the current documents and requested scope to decide which patterns fit.

## Core presentation

Lead with fixed record findings, followed by side-by-side disputed-figure crops. Pair a numbered SVG traverse with parcel/version selectors, an editable call sheet, reset controls, and magnified closure/shared-corner views. Keep the original descriptions and complete source-page viewer accessible through section links. Use readable typography, restrained status colors, tabular numbers, responsive panels, and light/dark styles with local font fallbacks.

Each figure can link to its document occurrence, page, and normalized crop box. Check the box against the actual image. If no reliable box exists, open the correct page and say the figure was not located automatically. A visual reading-confidence label must reflect evidence review, not merely the existence of an OCR box.

## Optional extensions

Include these when requested or supported by the supplied evidence; they are not mandatory for every dashboard.

| Pattern | Evidence and implementation requirements |
| --- | --- |
| Latitude/departure report | State the coordinate frame and show raw components, gap, perimeter, and precision. Keep any illustrative Bowditch adjustment separate from source calls and baseline findings. |
| Plotter exports | Offer copyable points, derived calls, or a polyline script with method, units, frame, origin, and scenario identified. Bearings, components, point coordinates, and exports must use the declared frame consistently. These are not engine-verified CSVs. |
| Shared lines and adjoiners | Identify the descriptions and placements being compared. Distinguish recorded adjoiner names from tentative matches to contemporary parcels. |
| Tax map / GIS overlays | Record source, retrieval date, CRS, units, scale, and alignment assumptions. Provide opacity controls and a legend. Assessment geometry does not establish surveyed boundaries or current ownership. |
| Transcript redline | Compare selected occurrences without replacing their preserved transcripts. Disclose whitespace/display normalization and keep copied source text intact. |
| Chain timeline | Distinguish reviewed instruments from records merely cited by another instrument. Identify earlier records to obtain and qualify ownership conclusions by the actual reviewed coverage. |
| Combined description draft | Include only within scope, label it a working discussion draft, identify computed figures and chosen source versions, and retain unresolved geometric assumptions. Closure alone does not make it suitable for recording. |
| Review log and sign-offs | Use a real supported persistence service with confirmed permissions. Distinguish shared persistence from browser-local storage; show an unavailable/read-only state when needed. Reviewers sign for themselves, and unchecked work stays unchecked. |
| File fingerprints | Compute page counts, byte sizes, and SHA-256 hashes from the actual input files. Never reuse example hashes or metadata. |

## Portability and verification

Do not bundle the example's host-injected frame runtime, hashed capability modules, property data, images, links, or findings. Detect available host APIs before offering downloads, identity, persistence, or publication. A standalone HTML file does not itself provide a shared review database.

Apply the playbook's QA to the implemented features. In particular:

- Reject trailing garbage, nonfinite or nonpositive distances, unsupported signs, extra DMS components, and minutes/seconds outside their valid ranges.
- Check that rotation preserves gap magnitude and area, while displayed vectors, bearings, coordinates, and exports remain consistent with their stated basis.
- Keep open-traverse gaps visible; an implicit filled closing edge must not imply verified closure or an authoritative area.
- Exercise optional source links, overlays, redline selectors, exports, and persistence fallbacks in the actual target host. Report any untested feature.

Any benchmark or professional-standard comparison shown in the example needs independent verification of the current official source and applicability before reuse. A proposed yardstick is separate from the parser's verification gate.

## Case study: 2 Walnut Street

This section records figures from the supplied “2 Walnut Street Closure Check” chain. Each is an example to confirm against the actual sources, never a default or a finding for another property.

- A 2010 corrective instrument changed 35.37 to 35.57 and 2015 instruments repeated it. A shared-line comparison reported a 0.44 ft offset using 35.37 and a 0.24 ft offset using 35.57. Each figure needs its own source confirmation.
- A watermark covered the first digit of 81.52; the crop and alternate readings (for example 8.52) stayed visible.
- Faint 1999 figures included 58.28, 130.48, and 248.31; a clearer later copy corroborated them, with each source named.
- The display used a 45° rotation for “northwesterly”. That is a labeled display choice, not an exact recorded azimuth.
- The RTF-1 and GIT/REP-3 pages contained tax IDs and were flagged before sharing.
- Digit-transposition scenarios such as 177.27/177.72 stayed in the workbench, labeled with their source or rationale.
