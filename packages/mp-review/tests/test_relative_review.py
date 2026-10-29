"""The relative-analysis entry point never promotes canonical verification."""

import hashlib
import json
import subprocess
import sys

import pytest
from mp_review import review_relative_file, verify_file


def rectangle():
    ids = ["a", "b", "c", "d"]
    return {
        "schema_version": "1.0",
        "frame": {
            "name": "arbitrary local frame",
            "first_azimuth_deg": 0,
            "origin": [5000, 5000],
            "orientation": "cw",
        },
        "courses": [
            {
                "course_id": course_id,
                "distance_ft": distance,
                "source": {"reference": "fixture:p1", "quote": f"  {distance} feet\n"},
            }
            for course_id, distance in zip(ids, [100, 50, 100, 50], strict=True)
        ],
        "constraints": [
            {
                "constraint_id": first + second,
                "kind": "interior",
                "from_course": first,
                "to_course": second,
                "angle_deg": 90,
                "source": {"reference": "fixture:p1", "quote": " interior angle 90 degrees\n"},
            }
            for first, second in zip(ids, ids[1:] + ids[:1], strict=True)
        ],
    }


def write_source(tmp_path, data=None):
    path = tmp_path / "relative.json"
    path.write_text(json.dumps(rectangle() if data is None else data, indent=2), encoding="utf-8")
    return path


def test_relative_results_preserve_unknown_bearings_and_never_verify(tmp_path):
    source = write_source(tmp_path)
    original = source.read_bytes()
    result = review_relative_file(source, output_dir=tmp_path / "out")

    assert result["status"] == "needs_review", result["errors"]
    assert result["verification"] is None
    assert result["engine_verified"] is False
    assert result["verified_export_eligible"] is False
    analysis = result["analysis"]
    assert analysis["status"] == "analyzed"
    assert analysis["engine_verified"] is False
    assert analysis["verified_export_eligible"] is False
    assert analysis["misclosure_ft"] == pytest.approx(0, abs=1e-10)
    assert analysis["area_sq_ft"] == pytest.approx(5000)
    assert all(
        course["recorded_bearing_azimuth_deg_from_north"] is None
        for course in analysis["description"]["courses"]
    )
    assert source.read_bytes() == original
    assert result["input"]["sha256"] == hashlib.sha256(original).hexdigest()
    assert (tmp_path / "out/source.json").read_bytes() == original
    assert not list((tmp_path / "out").glob("*.csv"))
    assert json.loads((tmp_path / "out/analysis.json").read_text()) == analysis
    audit = json.loads((tmp_path / "out/audit.json").read_text())
    assert audit["provider"] is None and audit["model"] is None
    assert audit["method"] == "deterministic_relative"
    assert audit["input"] == result["input"]
    assert audit["description"]["courses"][0]["source"]["quote"] == "  100 feet\n"


def test_valid_relative_analysis_is_reproducible_without_artifacts(tmp_path):
    source = write_source(tmp_path)
    first = review_relative_file(source)
    assert first == review_relative_file(source)
    assert first["artifacts"] == {}


@pytest.mark.parametrize("input_kind", ["description", "analysis"])
def test_canonical_verifier_rejects_relative_descriptions_and_results(tmp_path, input_kind):
    source = write_source(tmp_path)
    if input_kind == "analysis":
        relative = review_relative_file(source)
        assert relative["analysis"]["status"] == "analyzed"
        source = tmp_path / "analysis.json"
        source.write_text(json.dumps(relative["analysis"]), encoding="utf-8")

    result = verify_file(source, output_dir=tmp_path / "canonical")
    assert result["status"] == "error"
    assert result["errors"][0]["code"] == "invalid_input"
    assert result["verification"] is None
    assert result["calls"] == []
    assert not list((tmp_path / "canonical").glob("*_verified.csv"))


@pytest.mark.parametrize(
    "case, expected", [("ambiguous", "unresolved"), ("conflict", "inconsistent")]
)
def test_relative_unresolved_and_conflicting_results_do_not_compute_geometry(
    tmp_path, case, expected
):
    data = rectangle()
    if case == "ambiguous":
        data["constraints"] = [
            {
                "constraint_id": "ab",
                "kind": "perpendicular",
                "from_course": "a",
                "to_course": "b",
                "source": {"reference": "fixture:p1", "quote": "at right angles"},
            }
        ]
    else:
        data["constraints"].append(
            {**data["constraints"][0], "constraint_id": "bad", "angle_deg": 80}
        )
    result = review_relative_file(write_source(tmp_path, data), output_dir=tmp_path / "out")
    assert result["status"] == "needs_review"
    assert result["analysis"]["status"] == expected
    assert result["analysis"]["issues"]
    assert result["analysis"]["area_sq_ft"] is None
    assert result["verification"] is None
    assert not list((tmp_path / "out").glob("*verified*"))


@pytest.mark.parametrize(
    "content",
    [
        b"[]",
        b'{"schema_version":"1.0", "unexpected":true}',
        b'{"schema_version":"1.0", "schema_version":"2.0"}',
        b'{"frame": {"first_azimuth_deg": NaN}}',
        b"\xff\xfe invalid UTF-8",
    ],
)
def test_relative_invalid_input_is_preserved_and_fails_closed(tmp_path, content):
    source = tmp_path / "relative.json"
    source.write_bytes(content)
    result = review_relative_file(source, output_dir=tmp_path / "out")
    assert result["status"] == "error"
    assert result["errors"][0]["code"] == "invalid_input"
    assert result["analysis"] is None
    assert (tmp_path / "out/source.json").read_bytes() == content
    assert result["input"]["sha256"] == hashlib.sha256(content).hexdigest()
    assert not list((tmp_path / "out").glob("*verified*"))


def test_relative_unknown_field_rejected_on_otherwise_valid_description(tmp_path):
    data = rectangle()
    data["engine_verified"] = True
    result = review_relative_file(write_source(tmp_path, data))
    assert result["status"] == "error"
    assert result["analysis"] is None


def test_relative_existing_output_refused_without_changes(tmp_path):
    source = write_source(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    sentinel = out / "source.json"
    sentinel.write_text("do not overwrite")
    result = review_relative_file(source, output_dir=out)
    assert result["status"] == "error"
    assert result["errors"][0]["code"] == "output_exists"
    assert sentinel.read_text() == "do not overwrite"


def test_relative_input_errors_are_structured(tmp_path):
    missing = review_relative_file(tmp_path / "missing.json")
    assert missing["status"] == "error"
    assert missing["errors"][0]["code"] == "input_error"
    prose = tmp_path / "source.txt"
    prose.write_text("at right angles 100 feet")
    result = review_relative_file(prose)
    assert result["status"] == "error"
    assert result["errors"][0]["code"] == "invalid_input"
    assert result["analysis"] is None


def test_relative_report_escapes_source_and_constraint_text(tmp_path):
    data = rectangle()
    data["courses"][0]["source"]["quote"] = '<script>alert("source")</script>'
    data["constraints"][0]["source"]["reference"] = "<img src=x onerror=alert(1)>"
    result = review_relative_file(write_source(tmp_path, data), output_dir=tmp_path / "out")
    assert result["status"] == "needs_review"
    html = (tmp_path / "out/review.html").read_text()
    assert "<script>" not in html
    assert "<img src=" not in html
    assert "&lt;script&gt;" in html
    assert "Local geometry" in html
    assert "needs_review" in html


def cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "mp_review", "analyze-relative", *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_relative_cli_reports_needs_review_as_exit_one(tmp_path):
    source = write_source(tmp_path)
    completed = cli(source, "--output-dir", tmp_path / "out")
    assert completed.returncode == 1, completed.stderr
    assert len(completed.stdout.splitlines()) == 1
    result = json.loads(completed.stdout)
    assert result["status"] == "needs_review"
    assert result["analysis"]["status"] == "analyzed"
    assert not list((tmp_path / "out").glob("*.csv"))


def test_relative_cli_invalid_input_returns_error_exit(tmp_path):
    source = tmp_path / "bad.json"
    source.write_text("invalid JSON")
    completed = cli(source, "--output-dir", tmp_path / "out")
    assert completed.returncode == 2
    assert json.loads(completed.stdout)["errors"][0]["code"] == "invalid_input"


def test_relative_cli_respects_disabled_setting(tmp_path):
    settings = tmp_path / "settings.md"
    settings.write_text("---\nenabled: false\n---\n")
    completed = cli(tmp_path / "missing.json", "--settings", settings)
    assert completed.returncode == 2
    assert json.loads(completed.stdout)["errors"][0]["code"] == "plugin_disabled"


def test_relative_cli_uses_configured_fresh_output(tmp_path):
    source = write_source(tmp_path)
    config = tmp_path / ".claude"
    config.mkdir()
    settings = config / "metesparser.local.md"
    settings.write_text("---\noutput_dir: reviews\n---\n")
    completed = cli(source, "--settings", settings)
    assert completed.returncode == 1, completed.stderr
    result = json.loads(completed.stdout)
    assert result["status"] == "needs_review"
    assert len(list((tmp_path / "reviews").glob("review-*/analysis.json"))) == 1


def test_relative_cli_requires_output_destination(tmp_path):
    completed = cli(write_source(tmp_path))
    assert completed.returncode == 2
    assert json.loads(completed.stdout)["errors"][0]["code"] == "invalid_settings"
