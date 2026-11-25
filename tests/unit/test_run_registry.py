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

    def test_git_sha_for_file_resolves_relative_repo_path(self) -> None:
        from metesparser.run_registry import _git_sha_for_file

        sha = _git_sha_for_file(Path("prompts/normalize_text.yaml"))
        assert sha is not None and len(sha) == 40

    def test_git_sha_for_file_returns_none_on_nonzero_and_oserror(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        import subprocess
        from types import SimpleNamespace

        from metesparser.run_registry import _git_sha_for_file

        f = tmp_path / "x.yaml"
        f.write_text("a: 1\n", encoding="utf-8")

        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **kw: SimpleNamespace(returncode=128, stdout="stale\n"),
        )
        assert _git_sha_for_file(f) is None

        def _raise_oserror(*_a, **_kw):
            raise OSError("permission denied")

        monkeypatch.setattr(subprocess, "run", _raise_oserror)
        assert _git_sha_for_file(f) is None


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


class TestFormatComparisonTable:
    def test_formats_grouped_by_pdf(self) -> None:
        from metesparser.run_registry import format_comparison_table

        manifests = [
            RunManifest(
                run_id="uuid-1",
                timestamp_utc=datetime(2026, 2, 16, 15, 0, 0, tzinfo=UTC),
                source_pdf="deed_a.pdf",
                llm_provider="openai",
                llm_model="gpt-5.2",
                cache_enabled=False,
                prompt_versions={
                    "normalize_text": PromptVersion(git_sha="aaa1111bbb2222ccc", content_hash="x"),
                },
                results=RunResults(
                    call_count=4,
                    closure_passed=True,
                    misclosure_ft=0.001,
                    area_sq_ft=10000.0,
                    confidence_score=0.9,
                    warnings=[],
                ),
                parser_version="0.4.0",
            ),
            RunManifest(
                run_id="uuid-2",
                timestamp_utc=datetime(2026, 2, 16, 16, 0, 0, tzinfo=UTC),
                source_pdf="deed_a.pdf",
                llm_provider="openai",
                llm_model="gpt-5.2",
                cache_enabled=False,
                prompt_versions={
                    "normalize_text": PromptVersion(git_sha="ddd4444eee5555fff", content_hash="y"),
                },
                results=RunResults(
                    call_count=5,
                    closure_passed=False,
                    misclosure_ft=0.5,
                    area_sq_ft=10200.0,
                    confidence_score=0.7,
                    warnings=["Misclosure too high"],
                ),
                parser_version="0.4.0",
            ),
        ]

        output = format_comparison_table(manifests)
        assert "deed_a.pdf" in output
        assert "aaa1111" in output
        assert "ddd4444" in output
        assert "PASS" in output
        assert "FAIL" in output

    def test_empty_manifests(self) -> None:
        from metesparser.run_registry import format_comparison_table

        output = format_comparison_table([])
        assert "No runs found" in output

    def test_filter_by_pdf(self) -> None:
        from metesparser.run_registry import format_comparison_table

        manifests = [
            RunManifest(
                run_id=f"uuid-{i}",
                timestamp_utc=datetime(2026, 2, 16, 15, i, 0, tzinfo=UTC),
                source_pdf=f"deed_{c}.pdf",
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
            for i, c in enumerate(["a", "b"])
        ]

        output = format_comparison_table(manifests, pdf_filter="deed_a")
        assert "deed_a.pdf" in output
        assert "deed_b.pdf" not in output

    def test_mixed_naive_and_offset_timestamps_normalize_to_utc(self, tmp_path: Path) -> None:
        from datetime import timedelta, timezone

        from metesparser.run_registry import format_comparison_table, write_run_manifest

        offset_dt = datetime(2026, 2, 16, 15, 30, 0, tzinfo=timezone(timedelta(hours=5)))
        naive_dt = datetime(2026, 2, 16, 12, 0, 0)
        results = RunResults(
            call_count=4,
            closure_passed=True,
            misclosure_ft=0.0,
            area_sq_ft=10000.0,
            confidence_score=0.9,
            warnings=[],
        )
        m_offset = RunManifest(
            run_id="uuid-offset",
            timestamp_utc=offset_dt,
            source_pdf="deed.pdf",
            llm_provider="openai",
            llm_model="gpt-5.2",
            cache_enabled=False,
            prompt_versions={},
            results=results,
            parser_version="0.4.0",
        )
        m_naive = RunManifest(
            run_id="uuid-naive",
            timestamp_utc=naive_dt,
            source_pdf="deed.pdf",
            llm_provider="openai",
            llm_model="gpt-5.2",
            cache_enabled=False,
            prompt_versions={},
            results=results,
            parser_version="0.4.0",
        )

        path = write_run_manifest(m_offset, tmp_path)
        assert path.name.startswith("2026-02-16T103000-")

        table = format_comparison_table([m_naive, m_offset])
        assert "2026-02-16 10:30" in table
        assert "2026-02-16 12:00" in table
        assert table.index("2026-02-16 10:30") < table.index("2026-02-16 12:00")


def test_slugify_pdf_name_fallback_when_empty() -> None:
    from metesparser.run_registry import _slugify_pdf_name

    assert _slugify_pdf_name("---.pdf") == "deed"
    assert _slugify_pdf_name("!!!.pdf") == "deed"
