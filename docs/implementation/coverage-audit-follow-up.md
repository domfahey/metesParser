# B/D/F completion-audit coverage follow-up

Date: 2026-10-28. Worker/reviewer: `source_handoffs`; configured model per
parent assignment: GPT-6.1-sol, exact runtime snapshot unavailable. Parent requested closure of the weak D/F
test coverage found during the requirement audit. These are **coverage additions
against existing behavior**, not claimed behavioral RED/GREEN fixes. No
production files, commits, or pushes were made.

- Added active raster controls containing a literal malicious image/event label
  and a 2,000-character unbroken label at desktop and mobile widths. Chromium
  asserts exact legend/accessibility labels, no injected nodes/execution or
  overflow, independent keyboard opacity, unchanged frozen evidence and no
  provider request before connection. The HTML test separately validates active
  raster escaping and input/artifact nonmutation.
- Added first/last reorder-button enabled/disabled assertions before ordering
  changes and after both style reloads. Programmatic native clicks on disabled
  endpoints leave stacking unchanged.
- Added positive forward/reversed many-to-one grouping cases. They assert
  aggregate vector/length/bearing agreement, every contributing source ID/quote
  in explicit traversal order, unavailable position without placements, immutable
  input, no boundary/verification promotion, and a tentative forward merge
  suggestion.

Commands and results:

```sh
uv run pytest packages/mp-export/tests/test_online_map_html.py packages/mp-verify/tests/test_description_comparison_behavior.py --no-cov --import-mode=importlib -q
```

**78 passed in 0.57 seconds**. The first attempt failed because the schema-only
dashboard page placeholder has a bad PNG CRC; the new active-raster test now
generates a genuine synthetic Pillow PNG. That fixture failure is not a
production defect or behavioral RED claim.

```sh
METESPARSER_MAPBOX_BROWSER_TESTS=1 uv run pytest packages/mp-export/tests/browser/test_online_map_ui.py -k 'independent_scans or active_scan_labels' --no-cov --import-mode=importlib -q
```

**3 passed, 18 deselected in 2.78 seconds**. The initial uv cache sandbox denial
was retried through explicit escalation. These are offline provider-adapter
checks; live Mapbox/provider/native-client acceptance remains separate.
Ruff lint and formatting passed on the four test/fixture files.

The parent owns subsequent combined-suite and distribution gates. The changes
do not alter runtime wheel contents or packaged instructions.

Baseline HEAD: `c0d6074941c9a59e68cc1d37e1f89531621f23e0`.
Exact test/fixture identities at this gate:

| File | SHA-256 |
| --- | --- |
| `mp-export/tests/browser/conftest.py` | `24877c436e4aab81959a258013c790acb0bfb6014ebd06be781d8927d9aa3300` |
| `mp-export/tests/browser/test_online_map_ui.py` | `cacebf5f7fef4a6e0a4e01e056ce0cab64d46cd4e4096c86c3babea3be436b24` |
| `mp-export/tests/test_online_map_html.py` | `ebbaaafb0c63ec3f63098fe6d3271773a7b859d5da8b12929175dff4f1af194c` |
| `mp-verify/tests/test_description_comparison_behavior.py` | `3e5e93f0ac743dbcbd1446a4ff59b82f468e46c8f71befbf18cb9be7719be951` |
