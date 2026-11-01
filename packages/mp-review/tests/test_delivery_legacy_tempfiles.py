"""Legacy publishers staged through NamedTemporaryFile; killed mid-write they left tmpXXXXXXXX."""

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


def test_tmp_named_files_are_refused_untouched_with_manual_cleanup_message(tmp_path):
    # The name alone cannot prove provenance: 'tmp20261030' and 'tmpnotes_01' are plausible
    # user files, and a NamedTemporaryFile leftover looks identical. Refuse, never delete.
    bundle, revision, request = _setup(tmp_path)
    store = tmp_path / "deliveries"
    directory = store / request.id
    for name in ("tmp20261030", "tmpnotes_01", "tmpab12_x9z"):
        _crashed_files(directory)
        (directory / name).write_bytes(b"user")
        result = publish_delivery(bundle, revision, request, store)
        assert result["status"] == "error", name
        assert name in " ".join(result["errors"]), result
        assert "remove" in " ".join(result["errors"]).lower(), result
        assert (directory / name).read_bytes() == b"user"
        assert (directory / "pending.json").exists()
        for entry in directory.iterdir():
            entry.unlink()
        directory.rmdir()


def test_manual_cleanup_of_listed_tmp_file_allows_publish(tmp_path):
    bundle, revision, request = _setup(tmp_path)
    store = tmp_path / "deliveries"
    directory = store / request.id
    _crashed_files(directory)
    (directory / "tmpab12_x9z").write_bytes(b"half written")
    assert publish_delivery(bundle, revision, request, store)["status"] == "error"
    (directory / "tmpab12_x9z").unlink()
    result = publish_delivery(bundle, revision, request, store)
    assert result["status"] == "needs_review", result
    load_delivery(bundle, revision, directory)


def test_lookalike_temp_names_are_refused_untouched(tmp_path):
    bundle, revision, request = _setup(tmp_path)
    store = tmp_path / "deliveries"
    directory = store / request.id
    for name in ("tmp123", "tmpABCDEFGH", "tmpabcdefghi", "xtmpabcdefgh"):
        _crashed_files(directory)
        (directory / name).write_bytes(b"user")
        result = publish_delivery(bundle, revision, request, store)
        assert result["status"] == "error", name
        assert (directory / name).read_bytes() == b"user"
        for entry in directory.iterdir():
            entry.unlink()
        directory.rmdir()


def test_temp_named_symlink_is_refused_untouched(tmp_path):
    bundle, revision, request = _setup(tmp_path)
    store = tmp_path / "deliveries"
    directory = store / request.id
    _crashed_files(directory)
    (directory / "target.txt").write_text("keep")
    (directory / "tmpabcdefgh").symlink_to(directory / "target.txt")
    result = publish_delivery(bundle, revision, request, store)
    assert result["status"] == "error"
    assert (directory / "target.txt").read_text() == "keep"
