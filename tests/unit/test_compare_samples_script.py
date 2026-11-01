"""The sample comparison report groups result-level changes between two snapshots."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "compare_samples.py"


@pytest.fixture(scope="module")
def compare() -> ModuleType:
    spec = importlib.util.spec_from_file_location("compare_samples_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _call(bearing: float | None = 45.0, distance: float | None = 100.0) -> dict[str, Any]:
    return {
        "bearing_azimuth_deg_from_north": bearing,
        "distance_ft": distance,
        "is_tie_in": False,
        "is_exception": False,
    }


def _record(
    *,
    verified: bool = True,
    exported: bool = True,
    calls: list[dict[str, Any]] | None = None,
    tracts: list[dict[str, Any]] | None = None,
    error: dict[str, str] | None = None,
) -> dict[str, Any]:
    calls = [_call()] if calls is None else calls
    return {
        "extraction": {"error": None, "call_count": len(calls)},
        "calls": calls,
        "tracts": tracts or [],
        "verification": {
            "error": None,
            "verified": verified,
            "results": [
                {
                    "tract": None,
                    "misclosure_available": True,
                    "misclosure": 0.0,
                    "area": 1000.0,
                    "fully_verified": verified,
                }
            ],
        },
        "export": {"error": error, "ok": exported, "files": ["export.csv"] if exported else []},
    }


def test_unchanged_samples_produce_no_entry(compare: ModuleType):
    before = {"a.md": _record(), "b.md": _record(verified=False, exported=False)}
    after = {"a.md": _record(), "b.md": _record(verified=False, exported=False)}

    assert compare.diff_samples(before, after) == {}


def test_verification_and_export_flips_are_reported_as_lost_or_gained(compare: ModuleType):
    before = {
        "lost.md": _record(verified=True, exported=True),
        "gained.md": _record(verified=False, exported=False),
    }
    after = {
        "lost.md": _record(verified=False, exported=False),
        "gained.md": _record(verified=True, exported=True),
    }

    changes = compare.diff_samples(before, after)
    summary = compare.summarize(changes)

    assert set(changes["lost.md"]) >= {"verification_lost", "export_lost"}
    assert set(changes["gained.md"]) >= {"verification_gained", "export_gained"}
    assert summary["verification_lost"] == ["lost.md"]
    assert summary["verification_gained"] == ["gained.md"]
    assert summary["export_lost"] == ["lost.md"]
    assert summary["export_gained"] == ["gained.md"]


def test_course_value_changes_report_changed_indices_and_call_count(compare: ModuleType):
    before = {"deed.md": _record(calls=[_call(45.0, 100.0), _call(90.0, 50.0)])}
    after = {"deed.md": _record(calls=[_call(45.0, 100.5), _call(90.0, 50.0), _call(0.0, 10.0)])}

    detail = compare.diff_samples(before, after)["deed.md"]["course_values"]

    assert detail["call_count"] == {"before": 2, "after": 3}
    assert [item["index"] for item in detail["changed"]] == [0, 2]
    assert detail["changed"][0] == {
        "index": 0,
        "before": _call(45.0, 100.0),
        "after": _call(45.0, 100.5),
    }
    assert detail["changed"][1]["before"] is None


def test_tract_changes_are_reported_and_summarized(compare: ModuleType):
    main = {"label": "Tract 1", "type": "main", "role_basis": "heading"}
    before = {"deed.md": _record(tracts=[main])}
    after = {"deed.md": _record(tracts=[{**main, "role_basis": "inferred"}])}

    changes = compare.diff_samples(before, after)

    assert changes["deed.md"]["tract_changes"]["before"] == [main]
    assert compare.summarize(changes)["tract_changes"] == ["deed.md"]


def test_error_changes_are_reported_per_stage(compare: ModuleType):
    before = {"deed.md": _record(error=None)}
    after = {"deed.md": _record(exported=False, error={"type": "ValueError", "message": "x"})}

    changes = compare.diff_samples(before, after)

    assert set(changes["deed.md"]["errors"]) == {"export"}
    assert changes["deed.md"]["errors"]["export"]["after"] == {
        "type": "ValueError",
        "message": "x",
    }
    assert compare.summarize(changes)["errors"] == ["deed.md"]


def test_sample_present_on_one_side_is_reported_as_sample_set(compare: ModuleType):
    before = {"old.md": _record()}
    after = {"new.md": _record()}

    changes = compare.diff_samples(before, after)

    assert changes["old.md"] == {"sample_set": {"before": True, "after": False}}
    assert changes["new.md"] == {"sample_set": {"before": False, "after": True}}
    assert compare.summarize(changes)["sample_set"] == ["new.md", "old.md"]


def test_summarize_keeps_every_category_and_sorts_keys(compare: ModuleType):
    changes = {
        "z.md": {"verification_lost": {"before": True, "after": False}},
        "a.md": {"verification_lost": {"before": True, "after": False}},
    }

    summary = compare.summarize(changes)

    assert summary["verification_lost"] == ["a.md", "z.md"]
    assert set(summary) == set(compare.CATEGORIES)
    assert summary["export_gained"] == []


def test_format_summary_lists_samples_that_lost_verification_or_export(compare: ModuleType):
    summary = compare.summarize(
        {
            "lost-verify.md": {"verification_lost": {"before": True, "after": False}},
            "lost-export.md": {"export_lost": {"before": True, "after": False}},
            "gained.md": {"export_gained": {"before": False, "after": True}},
        }
    )

    text = compare.format_summary("main", "HEAD", 10, summary)

    assert "Samples: 10 (3 changed)" in text
    assert "Verification lost (1):\n  - lost-verify.md" in text
    assert "Export lost (1):\n  - lost-export.md" in text
    assert "gained.md" not in text


def test_accepted_keeps_only_keywords_an_older_signature_has(compare: ModuleType):
    def older(text: str, *, strict: bool = True) -> None:
        del text, strict

    kwargs = {"strict": False, "skipped_courses": []}

    assert compare._accepted(older, **kwargs) == {"strict": False}
