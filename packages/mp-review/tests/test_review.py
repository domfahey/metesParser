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


def test_multi_tract_text_variants_fail_closed(tmp_path):
    variants = {
        "tract_alpha": f"Tract A: {SQUARE}\nTract B: {SQUARE}",
        "tract_numeric": f"TRACT 1: {SQUARE}\nTRACT 2: {SQUARE}",
        "dual_beginning": f"{SQUARE}\n{SQUARE}",
    }
    for name, text in variants.items():
        out_dir = tmp_path / name
        result = review_text(text, output_dir=out_dir)
        assert result["status"] == "error", f"{name} should fail closed: {result}"
        assert result["errors"][0]["code"] == "invalid_input"
        assert not (out_dir / "calls_verified.csv").exists()


def test_single_main_tract_with_except_clause_computes_net_area(tmp_path):
    text = (
        SQUARE
        + "\nLESS AND EXCEPT:\n"
        + "BEGINNING at a stake; THENCE N 0° E 20 feet;\n"
        + "THENCE N 90° E 20 feet; THENCE S 0° E 20 feet;\n"
        + "THENCE N 90° W 20 feet to the point of beginning."
    )
    result = review_text(text, output_dir=tmp_path / "out")
    assert result["status"] != "error", result["errors"]
    assert result["errors"] == []
    assert result["verification"]["closure_passed"] is True
    assert abs(result["verification"]["area_sq_ft"] - 9600.0) < 0.01
    assert any(c["is_exception"] for c in result["calls"])


def test_multi_tract_json_fails_closed(tmp_path):
    from mp_models import DeedCall, LegalDescription, Tract, TractType

    square_calls = [
        DeedCall(
            course=1,
            direction_text="N 0° E",
            bearing_quadrant="N 0° E",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=100.0,
        ),
        DeedCall(
            course=2,
            direction_text="N 90° E",
            bearing_quadrant="N 90° E",
            bearing_azimuth_deg_from_north=90.0,
            distance_ft=100.0,
        ),
        DeedCall(
            course=3,
            direction_text="S 0° E",
            bearing_quadrant="S 0° E",
            bearing_azimuth_deg_from_north=180.0,
            distance_ft=100.0,
        ),
        DeedCall(
            course=4,
            direction_text="N 90° W",
            bearing_quadrant="N 90° W",
            bearing_azimuth_deg_from_north=270.0,
            distance_ft=100.0,
        ),
    ]
    legal = LegalDescription(
        calls=square_calls + square_calls,
        tracts=[
            Tract(label="Tract 1", tract_type=TractType.MAIN, calls=square_calls),
            Tract(label="Tract 2", tract_type=TractType.MAIN, calls=square_calls),
        ],
    )
    source = tmp_path / "multi.json"
    source.write_text(legal.model_dump_json(), encoding="utf-8")
    result = verify_file(source, output_dir=tmp_path / "out")
    assert result["status"] == "error"
    assert result["errors"][0]["code"] == "invalid_input"
    assert not (tmp_path / "out/calls_verified.csv").exists()


def test_csv_parsed_from_in_memory_utf8_without_rereading_disk(tmp_path):
    from mp_review.api import _run

    initial = review_text(SQUARE, output_dir=tmp_path / "initial")
    assert initial["status"] == "checks_passed"
    csv_bytes = (tmp_path / "initial/calls.csv").read_bytes()
    assert "°".encode() in csv_bytes

    result = _run(csv_bytes, "calls.csv", "csv", None, None)
    assert result["status"] == "checks_passed", result["errors"]
    assert len(result["calls"]) == 4
    assert "°" in result["calls"][0]["bearing_quadrant"]


def test_invalid_utf8_original_bytes_preserved(tmp_path):
    from mp_review import review_file

    source = tmp_path / "bad.txt"
    source.write_bytes(b"\xff\xfeN 0 E 100 feet")
    result = review_file(source, output_dir=tmp_path / "out")
    assert result["status"] == "error"
    assert (tmp_path / "out/source.txt").read_bytes() == source.read_bytes()
    assert result["input"]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()


def test_unmarked_first_parcel_with_also_or_together_with_fails_closed(tmp_path):
    for idx, marker in enumerate(("ALSO:", "TOGETHER WITH:")):
        text = f"{SQUARE}\n{marker} THENCE N 0° E 10 feet; THENCE N 90° E 10 feet."
        out_dir = tmp_path / f"multi_{idx}"
        result = review_text(text, output_dir=out_dir)
        assert result["status"] == "error", f"{marker} should fail closed: {result}"
        assert result["errors"][0]["code"] == "invalid_input"
        assert "Multiple parcel" in result["errors"][0]["message"]
        assert not (out_dir / "calls_verified.csv").exists()


def test_tracts_only_legal_description_json_accepted(tmp_path):
    from mp_models import DeedCall, LegalDescription, Tract, TractType

    square_calls = [
        DeedCall(
            course=1,
            direction_text="N 0° E",
            bearing_quadrant="N 0° E",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=100.0,
        ),
        DeedCall(
            course=2,
            direction_text="N 90° E",
            bearing_quadrant="N 90° E",
            bearing_azimuth_deg_from_north=90.0,
            distance_ft=100.0,
        ),
        DeedCall(
            course=3,
            direction_text="S 0° E",
            bearing_quadrant="S 0° E",
            bearing_azimuth_deg_from_north=180.0,
            distance_ft=100.0,
        ),
        DeedCall(
            course=4,
            direction_text="N 90° W",
            bearing_quadrant="N 90° W",
            bearing_azimuth_deg_from_north=270.0,
            distance_ft=100.0,
        ),
    ]
    legal = LegalDescription(
        tracts=[Tract(label="Tract 1", tract_type=TractType.MAIN, calls=square_calls)],
    )
    payload = legal.model_dump(mode="json")
    payload.pop("calls", None)
    source = tmp_path / "tracts_only.json"
    source.write_text(json.dumps(payload), encoding="utf-8")

    result = verify_file(source, output_dir=tmp_path / "out")
    assert result["status"] == "checks_passed", result["errors"]
    assert len(result["calls"]) == 4


def test_bom_prefixed_csv_parsed_while_preserving_raw_source_bytes(tmp_path):
    initial = review_text(SQUARE, output_dir=tmp_path / "initial")
    assert initial["status"] == "checks_passed"
    raw_csv = (tmp_path / "initial/calls.csv").read_bytes()
    bom_bytes = b"\xef\xbb\xbf" + raw_csv
    bom_csv = tmp_path / "bom.csv"
    bom_csv.write_bytes(bom_bytes)

    result = verify_file(bom_csv, output_dir=tmp_path / "out")
    assert result["status"] == "checks_passed", result["errors"]
    assert len(result["calls"]) == 4
    assert result["input"]["sha256"] == hashlib.sha256(bom_bytes).hexdigest()
    assert (tmp_path / "out/source.txt").read_bytes() == bom_bytes


def test_verified_sidecars_recorded_in_artifacts(tmp_path):
    text = (
        "COMMENCING at a stone; THENCE N 0° E 50 feet to the POINT OF BEGINNING; "
        + SQUARE.split("; ", 1)[1]
    )
    result = review_text(text, output_dir=tmp_path / "out")
    assert result["status"] == "checks_passed", result["errors"]
    assert "calls_verified.verification.txt" in result["artifacts"]
    assert "calls_verified.metadata.txt" in result["artifacts"]
    assert (tmp_path / "out/calls_verified.verification.txt").exists()
    assert (tmp_path / "out/calls_verified.metadata.txt").exists()


def test_approximate_stated_area_propagated_to_legal_description(tmp_path):
    text = SQUARE + "\nContaining approximately 10,000 square feet."
    result = review_text(text, output_dir=tmp_path / "out")
    assert result["status"] == "checks_passed", result["errors"]
    audit = json.loads((tmp_path / "out/audit.json").read_text())
    assert audit["legal_description"]["stated_area_approximate"] is True


def test_csv_parsed_in_single_pass_without_dict_reader(tmp_path, monkeypatch):
    import csv

    initial = review_text(SQUARE, output_dir=tmp_path / "initial")
    assert initial["status"] == "checks_passed"

    def _forbid_dict_reader(*_args, **_kwargs):
        raise AssertionError("csv.DictReader should not be called")

    monkeypatch.setattr(csv, "DictReader", _forbid_dict_reader)
    result = verify_file(tmp_path / "initial/calls.csv")
    assert result["status"] == "checks_passed", result["errors"]
    assert len(result["calls"]) == 4
