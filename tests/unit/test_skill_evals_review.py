"""Observed-run evidence must distinguish client startup from model execution."""

import hashlib
import json

import pytest

from scripts.skill_evals import summarize, validate_run
from tests.unit.test_skill_evals import make_run


def replace_transcript(path, content):
    record = json.loads(path.read_bytes())
    transcript = path.parent / "observed.jsonl"
    transcript.write_bytes(content)
    record.update(
        transcript_path="observed.jsonl", transcript_sha256=hashlib.sha256(content).hexdigest()
    )
    path.write_text(json.dumps(record))
    return record


@pytest.mark.parametrize(
    "payload",
    [
        b'{"type":"system","subtype":"init","model":"synthetic-native-model"}\n{"type":"assistant","error":"authentication_failed","message":{"role":"assistant","model":"<synthetic>","content":[{"type":"text","text":"OAuth session expired"}]}}\n{"type":"result","is_error":true,"result":"Authentication failed","total_cost_usd":0}\n',
        b'{"turns": []}',
        b'{"type":"system","subtype":"init","model":"synthetic-native-model"}\n',
    ],
)
def test_validator_rejects_all_pass_flags_without_observed_model_behavior(tmp_path, payload):
    path = make_run(tmp_path)
    replace_transcript(path, payload)
    errors = validate_run(path)
    assert errors
    assert any(
        "transcript" in error and ("observ" in error or "failure" in error) for error in errors
    )


def test_client_failure_can_be_recorded_as_not_run_without_a_behavior_score(tmp_path):
    path = make_run(tmp_path)
    record = replace_transcript(
        path,
        b'{"type":"result","is_error":true,"result":"Authentication failed","total_cost_usd":0}\n',
    )
    record.update(overall_result="not_run", overall_reason="Authentication failed before inference")
    for criterion in record["criteria"]:
        criterion.update(
            result="not_run",
            evidence="Client terminal authentication error; no model behavior observed.",
        )
    for action in record["required_actions"]:
        action.update(
            result="not_run",
            evidence="Client terminal authentication error",
            reason="No authenticated native client was available.",
        )
    path.write_text(json.dumps(record))
    assert validate_run(path) == []
    ledger = summarize([path])
    assert ledger["groups"][0]["validated_result_counts"]["pass"] == 0
    assert ledger["groups"][0]["validated_result_counts"]["not_run"] == 1


def test_not_run_conditions_do_not_become_an_observed_pair(tmp_path):
    baseline = make_run(tmp_path)
    record = json.loads(baseline.read_bytes())
    record.update(overall_result="not_run", overall_reason="Native client unavailable")
    for criterion in record["criteria"]:
        criterion.update(result="not_run", evidence="Client unavailable")
    for action in record["required_actions"]:
        action.update(
            result="not_run", evidence="Client unavailable", reason="Authentication unavailable"
        )
    baseline.write_text(json.dumps(record))
    skill = tmp_path / "SKILL.md"
    skill.write_text("Synthetic isolated skill resource")
    skill_record = dict(
        record,
        run_id="trial-b",
        condition="with_skill",
        skill_files_and_hashes=[
            {"path": "SKILL.md", "sha256": hashlib.sha256(skill.read_bytes()).hexdigest()}
        ],
    )
    with_skill = tmp_path / "with-skill.json"
    with_skill.write_text(json.dumps(skill_record))
    ledger = summarize([baseline, with_skill])
    assert ledger["pairs"][0]["status"] == "incomplete_pair"
    assert any("not_run" in reason for reason in ledger["pairs"][0]["reasons"])


@pytest.mark.parametrize("outcome", [[], {}])
def test_malformed_overall_result_returns_errors_instead_of_raising(tmp_path, outcome):
    path = make_run(tmp_path)
    record = json.loads(path.read_bytes())
    record["overall_result"] = outcome
    path.write_text(json.dumps(record))
    assert any("overall_result" in error for error in validate_run(path))
