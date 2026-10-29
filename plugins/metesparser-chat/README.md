# MetesParser review — Claude chat Skill

This standalone Skill archive is for Claude chat users who work with uploaded source documents or prepared MetesParser inputs and want source-linked metes-and-bounds parsing, review, plotting, or delivery. It contains one discovered skill, `metesparser-review`, with thirteen routed procedures; install it as a Skill ZIP, not as a plugin ZIP.

## Install

1. Build or obtain the complete `metesparser-chat-skill.zip` archive and its `.sha256` sidecar. Verify with `shasum -a 256 -c metesparser-chat-skill.zip.sha256`. Keep the enclosed `metesparser-review/` folder and its files together; do not substitute the plugin ZIP or upload an individual procedure.
2. In Claude, open **Customize → Skills**, choose **Upload skill**, and upload the ZIP. Do not use the plugin uploader.
3. Enable code execution for the chat session. The runtime needs Python 3.11+, executable bundled files, writable host storage, and network access to pinned dependencies on first use unless a compatible cache is already present. Before the first engine request in a session, run the [explicit runtime setup](references/chat-runtime.md#dependency-bootstrap) and confirm it succeeds.
4. Upload the source document or prepared input and ask for the requested result. The skill routes the request to one of its thirteen procedures.

The Skill runs in the current host's execution environment. A Python or `uv` installation on the user's computer does not provision the chat runtime. It does not use repository `.env` files or laptop credentials. See [runtime requirements and setup](references/chat-runtime.md).

## Use and retain results

The skill uses the shared MetesParser engine for deterministic parsing, geometry, checks, and rendering. It preserves unknown bearings and source uncertainties and separates source review, geometry, verification, and delivery status. It writes each run to a fresh host-writable directory.

Download and retain the complete result-folder ZIP. To continue in a later session, upload that ZIP with the new source or requested change, have the host unpack it into a fresh directory, and ask the Skill to run read-only `inspect-artifacts` on the relevant extracted bundle directory for the requested stage before reusing prior outputs. Inspection checks known artifact identities and dependencies and recommends where to resume; it does not validate a ZIP directly or search arbitrary nested folders. HTML files may need to be downloaded and opened in an external browser. The host may not reach a generated localhost URL, and online map/MCP access is not guaranteed.

Native Claude chat installation, skill discovery, document reading, runtime provisioning, and end-to-end acceptance have not yet been verified. Local packaging checks do not establish those host gates.

## Skills

The `metesparser-review` entrypoint routes among thirteen procedures under `skills/`. See [the skill instructions](SKILL.md) for the route table and outputs. Shared contracts live under `references/` and are loaded only when the selected procedure needs them.
