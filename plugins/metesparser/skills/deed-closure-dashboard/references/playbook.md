# Deed Closure Dashboard Playbook

Build an interactive closure check, like the 2 Walnut Street example, for a chain of title or any set of source documents. This playbook adapts the supplied Walnut Street workflow to the plugin's native-reading, source-preservation, and verification rules. Its historical figures are examples to verify against actual sources, never defaults for another property.

Contents: [Quick start](#1-quick-start) · [Inputs and data contract](#2-inputs-and-data-contract) · [Workflow](#3-workflow) · [Page specification](#4-page-specification) · [Walnut Street lessons](#5-walnut-street-lessons) · [QA before delivery or publication](#6-qa-before-delivery-or-publication) · [Current controls and delivery](#current-controls-and-delivery)

The finished page has six parts:

1. **Findings:** one card per description occurrence/version, showing closure, misclosure, precision, and uncertainty from record values only.
2. **Record evidence:** original-scan crops showing every disputed figure.
3. **Workbench:** all parcels, editable calls, live closure, closure-gap details, and shared-corner details.
4. **Metes and bounds as recorded:** transcripts with changing figures highlighted, plus extracted courses that can be copied as CSV.
5. **Source copies:** every recorded page in a full-size viewer.
6. **Method, limits, sources.**

## 1. Quick start

Upload the source PDFs or images to a Claude/Cowork session with native document reading and ask:

> Check the metes and bounds in these deeds for [property address, block/lot, municipality]. Compare the descriptions across the chain. Then build an interactive dashboard like the 2 Walnut Street one: findings, crops of the disputed figures, a workbench with a plot and editable call sheet, transcripts of each description with extracted courses, and copies of every deed page. Follow the deed-closure-dashboard playbook.

When delegating evidence, calculation, interface, or QA work, keep ownership separate and reconcile outputs against a common record ledger. Report only delegation that actually occurred.

The bundled `dashboard` command renders a validated version 1.0 deed-only bundle or version 1.1 bundle with explicit plot/map data as an offline HTML page. Use it as the standard renderer after source review and calculation; do not rebuild its HTML/JS or treat rendering as another document-reading stage. It includes per-occurrence findings, evidence crops, transcripts/course tables, page viewing, method notes, and source-linked deed plotting. Version 1.1 supports explicit scenes, placements, supplied map layers, and named point comparisons. Read [plot-and-overlays.md](plot-and-overlays.md) before preparing those fields. See [dashboard-bundle.md](dashboard-bundle.md) for schema, statuses, cache behavior, and exact artifacts.

## 2. Inputs and data contract

| Input | Notes |
| --- | --- |
| Every deed or source in the chain | Include corrective instruments and exhibits, which may introduce or repeat discrepancies. |
| Book/page or instrument identifiers | Read recording stamps and printed page references; mark unknown values. |
| Surveys, if available | Compare as corroborating evidence; do not automatically declare one source legally controlling. |
| Tax block/lot and municipality | Label each parcel without substituting tax identifiers for a boundary description. |

Give every source, page, description occurrence, parcel, record version, and scenario a stable ID. Store raw direction wording, stated angle text and angle type, interpreted interior angle, distance/unit, original quote, along/to wording, source location, reading status, and assumptions. Store the stated closing angle separately. Record book/page, grantor/grantee, interest, dates, consideration, and covered lots only when supported.

Keep three distinct objects: immutable record values, derived results with method/basis, and editable scenarios. Link every substituted or disputed figure back to its own source. A figure borrowed from another instrument is a comparison reading, not a silently repaired value in an obscured record.

## 3. Workflow

Enter at the earliest missing or invalid stage. Reuse matching source acquisition, transcription, selection, and map-preparation artifacts for unchanged inputs; steps below do not require repeating completed native reading. Recompute deterministic geometry for a new dashboard identity using the [artifact composition sequence](dashboard-bundle.md#compose-existing-plot-and-map-artifacts).

### Step 1: Read every supplied page

Use Claude's native document/image conversion. With available host rendering tools, inspect every PDF page at about 130 dpi, including exhibits, Certifications of Trust, acknowledgments, RTF-1, GIT/REP-3, and repeated copies. Rendering/cropping is for inspection and evidence, not a separate OCR provider. For non-PDF sources, preserve the supplied source identity and available page structure.

Build a page index per instrument: file/attachment ID, page order, book/page, document type, description locations, and reading coverage. Do not claim every page was viewed when native access or a rendering tool was unavailable. Obtain missing pages/exhibits or report incomplete coverage before claiming a complete chain comparison.

### Step 2: Find and transcribe every description

Locate every parcel description, including repeated copies within the same instrument. Keep each occurrence separate and preserve its original wording and figures, including typos and odd spacing such as `265.21feet` or `81degrees`.

Save an untouched transcript with source/page references. A display/search copy may remove line breaks and rejoin line-end hyphenation, but retain the original copy and a transformation record; do not strip meaningful hyphens or change words in the record baseline.

For faint passages, render near 300 dpi and inspect cropped strips rather than attempting to resolve a tiny digit from a full-page view. Record each uncertain figure and why it is uncertain: watermark, faint type, fold, clipping, or missing page. Preserve unknown readings. If another instrument is clearer, name that source and present the matching figure as corroboration or a labeled scenario until the obscured figure is independently resolved.

### Step 3: Run metesparser on the selected text

Run from the intended project root with a new output directory:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" review lot_X.txt --output-dir rev_lot_X
```

Full recorded bearings allow direct deterministic verification. Direction-only records may return `needs_review` and `incomplete bearing - cardinal only`; retain that result. A later local-angle analysis does not change the engine status. Engine-verified export still requires its existing checks and misclosure below 0.01 ft.

### Step 4: Analyze angle-based descriptions separately

Carry local headings forward from the first course using explicit source angles. If the initial compass bearing is absent, choose an arbitrary local axis for computation and label it as such. Do not represent it as a numeric bearing recorded in the document. Declare traversal orientation and every inferred/reflex turn. If the wording cannot resolve a turn, analyze labeled alternatives or leave the record finding indeterminate.

Use the tested `mp_verify.analyze_relative()` module through the plugin's dedicated command. Prepare a source-linked JSON description using the [relative-angle input contract](../../../references/relative-analysis.md). The [synthetic rectangle](relative-rectangle.json) is a runnable schema example, not property evidence.

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" analyze-relative lot_X_angles.json --output-dir rev_lot_X_angles
```

Retain the original canonical review separately. This command always returns top-level `needs_review` (exit 1) for valid input, even when `analysis.status` is `analyzed`. Inspect the nested analysis for `unresolved` or `inconsistent` constraints. It never writes CSV or makes a verified-export decision. Its immutable input and JSON results preserve source references, quotes, and explicit interpretations.

Supply straight legs only. Use the existing canonical engine for circular geometry; do not substitute chords or silently omit curves. The solver propagates relative headings from the declared first-course local axis and checks every resolved constraint, including any closing-angle constraint. It never selects a turn or repairs a distance to improve closure.

Display `precision_denominator` as the denominator in `1:N` when available. Null precision means unavailable or mathematically unbounded; do not label it infinite for a nonzero gap. An open traverse's area includes an implicit closing segment and is provisional. Local headings, gap components, and the heading-based closing angle are derived quantities, not source facts. Preserve full precision and use the same local frame for headings, coordinates, and exports.

Interpret the wording before supplying numeric interior angles:

| Wording | Interpretation |
| --- | --- |
| Interior angle A | Use A when the referenced legs/vertex are clear. |
| Exterior angle A | Under the playbook's reflex exterior-angle convention, use 360° − A. Confirm that convention from context; an exterior deflection angle can mean something different. |
| Right angles, turning toward the land | 90° interior angle when that turn is established. |
| Right angles, turning away from the land | 270° reflex interior angle when established. |
| Along a street after a right-angle call to it | Evaluate the implied 90°/270° choice only as an explicitly flagged interpretation. |

Check each result:

1. **Angle sum:** include the recorded closing angle at the POB and compare with `(n − 2) × 180°`. Missing or inferred angles make this conditional. A matching sum is necessary, not sufficient: compensating angle errors can still create misclosure. Do not conclude that all remaining error must be in distances.
2. **Gap vector:** show ΔE, ΔN, magnitude, and frame basis. A gap aligned with one course suggests a hypothesis to test, not proof that the distance is wrong.
3. **Direction words:** use an explicitly labeled display rotation consistent with available street/direction evidence. The Walnut example used a 45° rotation for “northwesterly”; do not treat that word as an exact recorded azimuth. The proposed within-67.5° direction-word check is a heuristic, not a bearing measurement or a substitute for resolving turn ambiguity.
4. **Earlier versions:** rerun each source's own values, including corrective instruments and repeated copies. A closing older version is evidence of a difference, not automatic authority to replace the newer record.
5. **Digit scenarios:** try transpositions such as 177.27/177.72 or alternate obscured readings such as 8.52/81.52 in the workbench only. Label the edited field and its source or rationale.

Use the supplied visual guidance as a rule of thumb, not a legal standard: absolute misclosure under 0.02 ft is green, 0.02–0.10 ft amber, and over 0.10 ft red; relative precision better than 1:10,000 is a separate favorable indicator. Show both metrics when they disagree rather than disguising a large absolute gap behind a good relative ratio. These bands never relax the engine's verified-export threshold.

### Step 5: Compare neighboring parcels

When a map comparison is requested, place each deed only from explicit evidence and a declared frame. Prepare and render the deed-only bundle first to obtain its geometry hash, then add a placement referencing that exact hash and rerender. A tie distance without supported orientation is insufficient for referenced placement; use an explicitly approximate placement or leave it unplaced. Do not imply that a tax parcel or its apparent visual fit determines the deed boundary.

Identify shared lines through supported lengths, adjoiner names, corners, and angles. Compare only explicitly named point correspondences in a common supported linear scene and report residual vectors, RMS, and maximum residual separately from deed misclosure. A residual fit is not survey accuracy. Do not pick a closing scenario silently or use closure as evidence that a reading is legally correct.

The Walnut example reported a 0.44 ft offset using 35.37 and a 0.24 ft offset using 35.57. Those figures require their own source confirmation. Approximate strip area as offset × shared-side length and label the approximation. Record whether parcels are conveyed together or separately when supported; do not infer title consequences from geometry alone.

### Step 6: Prepare evidence and page assets

- Crop each disputed figure in each occurrence at 250–300 dpi. Target grayscale JPEG quality around 70 and roughly 30–50 KB per crop, then check readability; embed crops as data URIs.
- Include every original page as a supporting image under `pages/`, approximately 1000 px wide, grayscale JPEG quality around 60. About 36 pages/6 MB was the example budget, not a completeness limit. Increase quality when needed to read critical evidence.
- Label assets with source ID, book/page, original page number, crop coordinates or other reproducible location, and description occurrence. Preserve originals separately.
- Index sensitive pages such as tax-ID forms. Identify them before sharing and verify the actual destination's privacy/access settings; do not promise default privacy.

### Step 7: Build and deliver

Render the reviewed bundle using the validated command and a fresh output directory:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" dashboard bundle.json --output-dir dashboard-new --cache-dir dashboard-cache
```

In the development workspace, `uv run metes-review dashboard bundle.json --output-dir dashboard-new --cache-dir dashboard-cache` is equivalent. A valid bundle returns top-level `needs_review` (exit 1); inspect the artifact paths and calculation statuses in its JSON output. Deliver `dashboard.html` with `source.json`, `source-review.json`, `calculations.json`, `stage-manifest.json`, and `render-manifest.json` so the input, review-data stage, calculations, and rendered output remain inspectable. The command does not publish or write the engine's verified CSV.

Record values and findings remain fixed while the browser edits a separate advisory scenario. Use Reset to restore that working copy. Do not describe scenario closure as a record finding. The immediate browser scenario calculator supports straight-course patches. The structured editor supports exact line/arc drafts and explicit add/remove/reorder; publish and render the revision through the shared engine for fresh geometry. The renderer supports explicitly supplied rigid placements and named point comparisons, but does not automatically match corners or infer parcel alignment.

Keep delivery local unless the user requested sharing and the host's actual access controls support it. Do not invent a public URL, declare an untested page published, or assume privacy. Identify tax-ID pages and verify the requested destination's privacy before sharing. Do not claim host-side read attestations; the bundle renderer has no review log.

## 4. Page specification

| Section | Must include |
| --- | --- |
| Header | Address or property identifier, block/lot if known, municipality/county, purpose, jump links. |
| Findings | One card per description occurrence/version. Status: closes, does not close, descriptions disagree, unclear scan, or conditional. Show misclosure, precision, angle sum, method/basis, engine status, and a one-line reason from record values only. |
| Record evidence | Side-by-side crops of each disputed figure, labeled by source/book/page/occurrence, with reading confidence and a short evidence-bounded explanation. |
| Workbench | Parcel toggles, numbered courses, POB, street labels, approximate/basis-qualified north arrow, 100 ft scale bar, parcel tabs, version selector, one-click suspect-figure scenarios, and Reset to record. Show gap vector/magnitude, precision, provisional area, perimeter, angle sum, and details of the closure gap and each shared corner. |
| Call sheet | Direction word and quote; stated angle text/type; editable interior angle accepting supported DMS forms; editable distance; computed local heading/bearing basis; ΔN/ΔE; direction-word check. Edited cells amber, disputed rows highlighted. Show stated closing angle separately from computed closing angle. Reject malformed/nonfinite values and unsupported angle formats instead of guessing. Never use JavaScript eval for input. |
| Metes and bounds | Tabs per instrument and repeated occurrence, location and parcel labels, preserved transcript with changed figures highlighted, scan notes, copy control. Highlight differences without changing copied source text. |
| Extracted courses | POB row followed by course, direction, angle as written, distance/unit, along/to, grouped by parcel/version/occurrence. Copy as CSV. Do not label a dashboard-specific angle table as the engine's verified CSV export. |
| Source copies | Instrument metadata supported by records; thumbnail grid of every page with labels and outlined description pages. Full-size viewer with previous/next, arrow keys, focus handling, and Open image. |
| Method, limits, sources | Angle-to-heading method, assumptions, checks and thresholds, source uncertainty, non-survey/non-title-opinion limitation, and complete instrument/book/page/source list. |

Copy buttons must fall back to a visible selected textarea when clipboard APIs are blocked. Do not depend on download links in Artifact views that block them. Escape quotes and source text for HTML/CSV correctly and retain Unicode surveying symbols. Display full-size source images without omitting sensitive pages silently; obtain an appropriate sharing decision instead.

## 5. Walnut Street lessons

The supplied HTML is an example only. See [example patterns](example-patterns.md) for optional extensions and [plot-and-overlays.md](plot-and-overlays.md) for map/plot evidence; build from the current source documents rather than copying its data, assets, or host runtime.

- A corrective deed may introduce a new discrepancy. The supplied example says a 2010 corrective instrument changed 35.37 to 35.57 and 2015 instruments repeated it; confirm this from the provided chain before stating it as a finding.
- Watermarks can obscure digits. The supplied example says a stamp covered the first digit of 81.52; show the crop and keep alternate readings visible.
- Faint 1999 figures included 58.28, 130.48, and 248.31 in the example. A clearer later copy can corroborate a reading, but disclose where each adopted or hypothetical number came from.
- Repeated descriptions in trust certifications and exhibits are separate comparison evidence.
- A rigid local-frame rotation changes neither closure magnitude nor area. It changes displayed components/headings and helps orient the plot; it does not establish a recorded basis of bearing.
- RTF-1 and GIT/REP-3 pages can contain tax IDs. Flag those pages before sharing.
- Neither the engine's `checks_passed` result nor a dashboard is a survey, title opinion, or boundary certification.

## 6. QA before delivery or publication

- [ ] Every supplied page viewed and indexed, or unread/missing coverage explicitly reported.
- [ ] Every description occurrence located, including exhibits and repeated copies.
- [ ] Faint/obscured figures inspected at suitable resolution and recorded as uncertain where unresolved.
- [ ] Angle sums include the stated closing angle; missing angles, discrepancies, and inferences are reported.
- [ ] Direction-word checks are shown with their display rotation/basis and unresolved disagreements.
- [ ] Each parcel/version analyzed independently, with differences explained without silently correcting records.
- [ ] Shared corners use explicitly identified versions and placements; record gaps remain visible.
- [ ] Findings match Python reference values within 0.001 ft; JavaScript and Python agree on analytic closed/open examples, reflex turns, translation/rotation, and invalid inputs.
- [ ] Editing a scenario changes only the workbench; reset restores its selected baseline and findings/transcripts/evidence remain unchanged.
- [ ] Page renders at 400 px without horizontal page scroll, in light/dark mode; call-sheet overflow stays within its own labeled container.
- [ ] Viewer, keyboard navigation, copy buttons and textarea fallback, version selectors, scenario controls, and reset work.
- [ ] Tax-ID pages identified before sharing; actual publishing scope/access verified, with no unsupported privacy promise.
- [ ] Actual subagent/model use and any untested browser, native-reading, or publishing step disclosed.

## Current controls and delivery

Deliver the local dashboard path with a short guide tied to the controls actually present:

- Select the parcel and description/calculation occurrence before reading its findings. Course buttons in the plot, recorded table, workbench and supported diagnosis open the linked source page/quote and evidence crop when supplied; missing crops remain explicit.
- Choose record values or a supplied scenario preset. Edit supported existing straight-course distances and azimuth/quadrant bearings in the advisory workbench; relative headings remain derived separately. Invalid input is highlighted and blocks the current scenario result. Keep the source reading unchanged; a transcription correction needs fresh source/call artifacts and source comparison.
- Read baseline and scenario closure sensitivity separately. Baseline diagnosis supports the documented analytic circular-arc subset; the immediate browser diagnosis remains straight-only. Unresolved or unsupported geometry and relative constraints can leave diagnosis unavailable; sensitivity is not a correction recommendation or canonical verification.
- Use **Reset to record** to restore the selected record baseline. **Reset view** changes the viewport only; **Fit**, pan/zoom, course/bearing/distance labels and map visibility/opacity/order are display controls. Scenario closure cannot promote engine/source status.

Use **Download draft**, **Load draft JSON** and the [revision commands](../../../references/revisions.md) for durable alternatives. Structured changes use `save-revision` followed by `render-revision`; inspect their current geometry separately from labeled last-valid geometry. Do not imply that in-session edits alone persist or become source corrections. When resuming outside that session, retain the artifact directory and use the [inspector summary](../../../references/artifact-handoffs.md#artifact-inspection-and-resume) to identify the earliest required stage.
