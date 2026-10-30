"""A crashed publish (no manifest) never wedges its delivery id (PR #60 review)."""

import importlib.util
import os
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
    return sorted(p.name for p in store.iterdir() if ".publishing-" in p.name)


def test_existing_package_directory_is_never_touched(tmp_path):
    bundle, revision, request = _setup(tmp_path)
    directory = tmp_path / "deliveries" / request.id
    _crashed_files(directory)
    (directory / "notes.txt").write_text("user data")
    result = publish_delivery(bundle, revision, request, tmp_path / "deliveries")
    assert result["status"] == "error"
    assert "already published" in result["errors"][0]
    assert (directory / "notes.txt").read_text() == "user data"
    assert (directory / "drawing.svg").read_bytes() == b"<svg>old</svg>"
    assert _staging(tmp_path / "deliveries") == []


def test_symlink_in_place_of_package_is_not_followed(tmp_path):
    bundle, revision, request = _setup(tmp_path)
    store = tmp_path / "deliveries"
    store.mkdir()
    target = tmp_path / "outside"
    target.mkdir()
    (store / request.id).symlink_to(target)
    result = publish_delivery(bundle, revision, request, store)
    assert result["status"] == "error"
    assert list(target.iterdir()) == []


def test_completed_delivery_stays_write_once(tmp_path):
    bundle, revision, request = _setup(tmp_path)
    store = tmp_path / "deliveries"
    assert publish_delivery(bundle, revision, request, store)["status"] == "needs_review"
    before = {p.name: p.read_bytes() for p in (store / request.id).iterdir()}
    changed = request.model_copy(update={"formats": ("svg",)})
    for again in (changed, request):
        result = publish_delivery(bundle, revision, again, store)
        assert result["status"] == "error"
        assert "already published" in result["errors"][0]
    assert {p.name: p.read_bytes() for p in (store / request.id).iterdir()} == before
    load_delivery(bundle, revision, store / request.id)


def test_concurrent_publish_of_one_id_has_exactly_one_winner(tmp_path, monkeypatch):
    import mp_review.delivery as delivery

    bundle, revision, request = _setup(tmp_path)
    store = tmp_path / "deliveries"
    inner = {}
    real = os.rename

    def rename(source, target):
        # Both publishers passed the existence check; the other one renames first.
        if not inner:
            inner["started"] = True
            inner["result"] = publish_delivery(bundle, revision, request, store)
        return real(source, target)

    monkeypatch.setattr(delivery.os, "rename", rename)
    outer = publish_delivery(bundle, revision, request, store)
    assert inner["result"]["status"] == "needs_review", inner
    assert outer["status"] == "error"
    assert "already published" in outer["errors"][0]
    load_delivery(bundle, revision, store / request.id)
    assert _staging(store) == []


def test_failed_publish_leaves_no_package_or_staging(tmp_path, monkeypatch):
    import mp_review.delivery as delivery

    bundle, revision, request = _setup(tmp_path)
    store = tmp_path / "deliveries"
    original = delivery._write_once

    def interrupted(path, content):
        if path.name == "metrics.json":
            raise KeyboardInterrupt
        return original(path, content)

    monkeypatch.setattr(delivery, "_write_once", interrupted)
    try:
        publish_delivery(bundle, revision, request, store)
    except KeyboardInterrupt:
        pass
    assert list(store.iterdir()) == []
    monkeypatch.undo()
    assert publish_delivery(bundle, revision, request, store)["status"] == "needs_review"
    load_delivery(bundle, revision, store / request.id)


def test_live_publisher_staging_is_ignored_not_removed(tmp_path):
    bundle, revision, request = _setup(tmp_path)
    store = tmp_path / "deliveries"
    live = store / f".{request.id}.publishing-{os.getpid()}-abc123"
    live.mkdir(parents=True)
    (live / "pending.json").write_text("{}")
    result = publish_delivery(bundle, revision, request, store)
    assert result["status"] == "needs_review", result
    assert (live / "pending.json").exists()
    load_delivery(bundle, revision, store / request.id)


_CRASH = """
import os, sys
from pathlib import Path
from mp_models.dashboard import DashboardBundle
from mp_models.delivery import DeliveryRequest
from mp_review.delivery import publish_delivery

bundle = DashboardBundle.model_validate_json(Path(sys.argv[1]).read_text())
request = DeliveryRequest.model_validate_json(Path(sys.argv[2]).read_text())
real, calls = os.fsync, []

def fsync(fd):
    calls.append(fd)
    if len(calls) == 3:
        os._exit(17)  # a hard crash part-way through writing the package
    return real(fd)

os.fsync = fsync
publish_delivery(bundle, sys.argv[3], request, sys.argv[4])
os._exit(0)
"""


def test_hard_crash_with_finder_litter_does_not_wedge_the_id(tmp_path):
    import subprocess
    import sys

    bundle, revision, request = _setup(tmp_path)
    store = tmp_path / "deliveries"
    (tmp_path / "bundle.json").write_text(bundle.model_dump_json())
    (tmp_path / "request.json").write_text(request.model_dump_json())
    crashed = subprocess.run(
        [
            sys.executable,
            "-c",
            _CRASH,
            str(tmp_path / "bundle.json"),
            str(tmp_path / "request.json"),
            str(revision),
            str(store),
        ],
        check=False,
    )
    assert crashed.returncode == 17
    # The OS (Finder) drops metadata into whatever the crash left behind.
    for directory in [store, *(p for p in store.rglob("*") if p.is_dir())]:
        (directory / ".DS_Store").write_bytes(b"\x00\x00\x00\x01Bud1")
    result = publish_delivery(bundle, revision, request, store)
    assert result["status"] == "needs_review", result
    load_delivery(bundle, revision, store / request.id)
    # Nothing from the crashed attempt survives beside the published package.
    assert sorted(p.name for p in store.iterdir()) == [".DS_Store", request.id]
