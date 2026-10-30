"""RecursionError after input loading is an internal error, not invalid input JSON."""

import json

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
