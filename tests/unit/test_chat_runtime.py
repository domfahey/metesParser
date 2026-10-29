"""Chat setup is explicit, integrity checked, and shares the review runtime."""

import hashlib
import importlib.util
import io
import json
import types
import zipfile
from pathlib import Path

import pytest


@pytest.fixture
def chat(tmp_path, monkeypatch):
    script = Path(__file__).parents[2] / "plugins/metesparser-chat/scripts/run-chat.py"
    spec = importlib.util.spec_from_file_location("chat_runtime_test", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache with spaces"))
    monkeypatch.setattr(module.shutil, "which", lambda _: None)
    monkeypatch.setattr(module, "platform_key", lambda: "darwin-arm64")
    launcher = types.SimpleNamespace(
        RUNTIME=tmp_path / "runtime with spaces",
        validate_runtime=lambda _: ("a" * 64, None),
        main=lambda args: 1,
    )
    monkeypatch.setattr(module, "load_launcher", lambda: launcher)
    return module, launcher


def wheel_fixture(chat, tmp_path, monkeypatch, *, corrupt=False):
    module, _ = chat
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("uv-0.9.6.data/scripts/uv", b"fake executable")
    data = buffer.getvalue()
    manifest = tmp_path / "uv-bootstrap.json"
    manifest.write_text(
        json.dumps(
            {
                "version": "0.9.6",
                "wheels": {
                    "darwin-arm64": {
                        "url": "https://files.pythonhosted.org/packages/test.whl",
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "binary_sha256": hashlib.sha256(b"fake executable").hexdigest(),
                        "size": len(data),
                    }
                },
            }
        )
    )
    monkeypatch.setattr(module, "MANIFEST", manifest)
    monkeypatch.setattr(module, "download", lambda _: b"corrupt" if corrupt else data)
    return module


def test_ordinary_invocation_never_downloads(chat, monkeypatch, capsys):
    module, _ = chat
    monkeypatch.setattr(module, "download", lambda _: pytest.fail("unexpected download"))
    assert module.main(["verify", "calls.csv"]) == 2
    assert "--setup" in json.loads(capsys.readouterr().out)["errors"][0]["message"]


def test_offline_setup_never_downloads(chat, monkeypatch):
    module, _ = chat
    monkeypatch.setattr(module, "download", lambda _: pytest.fail("unexpected download"))
    assert module.main(["--setup", "--offline"]) == 2


def test_bad_runtime_prevents_download(chat, monkeypatch):
    module, launcher = chat
    launcher.validate_runtime = lambda _: (None, "corrupt runtime")
    monkeypatch.setattr(module, "download", lambda _: pytest.fail("unexpected download"))
    assert module.main(["--setup"]) == 2


def test_corrupt_wheel_is_not_installed(chat, tmp_path, monkeypatch):
    module = wheel_fixture(chat, tmp_path, monkeypatch, corrupt=True)
    assert module.main(["--setup"]) == 2
    assert not module.cached_uv().exists()


def test_explicit_setup_and_cached_delegation(chat, tmp_path, monkeypatch, capsys):
    module = wheel_fixture(chat, tmp_path, monkeypatch)
    _, launcher = chat
    calls = []
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda command, **kw: (
            calls.append((command, kw)) or types.SimpleNamespace(returncode=0, stdout="", stderr="")
        ),
    )
    assert module.main(["--setup"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "ready"
    command, kwargs = calls[0]
    assert command[1:] == ["sync", "--project", str(launcher.RUNTIME), "--locked"]
    assert kwargs["env"]["UV_PROJECT_ENVIRONMENT"].endswith("/" + "a" * 64 + "/venv")
    assert kwargs["env"]["UV_CACHE_DIR"].endswith("/metesparser/uv-cache")
    seen = []
    # The sibling launcher sees the prepended PATH through its own which lookup.
    launcher.main = lambda args: seen.append((args, module.os.environ["PATH"])) or 1
    assert module.main(["verify", "a file.csv"]) == 1
    assert seen[0][0] == ["verify", "a file.csv"]
    assert seen[0][1].split(module.os.pathsep)[0] == str(module.cached_uv().parent)


def test_setup_offline_host_uv_and_failed_sync(chat, monkeypatch, capsys):
    module, _ = chat
    monkeypatch.setattr(module.shutil, "which", lambda _: "/host path/uv")
    commands = []
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda command, **kw: (
            commands.append(command)
            or types.SimpleNamespace(returncode=1, stdout="", stderr="offline cache missing")
        ),
    )
    assert module.main(["--setup", "--offline"]) == 2
    assert "--offline" in commands[0]
    assert "offline cache missing" in json.loads(capsys.readouterr().out)["errors"][0]["message"]


def test_cache_write_failure_is_structured(chat, tmp_path, monkeypatch, capsys):
    module = wheel_fixture(chat, tmp_path, monkeypatch)
    blocked = tmp_path / "file"
    blocked.write_text("not a directory")
    monkeypatch.setenv("XDG_CACHE_HOME", str(blocked))
    assert module.main(["--setup"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "error"


@pytest.mark.parametrize("status", [0, 1, 2])
def test_delegate_preserves_status_and_json(chat, monkeypatch, capsys, status):
    module, launcher = chat
    monkeypatch.setattr(module.shutil, "which", lambda _: "/host/uv")

    def run(args):
        print('{"status":"needs_review"}')
        return status

    launcher.main = run
    assert module.main(["verify", "calls.csv"]) == status
    assert capsys.readouterr().out == '{"status":"needs_review"}\n'


def test_tampered_cached_binary_is_not_executed(chat, tmp_path, monkeypatch, capsys):
    module = wheel_fixture(chat, tmp_path, monkeypatch)
    path = module.install_uv()
    path.write_bytes(b"changed")
    monkeypatch.setattr(module, "download", lambda _: pytest.fail("unexpected download"))
    assert module.main(["verify", "calls.csv"]) == 2
    assert "integrity" in json.loads(capsys.readouterr().out)["errors"][0]["message"]


def test_forged_cache_receipt_cannot_authorize_binary(chat, tmp_path, monkeypatch):
    module = wheel_fixture(chat, tmp_path, monkeypatch)
    path = module.install_uv()
    path.write_bytes(b"replaced executable")
    path.with_name("uv-install.json").write_text(
        json.dumps(
            {
                "wheel_sha256": module.wheel_record()["sha256"],
                "binary_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    )
    assert module.main(["verify", "calls.csv"]) == 2


def test_verified_cached_binary_does_not_need_receipt(chat, tmp_path, monkeypatch):
    module = wheel_fixture(chat, tmp_path, monkeypatch)
    path = module.cached_uv()
    path.parent.mkdir(parents=True)
    path.write_bytes(b"fake executable")
    path.chmod(0o755)
    monkeypatch.setattr(module, "download", lambda _: pytest.fail("unexpected download"))
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *a, **kw: types.SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    assert module.main(["--setup", "--offline"]) == 0
    assert module.main(["verify", "calls.csv"]) == 1


def test_downloaded_binary_must_match_manifest(chat, tmp_path, monkeypatch):
    module = wheel_fixture(chat, tmp_path, monkeypatch)
    manifest = json.loads(module.MANIFEST.read_text())
    manifest["wheels"]["darwin-arm64"]["binary_sha256"] = "0" * 64
    module.MANIFEST.write_text(json.dumps(manifest))
    assert module.main(["--setup"]) == 2
    assert not module.cached_uv().exists()


def test_network_error_is_structured(chat, tmp_path, monkeypatch, capsys):
    module = wheel_fixture(chat, tmp_path, monkeypatch)

    def fail_download(_):
        raise OSError("network unavailable")

    monkeypatch.setattr(module, "download", fail_download)
    assert module.main(["--setup"]) == 2
    assert "network unavailable" in capsys.readouterr().out
    assert not module.cached_uv().exists()


def test_unsupported_platform_with_host_uv_can_delegate(chat, monkeypatch):
    module, _ = chat

    def unsupported():
        raise ValueError("Unsupported platform")

    monkeypatch.setattr(module, "platform_key", unsupported)
    assert module.main(["--setup"]) == 2
    monkeypatch.setattr(module.shutil, "which", lambda _: "/host/uv")
    assert module.main(["verify", "calls.csv"]) == 1


def test_delegation_restores_path_on_exception(chat, monkeypatch):
    module, launcher = chat
    monkeypatch.setattr(module.shutil, "which", lambda _: "/host/uv")
    original = module.os.environ.get("PATH")

    def fail(_):
        raise OSError("cannot execute")

    launcher.main = fail
    assert module.main(["verify", "calls.csv"]) == 2
    assert module.os.environ.get("PATH") == original
