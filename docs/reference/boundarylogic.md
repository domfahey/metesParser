# BoundaryLogic research and UI reference

Reviewed: **2026-10-28**. Site: [boundarylogic.com](https://boundarylogic.com/).

Purpose: document BoundaryLogic's public product presentation and UI patterns relevant to MetesParser's composable review, plotting, and map skills. This is a research snapshot, not a product endorsement or an implementation specification.

## Contents

- [Evidence and coverage](#evidence-and-coverage)
- [Product structure](#product-structure)
- [Public-site interactions observed](#public-site-interactions-observed)
- [Plotting workspace layout](#plotting-workspace-layout)
- [Map and overlay workflow](#map-and-overlay-workflow)
- [Published capabilities](#published-capabilities)
- [Lessons for MetesParser](#lessons-for-metesparser)
- [Remaining evaluation questions](#remaining-evaluation-questions)

## Evidence and coverage

Three evidence levels are used throughout:

- **Observed interaction:** operated on the public site in a desktop Chrome session and checked the resulting UI.
- **Pictured UI:** visible in the site's screenshots or animated demonstrations; the application control itself was not operated.
- **Vendor claim:** stated in public page text, without independent functional or numerical verification.

Public pages were read with Firecrawl; navigation, demonstrations, screenshots, and image enlargement were inspected in the browser. The authenticated app was **not tested**: attempts to open its entry pages encountered browser-control failures, including a focus timeout and detachment. That is an inspection limitation, not evidence that BoundaryLogic is unavailable or that every feature requires authentication. No account was created, documents uploaded, or paid services used.

The research covered the homepage, Trace overview, manual plotting, AI plotting, map view, image overlays, verifications, exports, pricing, API, and trust pages. Sheet View was encountered as a navigation destination; its dedicated workflow was not inspected. Mobile, keyboard accessibility, actual exports, and API behavior remain untested.

## Product structure

The public navigation separates three delivery modes: **Trace**, the browser workspace; **API**, for software integration; and **Bulk Processing Services**, for volume work. The homepage also announces the rename from DeedPlotter AI to BoundaryLogic. These are public positioning statements. [Homepage](https://boundarylogic.com/)

For our purposes, the useful distinction is between an interactive review experience and reusable processing capabilities. A shared user interface need not collapse acquisition, parsing, verification, geometry, and rendering into one skill.

## Public-site interactions observed

| Surface | Action and observed result | Limit of observation |
| --- | --- | --- |
| Cookie dialog | Selected **Reject optional**; dialog dismissed. | No privacy-policy audit. |
| Main navigation | Opened **Platform**; a large menu grouped Trace, API, and bulk services with their documentation/pricing links. | Only this menu was exercised. |
| Homepage workspace graphic | Clicked **Open the Trace workspace**; navigated to the Trace overview. | It leads to a marketing page, not an editable project. |
| Trace workspace demonstration | Clicked the **editor** hotspot; the demonstration was brought into view and the hotspot highlighted. | No editable call input opened. |
| Trace workflow demonstration | Clicked **Review** and **Import**; explanatory content and the adjacent illustration changed. **Check** and **Export** states were also observed during automatic cycling. | Demonstration states, not extraction, verification, or downloads. |
| Feature-page contents | Clicked numbered map/overlay steps; the page scrolled to the section and the URL acquired a step fragment. | Navigation within the public feature page. |
| Screenshot viewer | Clicked **Enlarge** on map screenshots; a dark backdrop, large image, caption, and **Close** button appeared. Closing restored the feature page. | A working image lightbox, not a live map. |
| App entry | Followed **Sign in** and attempted direct entry-page navigation. | Browser control failed; no authenticated workspace observed. |

Sources: [Homepage](https://boundarylogic.com/), [Trace overview](https://boundarylogic.com/trace/), [Map view](https://boundarylogic.com/trace/features/map-view/), [Image overlays](https://boundarylogic.com/trace/features/image-overlays/).

### Visual hierarchy and navigation

The desktop site uses a pale drafting-grid background, large dark sans-serif headings, ample whitespace, rust-colored primary actions, and outlined secondary actions. The main header contains Platform, Industries, Resources, a theme control, Sign in, and Start free. A second Trace navigation row offers Overview, Features, Pricing, Docs, Releases, and Enterprise; the active section has a rust underline. Headers remain visible while scrolling.

Feature pages use the same sequence: short outcome statement, numbered workflow, large screenshots, capability list, FAQ, related features, and a final action. A left-side contents list provides direct access to each numbered step. FAQ accordions expose keyboard-navigation instructions, but keyboard behavior was not tested. [Trace overview](https://boundarylogic.com/trace/), [Map view](https://boundarylogic.com/trace/features/map-view/)

## Plotting workspace layout

**Pictured UI on the Trace overview:** the main workspace places editable-looking calls, drawing, and tract metrics side by side. This arrangement keeps the description and its geometric consequences visible together; actual editing was not tested. [Trace overview](https://boundarylogic.com/trace/)

```text
Account / team / credits
Project or document title                 View on sheet | Import with AI | Export
┌─────────────────────┬──────────────────────────┬─────────────────────────┐
│ Calls editor        │ Plot                     │ Tract card              │
│                     │                          │                         │
│ Tract / curve /     │ Bearing and call labels  │ Area / perimeter        │
│ PLSS entry controls │ POB and monument labels  │ Closure / precision     │
│ Numbered courses    │ North arrow and scale    │ Remainder to POB        │
│ Source wording     │ View controls            │ Diagnose closure        │
│                     │                          │ Numbered call list      │
└─────────────────────┴──────────────────────────┴─────────────────────────┘
```

The editor illustration uses syntax coloring and line numbers, with controls for a new tract, curve, and PLSS input. The plot illustration labels straight and curved courses and marks the POB. The tract card displays a precision badge, an area-unit selector, summary metrics, a remainder bearing/distance, and a diagnosis action. These controls are **depicted**, not functionally verified. [Trace overview](https://boundarylogic.com/trace/)

### Review loop demonstrated

1. **Import:** the visual transitions from a document excerpt to ordered calls.
2. **Review:** an extracted-call list appears beside the plot; one row carries an edited marker.
3. **Check:** a compact card presents area, perimeter, closure, precision, and the remainder to the POB.
4. **Export:** a list of output files appears with a downloaded state.

The public demo both accepts step selections and cycles automatically. Its downloaded state is an illustration; no file was downloaded during this inspection. The pattern worth borrowing is a short, visible review loop with edits and metrics in context. [Trace overview](https://boundarylogic.com/trace/)

## Map and overlay workflow

### Map workspace: pictured UI

The enlarged first screenshot on the Map view page shows a different workspace arrangement:

- **Navigation sidebar:** Manual Plotting, Add Document, Document Queue, Manage Layers, Project Documents, Project Anchor, and Map Layers. Share Project, Export Plot, Print View, Help, and Collapse sit below.
- **Layer panel:** named tracts with colored geometry thumbnails, call counts, overflow menus, and expansion chevrons.
- **Map canvas:** multiple colored easement geometries, vertices, line IDs, large tract labels, and street context. A floating toolbar sits above the map; scale and view controls sit near its lower corners.

The screenshot visibly includes **Mapbox attribution**. This establishes Mapbox use in the pictured interface, not the current production SDK version, all basemap sources, or licensing terms. The page's text still contains an unresolved basemap/imagery-source placeholder. [Map view, step 1](https://boundarylogic.com/trace/features/map-view/#step-1)

The second screenshot's caption describes layer management, but the enlarged image shows the application navigation sidebar. Do not infer working visibility, ordering, or locking controls from that caption alone. [Map view, step 2](https://boundarylogic.com/trace/features/map-view/#step-2)

### Placement and layer controls: vendor claims

The documented sequence is to set a project anchor by address, choose sheet/streets/satellite/3D, then control layers. The vendor describes visibility, ordering, locking, PLSS toggles, and tract-derived names with letter fallbacks. It states that hiding a layer changes the view without deleting its document. These operations were not exercised. [Map view](https://boundarylogic.com/trace/features/map-view/)

**MetesParser interpretation:** an address can help navigate a map, but it does not establish a boundary's POB, orientation, units, or survey basis. Keep viewport centering separate from an evidenced placement transform. Visual agreement with streets or parcel lines must not change verification status.

### Image overlays: pictured UI and vendor claims

The step-2 screenshot shows a plat image as a named layer with an expanded thumbnail above tract layers. A small instance of the plat appears on the map, which also carries Mapbox attribution. This was an image inspection; no alignment handles were operated. [Image overlays, step 2](https://boundarylogic.com/trace/features/image-overlays/#step-2)

The published workflow is:

1. Upload a plat, aerial, or survey scan as an image layer.
2. Move, scale, rotate, and adjust opacity; rename the layer.
3. Lock the image and order it among tract layers.

The vendor says overlays appear in map, sheet, plotting, and guest-share views, and leave plotted calls/checks unchanged. The inspected page does not establish a control-point registration method, residual/error reporting, supported file extensions, or coordinate-system handling. [Image overlays](https://boundarylogic.com/trace/features/image-overlays/)

**MetesParser design implication:** retain the convenient layer metaphor, but expose image provenance, coordinate frame, controls, transform, and residuals. A manual fit should remain an explicit scenario or placement with recorded assumptions.

## Published capabilities

All rows below describe **vendor claims**, not benchmark results.

| Capability | Published behavior | Reference |
| --- | --- | --- |
| Manual plotting | Shorthand bearings/distances, curves/chords, and PLSS entry; drawing and metrics update during entry. | [Manual plotting](https://boundarylogic.com/trace/features/manual-plotting/) |
| AI plotting | PDF/scan or pasted text becomes an editable draft of ordered calls, including POB and curve information; professional review is still required. | [AI plotting](https://boundarylogic.com/trace/features/ai-plotting/) |
| Verification display | Area, perimeter, closure error, precision, remainder to POB, and gap/overlap flags. | [Verifications](https://boundarylogic.com/trace/features/verifications/) |
| Export | PDF, DXF, Shapefile, KML, and GeoJSON; the page describes DXF layers, polylines, and labels. | [Exports](https://boundarylogic.com/trace/features/exports/) |
| API | Text or PDF/JPEG/PNG/TIFF input; ordered calls, geometry, closure information, and exports; optional PLSS locate output. Access is sales-gated. | [API](https://boundarylogic.com/api/) |

The verification page does not publish enough algorithm/tolerance detail to equate its displayed precision with MetesParser's export gates. It contains a bearing/distance-table placeholder; the export page contains a title-block-logo placeholder. No numerical correctness or format round-trip test was performed. [Verifications](https://boundarylogic.com/trace/features/verifications/), [Exports](https://boundarylogic.com/trace/features/exports/)

### Commercial and operational context

As of the review date, the pricing page lists free manual plotting with PDF/DXF and sheet/streets views, Professional at **$29.99/seat/month**, Expert at **$49.99/seat/month**, and custom Enterprise pricing. The paid tiers include stated AI allowances; trial/credit terms should be rechecked before purchase. The AI trial is described as requiring a card, while free manual plotting is not. [Pricing](https://boundarylogic.com/trace/pricing/), [AI plotting](https://boundarylogic.com/trace/features/ai-plotting/)

The trust page describes Azure hosting and external AI processing for extraction/analysis. Detailed retention, training-use, data-residency, and contractual terms were not assessed. Do not treat this reference as approval to upload matter files. [Trust center](https://boundarylogic.com/trust/)

## Lessons for MetesParser

These are **our recommendations**, not claims about BoundaryLogic internals. The current plugin already has six capabilities, two workflows, and one compatibility alias; standalone plotting, overlay preparation, and online rendering already exist. Extend those boundaries instead of introducing another all-purpose plotting skill. [Current catalog](../../plugins/metesparser/README.md), [Handoff contract](../../plugins/metesparser/references/artifact-handoffs.md)

The subsequent three-agent repository review confirmed that linked call/plot/source selection, tract metrics, isolated scenario editing, and raster fit/checkpoint residual calculations already exist. The [implementation plan](../plans/2026-10-28-skill-evidence-and-review-improvements.md) targets the remaining gaps and assigns subagent ownership and red-green acceptance tests.

| Pattern to adapt | Proposed improvement | Existing owner / constraint |
| --- | --- | --- |
| Calls, plot, and metrics together | Reuse existing synchronized source/call/segment selection for new diagnostic candidates. | Dashboard presentation; preserve immutable records and separate scenario edits. |
| Compact tract card | Extend existing metrics with diagnosis context and explicit unresolved evidence. | Reuse verification/plot artifacts; a green-looking card must not grant export eligibility. |
| Diagnosis action | Rank source-reinspection candidates with displacement/sensitivity evidence; show alternative readings explicitly. | Existing [todo 4](../todos.md): do not choose a correction because it closes. |
| Multiple named tract layers | Compare explicitly paired versions/adjoining lines and display disagreements in context. | Existing [todo 5](../todos.md): require compatible basis/alignment or return `not_comparable`. |
| Image layer among vectors | Extend existing visibility with per-scan opacity/order and clearer registration evidence summaries. Defer locking until layers can be edited or moved. | `prepare-parcel-overlay` owns preparation; `render-online-map` owns provider rendering. |
| Visible project/workflow state | Add an artifact inspector that identifies reusable outputs, missing prerequisites, stale hashes, and the next valid stage. | Reuse the handoff/invalidation contract; avoid unnecessary rereading or recalculation. |
| Clear import/review/check/export stages | Evaluate each source-reading and handoff step separately, then test the full user flow. | Existing [todo 6](../todos.md) and [evaluation protocol](../../plugins/metesparser/evals/README.md). |

### Suggested order

1. **Strengthen source handoffs and evaluations.** Turn acquisition/selection record examples into validated contracts, then run paired real-document evaluations. Structural validation proves identity/shape, not transcription truth. The existing evaluation catalog and three unpaired Codex smoke checks are a starting point; they do not establish native Claude document accuracy. [Source preparation](../../plugins/metesparser/references/source-preparation.md), [Evaluation status](../../plugins/metesparser/evals/README.md#current-recorded-status)
2. **Make the review loop easier to inspect.** Connect the existing source-linked call selection to the sensitivity-diagnostics work. Keep source readings, scenario values, and deterministic results visibly distinct.
3. **Improve map usability around existing contracts.** Add clear layer controls and placement evidence summaries; validate local rendering, live Mapbox, and native-client display as separate gates. Do not infer placement from a plausible-looking fit.

These recommendations do not change the task tracker or authorize implementation. They connect the observed UI patterns to existing work rather than asserting that the current dashboard lacks every pictured control.

## Remaining evaluation questions

If a hands-on product evaluation is later requested, use synthetic or explicitly approved documents and record these checks:

- Does selecting a call select its segment and reveal the exact source text/page? Does editing preserve the original reading and an audit history?
- How are incomplete bearings, unreadable digits, commencement calls, curves, exceptions, and repeated exhibits represented?
- What does the diagnosis action recommend, and can it favor a geometrically closing but unsupported reading?
- Does moving a plot change only placement, or also bearings/distances? Which CRS, units, north basis, and anchor uncertainty are retained?
- Can an image fit be reproduced from recorded controls and transforms, with residuals and provenance?
- What do export files contain for open traverses, unplaced geometry, curves, and uncertain calls? Are all coordinates and units explicit?
- How do source edits invalidate verification, placement, caches, and shared views?
- What actually persists across sessions, and how do undo, autosave, concurrent edits, and mobile layouts behave?

None of these questions was resolved by the public demonstrations. Revisit the linked pages and perform controlled app tests before using this snapshot for product parity, purchasing, or technical integration decisions.
