# Workstream G: skill integration and distribution documentation

Date: 2026-10-28. Owner: `/root/skill_docs` (Codex subagent; exact runtime model version not exposed). Plan: [source evidence, diagnostics, maps, and composable skills](../plans/2026-10-28-skill-evidence-and-review-improvements.md), workstream G. No commits. Scope: skill entrypoints, plugin shared references/catalog/changelog, and this evidence record.

## Documentation changes

- Replaced the informal schema 1.0 source-record examples with schema 1.1 source/page/transcript/path/hash/uncertainty and description-span fields, canonical model/example links, root-bounded validation command, advisory exit behavior, and a no-invented-facts migration procedure.
- Added standalone closure-diagnosis and bounded artifact-inspection usage to the relevant skills and handoff reference. Dashboard diagnosis remains separate from canonical results; inspection is conditional when freshness/dependencies are unclear.
- Documented per-raster visibility, opacity and raise/lower controls, fit versus independent checkpoint residuals, frame/basis/unit/placement summaries, and presentation-only state.
- Added the `compare-descriptions` capability and its focused limits reference after F supplied the frozen request model, fixture and CLI flag. Preserved all prior skill names, the `review-deed` alias, and the 2 workflow structure. Catalog: seven capabilities, two workflows, one alias.

## Local validation

Commands run from the repository root on 2026-10-28:

```sh
uv run pytest plugins/metesparser/tests/test_launcher.py -q --no-cov --import-mode=importlib
```

Result: **19 passed**. This covers launcher forwarding for `validate-source`, `inspect-artifacts`, `diagnose-closure`, and `compare-descriptions`, including retention of `needs_review` / exit 1.

```sh
uv run pytest tests/unit/test_plugin_build.py::test_plugin_archive_includes_standalone_online_map_capability -q --no-cov
```

Result: **1 passed**. This existing test checks archive inclusion of the online-map entrypoint and absence of evaluation material; it does **not** assert discovery of the new comparison skill.

The repository has no dedicated skill-manifest/discovery test. A read-only inventory found ten `skills/*/SKILL.md` entrypoints with unique names (seven capabilities, two workflows, one alias). That inventory and link scan were performed together with:

```sh
uv run python -c 'from pathlib import Path; import re; root=Path("plugins/metesparser"); bad=[]; links=0
for f in root.rglob("*.md"):
 t=f.read_text()
 for dest in re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", t):
  dest=dest.split()[0].strip("<>")
  if ":" in dest or dest.startswith("#"): continue
  target=dest.split("#",1)[0]
  if target:
   links+=1
   if not (f.parent/target).exists(): bad.append((str(f),dest))
skills=sorted(p.name for p in (root/"skills").iterdir() if p.is_dir() and (p/"SKILL.md").exists())
print("local markdown links checked:",links,"broken:",len(bad))
print("discovered skill entrypoints:",len(skills),", ".join(skills))
assert not bad and len(skills)==10'
```

Result: **195 local markdown links checked, 0 broken**; discovered `compare-descriptions`, `convert-document-to-text`, `deed-closure-dashboard`, `extract-metes-and-bounds`, `plot-metes-and-bounds`, `prepare-parcel-overlay`, `render-online-map`, `review-deed`, `review-metes-and-bounds`, and `verify-traverse`.

## Integration and remaining gates

- Parent-owned `tests/unit/test_plugin_build.py` should add a focused archive/discovery assertion for `skills/compare-descriptions/SKILL.md` and its README if desired; existing build coverage is renderer-specific.
- Source/diagnosis implementation evidence is in [source-handoffs-evidence.md](source-handoffs-evidence.md) and [diagnostics-evidence.md](diagnostics-evidence.md). F's fixture and supported comparison contract are linked by the new skill/reference. Skill prose does not establish runtime acceptance by itself.
- No extracted plugin was built/launched outside the checkout in this workstream. Native Claude document reading, paired model behavior evaluations, native map display, and live Mapbox acceptance remain **not run** here. The evaluation recommendation/todo 6 remains open until its observed paired transcripts and scores exist; authored cases or plugin checks do not complete it.

## Chronological follow-up: packaged navigation and runtime acceptance

The validation above is the original G workstream snapshot. Subsequent work superseded its archive/discovery and extracted-runtime statements without changing that historical record:

- `tests/unit/test_packaged_skill_navigation.py` now extracts a built plugin and checks that comparison, source-handoff, and diagnosis documentation links stay inside the archive; packaged schemas match the current public models; and the shipped examples execute through the runtime validators/engines. Its four tests passed in the focused navigation/evaluation suite. See [independent navigation review](evaluation-navigation-independent-review.md#green).
- Both plugin variants were later built and launched from extracted directories outside the checkout. The earlier smoke ran 16 commands per archive and passed the recorded exact-input, read-only, advisory-export, vector, and raster assertions. Its report remains at `/private/tmp/metesparser-release-smoke-20261028/runs/final/results/run.json`. The [completion-audit follow-up](2026-10-28-evidence-review-ledger.md#completion-audit-follow-up) records the authoritative rebuilt archives and extended 20-command smoke after the inspector fixes.
- These local packaging/runtime checks do not establish native skill discovery or source-reading accuracy, paired model behavior, visible native-client display, or live Mapbox provider acceptance. Those gates remain separate; todo 6 remains open.
