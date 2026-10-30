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


def test_legacy_tempfile_residue_is_cleared_and_published(tmp_path):
    bundle, revision, request = _setup(tmp_path)
    store = tmp_path / "deliveries"
    directory = store / request.id
    _crashed_files(directory)
    (directory / "tmpab12_x9z").write_bytes(b"half written")  # NamedTemporaryFile default name
    result = publish_delivery(bundle, revision, request, store)
    assert result["status"] == "needs_review", result
    load_delivery(bundle, revision, directory)
    assert not (directory / "tmpab12_x9z").exists()


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
