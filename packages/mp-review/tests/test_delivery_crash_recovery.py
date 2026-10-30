"""A crashed publish (no manifest) never wedges its delivery id (PR #60 review)."""

import importlib.util
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


def test_retry_after_crashed_publish_discards_leftovers_and_replays(tmp_path):
    bundle, revision, request = _setup(tmp_path)
    directory = tmp_path / "deliveries" / request.id
    _crashed_files(directory)
    result = publish_delivery(bundle, revision, request, tmp_path / "deliveries")
    assert result["status"] == "needs_review", result
    assert b"old" not in (directory / "drawing.svg").read_bytes()
    load_delivery(bundle, revision, directory)


def test_unexpected_files_in_incomplete_directory_are_refused_and_kept(tmp_path):
    bundle, revision, request = _setup(tmp_path)
    directory = tmp_path / "deliveries" / request.id
    _crashed_files(directory)
    (directory / "notes.txt").write_text("user data")
    result = publish_delivery(bundle, revision, request, tmp_path / "deliveries")
    assert result["status"] == "error"
    assert (directory / "notes.txt").read_text() == "user data"
    assert (directory / "drawing.svg").read_bytes() == b"<svg>old</svg>"


def test_symlink_in_incomplete_directory_is_not_followed(tmp_path):
    bundle, revision, request = _setup(tmp_path)
    directory = tmp_path / "deliveries" / request.id
    directory.mkdir(parents=True)
    target = tmp_path / "outside.txt"
    target.write_text("keep")
    (directory / "drawing.svg").symlink_to(target)
    result = publish_delivery(bundle, revision, request, tmp_path / "deliveries")
    assert target.read_text() == "keep"
    assert result["status"] == "error"


def test_completed_delivery_stays_write_once(tmp_path):
    bundle, revision, request = _setup(tmp_path)
    store = tmp_path / "deliveries"
    assert publish_delivery(bundle, revision, request, store)["status"] == "needs_review"
    changed = request.model_copy(update={"formats": ("svg",)})
    assert publish_delivery(bundle, revision, changed, store)["status"] == "error"
    load_delivery(bundle, revision, store / request.id)


def _no_fcntl(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "fcntl", None)


def test_unlocked_publish_never_clears_leftovers(tmp_path, monkeypatch):
    _no_fcntl(monkeypatch)
    bundle, revision, request = _setup(tmp_path)
    directory = tmp_path / "deliveries" / request.id
    _crashed_files(directory)
    result = publish_delivery(bundle, revision, request, tmp_path / "deliveries")
    # Differing leftovers are refused by write-once, never unlinked.
    assert result["status"] == "error"
    assert (directory / "drawing.svg").read_bytes() == b"<svg>old</svg>"
    assert not (directory / "delivery-manifest.json").exists()


def test_unlocked_concurrent_publish_is_refused_without_deleting(tmp_path, monkeypatch):
    _no_fcntl(monkeypatch)
    bundle, revision, request = _setup(tmp_path)
    store = tmp_path / "deliveries"
    directory = store / request.id
    inner = {}
    import mp_review.delivery as delivery

    real = delivery._components

    def components(*args, **kwargs):
        # A second publish of the same id starts while the first is mid-flight.
        (directory / "pending.json").write_bytes((directory / "pending.json").read_bytes())
        before = sorted(p.name for p in directory.iterdir())
        inner["result"] = publish_delivery(bundle, revision, request, store)
        inner["unchanged"] = before == sorted(p.name for p in directory.iterdir())
        return real(*args, **kwargs)

    monkeypatch.setattr(delivery, "_components", components)
    outer = publish_delivery(bundle, revision, request, store)
    assert inner["result"]["status"] == "error"
    assert inner["unchanged"]
    assert outer["status"] == "needs_review", outer
    load_delivery(bundle, revision, directory)
    assert not [p for p in store.iterdir() if p.name != request.id]


def test_unlocked_crashed_publish_gives_clear_error(tmp_path, monkeypatch):
    _no_fcntl(monkeypatch)
    bundle, revision, request = _setup(tmp_path)
    store = tmp_path / "deliveries"
    import mp_review.delivery as delivery

    def boom(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(delivery, "_components", boom)
    try:
        publish_delivery(bundle, revision, request, store)
    except KeyboardInterrupt:
        pass
    monkeypatch.undo()
    _no_fcntl(monkeypatch)
    # Simulate a hard crash: a claim file survives.
    claim = store / f"{request.id}.publishing"
    claim.write_text("")
    result = publish_delivery(bundle, revision, request, store)
    assert result["status"] == "error"
    assert "remove" in result["errors"][0] and str(claim) in result["errors"][0]
    assert claim.exists()
