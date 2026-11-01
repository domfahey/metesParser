"""Legacy incomplete publishes, long ids and dead-publisher staging (PR #60 review)."""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

from mp_review.delivery import load_delivery, publish_delivery


def _setup(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "_race", Path(__file__).with_name("test_delivery_publish_race.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._setup(tmp_path)


def _crashed_files(directory: Path) -> None:
    directory.mkdir(parents=True)
    (directory / "pending.json").write_bytes(b'{"old": true}')
    (directory / "drawing.svg").write_bytes(b"<svg>old</svg>")


def _staging(store: Path) -> list[str]:
    return sorted(p.name for p in store.iterdir() if p.name.startswith(".publishing-"))


def test_legacy_manifestless_directory_is_cleared_and_published(tmp_path):
    bundle, revision, request = _setup(tmp_path)
    store = tmp_path / "deliveries"
    directory = store / request.id
    _crashed_files(directory)
    (directory / ".DS_Store").write_bytes(b"\x00")
    result = publish_delivery(bundle, revision, request, store)
    assert result["status"] == "needs_review", result
    load_delivery(bundle, revision, directory)
    assert (directory / "drawing.svg").read_bytes() != b"<svg>old</svg>"


def test_manifestless_directory_with_unknown_entries_is_refused_untouched(tmp_path):
    bundle, revision, request = _setup(tmp_path)
    store = tmp_path / "deliveries"
    directory = store / request.id
    _crashed_files(directory)
    (directory / "notes.txt").write_text("user data")
    result = publish_delivery(bundle, revision, request, store)
    assert result["status"] == "error"
    assert "not a published delivery" in result["errors"][0]
    assert (directory / "notes.txt").read_text() == "user data"
    assert (directory / "pending.json").read_bytes() == b'{"old": true}'


def test_manifestless_directory_with_subdirectory_is_refused(tmp_path):
    bundle, revision, request = _setup(tmp_path)
    store = tmp_path / "deliveries"
    directory = store / request.id
    _crashed_files(directory)
    (directory / "drawing.dxf").mkdir()
    result = publish_delivery(bundle, revision, request, store)
    assert result["status"] == "error"
    assert (directory / "drawing.svg").exists()


def test_long_delivery_id_publishes(tmp_path):
    bundle, revision, request = _setup(tmp_path)
    long_id = "a" + "b" * 249
    request = request.model_copy(update={"id": long_id})
    store = tmp_path / "deliveries"
    result = publish_delivery(bundle, revision, request, store)
    assert result["status"] == "needs_review", result
    assert [p.name for p in store.iterdir()] == [long_id]


def test_dead_publisher_staging_is_removed(tmp_path):
    import mp_review.delivery as delivery

    bundle, revision, request = _setup(tmp_path)
    store = tmp_path / "deliveries"
    store.mkdir()
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    staging = delivery._make_staging(store, request.id)
    dead = staging.with_name(staging.name.replace(f"-{os.getpid()}-", f"-{proc.pid}-", 1))
    staging.rename(dead)
    (dead / "x").write_text("partial")
    result = publish_delivery(bundle, revision, request, store)
    assert result["status"] == "needs_review", result
    assert _staging(store) == []
