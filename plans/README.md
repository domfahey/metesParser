# Implementation plans

Prepared with the improve planning skill on 2026-10-27. These are implementation handoffs, not completion reports. Historical plans remain in `docs/plans/`.

| Plan | Outcome | Priority | Effort | Dependencies | Status |
|---|---|---|---|---|---|
| [001](001-mapbox-online-viewer.md) | Optional Mapbox viewer combining registered tax maps and recorded deed geometry | P1 | L | Existing plot, registration, and dashboard contracts | IMPLEMENTED — local gates passed; live token blocked, native-host acceptance not run |

The parent executor owns this index. Read the entire plan before dispatching its bounded work packets. Use at most three concurrent workers plus the parent. Every worker must preserve existing changes and report red/green evidence, limitations, and files changed.

Plan 001 separates deterministic implementation acceptance, live Mapbox acceptance, and native plugin-host acceptance. Update those gates separately; mocked browser tests do not complete the live gates. Do not mark the plan DONE while required acceptance remains outstanding.

Decisions retained to avoid repeated exploration:

- Keep the existing offline dashboard and standalone plot independently useful.
- Use Mapbox for the first online renderer, with provider-independent display geometry.
- Reproject registered tax-map imagery; transforming its four corners alone is insufficient across arbitrary projections.
- Extend the existing composable skills; do not add a Mapbox-specific skill.
- Defer online scenario editing, interactive registration, automatic alignment, and additional map providers.
