"""verify the single-tract review audit payload has no per-tract key."""

from __future__ import annotations

import mp_review.api as api

SQUARE = "BEGINNING at a point; THENCE N 0° E 100 feet; THENCE S 90° E 100 feet; THENCE S 0° E 100 feet; THENCE N 90° W 100 feet."


def test_audit_payload_omits_tract_key_for_single_traverse():
    out = api._run(SQUARE.encode(), "d.txt", "text", None, None, include_audit=True)
    assert "tract_verification_audits" not in out["audit"]


def test_audit_payload_records_empty_skipped_courses():
    out = api._run(SQUARE.encode(), "d.txt", "text", None, None, include_audit=True)
    assert out["audit"]["skipped_courses"] == []


def test_audit_payload_records_skipped_courses_and_blocks_status(monkeypatch, tmp_path):
    from mp_models.audit import SkippedCourse

    original = api.prepare_text

    def non_strict(text, *, audit_context):
        prepared = original(text, audit_context=audit_context)
        audit_context.skipped_courses.append(
            SkippedCourse(
                course=5,
                source_course=5,
                source_excerpt="THENCE somewhere",
                error_type="ValueError",
                error="unparsed",
            )
        )
        return prepared

    monkeypatch.setattr(api, "prepare_text", non_strict)
    out = api._run(SQUARE.encode(), "d.txt", "text", tmp_path / "out", None, include_audit=True)
    assert [s["source_excerpt"] for s in out["audit"]["skipped_courses"]] == ["THENCE somewhere"]
    assert out["status"] != "checks_passed"
    assert "calls_verified.csv" not in out["artifacts"]
    written = (tmp_path / "out/audit.json").read_text()
    assert "THENCE somewhere" in written
