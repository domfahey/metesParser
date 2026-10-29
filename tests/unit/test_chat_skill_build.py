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
    (template / "SKILL.md").write_text(
        "---\nname: metesparser-review\ndescription: Review deeds\n---\n"
        "[Review](skills/review-metes-and-bounds/WORKFLOW.md)\n"
        "[Runtime](references/chat-runtime.md)\n"
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
        assert "metesparser-review/CHANGELOG.md" in names
        for name in sorted(names):
            if not name.endswith(".md"):
                continue
            text = archive.read(name).decode()
            assert "CLAUDE_PLUGIN_ROOT" not in text
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
    (builder.CHAT_TEMPLATE / "SKILL.md").write_text("[Missing](missing.md)\n")
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
