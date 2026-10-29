"""Adapt the shared Claude plugin into one self-contained Claude chat Skill ZIP."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import posixpath
import re
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
CHAT_TEMPLATE = ROOT / "plugins/metesparser-chat"
SKILL_ROOT = "metesparser-review"
_spec = importlib.util.spec_from_file_location(
    "metesparser_plugin_builder", ROOT / "scripts/build_claude_plugin.py"
)
assert _spec is not None and _spec.loader is not None
plugin_builder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(plugin_builder)
LINK = re.compile(r"(\]\()([^\s)]+)([^)]*\))")
EXCLUDED_PARTS = {
    ".claude-plugin",
    "tests",
    "evals",
    "__pycache__",
    ".DS_Store",
    ".venv",
    ".uv-cache",
}


def _adapt_markdown(text: str, source: str) -> str:
    """Retain relative layout while changing discoverable skills into procedures."""
    if source.startswith("skills/") and source.endswith("/SKILL.md"):
        text = re.sub(r"\A---\r?\n.*?\r?\n---(?:\r?\n|\Z)", "", text, count=1, flags=re.DOTALL)
    text = text.replace("CLAUDE_PLUGIN_ROOT", "METESPARSER_SKILL_ROOT")
    text = text.replace("SKILL.md", "WORKFLOW.md")
    text = text.replace("scripts/run-review.py", "scripts/run-chat.py")
    text = text.replace(
        "uv run metes-review", 'python3 "${METESPARSER_SKILL_ROOT}/scripts/run-chat.py"'
    )
    text = re.sub(r"plugins/metesparser/([^\s`\"]+)", r'"${METESPARSER_SKILL_ROOT}/\1"', text)
    if source == "references/usage.md":
        text = re.sub(
            r"(?m)^Load the extracted plugin using .*?$",
            "Upload the complete Skill ZIP and enable code execution in Claude chat. "
            "Follow [chat runtime setup](chat-runtime.md) before running the engine. "
            "Supply the document and request the relevant deliverable; native document reading "
            "must be available in that session. Native chat acceptance remains separate from local packaging checks.",
            text,
        )
        text = re.sub(
            r"(?m)^The Python launcher requires Python 3\.11\+ and .*?$",
            "Follow [chat runtime prerequisites and explicit setup](chat-runtime.md). "
            "Use the extracted Skill distribution and its chat wrapper. Report missing runtime "
            "prerequisites without claiming an engine run; optional geo/web-map operations "
            "require a distribution carrying their dependencies.",
            text,
        )
    if source == "skills/render-online-map/references/local-viewer.md":
        text = re.sub(
            r"(?m)^In a source checkout, install optional dependencies .*?$",
            "Use a chat Skill archive built with the web-map dependency profile for raster "
            "reprojection. Follow [chat runtime setup](../../../references/chat-runtime.md), "
            "then use the packaged chat wrapper. Default and minimal archives report missing "
            "optional dependencies; do not substitute model calculations.",
            text,
        )

    def rewrite(match: re.Match[str]) -> str:
        target = match[2]
        if urlsplit(target).scheme or target.startswith("#"):
            return match[0]
        path = target.split("#", 1)[0]
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(source), path))
        if resolved == "README.md" and not (CHAT_TEMPLATE / "README.md").is_file():
            target = posixpath.relpath("SKILL.md", posixpath.dirname(source) or ".")
        return match[1] + target + match[3]

    return LINK.sub(rewrite, text)


def _validate(files: dict[str, bytes]) -> None:
    skills = [name for name in files if Path(name).name == "SKILL.md"]
    if skills != ["SKILL.md"]:
        raise ValueError("chat archive must contain exactly one root SKILL.md")
    for name, content in files.items():
        if not name.endswith(".md"):
            continue
        text = content.decode("utf-8")
        if "CLAUDE_PLUGIN_ROOT" in text or str(ROOT) in text:
            raise ValueError(f"unadapted source-checkout reference in {name}")
        for match in LINK.finditer(text):
            target = match[2].strip("<>")
            if urlsplit(target).scheme or target.startswith("#"):
                continue
            path = unquote(target.split("#", 1)[0])
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), path))
            if resolved not in files:
                raise ValueError(f"missing packaged Markdown target in {name}: {target}")


def build(output: Path, *, offline: bool = False, geo: bool = True, web_map: bool = False) -> Path:
    """Reuse the plugin's exact engine build, adapting only the instruction layer."""
    if web_map and not geo:
        raise ValueError("web-map requires geo support")
    if not (CHAT_TEMPLATE / "SKILL.md").is_file():
        raise FileNotFoundError(f"chat Skill template is missing: {CHAT_TEMPLATE / 'SKILL.md'}")
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    # Staging beside the destination permits atomic publication of each completed file.
    with tempfile.TemporaryDirectory(prefix=".metesparser-chat-", dir=output.parent) as temporary:
        staging = Path(temporary)
        plugin_zip = plugin_builder.build(
            staging / "plugin.zip", offline=offline, geo=geo, web_map=web_map
        )
        files: dict[str, bytes] = {}
        with zipfile.ZipFile(plugin_zip) as archive:
            for name in archive.namelist():
                path = Path(name)
                if (
                    name.endswith("/")
                    or EXCLUDED_PARTS.intersection(path.parts)
                    or name == "README.md"
                ):
                    continue
                content = archive.read(name)
                if name.endswith(".md") and not name.startswith("runtime/"):
                    content = _adapt_markdown(content.decode("utf-8"), name).encode("utf-8")
                if path.name == "SKILL.md" and name.startswith("skills/"):
                    name = str(path.with_name("WORKFLOW.md"))
                files[name] = content
        # Chat-specific entrypoint, runtime guidance and bootstrap override shared resources.
        for path in sorted(CHAT_TEMPLATE.rglob("*")):
            relative = path.relative_to(CHAT_TEMPLATE)
            if path.is_file() and not EXCLUDED_PARTS.intersection(relative.parts):
                if relative.parts[0] == "runtime":
                    raise ValueError("chat templates cannot replace the shared engine runtime")
                if relative.as_posix() == "scripts/run-review.py":
                    raise ValueError("chat templates cannot replace the shared engine launcher")
                files[relative.as_posix()] = path.read_bytes()
        _validate(files)
        staged_zip = staging / "skill.zip"
        with zipfile.ZipFile(staged_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in sorted(files.items()):
                archive.writestr(f"{SKILL_ROOT}/{name}", content)
        digest = hashlib.sha256(staged_zip.read_bytes()).hexdigest()
        sidecar = staging / "skill.zip.sha256"
        sidecar.write_text(f"{digest}  {output.name}\n", encoding="utf-8")
        os.replace(staged_zip, output)
        os.replace(sidecar, output.with_suffix(output.suffix + ".sha256"))
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/metesparser-chat-skill.zip")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument(
        "--without-geo", action="store_true", help="Omit optional map import dependencies"
    )
    parser.add_argument(
        "--with-web-map",
        action="store_true",
        help="Include optional online map preparation dependencies",
    )
    args = parser.parse_args()
    if args.with_web_map and args.without_geo:
        parser.error("--with-web-map requires geo; cannot combine with --without-geo")
    print(
        build(
            args.output, offline=args.offline, geo=not args.without_geo, web_map=args.with_web_map
        )
    )


if __name__ == "__main__":
    main()
