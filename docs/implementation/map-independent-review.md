# Independent map-control and evidence review — 2026-10-28

Outcome: no concrete UI or evidence-misstatement defect found in the reviewed D implementation. This reviewer did not author the map-control change. No production files or tests were changed during this review.

## Scope and reasoning

- Each rendered raster has its own labeled opacity input, visibility toggle and stable raster ID. JavaScript opacity state is keyed by that raster ID and updates only the matching provider layer. Native range inputs and buttons retain keyboard behavior; unavailable reorder moves are disabled at the ends.
- Raster ordering is bottom-to-top. A swap changes only the raster-order array and the matching control order. Provider `moveLayer` places every raster before `review-parcel_context`, preserving the relative context/course/POB/closure/selection layers above scans. Initial and style-reload construction adds rasters in stored order before those vector layers.
- Style reload uses the unchanged session `rasterOrder`, per-ID `rasterOpacity` and visibility dictionaries when recreating provider layers. Selection is reconstructed from the selected call ID. Disconnect/reconnect retains these presentation settings in the same viewer session. No storage writes, geometry fitting, placement edit or evidence mutation was introduced.
- Serialized bundle/artifact/view inputs are deep-frozen; interactive dictionaries/arrays are separate. Presentation handlers do not modify registration controls, source bytes, provenance hashes, canonical findings or verification status. The reviewed browser tests hash the immutable JSON payload after interaction.
- Evidence text preserves source label/filename/hash/provider/date, source scene/CRS/units, fit/checkpoint counts and respective RMS units. Zero checkpoints explicitly states that independent checkpoint accuracy is unknown. Both zero-checkpoint and zero-fit-RMS/10-m-checkpoint fixtures are present. The wording expressly says a small fitting residual is not an accuracy estimate.
- Calculation evidence retains recorded frame/bearing-basis/foot-definition information and actual placement statuses. It discloses unknown numerical placement uncertainty and that recorded bearings alone do not establish geographic north. It does not promote approximate registration/placement into referenced survey accuracy.
- User-supplied labels and provenance text are escaped in HTML and placed via textContent in browser panels. The added CSS constrains long labels and small-screen control widths; no unsafe interpolation was introduced into event handlers.

## Evidence inspected

The review read the complete renderer/JavaScript/CSS, the current tracked diff, the deterministic layer test harness, synthetic two-raster/poor-checkpoint fixtures, focused HTML tests, and browser tests. It also checked the upstream web-map validator binds raster registration status/RMS/units to the source registration, so summaries are not assembled from unchecked derived evidence.

The author separately reported **22 deterministic Chromium cases passed**, including the poor-checkpoint case. This independent review did not repeat that run because no new behavioral concern was found. Provider-stub browser checks do not establish live Mapbox pixels, provider access, WebGL behavior or native-client visible acceptance; those remain separately reported gates.

## Exact reviewed snapshot

Baseline HEAD: `c0d6074941c9a59e68cc1d37e1f89531621f23e0`.

SHA-256 of the exact bytes returned by `git diff --binary HEAD --` over the seven files below: `493d73cf51c33ff5f224094a94c4f81611de960bf31bc392e728aaeafcd764a4`.

| Reviewed file | SHA-256 of complete file bytes |
| --- | --- |
| `packages/mp-export/src/mp_export/online_map_html.py` | `957c46ac0b654478cbfa5228e14f67172804faf9e79c9d5f49b4e6a41006b94b` |
| `packages/mp-export/src/mp_export/dashboard_assets/online_map.js` | `e43797e3d5ac8310f6e90b2c0b5e9d64f758a7dbc4ba34467dc5606ec2d2f394` |
| `packages/mp-export/src/mp_export/dashboard_assets/online_map.css` | `c90bef29c3965c6a78d8089cfc0adfa3bbde20a81249e9d1e8f5d57168690c93` |
| `packages/mp-export/tests/test_online_map_html.py` | `bfab075ab8c74a1302fdf030cdf7bd12823c52a8111b807b563401c5ce19746a` |
| `packages/mp-export/tests/browser/test_online_map_ui.py` | `ba092c806bdeeb04f0acc4e5ea417e62daa424fd501415c5bf7472aa8f55807a` |
| `packages/mp-export/tests/browser/conftest.py` | `509dcd6bd63b3ecf5b2f0bb69fa46f8808f62d014801311a2aee6853077eabf8` |
| `packages/mp-export/tests/browser/mapbox_stub.js` | `e6b4ecd54b3dc8725d93c07c432173808b5be2fdd67c360814f0125f0e1adeda` |

A later formatter-only change produces a different byte hash; these identities describe this review snapshot, not an unbounded future checkout.

## Final integrated browser acceptance

After F/B/D integration stabilized, this reviewer ran both required targets against the current checkout:

- `make test-dashboard-browser`: exit **0**, **15 passed in 8.15s**, zero skipped. Log: `/private/tmp/metesparser-final-dashboard-browser.log`; SHA-256 `07fd900cc66f559958480c7543344089e636566942bba36c178b65ec7bbbfd37`.
- `make test-mapbox-browser`: exit **0**, **22 passed in 15.24s**, zero skipped. Log: `/private/tmp/metesparser-final-mapbox-browser.log`; SHA-256 `7b012c26ac45743f177d8c178521fe6e745730c52183549742bacd0ca5d19545`.

The Mapbox target includes deterministic provider-adapter tests and the pinned SDK local-style/source/worker/reload case. No live-provider target was run and no token was supplied. These results therefore confirm local browser behavior and remain separate from live-provider or native-client display acceptance. No production edits were needed.
