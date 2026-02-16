"""Tests for run_registry.py — run manifest models and I/O."""

from __future__ import annotations

import json
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


class TestWriteRunManifest:
    def _make_manifest(self) -> RunManifest:
        return RunManifest(
            run_id="test-uuid",
            timestamp_utc=datetime(2026, 2, 16, 15, 30, 0, tzinfo=UTC),
            source_pdf="18 Pennbrook Dr - Deed Image (11985 - 00829).pdf",
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

    def test_writes_json_file(self, tmp_path: Path) -> None:
        from metesparser.run_registry import write_run_manifest

        manifest = self._make_manifest()
        path = write_run_manifest(manifest, tmp_path)

        assert path.exists()
        assert path.suffix == ".json"
        data = json.loads(path.read_text())
        assert data["run_id"] == "test-uuid"

    def test_filename_contains_timestamp_and_pdf_stem(self, tmp_path: Path) -> None:
        from metesparser.run_registry import write_run_manifest

        manifest = self._make_manifest()
        path = write_run_manifest(manifest, tmp_path)

        assert "2026-02-16" in path.name
        assert "18-pennbrook" in path.name.lower()

    def test_creates_runs_dir_if_missing(self, tmp_path: Path) -> None:
        from metesparser.run_registry import write_run_manifest

        runs_dir = tmp_path / "runs"
        manifest = self._make_manifest()
        path = write_run_manifest(manifest, runs_dir)

        assert runs_dir.exists()
        assert path.exists()


class TestLoadRunManifests:
    def test_loads_all_manifests(self, tmp_path: Path) -> None:
        from metesparser.run_registry import load_run_manifests, write_run_manifest

        for i in range(3):
            m = RunManifest(
                run_id=f"uuid-{i}",
                timestamp_utc=datetime(2026, 2, 16, 15, i, 0, tzinfo=UTC),
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
            write_run_manifest(m, tmp_path)

        manifests = load_run_manifests(tmp_path)
        assert len(manifests) == 3

    def test_empty_dir_returns_empty_list(self, tmp_path: Path) -> None:
        from metesparser.run_registry import load_run_manifests

        manifests = load_run_manifests(tmp_path)
        assert manifests == []

    def test_skips_malformed_json(self, tmp_path: Path) -> None:
        (tmp_path / "bad.json").write_text("{invalid json")

        from metesparser.run_registry import load_run_manifests

        manifests = load_run_manifests(tmp_path)
        assert manifests == []
