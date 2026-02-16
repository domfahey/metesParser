"""Tests for run_registry.py — run manifest models and I/O."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from metesparser.run_registry import (
    PromptVersion,
    RunManifest,
    RunResults,
)


class TestPromptVersion:
    def test_create_with_git_sha(self) -> None:
        pv = PromptVersion(git_sha="abc1234", content_hash="sha256deadbeef")
        assert pv.git_sha == "abc1234"
        assert pv.content_hash == "sha256deadbeef"

    def test_create_without_git_sha(self) -> None:
        pv = PromptVersion(git_sha=None, content_hash="sha256deadbeef")
        assert pv.git_sha is None


class TestRunResults:
    def test_create(self) -> None:
        r = RunResults(
            call_count=4,
            closure_passed=True,
            misclosure_ft=0.001,
            area_sq_ft=2971.0,
            confidence_score=0.85,
            warnings=[],
        )
        assert r.call_count == 4
        assert r.closure_passed is True

    def test_with_warnings(self) -> None:
        r = RunResults(
            call_count=4,
            closure_passed=False,
            misclosure_ft=0.5,
            area_sq_ft=2971.0,
            confidence_score=0.6,
            warnings=["Misclosure exceeds tolerance"],
        )
        assert len(r.warnings) == 1


class TestRunManifest:
    def test_create_full(self) -> None:
        m = RunManifest(
            run_id="test-uuid",
            timestamp_utc=datetime(2026, 2, 16, tzinfo=UTC),
            source_pdf="test.pdf",
            llm_provider="openai",
            llm_model="gpt-5.2",
            cache_enabled=False,
            prompt_versions={
                "extract_text_from_pdf": PromptVersion(git_sha="aaa", content_hash="bbb"),
            },
            results=RunResults(
                call_count=4,
                closure_passed=True,
                misclosure_ft=0.0,
                area_sq_ft=10000.0,
                confidence_score=0.9,
                warnings=[],
            ),
            parser_version="0.4.0",
        )
        assert m.schema_version == "1.0.0"
        assert m.source_pdf == "test.pdf"

    def test_roundtrip_json(self) -> None:
        m = RunManifest(
            run_id="test-uuid",
            timestamp_utc=datetime(2026, 2, 16, tzinfo=UTC),
            source_pdf="test.pdf",
            llm_provider="openai",
            llm_model="gpt-5.2",
            cache_enabled=False,
            prompt_versions={},
            results=RunResults(
                call_count=4,
                closure_passed=True,
                misclosure_ft=0.0,
                area_sq_ft=10000.0,
                confidence_score=0.9,
                warnings=[],
            ),
            parser_version="0.4.0",
        )
        json_str = m.model_dump_json()
        loaded = RunManifest.model_validate_json(json_str)
        assert loaded.run_id == m.run_id


class TestGetPromptVersions:
    def test_returns_dict_of_prompt_versions(self, tmp_path: Path) -> None:
        prompt_file = tmp_path / "test_prompt.yaml"
        prompt_file.write_text("system_prompt: hello\n")

        from metesparser.run_registry import get_prompt_versions

        versions = get_prompt_versions(tmp_path)
        assert "test_prompt" in versions
        assert versions["test_prompt"].content_hash  # non-empty hash

    def test_content_hash_changes_with_content(self, tmp_path: Path) -> None:
        prompt_file = tmp_path / "test_prompt.yaml"

        prompt_file.write_text("version: 1\n")
        from metesparser.run_registry import get_prompt_versions

        v1 = get_prompt_versions(tmp_path)

        prompt_file.write_text("version: 2\n")
        v2 = get_prompt_versions(tmp_path)

        assert v1["test_prompt"].content_hash != v2["test_prompt"].content_hash

    def test_git_sha_is_none_outside_repo(self, tmp_path: Path) -> None:
        prompt_file = tmp_path / "test_prompt.yaml"
        prompt_file.write_text("system_prompt: hello\n")

        from metesparser.run_registry import get_prompt_versions

        versions = get_prompt_versions(tmp_path)
        # tmp_path is not inside a git repo, so git_sha should be None
        assert versions["test_prompt"].git_sha is None
