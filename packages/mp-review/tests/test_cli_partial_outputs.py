"""Internal-recursion reports every output path handed to this run, never anything else."""

import json

import pytest
from mp_review import cli


def _run(monkeypatch, capsys, argv):
    monkeypatch.setattr("sys.argv", ["metes-review", *argv])
    with pytest.raises(SystemExit) as exit_info:
        cli.main()
    return exit_info.value.code, json.loads(capsys.readouterr().out)


def test_in_place_rewrite_and_subdirectory_write_are_reported(tmp_path, monkeypatch, capsys):
    out = tmp_path / "out"
    out.mkdir()
    (out / "existing.json").write_text("{}")
    source = tmp_path / "in.json"
    source.write_text("{}")

    def exploding(args, settings):
        cli.output_path(settings, args.output_dir)
        (out / "existing.json").write_text('{"rewritten": 1}')  # no top-level entry change
        raise RecursionError

    monkeypatch.setattr(cli, "_execute", exploding)
    argv = ["analyze-corridor", str(source), "--output-dir", str(out)]
    _, result = _run(monkeypatch, capsys, argv)
    assert result["partial_output_directories"] == [str(out)]
    assert "may contain partial output" in result["errors"][0]["message"]


@pytest.mark.parametrize(
    "command",
    [
        ["import-overlay", "SRC", "--format", "geojson", "--target-crs", "EPSG:3857"],
        ["register-raster", "SRC", "--controls", "SRC"],
        ["revision-template", "SRC"],
        ["corpus", "SRC"],
    ],
    ids=lambda c: c[0],
)
def test_explicit_output_path_is_reported(command, tmp_path, monkeypatch, capsys):
    source = tmp_path / "in.json"
    source.write_text("{}")
    output = tmp_path / "result.json"

    def exploding(args, settings):
        output.write_text("{}")
        raise RecursionError

    monkeypatch.setattr(cli, "_execute", exploding)
    argv = [str(source) if a == "SRC" else a for a in command]
    _, result = _run(monkeypatch, capsys, [*argv, "--output", str(output)])
    assert result["errors"][0]["code"] == "internal_recursion_error"
    assert result["partial_output_directories"] == [str(output)]


def test_unhanded_and_missing_paths_are_never_listed(tmp_path, monkeypatch, capsys):
    source = tmp_path / "in.json"
    source.write_text("{}")
    (tmp_path / "other").mkdir()

    def exploding(args, settings):
        raise RecursionError

    monkeypatch.setattr(cli, "_execute", exploding)
    argv = ["import-overlay", str(source), "--format", "geojson", "--target-crs", "EPSG:3857"]
    _, result = _run(monkeypatch, capsys, [*argv, "--output", str(tmp_path / "never.json")])
    assert result["partial_output_directories"] == []
