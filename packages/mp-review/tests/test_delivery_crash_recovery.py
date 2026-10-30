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
