import hashlib
import json

from mp_review import review_text, verify_file

SQUARE = """BEGINNING at an iron pin; THENCE N 0° E 100 feet;
THENCE N 90° E 100 feet; THENCE S 0° E 100 feet;
THENCE N 90° W 100 feet to the point of beginning."""


def test_square_artifacts_and_provenance(tmp_path):
    result = review_text(SQUARE, output_dir=tmp_path / "out")
    assert result["status"] == "checks_passed"
    assert result["input"]["sha256"] == hashlib.sha256(SQUARE.encode()).hexdigest()
    assert (tmp_path / "out/source.txt").read_text() == SQUARE
    assert (tmp_path / "out/calls_verified.csv").exists()
    audit = json.loads((tmp_path / "out/audit.json").read_text())
    assert audit["provider"] is None and audit["model"] is None


def test_existing_output_refused(tmp_path):
    result = review_text(SQUARE, output_dir=tmp_path)
    assert result["status"] == "error"
    assert result["errors"][0]["code"] == "output_exists"
    assert not list(tmp_path.iterdir())


def test_incomplete_bearing_never_verified(tmp_path):
    result = review_text("THENCE southwesterly 100 feet;", output_dir=tmp_path / "out")
    assert result["status"] != "checks_passed"
    assert all(c["bearing_azimuth_deg_from_north"] is None for c in result["calls"])
    assert not (tmp_path / "out/calls_verified.csv").exists()


def test_bad_json_fail_closed(tmp_path):
    source = tmp_path / "bad.json"
    source.write_text('[{"course":1,"distance_ft":100}, {"course":"oops"}]')
    result = verify_file(source)
    assert result["status"] == "error"
    assert result["calls"] == []


def test_html_escaped(tmp_path):
    review_text("<script>alert(1)</script>" + SQUARE, output_dir=tmp_path / "out")
    html = (tmp_path / "out/review.html").read_text()
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_poc_tie_in_not_part_of_boundary():
    text = (
        "COMMENCING at a stone; THENCE N 0° E 50 feet to the POINT OF BEGINNING; "
        + SQUARE.split("; ", 1)[1]
    )
    result = review_text(text)
    assert result["status"] == "checks_passed"
    assert result["calls"][0]["is_tie_in"] is True
    assert len(result["calls"]) == 5


def test_strict_csv_bad_row_never_partial(tmp_path):
    review_text(SQUARE, output_dir=tmp_path / "initial")
    path = tmp_path / "initial/calls.csv"
    with path.open("a") as handle:
        handle.write("bad,row\n")
    result = verify_file(path)
    assert result["status"] == "error"
    assert result["calls"] == []


def test_cli_one_json_and_status(tmp_path):
    import os
    import subprocess
    import sys

    source = tmp_path / "square.txt"
    source.write_text(SQUARE)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "mp_review",
            "review",
            str(source),
            "--output-dir",
            str(tmp_path / "out"),
        ],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["status"] == "checks_passed"
    assert len(completed.stdout.splitlines()) == 1


def test_supplied_area_kept_through_export(tmp_path):
    result = review_text(SQUARE, stated_area_sq_ft=10000, output_dir=tmp_path / "out")
    assert result["status"] == "checks_passed", result["errors"]
    audit = json.loads((tmp_path / "out/audit.json").read_text())
    assert audit["legal_description"]["stated_area_sq_ft"] == 10000


def test_area_mismatch_no_verified_artifact(tmp_path):
    result = review_text(SQUARE, stated_area_sq_ft=50000, output_dir=tmp_path / "out")
    assert result["status"] == "needs_review"
    assert not (tmp_path / "out/calls_verified.csv").exists()


def test_field_audits_capture_excerpts_and_checks(tmp_path):
    review_text(SQUARE, output_dir=tmp_path / "out")
    audit = json.loads((tmp_path / "out/audit.json").read_text())
    assert len(audit["call_audits"]) == 4
    assert audit["call_audits"][0]["source_excerpt"]
    assert audit["call_audits"][0]["transformations"]
    assert audit["verification_audit"]["checks"]
    assert audit["extraction_record"] is None


def test_multiple_parcels_fail_closed(tmp_path):
    result = review_text(
        "Parcel A: " + SQUARE + "\nParcel B: " + SQUARE, output_dir=tmp_path / "out"
    )
    assert result["status"] == "error"
    assert result["errors"][0]["code"] == "invalid_input"
    assert not (tmp_path / "out/calls_verified.csv").exists()


def test_invalid_utf8_original_bytes_preserved(tmp_path):
    from mp_review import review_file

    source = tmp_path / "bad.txt"
    source.write_bytes(b"\xff\xfeN 0 E 100 feet")
    result = review_file(source, output_dir=tmp_path / "out")
    assert result["status"] == "error"
    assert (tmp_path / "out/source.txt").read_bytes() == source.read_bytes()
    assert result["input"]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
