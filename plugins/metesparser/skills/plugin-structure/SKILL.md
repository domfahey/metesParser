---
name: plugin-structure
description: Create or organize Claude Code plugins, configure plugin.json, component auto-discovery, and portable plugin paths. Use for plugin scaffolding or architecture changes.
metadata:
  version: "0.1.0"
---

# Plugin structure

Inspect the existing plugin before creating files. Put its manifest at `.claude-plugin/plugin.json`; put `skills/`, `commands/`, `agents/`, `hooks/`, and `scripts/` at the plugin root. Create only components the requested workflow uses.

Use a unique kebab-case manifest name, semantic version, concise description, and author. Prefer conventional directories and auto-discovery over redundant component paths. Custom manifest paths start with `./` and supplement conventional paths. Skill entries point to directories containing `SKILL.md`, not the Markdown file itself.

Each skill belongs in `skills/<kebab-case-name>/SKILL.md` with frontmatter `name` and a description explaining when to use it. Put detailed guidance in references and repeatable execution in scripts. Use kebab-case names for supporting scripts and references.

Use `${CLAUDE_PLUGIN_ROOT}` for paths in components, quote paths in shell commands, and resolve helpers relative to their script location where that variable is unavailable. Never depend on the caller's working directory to locate plugin resources. Per-project user settings are a separate concern: see [Plugin Settings](../plugin-settings/SKILL.md).

Document prerequisites and actual install methods in the root README. Validate the plugin with `claude plugin validate PATH --strict --json`, then exercise its scripts from an unrelated working directory and a path containing spaces. Distinguish manifest validation from actual client installation and end-to-end acceptance. Do not invent a marketplace installation target or create unused hooks, agents, or MCP servers.
