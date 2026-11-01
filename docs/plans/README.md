# Implementation plans

Dated plans, design notes, evidence records and acceptance handoffs. Status is taken from each file's own status line or heading as of 2026-10-31. Local implementation gates are kept separate from live-provider and native Claude host acceptance.

| Date | Document | Topic | Status |
|---|---|---|---|
| 2026-02-17 | [Multi-tract support design](2026-02-17-multi-tract-support-design.md) | Multi-tract deed design | Approved (design) |
| 2026-02-17 | [Multi-tract support plan](2026-02-17-multi-tract-support-plan.md) | Multi-tract detection, splitting and per-tract verification | No status recorded |
| 2026-10-26 | [Deed plotting and tax overlays](2026-10-26-deed-plot-and-tax-overlay-plan.md) | Source-linked deed plots and optional tax-parcel layers | Implemented 2026-10-27 (Releases A–C); native host acceptance not run |
| 2026-10-27 | [Composable skills refactor](2026-10-27-composable-skills-refactor.md) | Artifact-bounded skill responsibilities | Implemented |
| 2026-10-27 | [Deed plot implementation](2026-10-27-deed-plot-implementation.md) | Evidence for the deed plot releases | Implemented 2026-10-27 |
| 2026-10-27 | [Plan 001: Mapbox online viewer](2026-10-27-mapbox-online-viewer.md) | Optional Mapbox viewer combining registered tax maps and recorded deed geometry | IMPLEMENTED — local gates passed; live token blocked, native-host acceptance not run |
| 2026-10-28 | [BoundaryLogic Cowork plan audit](2026-10-28-boundarylogic-cowork-plan-audit.md) | Specification audit (A01–A10) | Audit complete; amendments incorporated; implementation and behavioral acceptance remain planned |
| 2026-10-28 | [BoundaryLogic Cowork workflow plan](2026-10-28-boundarylogic-cowork-workflow-plan.md) | Cowork workflow improvements | Local implementation complete; native Claude/Cowork acceptance not run |
| 2026-10-28 | [Source evidence and skill improvements](2026-10-28-skill-evidence-and-review-improvements.md) | Source evidence, diagnostics, maps and composable skills | Local implementation passed; paired evaluations and live provider/native-client acceptance outstanding |
| 2026-10-31 | [PR #60 review-loop handoff](2026-10-31-pr60-review-loop-handoff.md) | Paused review loop for PR #60 | Paused; superseded once PR #60 merges |

Plan 001 separates deterministic implementation acceptance, live Mapbox acceptance, and native plugin-host acceptance. Update those gates separately; mocked browser tests do not complete the live gates. Do not mark the plan DONE while required acceptance remains outstanding.

Decisions retained for Plan 001:

- Keep the existing offline dashboard and standalone plot independently useful.
- Use Mapbox for the first online renderer, with provider-independent display geometry.
- Reproject registered tax-map imagery; transforming its four corners alone is insufficient across arbitrary projections.
- Extend the existing composable skills; do not add a Mapbox-specific skill.
- Defer online scenario editing, interactive registration, automatic alignment, and additional map providers.
