import json
import math
from pathlib import Path

from mp_review.cli import main
from mp_review.corpus import run_corpus

FIXTURES = Path(__file__).parent / "fixtures"


def test_reviewed_corpus_checks_geometry_and_selected_fields(tmp_path):
    report = run_corpus(FIXTURES / "corpus.json", tmp_path / "report.json")
    assert report["status"] == "passed"
    assert report["passed"] == 5
    assert report["failed"] == 0
    persisted = json.loads((tmp_path / "report.json").read_text())
    square = persisted["cases"][0]
    assert all(check["passed"] for check in square["assertions"])


def test_expected_value_change_fails_instead_of_snapshotting_actual(tmp_path):
    manifest = json.loads((FIXTURES / "corpus.json").read_text())
    manifest["cases"][0]["expect"]["area_sq_ft"] = 9999
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(manifest))
    # Manifest-relative fixtures must stay relative to the manifest. Copy the small fixture set.
    for name in (
        "square.txt",
        "incomplete.txt",
        "bowtie.json",
        "compound-units.txt",
        "semicircle.json",
    ):
        (tmp_path / name).write_bytes((FIXTURES / name).read_bytes())
    report = run_corpus(changed)
    square = report["cases"][0]
    assert report["status"] == "failed"
    area_check = next(item for item in square["assertions"] if item["assertion"] == "area_sq_ft")
    assert area_check["expected"] == 9999
    assert math.isclose(area_check["actual"], 10000, abs_tol=0.01)
    assert area_check["passed"] is False


def test_bad_case_isolated_and_strict_csv_rejected(tmp_path):
    manifest = {
        "schema_version": "1.0",
        "reviewed_basis": "Reviewed known malformed CSV and square fixture.",
        "cases": [
            {
                "id": "bad-csv",
                "input": {"kind": "csv", "path": "malformed.csv"},
                "expect": {"status": "error", "error_code": ["invalid_input"]},
            },
            {
                "id": "good-square",
                "input": {"kind": "text", "path": "square.txt"},
                "expect": {"status": "checks_passed", "call_count": 4},
            },
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    for name in ("malformed.csv", "square.txt"):
        (tmp_path / name).write_bytes((FIXTURES / name).read_bytes())
    report = run_corpus(path)
    assert report["failed"] == 0 and report["passed"] == 2
    assert report["cases"][0]["status"] == "passed"
    assert report["cases"][0]["result"]["status"] == "error"
    assert report["cases"][0]["result"]["errors"][0]["code"] == "invalid_input"
    assert report["cases"][1]["status"] == "passed"


def test_expectation_typo_is_rejected_instead_of_ignored(tmp_path):
    manifest = json.loads((FIXTURES / "corpus.json").read_text())
    manifest["cases"][0]["expect"]["misclosur_ft"] = 0
    path = tmp_path / "typo.json"
    path.write_text(json.dumps(manifest))
    for fixture in FIXTURES.iterdir():
        if fixture.is_file() and fixture.name != "corpus.json":
            (tmp_path / fixture.name).write_bytes(fixture.read_bytes())
    report = run_corpus(path)
    case = report["cases"][0]
    assert report["status"] == "failed"
    assert case["error"]["type"] == "ValueError"
    assert "misclosur_ft" in case["error"]["message"]


def test_empty_selected_call_expectations_are_rejected(tmp_path):
    manifest = {
        "schema_version": "1.0",
        "reviewed_basis": "Reviewed that expectation lists cannot pass vacuously.",
        "cases": [
            {
                "id": "empty",
                "input": {"kind": "text", "path": "missing.txt"},
                "expect": {"selected_calls": []},
            }
        ],
    }
    path = tmp_path / "vacuous.json"
    path.write_text(json.dumps(manifest))
    report = run_corpus(path)
    assert report["status"] == "failed"
    assert "at least one field assertion" in report["cases"][0]["error"]["message"]


def test_empty_corpus_and_unreviewed_manifest_rejected(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text(
        json.dumps({"schema_version": "1.0", "reviewed_basis": "fixture review", "cases": []})
    )
    try:
        run_corpus(path)
    except ValueError as exc:
        assert "must not be empty" in str(exc)
    else:
        raise AssertionError("empty corpus should be rejected")

    path.write_text(json.dumps({"schema_version": "1.0", "cases": [{"id": "x"}]}))
    try:
        run_corpus(path)
    except ValueError as exc:
        assert "reviewed_basis" in str(exc)
    else:
        raise AssertionError("unreviewed manifest should be rejected")


def test_malformed_case_is_isolated(tmp_path):
    manifest = {
        "schema_version": "1.0",
        "reviewed_basis": "Reviewed case schema behavior.",
        "cases": [
            None,
            {
                "id": "good",
                "input": {"kind": "text", "path": "square.txt"},
                "expect": {"status": "checks_passed", "call_count": 4},
            },
        ],
    }
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(manifest))
    (tmp_path / "square.txt").write_bytes((FIXTURES / "square.txt").read_bytes())
    report = run_corpus(path)
    assert report["failed"] == 1 and report["passed"] == 1
    assert report["cases"][0]["error"]["message"] == "case must be an object"
    assert report["cases"][1]["status"] == "passed"


def test_cli_corpus_exit_codes_and_structured_manifest_error(tmp_path, monkeypatch, capsys):
    success_manifest = FIXTURES / "corpus.json"
    monkeypatch.setattr("sys.argv", ["metes-review", "corpus", str(success_manifest)])
    try:
        main()
    except SystemExit as exc:
        assert exc.code == 0
    else:
        raise AssertionError("successful corpus must exit zero")
    assert json.loads(capsys.readouterr().out)["status"] == "passed"

    failed_data = json.loads(success_manifest.read_text())
    failed_data["cases"][0]["expect"]["area_sq_ft"] = 9999
    failed_manifest = tmp_path / "failed.json"
    failed_manifest.write_text(json.dumps(failed_data))
    for fixture in FIXTURES.iterdir():
        if fixture.is_file() and fixture.name != "corpus.json":
            (tmp_path / fixture.name).write_bytes(fixture.read_bytes())
    monkeypatch.setattr("sys.argv", ["metes-review", "corpus", str(failed_manifest)])
    try:
        main()
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("failed corpus must exit one")
    assert json.loads(capsys.readouterr().out)["status"] == "failed"

    bad_manifest = tmp_path / "bad.json"
    bad_manifest.write_text("{}")
    monkeypatch.setattr("sys.argv", ["metes-review", "corpus", str(bad_manifest)])
    try:
        main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("malformed manifest must exit two")
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert payload["errors"][0]["code"] == "invalid_manifest"


def test_assertions_do_not_treat_bool_as_number():
    from mp_review.corpus import _assertions

    result = {
        "calls": [
            {"is_exception": False, "is_tie_in": True},
        ]
    }
    checks_tol = _assertions(
        result,
        {"selected_calls": [{"is_exception": 0.0005}], "numeric_tolerance": 0.001},
    )
    assert checks_tol[0]["passed"] is False

    checks_zero = _assertions(result, {"selected_calls": [{"is_exception": 0}]})
    assert checks_zero[0]["passed"] is False

    checks_one = _assertions(result, {"selected_calls": [{"is_tie_in": 1}]})
    assert checks_one[0]["passed"] is False

    checks_bool = _assertions(result, {"selected_calls": [{"is_exception": False}]})
    assert checks_bool[0]["passed"] is True
    assert checks_bool[0]["tolerance"] is None


def test_missing_selected_call_fails_even_when_expected_is_none():
    from mp_review.corpus import _assertions

    checks = _assertions(
        {"calls": []},
        {"selected_calls": [{"bearing_azimuth_deg_from_north": None}]},
    )
    assert len(checks) == 1
    assert checks[0]["passed"] is False
    assert checks[0]["actual"] == "<missing call>"


def test_manifest_with_nan_or_infinity_rejected(tmp_path):
    for constant in ("NaN", "Infinity", "-Infinity"):
        manifest_path = tmp_path / f"{constant}.json"
        manifest_path.write_text(
            '{"schema_version":"1.0","reviewed_basis":"test","cases":[{"id":"c","input":{"kind":"text","path":"square.txt"},"expect":{"misclosure_ft":'
            + constant
            + "}}]}",
            encoding="utf-8",
        )
        try:
            run_corpus(manifest_path)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Manifest containing {constant} should be rejected")


def test_run_corpus_rejects_nan_when_writing_report(tmp_path, monkeypatch):
    manifest = {
        "schema_version": "1.0",
        "reviewed_basis": "test",
        "cases": [
            {
                "id": "nan-result",
                "input": {"kind": "text", "path": "square.txt"},
                "expect": {"status": "checks_passed"},
            }
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "square.txt").write_bytes((FIXTURES / "square.txt").read_bytes())

    monkeypatch.setattr(
        "mp_review.api.review_file",
        lambda *_args, **_kwargs: {
            "status": "checks_passed",
            "calls": [],
            "verification": {"misclosure_ft": float("nan")},
        },
    )
    try:
        run_corpus(manifest_path, tmp_path / "report.json")
    except ValueError:
        pass
    else:
        raise AssertionError("Writing report with NaN should fail with allow_nan=False")


def test_invalid_tolerance_rejected(tmp_path):
    (tmp_path / "square.txt").write_bytes((FIXTURES / "square.txt").read_bytes())
    for tol_key in ("misclosure_ft_tolerance", "area_sq_ft_tolerance", "numeric_tolerance"):
        for bad_val in (True, -0.1, "0.01", None):
            manifest = {
                "schema_version": "1.0",
                "reviewed_basis": "test",
                "cases": [
                    {
                        "id": "bad-tol",
                        "input": {"kind": "text", "path": "square.txt"},
                        "expect": {"status": "checks_passed", tol_key: bad_val},
                    }
                ],
            }
            manifest_path = tmp_path / "tol.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            report = run_corpus(manifest_path)
            assert report["status"] == "failed"
            assert report["cases"][0]["error"]["type"] == "ValueError"


def test_cli_corpus_output_error_distinguished_from_invalid_manifest(tmp_path, monkeypatch, capsys):
    bad_manifest = tmp_path / "bad.json"
    bad_manifest.write_text("{}")
    monkeypatch.setattr("sys.argv", ["metes-review", "corpus", str(bad_manifest)])
    try:
        main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("malformed manifest must exit two")
    invalid_payload = json.loads(capsys.readouterr().out)
    assert invalid_payload["artifacts"] == {}
    assert invalid_payload["errors"][0]["code"] == "invalid_manifest"

    existing_dir = tmp_path / "already_a_dir"
    existing_dir.mkdir()
    monkeypatch.setattr(
        "sys.argv",
        [
            "metes-review",
            "corpus",
            str(FIXTURES / "corpus.json"),
            "--output",
            str(existing_dir),
        ],
    )
    try:
        main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("unwritable output must exit two")
    output_payload = json.loads(capsys.readouterr().out)
    assert output_payload["status"] == "error"
    assert output_payload["artifacts"] == {}
    assert output_payload["errors"][0]["code"] == "output_error"
