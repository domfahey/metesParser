# Claude chat runtime

The chat archive carries the review launcher and pinned MetesParser runtime artifacts. The execution host needs Python 3.11+, permission to execute Python, writable output/cache storage, and network access to fetch pinned third-party dependencies on first use unless a compatible runtime/cache is already provisioned. Setup uses a `uv` already on `PATH` (used as found, not verified against the pin), otherwise a cached pinned `uv` whose hash is verified, otherwise downloads and verifies the pinned copy. The archive does not include every third-party wheel. Runtime availability is per host/session; do not rely on laptop installations, repository files, inherited environment variables, credentials, or persistent shell state.

## Locate the launcher

Set `METESPARSER_SKILL_ROOT` to the directory from which you read this skill's `SKILL.md`. Set that variable explicitly, then call `python3 "$METESPARSER_SKILL_ROOT/scripts/run-chat.py"`. Do not use an inherited or guessed root. If you cannot determine that directory, stop and report that the launcher cannot be located safely.

Each tool execution may start in a fresh process. Set the root and invoke the wrapper in the same request; do not expect shell variables, installed packages, or temporary paths to persist between requests. Run from a host-writable working directory and use absolute input/output paths. Chat has no project settings, so always pass `--output-dir` with a new directory. Keep output directories fresh and inside a location the current host permits the user to download.

## Dependency bootstrap

Run setup explicitly before the first engine command:

```sh
METESPARSER_SKILL_ROOT="/actual/extracted/path"
python3 "$METESPARSER_SKILL_ROOT/scripts/run-chat.py" --setup
```

The wrapper uses a `uv` already on `PATH` as found (it is not verified against the pin), otherwise the cached pinned `uv` 0.9.6 after checking its hash, otherwise downloads the pinned wheel (see [`uv-bootstrap.json`](uv-bootstrap.json)), verifies its size and hashes and caches it, then runs a locked dependency sync. For an offline setup, use:

```sh
METESPARSER_SKILL_ROOT="/actual/extracted/path"
python3 "$METESPARSER_SKILL_ROOT/scripts/run-chat.py" --setup --offline
```

Offline setup uses only host/cached `uv` and cached dependencies. If they are unavailable, setup fails; do not switch to an unpinned install. Normal operation accepts the original launcher arguments and preserves its JSON output and exit codes. It does not install `uv` automatically during normal operation; the launcher may provision locked dependencies from the network as the original does. Setup and caches belong to the current execution host/session, do not read project `.env` files, and do not request credentials. If setup fails, report the runtime error and do not claim an engine result.

## Network hosts

An administrator who restricts network access needs to allow `files.pythonhosted.org` (the pinned `uv` wheel named in [`uv-bootstrap.json`](uv-bootstrap.json), and the locked dependency wheels) and `pypi.org` (the PyPI index used by `uv sync`). No other host is contacted by setup. `--setup --offline` never downloads anything.

## Output and host limits

Use the procedure's required command and preserve its exact exit status and JSON status. Code execution or download limits may constrain large deeds or bundles; report a blocked or incomplete operation with its available artifacts. Package the complete result directory, including source/handoff records and revision identity files, as a ZIP for download and later reupload. Revalidate artifacts when they return in a later session.

Generated HTML is an artifact, not proof that embedded scripts run in chat. Provide it for download and use an external browser when needed; do not assume the chat browser can reach localhost. Online Mapbox rendering and MCP calls require the specific user request, runtime extras, provider/connector availability, and procedure-specific evidence. Keep offline artifacts usable and report unavailable host gates separately. Native chat acceptance remains pending.
