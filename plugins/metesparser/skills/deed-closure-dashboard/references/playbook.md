# Deed Closure Dashboard Playbook

Build an interactive closure check, like the 2 Walnut Street example, for a chain of title or any set of source documents. This playbook adapts the supplied Walnut Street workflow to the plugin's native-reading, source-preservation, and verification rules. Its historical figures are examples to verify against actual sources, never defaults for another property.

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

Use the [skill's subagent workflow](../SKILL.md) to divide evidence, calculation, interface, and QA work. Prefer smaller capable models for bounded tasks; escalate source ambiguity and mathematical interpretation. Keep file ownership separate and reconcile all outputs against a common record ledger.

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

Use this reference calculation for straight angle-based legs. Retain each interpretation's inputs and outputs so calculations can be rerun. Use the existing engine for circular geometry; do not feed chord approximations into this straight-leg helper as if they were recorded boundary lines.

```python
import math

def dms(d, m=0, s=0):
    if not all(math.isfinite(v) for v in (d, m, s)) or d < 0 or not 0 <= m < 60 or not 0 <= s < 60:
        raise ValueError("Expected nonnegative DMS with minutes/seconds below 60")
    return d + m / 60 + s / 3600

def traverse(legs, az0=0, orient="ccw", start=(0, 0), closing_angle=None):
    """Return local-frame analysis, never an engine verification result.

    legs: [(None, first_distance), (interior_angle, distance), ...].
    closing_angle: separately recorded interior angle at the POB, or None.
    orient: ccw means the land lies left of travel; cw means right.
    """
    if orient not in ("cw", "ccw") or len(legs) < 3 or legs[0][0] is not None:
        raise ValueError("Use 3+ straight legs, first angle None, and cw/ccw orientation")
    if not all(math.isfinite(v) for v in (az0, *start)):
        raise ValueError("Frame values must be finite")
    if closing_angle is not None and (not math.isfinite(closing_angle) or not 0 < closing_angle < 360):
        raise ValueError("Closing interior angle must be between 0 and 360 degrees")
    x, y = start
    az = az0 % 360
    points = [(x, y)]
    courses = []
    perimeter = 0.0
    angles = []
    for i, (angle, distance) in enumerate(legs):
        if not math.isfinite(distance) or distance <= 0:
            raise ValueError("Distances must be positive finite values in feet")
        if i:
            if angle is None or not math.isfinite(angle) or not 0 < angle < 360:
                raise ValueError("Every later course needs an explicit/interpreted interior angle")
            turn = 180 - angle
            az = (az - turn if orient == "ccw" else az + turn) % 360
            angles.append(angle)
        dx = distance * math.sin(math.radians(az))
        dy = distance * math.cos(math.radians(az))
        x, y = x + dx, y + dy
        points.append((x, y))
        courses.append(dict(local_azimuth_deg=az, dE=dx, dN=dy))
        perimeter += distance
    dE, dN = x - start[0], y - start[1]
    misclosure = math.hypot(dE, dN)
    # Translate before shoelace; include the implicit last-to-first edge.
    local = [(px - start[0], py - start[1]) for px, py in points]
    area = abs(math.fsum(a[0] * b[1] - b[0] * a[1]
                         for a, b in zip(local, local[1:] + local[:1]))) / 2
    turn_at_pob = ((az - az0 if orient == "ccw" else az0 - az) + 180) % 360 - 180
    ratio = perimeter / misclosure if misclosure else None
    return dict(method="local_angle_analysis", engine_verified=False,
                misclosure=misclosure, dE=dE, dN=dN, perimeter=perimeter,
                precision=ratio if ratio is not None and math.isfinite(ratio) else None,
                area=area, area_basis="implicit_closing_segment", points=points, courses=courses,
                stated_angle_sum=math.fsum(angles + [closing_angle]) if closing_angle is not None else None,
                expected_angle_sum=(len(legs) - 2) * 180,
                computed_closing_angle=(180 - turn_at_pob) % 360)
```

Display null precision as infinite only when misclosure is actually zero; otherwise label unavailable/overflow explicitly. An open traverse's area includes an implicit closing segment and is provisional. Computed local headings and the heading-based closing angle are derived quantities, not source facts. Preserve all inputs at full precision.

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

Place each parcel with its own documented tie call and declared local alignment. The Walnut example used “248.31 ft southwardly from the corner of Walnut and Ellis.” If the tie bearing/alignment is unresolved, show the comparison as conditional rather than inventing geographic placement.

Identify shared lines through supported lengths, adjoiner names, corners, and angles. Measure offsets using the versions that close to avoid confusing a parcel's own gap with an inter-parcel offset, but label the selected versions and also report the record-value discrepancy. Do not pick a closing scenario silently or use closure as evidence that a reading is legally correct.

The Walnut example reported a 0.44 ft offset using 35.37 and a 0.24 ft offset using 35.57. Those figures require their own source confirmation. Approximate strip area as offset × shared-side length and label the approximation. Record whether parcels are conveyed together or separately when supported; do not infer title consequences from geometry alone.

### Step 6: Prepare evidence and page assets

- Crop each disputed figure in each occurrence at 250–300 dpi. Target grayscale JPEG quality around 70 and roughly 30–50 KB per crop, then check readability; embed crops as data URIs.
- Include every original page as a supporting image under `pages/`, approximately 1000 px wide, grayscale JPEG quality around 60. About 36 pages/6 MB was the example budget, not a completeness limit. Increase quality when needed to read critical evidence.
- Label assets with source ID, book/page, original page number, crop coordinates or other reproducible location, and description occurrence. Preserve originals separately.
- Index sensitive pages such as tax-ID forms. Identify them before sharing and verify the actual destination's privacy/access settings; do not promise default privacy.

### Step 7: Build and deliver

Build one HTML page with inline CSS and JavaScript and no third-party libraries. Use SVG for the plot. Keep source-derived record data immutable; edits operate on a working copy with Reset to record. The record findings must not change when calls, versions, rotation, or scenarios are edited in the workbench. A deliberate record-version selection may display that version's own frozen findings.

Use available host Artifact tools to publish only within the requested sharing scope, passing page images as supporting files. Update the same URL only if the host supports it. Otherwise deliver the HTML and `pages/` folder locally and report that publication/update was unavailable. Do not invent a public URL, declare an untested page published, or assume privacy.

## 4. Page specification

| Section | Must include |
| --- | --- |
| Header | Address or property identifier, block/lot if known, municipality/county, purpose, jump links. |
| Findings | One card per description occurrence/version. Status: closes, does not close, descriptions disagree, unclear scan, or conditional. Show misclosure, precision, angle sum, method/basis, engine status, and a one-line reason from record values only. |
| Record evidence | Side-by-side crops of each disputed figure, labeled by source/book/page/occurrence, with reading confidence and a short evidence-bounded explanation. |
| Workbench | Parcel toggles, numbered courses, POB, street labels, approximate/basis-qualified north arrow, 100 ft scale bar, parcel tabs, version selector, one-click suspect-figure scenarios, and Reset to record. Show gap vector/magnitude, precision, provisional area, perimeter, angle sum, and details of the closure gap and each shared corner. |
| Call sheet | Direction word and quote; stated angle text/type; editable interior angle accepting supported DMS forms; editable distance; computed local heading/bearing basis; ΔN/ΔE; direction-word check. Edited cells amber, disputed rows highlighted. Show stated closing angle separately from computed closing angle. Reject malformed/nonfinite values and unsupported angle formats instead of guessing. Never use JavaScript eval for input. |
| Metes and bounds | Tabs per instrument and repeated occurrence, location and parcel labels, preserved transcript with changed figures highlighted, scan notes, copy control. Highlight differences without changing copied source text. |
| Extracted courses | POB row followed by course, direction, angle as written, distance/unit, along/to, grouped by parcel/version/occurrence. Copy as CSV. Do not label a dashboard-specific angle table as the engine's verified 21-column CSV. |
| Source copies | Instrument metadata supported by records; thumbnail grid of every page with labels and outlined description pages. Full-size viewer with previous/next, arrow keys, focus handling, and Open image. |
| Method, limits, sources | Angle-to-heading method, assumptions, checks and thresholds, source uncertainty, non-survey/non-title-opinion limitation, and complete instrument/book/page/source list. |

Copy buttons must fall back to a visible selected textarea when clipboard APIs are blocked. Do not depend on download links in Artifact views that block them. Escape quotes and source text for HTML/CSV correctly and retain Unicode surveying symbols. Display full-size source images without omitting sensitive pages silently; obtain an appropriate sharing decision instead.

## 5. Walnut Street lessons

The supplied HTML is an example only. See [example patterns](example-patterns.md) for optional extensions; build from the current source documents rather than copying its data, assets, or host runtime.

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
