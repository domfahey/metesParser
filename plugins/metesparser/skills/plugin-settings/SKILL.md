---
name: plugin-settings
description: Add or maintain per-project Claude plugin configuration using .claude/plugin-name.local.md YAML frontmatter, validated defaults, and user-local state. Use for configurable plugin behavior or settings parsers.
metadata:
  version: "0.1.0"
---

# Plugin settings

Inspect the plugin's existing settings schema and readers before adding configuration. Store user-managed project settings at `.claude/<plugin-name>.local.md`; keep them out of Git with `.claude/*.local.md` and `.claude/*.local.json`. Ship a documented template rather than a live user settings file.

Parse only the first YAML frontmatter block with a safe YAML parser. Reject malformed frontmatter, duplicate keys, unsupported settings, and wrong types. Do not parse YAML with grep/sed or treat the Markdown body as executable instructions. Define defaults for an absent file, and document CLI precedence and how the project directory is selected. Check path containment using resolved paths, including symlinks.

Keep configuration narrow. User settings must not bypass mandatory validation, fabricate missing data, or silently change geometric tolerances. Read `enabled` before processing; disabled runs must create no review artifacts. Avoid conflating configuration with mutable task state or rewriting user-owned files during normal runs.

For this plugin, use the supported schema and precedence in [MetesParser settings](../../references/plugin-settings.md). The launcher rereads settings for each invocation, so these settings do not require a Claude restart. Other plugins that load configuration only at session or hook registration time may require a restart; document the actual lifecycle.

Test missing files, disabled mode, quoted and invalid booleans, duplicate/unknown keys, malformed YAML, path escape, CLI overrides, and repeated invocations. Verify any new dependency is included in the distributable runtime lock.
