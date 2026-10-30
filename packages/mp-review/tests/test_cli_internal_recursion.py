"""RecursionError after input loading is an internal error, not invalid input JSON."""

import json
import os

import pytest
from mp_review import cli


def _run(monkeypatch, capsys, argv):
    monkeypatch.setattr("sys.argv", ["metes-review", *argv])
    with pytest.raises(SystemExit) as exit_info:
        cli.main()
    return exit_info.value.code, json.loads(capsys.readouterr().out)


def test_recursion_after_writing_is_internal_error_reporting_artifacts(
    tmp_path, monkeypatch, capsys
):
    out = tmp_path / "out"
    source = tmp_path / "in.json"
    source.write_text("{}")

    def exploding(args, settings):
        target = cli.output_path(settings, args.output_dir)
        target.mkdir(parents=True)
        (target / "written.json").write_text("{}")
        raise RecursionError

    monkeypatch.setattr(cli, "_execute", exploding)
    argv = ["analyze-corridor", str(source), "--output-dir", str(out)]
    code, result = _run(monkeypatch, capsys, argv)
    assert code == 2
    assert result["status"] == "error"
    assert result["errors"][0]["code"] == "internal_recursion_error"
    assert result["artifacts"] == {"written.json": str(out / "written.json")}


def test_recursion_in_json_decoder_is_still_invalid_input(tmp_path, monkeypatch, capsys):
    source = tmp_path / "in.json"
    source.write_text("[" * 100000 + "]" * 100000)
    argv = ["analyze-corridor", str(source), "--output-dir", str(tmp_path / "o")]
    code, result = _run(monkeypatch, capsys, argv)
    assert code == 2
    assert result["errors"][0]["code"] == "invalid_input_json"


def test_recursion_in_input_validation_is_invalid_input(tmp_path, monkeypatch, capsys):
    source = tmp_path / "in.json"
    source.write_text('{"a": ' + "[" * 2000 + "]" * 2000 + "}")
    argv = ["plot", str(source), "--output-dir", str(tmp_path / "o")]
    code, result = _run(monkeypatch, capsys, argv)
    assert code == 2
    assert result["errors"][0]["code"] == "invalid_input_json"


def test_internal_recursion_lists_only_this_runs_files(tmp_path, monkeypatch, capsys):
    out = tmp_path / "out"
    out.mkdir()
    old = out / "old.json"
    old.write_text("{}")
    os.utime(old, (1, 1))
    source = tmp_path / "in.json"
    source.write_text("{}")

    def exploding(args, settings):
        target = cli.output_path(settings, args.output_dir)
        (target / "new.json").write_text("{}")
        raise RecursionError

    monkeypatch.setattr(cli, "_execute", exploding)
    argv = ["analyze-corridor", str(source), "--output-dir", str(out)]
    _, result = _run(monkeypatch, capsys, argv)
    assert result["artifacts"] == {"new.json": str(out / "new.json")}
    assert not hasattr(cli, "_OUTPUT_DIRS")


def test_output_path_does_not_walk_directory(tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()

    def boom(self, *a, **k):
        raise AssertionError("rglob walked")

    monkeypatch.setattr(type(out), "rglob", boom)
    assert cli.output_path({}, out) == out
