# MetesParser project settings

Create `.claude/metesparser.local.md` in the project from which you run the launcher:

```markdown
---
enabled: true
output_dir: deed-reviews
---

Optional project notes. The engine ignores this Markdown body.
```

The file is optional and user-managed; use `chmod 600 .claude/metesparser.local.md` when notes are private. Do not commit it. The plugin never creates or rewrites this file automatically.

| Field | Type | Default | Behavior |
| --- | --- | --- | --- |
| `enabled` | YAML boolean | `true` | `false` stops processing with exit 2 and error code `plugin_disabled`, without creating review artifacts. |
| `output_dir` | Project-relative string | unset | Base directory for fresh `review-<unique-id>` folders when no explicit `--output-dir` is supplied. |

The launcher selects `.claude/metesparser.local.md` relative to its caller's working directory, not its installation directory or the input file's directory. Run it from the intended project root. An explicit `--settings PATH` selects another settings file; configured relative output paths resolve from that file's grandparent (the project directory containing `.claude`). Plain `python -m mp_review` loads settings only when `--settings` is supplied.

An explicit `--output-dir` takes precedence over a configured output base. Without either, processing returns `invalid_settings` (exit 2). Explicit output paths retain the existing new-directory requirement. A configured base may exist; every run gets a fresh child. The `corpus` command honors `enabled` and validates settings, but keeps its explicit `--output` report behavior.

Unsupported keys, duplicate keys, non-boolean `enabled`, malformed frontmatter, absolute configured paths, and configured paths escaping the project (including symlinks) fail with `invalid_settings` before processing. No setting changes parsing strictness, closure tolerance, bearings, units, or verification/export gates. Missing settings use current CLI defaults. Settings are read every run; no restart is needed.
