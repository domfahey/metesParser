"""Distribution contracts for the standalone chat Skill adapter."""

import hashlib
import importlib.util
import json
import posixpath
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_builder():
    spec = importlib.util.spec_from_file_location(
        "chat_skill_builder", ROOT / "scripts/build_claude_skill.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def builder(tmp_path, monkeypatch):
    module = load_builder()
    template = tmp_path / "template"
    template.mkdir()
    plugin = ROOT / "plugins/metesparser"
    links = [
        f"[{path.parent.name}](skills/{path.parent.name}/WORKFLOW.md)"
        for path in sorted((plugin / "skills").glob("*/SKILL.md"))
    ] + [
        f"[{path.stem}](references/{path.name})"
        for path in sorted((plugin / "references").glob("*.md"))
        if path.name != "plugin-settings.md"
    ]
    (template / "SKILL.md").write_text(
        "---\nname: metesparser-review\n"
        "description: Review deeds. Use when the user asks to check a legal description.\n---\n"
        + "\n".join(links)
        + "\n[Runtime](references/chat-runtime.md)\n"
    )
    (template / "references").mkdir()
    (template / "references/chat-runtime.md").write_text("Use the packaged runtime.\n")
    (template / "README.md").write_text("# Chat Skill\n\n## Skills\n[Instructions](SKILL.md)\n")
    (template / "scripts").mkdir()
    (template / "scripts/run-chat.py").write_text("# Chat bootstrap wrapper\n")
    monkeypatch.setattr(module, "CHAT_TEMPLATE", template)
    monkeypatch.setattr(module.plugin_builder.shutil, "which", lambda name: "/fake/uv")

    def fake_run(arguments, *, cwd):
        if arguments[1] == "build":
            output_dir = Path(arguments[arguments.index("--out-dir") + 1])
            package = arguments[arguments.index("--package") + 1]
            (output_dir / f"{package.replace('-', '_')}-1.0.0-py3-none-any.whl").write_bytes(
                b"wheel"
            )
        elif arguments[1] == "lock":
            (Path(arguments[arguments.index("--project") + 1]) / "uv.lock").write_text(
                "version = 1\n"
            )

    monkeypatch.setattr(module.plugin_builder, "run", fake_run)
    return module


def test_archive_has_one_skill_and_closed_navigation(builder, tmp_path):
    output = builder.build(tmp_path / "skill.zip")
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        assert {name.split("/")[0] for name in names} == {"metesparser-review"}
        assert [name for name in names if name.endswith("/SKILL.md")] == [
            "metesparser-review/SKILL.md"
        ]
        assert not any(
            ".claude-plugin" in name or "/tests/" in name or "/evals/" in name for name in names
        )
        assert "metesparser-review/README.md" in names
        assert "metesparser-review/CHANGELOG.md" not in names
        for name in sorted(names):
            if not name.endswith(".md"):
                continue
            text = archive.read(name).decode()
            assert "CLAUDE_PLUGIN_ROOT" not in text
            for phrase in builder.FORBIDDEN:
                assert phrase not in text.lower(), (name, phrase)
            assert "/scripts/run-review.py" not in text
            assert "plugins/metesparser/" not in text
            assert str(ROOT) not in text
            if name.endswith("/WORKFLOW.md"):
                assert not text.startswith("---\n")
            for target in re.findall(r"\]\(([^)]+)\)", text):
                target = target.split()[0].strip("<>")
                if urlsplit(target).scheme or target.startswith("#"):
                    continue
                path = unquote(target.split("#")[0])
                resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), path))
                assert resolved in names, (name, target, resolved)
            for script_path in re.findall(r"\$\{METESPARSER_SKILL_ROOT\}/([^\s\"`]+)", text):
                assert "metesparser-review/" + script_path in names, (name, script_path)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    assert output.with_suffix(".zip.sha256").read_text() == f"{digest}  skill.zip\n"


def test_engine_files_and_fingerprint_are_preserved(builder, tmp_path):
    plugin = builder.plugin_builder.build(tmp_path / "plugin.zip", offline=True, geo=False)
    skill = builder.build(tmp_path / "skill.zip", offline=True, geo=False)
    with zipfile.ZipFile(plugin) as original, zipfile.ZipFile(skill) as adapted:
        for name in original.namelist():
            if name.startswith("runtime/"):
                assert adapted.read("metesparser-review/" + name) == original.read(name)
        metadata = json.loads(adapted.read("metesparser-review/runtime/engine.json"))
        assert adapted.read("metesparser-review/scripts/run-review.py") == original.read(
            "scripts/run-review.py"
        )
        assert (
            hashlib.sha256(json.dumps(metadata["sha256"], sort_keys=True).encode()).hexdigest()
            == metadata["fingerprint"]
        )
        for name, digest in metadata["sha256"].items():
            assert (
                hashlib.sha256(adapted.read("metesparser-review/runtime/" + name)).hexdigest()
                == digest
            )


@pytest.mark.parametrize("geo,web_map", [(False, False), (True, False), (True, True)])
def test_profiles_are_forwarded_to_shared_builder(builder, tmp_path, monkeypatch, geo, web_map):
    original = builder.plugin_builder.build
    calls = []

    def record(output, **kwargs):
        calls.append(kwargs)
        return original(output, **kwargs)

    monkeypatch.setattr(builder.plugin_builder, "build", record)
    builder.build(tmp_path / "skill.zip", offline=True, geo=geo, web_map=web_map)
    assert calls == [{"offline": True, "geo": geo, "web_map": web_map}]


def test_invalid_profile_fails_before_building(builder, tmp_path, monkeypatch):
    monkeypatch.setattr(
        builder.plugin_builder, "build", lambda *a, **k: pytest.fail("must not build")
    )
    with pytest.raises(ValueError, match="requires geo"):
        builder.build(tmp_path / "skill.zip", geo=False, web_map=True)
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/build_claude_skill.py"),
            "--without-geo",
            "--with-web-map",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "requires geo" in result.stderr


def test_failed_build_preserves_previous_artifacts(builder, tmp_path, monkeypatch):
    output = tmp_path / "skill.zip"
    output.write_bytes(b"previous archive")
    sidecar = output.with_suffix(".zip.sha256")
    sidecar.write_text("previous digest")

    def fail(*args, **kwargs):
        raise RuntimeError("engine build failed")

    monkeypatch.setattr(builder.plugin_builder, "build", fail)
    with pytest.raises(RuntimeError, match="engine build failed"):
        builder.build(output)
    assert output.read_bytes() == b"previous archive"
    assert sidecar.read_text() == "previous digest"


def test_broken_overlay_navigation_does_not_publish(builder, tmp_path):
    output = tmp_path / "skill.zip"
    output.write_bytes(b"previous archive")
    sidecar = output.with_suffix(".zip.sha256")
    sidecar.write_text("previous digest")
    (builder.CHAT_TEMPLATE / "SKILL.md").write_text(
        "---\nname: metesparser-review\ndescription: Reviews deeds. Use when asked.\n---\n"
        "[Missing](missing.md)\n"
    )
    with pytest.raises(ValueError, match="missing packaged Markdown target"):
        builder.build(output)
    assert output.read_bytes() == b"previous archive"
    assert sidecar.read_text() == "previous digest"


def test_chat_overlay_cannot_replace_shared_runtime(builder, tmp_path):
    runtime = builder.CHAT_TEMPLATE / "runtime"
    runtime.mkdir()
    (runtime / "engine.json").write_text("{}")
    with pytest.raises(ValueError, match="cannot replace the shared engine runtime"):
        builder.build(tmp_path / "skill.zip")
    assert not (tmp_path / "skill.zip").exists()


def test_chat_overlay_cannot_replace_shared_launcher(builder, tmp_path):
    (builder.CHAT_TEMPLATE / "scripts/run-review.py").write_text("# overwritten")
    with pytest.raises(ValueError, match="cannot replace the shared engine launcher"):
        builder.build(tmp_path / "skill.zip")


def test_real_chat_template_runs_closed_packaged_navigation(builder, tmp_path, monkeypatch):
    monkeypatch.setattr(builder, "CHAT_TEMPLATE", ROOT / "plugins/metesparser-chat")
    output = builder.build(tmp_path / "skill.zip")
    with zipfile.ZipFile(output) as archive:
        usage = archive.read("metesparser-review/references/usage.md").decode()
        assert "claude --plugin-dir" not in usage
        assert "source plugin directory" not in usage
        assert "(chat-runtime.md)" in usage
        assert "../README.md#skills" in usage
        example = archive.read(
            "metesparser-review/skills/deed-closure-dashboard/references/dashboard-bundle.md"
        ).decode()
        assert (
            'python3 "${METESPARSER_SKILL_ROOT}/scripts/run-chat.py" dashboard "${METESPARSER_SKILL_ROOT}/skills/deed-closure-dashboard/references/dashboard-example.json"'
            in example
        )
        assert (
            archive.read("metesparser-review/scripts/run-chat.py")
            == (ROOT / "plugins/metesparser-chat/scripts/run-chat.py").read_bytes()
        )


@pytest.fixture
def real(builder, monkeypatch):
    monkeypatch.setattr(builder, "CHAT_TEMPLATE", ROOT / "plugins/metesparser-chat")
    return builder


def _read(output):
    with zipfile.ZipFile(output) as archive:
        return {
            name.removeprefix("metesparser-review/"): archive.read(name)
            for name in archive.namelist()
        }


def _frontmatter_description(text):
    match = re.match(r"---\n(.*?)\n---", text, flags=re.DOTALL)
    return re.search(r"(?m)^description: (.*)$", match[1])[1]


def test_real_skill_description_is_a_short_third_person_trigger():
    text = (ROOT / "plugins/metesparser-chat/SKILL.md").read_text()
    description = _frontmatter_description(text)
    assert len(description) <= 200
    assert "Use when" in description
    assert not re.match(r"(?i)(i|you|we)\b", description)
    assert re.search(r"(?m)^name: metesparser-review$", text)


@pytest.mark.parametrize(
    "description,message",
    [
        ("Routes uploaded deeds through review procedures.", "Use when"),
        ("Reviews deeds. Use when " + "x" * 200, "exceeds 200"),
    ],
)
def test_validate_rejects_bad_descriptions(builder, description, message):
    skill = f"---\nname: metesparser-review\ndescription: {description}\n---\n"
    with pytest.raises(ValueError, match=message):
        builder._validate({"SKILL.md": skill.encode()})


GOOD_SKILL = (
    "---\nname: metesparser-review\n"
    "description: Reviews deeds. Use when asked to check one.\n---\n"
    "[next](references/next.md)\n"
)


@pytest.mark.parametrize(
    "phrase",
    [
        "the plugin root",
        "Plugin Root",
        "the project root",
        "the repository root",
        "/tmp/output",
        "Claude Code",
        "${CLAUDE_PLUGIN_ROOT}/scripts",
        "see .claude/metesparser.local.md",
    ],
)
def test_validate_rejects_plugin_only_phrasing(builder, phrase):
    files = {
        "SKILL.md": GOOD_SKILL.encode(),
        "references/next.md": f"# Next\n\n{phrase}\n".encode(),
    }
    with pytest.raises(ValueError, match="unadapted"):
        builder._validate(files)
    files["references/next.md"] = b"# Next\n\nNothing plugin-specific.\n"
    builder._validate(files)


def test_validate_rejects_unlinked_files_but_not_engine_files(builder):
    files = {
        "SKILL.md": GOOD_SKILL.encode(),
        "references/next.md": b"# Next\n",
        "runtime/engine.json": b"{}",
        "scripts/run-chat.py": b"",
    }
    builder._validate(files)
    files["references/orphan.md"] = b"# Orphan\n"
    with pytest.raises(ValueError, match="not linked from SKILL.md: references/orphan.md"):
        builder._validate(files)


def test_files_named_by_linked_json_records_count_as_linked(builder):
    files = {
        "SKILL.md": GOOD_SKILL.replace("next.md", "bundle/record.json").encode(),
        "references/bundle/record.json": json.dumps({"items": [{"path": "payload.txt"}]}).encode(),
        "references/bundle/payload.txt": b"x",
    }
    builder._validate(files)


def test_real_archive_ships_only_linked_navigation_files(real, tmp_path):
    files = _read(real.build(tmp_path / "skill.zip"))
    names = set(files)
    assert not [n for n in names if n.endswith("CHANGELOG.md") or n.endswith("plugin-settings.md")]
    assert not [n for n in names if re.fullmatch(r"skills/[^/]+/README\.md", n)]
    # _validate already proves reachability; recompute it independently of the builder's helper.
    reached, pending = {"SKILL.md"}, ["SKILL.md"]
    while pending:
        current = pending.pop()
        if not current.endswith(".md"):
            continue
        for target in re.findall(r"\]\(([^)\s]+)", files[current].decode()):
            if urlsplit(target).scheme or target.startswith("#"):
                continue
            resolved = posixpath.normpath(
                posixpath.join(posixpath.dirname(current), unquote(target.split("#")[0]))
            )
            if resolved in names and resolved not in reached:
                reached.add(resolved)
                pending.append(resolved)
    for record in [n for n in names if n.endswith(".json") and n in reached]:
        for item in re.findall(r'"path":\s*"([^"]+)"', files[record].decode()):
            reached.add(posixpath.normpath(posixpath.join(posixpath.dirname(record), item)))
    unlinked = {n for n in names if n not in reached and not n.startswith(("runtime/", "scripts/"))}
    assert not unlinked


def test_real_references_over_100_lines_have_a_contents_list(real, tmp_path):
    files = _read(real.build(tmp_path / "skill.zip"))
    long_files = [
        name
        for name, content in files.items()
        if name.endswith(".md")
        and name.startswith(("references/", "skills/"))
        and len(content.decode().splitlines()) > 100
    ]
    assert long_files
    for name in long_files:
        assert re.search(r"(?mi)^#{2,3} (table of )?contents$", files[name].decode()), name


def test_contents_list_is_generated_with_working_anchors(builder):
    body = "\n".join(f"line {i}" for i in range(120))
    text = (
        f"# Title\n\nIntro.\n\n## First `part`\n\n{body}\n\n```sh\n# not a heading\n```\n\n"
        "## Second, part\n"
    )
    adapted = builder._adapt_markdown(text, "references/long.md")
    assert adapted.splitlines()[:4] == ["# Title", "", "## Contents", ""]
    assert "- [First `part`](#first-part)" in adapted
    assert "- [Second, part](#second-part)" in adapted
    assert "not a heading" not in adapted.split("## First")[0]
    short = builder._adapt_markdown("# Short\n\n## One\n\n## Two\n", "references/short.md")
    assert "## Contents" not in short
    already = "# T\n\n## Contents\n\n- x\n\n## A\n\n## B\n" + body
    assert builder._adapt_markdown(already, "references/x.md").count("## Contents") == 1


FALLBACK = "never guess the launcher location"


@pytest.mark.parametrize(
    "source,text,expected,absent",
    [
        (
            "skills/a/SKILL.md",
            "Locate the launcher relative to the skill's plugin root if `METESPARSER_SKILL_ROOT` is unavailable.",
            FALLBACK,
            "plugin root",
        ),
        (
            "skills/a/references/b.md",
            "If `METESPARSER_SKILL_ROOT` is unavailable, locate the archive root relative to this procedure file.",
            "../../../references/chat-runtime.md#locate-the-launcher",
            "relative to this procedure",
        ),
        (
            "skills/a/SKILL.md",
            "In environments without `METESPARSER_SKILL_ROOT`, locate the plugin root relative to this skill file and use the same launcher through `python3`.",
            FALLBACK,
            "plugin root",
        ),
        (
            "skills/a/SKILL.md",
            "Plugin root: `${CLAUDE_PLUGIN_ROOT}`\n\nNext paragraph.",
            "Next paragraph.",
            "Plugin root",
        ),
        (
            "skills/a/SKILL.md",
            "Commands below use the plugin root that the invoking skill printed; substitute it for `${CLAUDE_PLUGIN_ROOT}`.",
            "Commands below use `${METESPARSER_SKILL_ROOT}`, set as described in [chat runtime](../../references/chat-runtime.md#locate-the-launcher).",
            "substitute it",
        ),
        (
            "skills/a/SKILL.md",
            "Run from the intended project root: `x`. Then run from the project root with a new output.",
            "Run from a host-writable working directory: `x`. Then run from a host-writable working directory with",
            "project root",
        ),
        (
            "skills/a/references/b.md",
            "From the repository root, run it with fresh output/cache paths:\n\n```sh\npython3 x --output-dir /tmp/metesparser-dashboard-example --cache-dir /tmp/metesparser-dashboard-cache\n```",
            "Run it with fresh output/cache paths:\n\n```sh\npython3 x --output-dir NEW_OUTPUT_DIR --cache-dir NEW_CACHE_DIR\n```",
            "/tmp/",
        ),
        (
            "skills/a/SKILL.md",
            "Use an actual new directory, or omit `--output-dir` when a configured output base supplies fresh folders. Honor disabled or invalid [project settings](../../references/plugin-settings.md). Done.",
            "Use an actual new directory. Chat has no project settings or configured output base, so always pass `--output-dir` with a new directory. Done.",
            "plugin-settings",
        ),
        (
            "references/usage.md",
            "Output directories must be new. A configured output base can supply a fresh child when `--output-dir` is omitted. See [project settings](plugin-settings.md) for `.claude/metesparser.local.md`, CLI precedence, and per-run reload behavior.\n\nNext.",
            "Chat has no project settings or configured output base, so always pass `--output-dir` with a new directory.\n\nNext.",
            ".claude/",
        ),
        (
            "skills/a/SKILL.md",
            "analyze-relative INPUT --output-dir DIR`. A configured output base supplies fresh folders if `--output-dir` is omitted; see [project settings](../../references/plugin-settings.md). Honor disabled or invalid settings. End.",
            "Chat has no project settings or configured output base, so always pass `--output-dir` with a new directory. End.",
            "plugin-settings",
        ),
        (
            "skills/a/references/mapbox-mcp.md",
            "For user-requested Claude Code connection setup, follow Mapbox's [hosted guide](https://x.test/g#21-claude-code): it documents `claude mcp add --transport http m https://mcp.mapbox.com/mcp`, then `/mcp` and the authentication flow. Setup is optional; do not edit global configuration.",
            "Connection setup is optional and belongs to the host's own connector settings; do not edit global configuration.",
            "Claude Code",
        ),
        (
            "skills/a/references/mapbox-mcp.md",
            "Upstream documents MCP Apps support for Claude Desktop, Claude Code, VS Code/GitHub Copilot, and Goose.",
            "Claude Desktop, VS Code/GitHub Copilot, and Goose.",
            "Claude Code",
        ),
        (
            "references/usage.md",
            "Intro.\n\n## Documentation and changes\n\nRecord changes in the [plugin changelog](../CHANGELOG.md).\n\n## Next\n\nKeep.",
            "## Next\n\nKeep.",
            "CHANGELOG",
        ),
        (
            "skills/a/references/b.md",
            '```sh\npython3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" dashboard b.json\n# or, in the development workspace:\nuv run metes-review dashboard b.json\n```',
            '```sh\npython3 "${METESPARSER_SKILL_ROOT}/scripts/run-chat.py" dashboard b.json\n```',
            "development workspace",
        ),
    ],
)
def test_plugin_phrasing_transforms(real, source, text, expected, absent):
    adapted = real._adapt_markdown(text, source)
    assert expected in adapted
    assert absent.lower() not in adapted.lower()


def test_transformation_table_names_are_unique(builder):
    names = [name for name, _pattern, _replacement in builder.TRANSFORMS]
    assert len(names) == len(set(names))


def test_archive_entries_are_sorted_with_fixed_dates_and_modes(builder, tmp_path):
    with zipfile.ZipFile(builder.build(tmp_path / "skill.zip")) as archive:
        infos = archive.infolist()
    assert [i.filename for i in infos] == sorted(i.filename for i in infos)
    assert {i.date_time for i in infos} == {(1980, 1, 1, 0, 0, 0)}
    for info in infos:
        mode = (info.external_attr >> 16) & 0o777
        expected = 0o755 if info.filename.startswith("metesparser-review/scripts/") else 0o644
        assert mode == expected, info.filename
    assert any(i.filename == "metesparser-review/SKILL.md" for i in infos)


def test_two_builds_are_byte_identical(builder, tmp_path):
    first = builder.build(tmp_path / "one" / "skill.zip")
    second = builder.build(tmp_path / "two" / "skill.zip")
    assert first.read_bytes() == second.read_bytes()
    assert (
        first.with_suffix(".zip.sha256").read_text().split()[0]
        == hashlib.sha256(second.read_bytes()).hexdigest()
    )


def test_source_date_epoch_sets_entry_dates(builder, tmp_path, monkeypatch):
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1767225600")  # 2026-01-01T00:00:00Z
    with zipfile.ZipFile(builder.build(tmp_path / "skill.zip")) as archive:
        assert {i.date_time for i in archive.infolist()} == {(2026, 1, 1, 0, 0, 0)}
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "0")  # before the ZIP epoch: clamp
    with zipfile.ZipFile(builder.build(tmp_path / "other.zip")) as archive:
        assert {i.date_time for i in archive.infolist()} == {(1980, 1, 1, 0, 0, 0)}


def test_chat_instructions_do_not_contradict_on_launcher_location(real, tmp_path):
    files = _read(real.build(tmp_path / "skill.zip"))
    skill = files["SKILL.md"].decode()
    runtime = files["references/chat-runtime.md"].decode()
    for text in (skill, runtime):
        assert "skill/resource metadata" not in text
        assert "directory from which you read" in text
    assert "files.pythonhosted.org" in runtime and "pypi.org" in runtime
    assert "files.pythonhosted.org" in files["README.md"].decode()
    for name, content in files.items():
        if name.startswith(("skills/", "references/")) and name.endswith(".md"):
            text = content.decode().lower()
            assert "relative to the skill" not in text, name
            assert "locate the plugin" not in text, name
