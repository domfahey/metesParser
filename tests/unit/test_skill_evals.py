"""Regression tests for deterministic preparation and evidence validation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pypdf import PdfReader

from scripts.skill_evals import (
    _fixture_json,
    _page_lines,
    _selection_text,
    main,
    materialize,
    summarize,
    validate_run,
)

ROOT = Path(__file__).resolve().parents[2]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_run(tmp_path: Path, *, outcome: str = "pass") -> Path:
    candidate = tmp_path / "candidate"
    evaluator = tmp_path / "evaluator"
    materialize("source-reading-obscured-digits", candidate, evaluator)
    transcript = tmp_path / "transcript.json"
    transcript.write_text(json.dumps({"turns": [{"role": "assistant", "text": "uncertain"}]}))
    manifest_path = candidate / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    record = {
        "schema_version": "1.0",
        "run_id": "trial-a",
        "case_id": "source-reading-obscured-digits",
        "pair_id": "pair-a",
        "condition": "baseline",
        "model_provider": "test",
        "model_name_version": "synthetic-1",
        "client_surface": "test-client",
        "started_at_utc": "2026-10-28T12:00:00Z",
        "case_source_commit": "test-commit",
        "case_source_sha256": sha256(ROOT / "plugins/metesparser/evals/cases.json"),
        "fresh_session": True,
        "skill_files_and_hashes": [],
        "available_tools_and_schema_evidence": [],
        "artifact_paths": [item["path"] for item in manifest["artifacts"]],
        "input_manifest_path": "candidate/manifest.json",
        "input_manifest_sha256": sha256(manifest_path),
        "rubric_path": "evaluator/rubric.json",
        "candidate_bundle_path": "candidate",
        "isolation_status": "equivalent",
        "transcript_path": "transcript.json",
        "transcript_sha256": sha256(transcript),
        "criteria": [
            {"criterion_id": item["id"], "result": outcome, "evidence": "turn 1"}
            for item in json.loads((evaluator / "rubric.json").read_text())["criteria"]
        ],
        "required_actions": [
            {"action": "native_document_reading", "result": "pass", "evidence": "transcript turn 1"}
        ],
        "overall_result": outcome,
    }
    path = tmp_path / "run.json"
    path.write_text(json.dumps(record))
    return path


def test_materialize_creates_synthetic_pdf_and_image_families_without_rubric_leak(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate"
    evaluator = tmp_path / "evaluator"
    materialize("source-reading-obscured-digits", candidate, evaluator)

    manifest = json.loads((candidate / "manifest.json").read_text())
    assert manifest["case_id"] == "source-reading-obscured-digits"
    kinds = {artifact["kind"] for artifact in manifest["artifacts"]}
    assert {"pdf", "png"} <= kinds
    assert all((candidate / artifact["path"]).is_file() for artifact in manifest["artifacts"])
    assert (evaluator / "rubric.json").is_file()
    candidate_text = " ".join(
        p.read_text(errors="ignore") for p in candidate.rglob("*") if p.is_file()
    )
    assert "criterion_id" not in candidate_text
    assert "evaluator rubric" not in candidate_text.lower()
    assert len(PdfReader(candidate / manifest["artifacts"][0]["path"]).pages) == 1
    from PIL import Image

    with Image.open(candidate / manifest["artifacts"][1]["path"]) as page:
        assert page.size[0] >= 1000
        assert len(page.getcolors(maxcolors=1_000_000) or []) > 2


def test_source_family_artifacts_contain_distinct_real_synthetic_evidence() -> None:
    obscured = " ".join(_page_lines("source-reading-obscured-digits")[0])
    missing = " ".join(_page_lines("source-reading-missing-exhibit")[0])
    repeated = _page_lines("source-reading-repeated-occurrences")
    selected = " ".join(_page_lines("selection-only")[0])
    assert "37 sec" in obscured
    assert "NO EXHIBIT A ATTACHED" in missing
    assert "OCCURRENCE 1" in " ".join(repeated[0])
    assert "OCCURRENCE 2" in " ".join(repeated[1])
    assert "BACKGROUND - PRIOR DEED" in selected
    assert "LESS AND EXCEPT" in selected
    assert b"BACKGROUND - PRIOR DEED DESCRIPTION" in _selection_text()


def test_materialized_repeated_occurrences_are_two_image_only_pdf_pages(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    materialize("source-reading-repeated-occurrences", candidate, tmp_path / "evaluator")
    pdf_path = candidate / "artifacts/source-1.pdf"
    reader = PdfReader(pdf_path)
    assert len(reader.pages) == 2
    assert all(not page.extract_text() for page in reader.pages)


def test_map_selection_and_reuse_fixture_inputs_have_concrete_observations(tmp_path: Path) -> None:
    map_case = tmp_path / "map-case"
    materialize("map-presentation-routing", map_case, tmp_path / "map-rubric")
    map_input = json.loads((map_case / "artifacts/source-1.json").read_text())
    from mp_models.webmap import StandaloneWebMapInput

    bundle = StandaloneWebMapInput.model_validate(map_input["bundle"])
    assert len(bundle.raster_layers) == 2
    assert all((map_case / asset).is_file() for asset in map_input["raster_layer_paths"])
    assert map_input["controls"] == ["visibility", "order"]
    assert "browser_tool_available" not in map_input
    selection = tmp_path / "selection"
    materialize("selection-only", selection, tmp_path / "selection-rubric")
    selected_text = (selection / "artifacts/source-2.txt").read_text()
    assert "NEW DESCRIPTION - BEGINNING" in selected_text
    assert "LESS AND EXCEPT: the north 10 feet conveyed to the town." in selected_text

    restart = tmp_path / "restart"
    materialize("reuse-restart", restart, tmp_path / "restart-rubric")
    from mp_review.artifact_inspect import inspect_artifacts

    unchanged = inspect_artifacts(restart / "artifacts/unchanged", requested_stage="plot")
    changed = inspect_artifacts(restart / "artifacts/changed", requested_stage="plot")
    assert unchanged["earliest_invalid_stage"] is None
    assert any(
        item["kind"] == "review" and item["status"] == "present_valid"
        for item in unchanged["artifacts"]
    )
    assert any(
        item["kind"] == "plot" and item["status"] == "present_valid"
        for item in unchanged["artifacts"]
    )
    assert changed["earliest_invalid_stage"] == "convert"
    assert any(
        item["kind"] == "acquisition" and item["status"] == "stale" for item in changed["artifacts"]
    )
    assert any(
        item["kind"] == "review" and item["status"] in {"blocked", "stale"}
        for item in changed["artifacts"]
    )
    assert any(
        item["kind"] == "plot" and item["status"] in {"blocked", "stale"}
        for item in changed["artifacts"]
    )


@pytest.mark.parametrize(
    "case_id",
    [
        "comparison-reversed-lines",
        "comparison-incompatible-basis",
        "comparison-structural-tentative",
    ],
)
def test_comparison_fixtures_are_schema_valid_and_run_engine(tmp_path: Path, case_id: str) -> None:
    from mp_models.comparison import ComparisonRequest
    from mp_verify.comparison import compare_descriptions

    candidate = tmp_path / "candidate"
    materialize(case_id, candidate, tmp_path / "evaluator")
    request_path = candidate / "artifacts/source-1.json"
    request = ComparisonRequest.model_validate_json(request_path.read_bytes())
    result = compare_descriptions(request)
    assert not result.boundary_established and not result.verified_export_eligible
    if case_id == "comparison-reversed-lines":
        assert result.pairs[0].displacement.outcome == "agree"
    elif case_id == "comparison-incompatible-basis":
        assert result.pairs[0].displacement.outcome == "not_comparable"
        assert result.pairs[0].position.outcome == "unavailable"
        assert any(item.kind == "changed" and item.tentative for item in result.structural)
    else:
        assert any(
            item.kind in {"split_candidate", "merge_candidate"} for item in result.structural
        )
        assert all(item.tentative for item in result.structural)


def test_closure_diagnosis_fixture_validates_against_public_request_schema() -> None:
    from mp_models.diagnostics import ClosureDiagnosticRequest

    request = ClosureDiagnosticRequest.model_validate(_fixture_json("closure-diagnosis"))
    assert [call.call_id for call in request.calls] == ["c1", "c2", "c3", "c4"]
    assert request.calls[0].call.distance_ft == 100.5
    assert request.input_sha256


def test_map_evidence_fixture_has_low_fit_rms_and_bad_independent_checkpoints() -> None:
    from mp_models.raster import RasterRegistration

    data = _fixture_json("map-evidence-checkpoints")
    registration = RasterRegistration.model_validate(data["registration"])
    assert registration.fit_rms is not None and registration.fit_rms < 1
    assert registration.checkpoint_rms is not None
    assert registration.checkpoint_rms > data["checkpoint_limit_px"]
    assert data["status"] == "needs_review"


def test_materialize_cli_writes_candidate_and_evaluator_outputs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "input"
    evaluator = tmp_path / "rubric"
    assert (
        main(
            [
                "materialize",
                "selection-only",
                "--output-dir",
                str(output),
                "--evaluator-dir",
                str(evaluator),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["manifest_sha256"] == sha256(
        output / "manifest.json"
    )


def test_materialize_rejects_overlapping_candidate_and_rubric_roots(tmp_path: Path) -> None:
    candidate = tmp_path / "bundle"
    evaluator = candidate / "evaluator"
    with pytest.raises(ValueError, match="must be separate, non-overlapping directories"):
        materialize("selection-only", candidate, evaluator)
    assert not candidate.exists()


def test_fixture_catalog_covers_required_matrix(tmp_path: Path) -> None:
    families = {
        "source-reading-obscured-digits",
        "source-reading-missing-exhibit",
        "source-reading-repeated-occurrences",
        "selection-only",
        "reuse-restart",
        "closure-diagnosis",
        "map-presentation-routing",
        "map-interaction-optional",
        "map-evidence-checkpoints",
        "comparison-reversed-lines",
        "comparison-incompatible-basis",
        "comparison-structural-tentative",
        "end-to-end-review",
    }
    for case_id in families:
        candidate = tmp_path / case_id
        evaluator = tmp_path / "rubrics" / case_id
        result = materialize(case_id, candidate, evaluator)
        manifest = json.loads((candidate / "manifest.json").read_text())
        assert result["manifest_sha256"] == sha256(candidate / "manifest.json")
        assert [entry["path"] for entry in manifest["artifacts"]] == json.loads(
            (candidate / "request.json").read_text()
        )["input_artifact_paths"]
        assert all(
            sha256(candidate / entry["path"]) == entry["sha256"] for entry in manifest["artifacts"]
        )
        assert (evaluator / "rubric.json").is_file()
        assert not (candidate / "rubric.json").exists()


def test_validate_run_accepts_complete_observable_record(tmp_path: Path) -> None:
    assert validate_run(make_run(tmp_path)) == []


def test_run_record_cli_and_jsonl_summary_validate_evidence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = make_run(tmp_path)
    assert main(["validate-run", str(run)]) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True
    record = json.loads(run.read_text())
    jsonl = tmp_path / "runs.jsonl"
    jsonl.write_text(json.dumps(record) + "\n")
    assert main(["summarize", str(jsonl)]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["groups"][0]["valid_runs"] == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_transcript",
        "wrong_transcript_hash",
        "missing_criterion",
        "stale_input_hash",
        "contradictory_overall_pass",
        "unrun_required_action",
        "rubric_leakage",
        "missing_model_version",
        "missing_tool_evidence",
        "missing_skill_hashes",
        "missing_action_evidence",
        "unrun_action_without_reason",
    ],
)
def test_validate_run_rejects_incomplete_or_contradictory_evidence(
    tmp_path: Path, mutation: str
) -> None:
    path = make_run(tmp_path)
    record = json.loads(path.read_text())
    if mutation == "missing_transcript":
        record["transcript_path"] = "absent.json"
    elif mutation == "wrong_transcript_hash":
        record["transcript_sha256"] = "0" * 64
    elif mutation == "missing_criterion":
        record["criteria"] = []
    elif mutation == "stale_input_hash":
        record["input_manifest_sha256"] = "0" * 64
    elif mutation == "contradictory_overall_pass":
        record["criteria"][0]["result"] = "fail"
    elif mutation == "unrun_required_action":
        record["required_actions"][0]["result"] = "not_run"
        record["required_actions"][0]["reason"] = "No native document client was available."
    elif mutation == "rubric_leakage":
        candidate = tmp_path / "candidate"
        evaluator = tmp_path / "evaluator"
        rubric_copy = candidate / "internal-notes.txt"
        copied_rubric = json.loads((evaluator / "rubric.json").read_text())
        rubric_copy.write_text(json.dumps(copied_rubric, indent=3))
    elif mutation == "missing_model_version":
        record["model_name_version"] = ""
    elif mutation == "missing_tool_evidence":
        del record["available_tools_and_schema_evidence"]
    elif mutation == "missing_skill_hashes":
        record["condition"] = "with_skill"
    elif mutation == "missing_action_evidence":
        record["required_actions"][0].pop("evidence")
    elif mutation == "unrun_action_without_reason":
        record["required_actions"][0]["result"] = "not_run"
    path.write_text(json.dumps(record))
    errors = validate_run(path)
    assert errors
    if mutation == "rubric_leakage":
        assert any("evaluator-only rubric criteria" in error for error in errors)


def test_validate_run_rejects_pass_when_criterion_is_not_run(tmp_path: Path) -> None:
    path = make_run(tmp_path)
    record = json.loads(path.read_text())
    record["criteria"][0]["result"] = "not_run"
    path.write_text(json.dumps(record))
    assert validate_run(path)


def test_validate_run_rejects_duplicate_criterion_ids(tmp_path: Path) -> None:
    path = make_run(tmp_path)
    record = json.loads(path.read_text())
    record["criteria"].append(dict(record["criteria"][0]))
    path.write_text(json.dumps(record))
    assert any("duplicate criterion" in error for error in validate_run(path))


def test_validate_run_cannot_pass_with_weakened_evaluator_rubric(tmp_path: Path) -> None:
    path = make_run(tmp_path)
    record = json.loads(path.read_text())
    (tmp_path / "evaluator/rubric.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "case_id": record["case_id"],
                "criteria": [],
                "required_actions": [],
            }
        )
    )
    record["criteria"] = []
    record["required_actions"] = []
    path.write_text(json.dumps(record))
    assert any("authoritative rubric" in error for error in validate_run(path))


def test_validate_run_rejects_rubric_path_inside_candidate_bundle(tmp_path: Path) -> None:
    path = make_run(tmp_path)
    record = json.loads(path.read_text())
    record["rubric_path"] = "candidate/rubric.json"
    path.write_text(json.dumps(record))
    assert any("rubric path must be outside" in error for error in validate_run(path))


def test_validate_run_reports_malformed_criterion_and_action_items(tmp_path: Path) -> None:
    path = make_run(tmp_path)
    record = json.loads(path.read_text())
    record["criteria"] = ["not-an-object"]
    record["required_actions"] = [None]
    path.write_text(json.dumps(record))
    errors = validate_run(path)
    assert any("criteria must be an array of objects" in error for error in errors)
    assert any("required_actions must be an array of objects" in error for error in errors)


def test_validate_run_rejects_request_symlink_outside_candidate_root(tmp_path: Path) -> None:
    path = make_run(tmp_path)
    record = json.loads(path.read_text())
    candidate = tmp_path / "candidate"
    original_request = candidate / "request.json"
    outside = tmp_path / "outside-request.json"
    outside.write_bytes(original_request.read_bytes())
    original_request.unlink()
    original_request.symlink_to(outside)
    manifest_path = candidate / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["request_sha256"] = sha256(outside)
    manifest_path.write_text(json.dumps(manifest))
    record["input_manifest_sha256"] = sha256(manifest_path)
    path.write_text(json.dumps(record))
    assert any("candidate request" in error for error in validate_run(path))


def test_validate_run_rejects_changed_exposed_skill_resource(tmp_path: Path) -> None:
    path = make_run(tmp_path)
    record = json.loads(path.read_text())
    resource = tmp_path / "exposed" / "SKILL.md"
    resource.parent.mkdir()
    resource.write_text("original skill bytes")
    record["condition"] = "with_skill"
    record["skill_files_and_hashes"] = [{"path": "exposed/SKILL.md", "sha256": sha256(resource)}]
    path.write_text(json.dumps(record))
    resource.write_text("changed skill bytes")
    assert any("skill resource hash mismatch" in error for error in validate_run(path))


def test_validate_run_rejects_empty_transcript_even_with_matching_hash(tmp_path: Path) -> None:
    path = make_run(tmp_path)
    record = json.loads(path.read_text())
    transcript = tmp_path / "transcript.json"
    transcript.write_bytes(b"")
    record["transcript_sha256"] = sha256(transcript)
    path.write_text(json.dumps(record))
    assert any("transcript is empty" in error for error in validate_run(path))


@pytest.mark.parametrize(
    "mutation,expected",
    [
        (
            lambda run: run.update(skill_files_and_hashes=None),
            "skill hashes and available tool/schema evidence must be arrays",
        ),
        (
            lambda run: run.update(available_tools_and_schema_evidence=None),
            "skill hashes and available tool/schema evidence must be arrays",
        ),
        (
            lambda run: run.update(condition=[]),
            "condition must be baseline, with_skill, or non_equivalent",
        ),
        (
            lambda run: run["criteria"][0].update(criterion_id=None),
            "criterion IDs must be nonempty strings",
        ),
        (lambda run: run["criteria"][0].update(result=[]), "invalid criterion result"),
    ],
)
def test_validate_run_reports_malformed_nested_values_without_raising(
    tmp_path: Path, mutation, expected: str
) -> None:
    path = make_run(tmp_path)
    record = json.loads(path.read_text())
    mutation(record)
    path.write_text(json.dumps(record))
    assert any(expected in error for error in validate_run(path))


def test_validate_run_rejects_artifact_symlink_outside_candidate_root(tmp_path: Path) -> None:
    path = make_run(tmp_path)
    record = json.loads(path.read_text())
    candidate = tmp_path / "candidate"
    manifest_path = candidate / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    source = candidate / manifest["artifacts"][0]["path"]
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(source.read_bytes())
    source.unlink()
    source.symlink_to(outside)
    manifest_path.write_text(json.dumps(manifest))
    record["input_manifest_sha256"] = sha256(manifest_path)
    path.write_text(json.dumps(record))
    assert any("input artifact" in error for error in validate_run(path))


def test_summarize_rejects_duplicate_condition_records(tmp_path: Path) -> None:
    baseline = make_run(tmp_path)
    record = json.loads(baseline.read_text())
    record["condition"] = "baseline"
    baseline.write_text(json.dumps(record))
    with_skill = dict(record, condition="with_skill", run_id="trial-b")
    with_skill["skill_files_and_hashes"] = [{"path": "skills/entry.md", "sha256": "a" * 64}]
    second_baseline = dict(record, run_id="trial-c")
    skill_path = tmp_path / "skill.json"
    duplicate_path = tmp_path / "duplicate.json"
    skill_path.write_text(json.dumps(with_skill))
    duplicate_path.write_text(json.dumps(second_baseline))

    summary = summarize([baseline, skill_path, duplicate_path])
    assert summary["pairs"][0]["status"] == "non_equivalent"
    assert any("exactly one baseline" in reason for reason in summary["pairs"][0]["reasons"])


def test_not_run_overall_result_requires_reason(tmp_path: Path) -> None:
    path = make_run(tmp_path)
    record = json.loads(path.read_text())
    record["overall_result"] = "not_run"
    path.write_text(json.dumps(record))
    assert any("not-run overall result requires a reason" in error for error in validate_run(path))


def test_summarize_keeps_client_and_model_pairs_separate_and_flags_mismatch(tmp_path: Path) -> None:
    baseline = make_run(tmp_path / "baseline")
    with_skill = make_run(tmp_path / "with-skill")
    baseline_record = json.loads(baseline.read_text())
    baseline_record["condition"] = "baseline"
    baseline.write_text(json.dumps(baseline_record))
    skill_record = json.loads(with_skill.read_text())
    skill_record.update(
        {"condition": "with_skill", "run_id": "trial-b", "model_name_version": "other-model"}
    )
    with_skill.write_text(json.dumps(skill_record))

    summary = summarize([baseline, with_skill])
    assert summary["pairs"][0]["status"] == "non_equivalent"
    assert summary["groups"][0]["client_surface"] == "test-client"
    assert "improvement_score" not in summary


def test_summarize_requires_identical_tools_for_equivalent_pair(tmp_path: Path) -> None:
    baseline = make_run(tmp_path)
    baseline_record = json.loads(baseline.read_text())
    baseline_record["condition"] = "baseline"
    baseline.write_text(json.dumps(baseline_record))
    skill_record = dict(baseline_record)
    skill_record.update(
        condition="with_skill",
        run_id="trial-b",
        skill_files_and_hashes=[{"path": "skills/entry.md", "sha256": "a" * 64}],
    )
    skill_record["available_tools_and_schema_evidence"] = [{"tool": "different-browser"}]
    skill_path = tmp_path / "skill.json"
    skill_path.write_text(json.dumps(skill_record))

    summary = summarize([baseline, skill_path])
    assert summary["pairs"][0]["status"] == "non_equivalent"
    assert "mismatched available tools or tool schemas" in summary["pairs"][0]["reasons"]
