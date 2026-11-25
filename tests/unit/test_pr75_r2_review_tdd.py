"""Red-Green TDD regression tests for PR #75 Round 2 Track 3 (mp-review) findings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from mp_models import (
    EASEMENT_TRACT_NOTE,
    EXCEPTION_TRACT_NOTE,
    DeedCall,
    LegalDescription,
    Tract,
    TractType,
)
from mp_review import review_file, review_text
from mp_review.corpus import _assertions, run_corpus
from mp_review.settings import SettingsError, read_settings


def _square_calls(side: float = 100.0) -> list[DeedCall]:
    return [
        DeedCall(
            course=1,
            direction_text="N 0° E",
            bearing_quadrant="N 0°00' E",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=side,
        ),
        DeedCall(
            course=2,
            direction_text="N 90° E",
            bearing_quadrant="N 90°00' E",
            bearing_azimuth_deg_from_north=90.0,
            distance_ft=side,
        ),
        DeedCall(
            course=3,
            direction_text="S 0° E",
            bearing_quadrant="S 0°00' E",
            bearing_azimuth_deg_from_north=180.0,
            distance_ft=side,
        ),
        DeedCall(
            course=4,
            direction_text="N 90° W",
            bearing_quadrant="N 90°00' W",
            bearing_azimuth_deg_from_north=270.0,
            distance_ft=side,
        ),
    ]


# ---------------------------------------------------------------------------
# #1: Settings output_dir must not climb upward to ancestor markers ($HOME/.claude)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("marker", [".claude", ".git", "pyproject.toml"])
def test_read_settings_does_not_climb_to_ancestor_markers(tmp_path: Path, marker: str) -> None:
    """#1: Settings in a subdirectory must never climb to ancestor ~/.claude, .git, or pyproject.toml."""
    ancestor = tmp_path / "home_like"
    if marker == "pyproject.toml":
        ancestor.mkdir()
        (ancestor / marker).write_text("[project]\nname='x'\n", encoding="utf-8")
    else:
        (ancestor / marker).mkdir(parents=True)

    proj = ancestor / "workspace" / "project"
    proj.mkdir(parents=True)
    settings = proj / "metesparser.local.md"
    settings.write_text('---\noutput_dir: "../.ssh"\n---\n', encoding="utf-8")

    with pytest.raises(SettingsError, match="within the project directory"):
        read_settings(settings)

    settings.write_text('---\noutput_dir: "out"\n---\n', encoding="utf-8")
    parsed = read_settings(settings)
    assert parsed["output_dir"] == (proj / "out").resolve()


def test_read_settings_nested_under_claude_stays_in_immediate_parent(tmp_path: Path) -> None:
    """#1: .claude/nested/metesparser.local.md must stay inside .claude/nested, not climb to proj."""
    proj = tmp_path / "proj"
    nested = proj / ".claude" / "nested"
    nested.mkdir(parents=True)

    escape_settings = nested / "metesparser.local.md"
    escape_settings.write_text('---\noutput_dir: "../out"\n---\n', encoding="utf-8")
    with pytest.raises(SettingsError, match="within the project directory"):
        read_settings(escape_settings)

    local_settings = nested / "metesparser.local.md"
    local_settings.write_text('---\noutput_dir: "out"\n---\n', encoding="utf-8")
    assert read_settings(local_settings)["output_dir"] == (nested / "out").resolve()

    direct_claude = proj / ".claude" / "metesparser.local.md"
    direct_claude.write_text('---\noutput_dir: "out"\n---\n', encoding="utf-8")
    assert read_settings(direct_claude)["output_dir"] == (proj / "out").resolve()


# ---------------------------------------------------------------------------
# #2a: Multi-tract JSON trust boundary, empty main bypass, easement mixing,
#      and per-tract non-boundary marking
# ---------------------------------------------------------------------------


def test_json_mismatched_flat_calls_with_main_and_exception_tracts_rejected(tmp_path: Path) -> None:
    """#2a: Attacker supplying calls=[main] while tracts=[main, exception] must be rejected."""
    main_calls = _square_calls(100.0)
    exc_calls = _square_calls(20.0)
    legal = LegalDescription(
        calls=main_calls,  # omits exception calls
        tracts=[
            Tract(
                label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=main_calls
            ),
            Tract(
                label="Exception 1",
                tract_type=TractType.EXCEPTION,
                role_basis="heading",
                calls=exc_calls,
            ),
        ],
    )
    src = tmp_path / "mismatched_exc.json"
    src.write_text(json.dumps(legal.model_dump(mode="json")), encoding="utf-8")

    out_dir = tmp_path / "out"
    result = review_file(src, output_dir=out_dir)
    assert result["status"] == "error"
    assert result["errors"][0]["code"] == "invalid_input"
    assert "do not match tracts" in result["errors"][0]["message"]
    assert not (out_dir / "calls_verified.csv").exists()


def test_json_empty_main_and_easement_with_flat_calls_rejected(tmp_path: Path) -> None:
    """#2a: Empty main + empty easement with unmarked flat calls must not bypass non-boundary check."""
    legal = LegalDescription(
        calls=_square_calls(100.0),
        tracts=[
            Tract(label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=[]),
            Tract(
                label="Easement 1", tract_type=TractType.EASEMENT, role_basis="heading", calls=[]
            ),
        ],
    )
    src = tmp_path / "empty_main_bypass.json"
    src.write_text(json.dumps(legal.model_dump(mode="json")), encoding="utf-8")

    out_dir = tmp_path / "out"
    result = review_file(src, output_dir=out_dir)
    assert result["status"] == "error"
    assert result["errors"][0]["code"] == "invalid_input"
    assert not (out_dir / "calls_verified.csv").exists()


def test_json_mismatched_flat_calls_with_broken_main_tract_rejected(tmp_path: Path) -> None:
    """#2a: Supplying closing flat calls while main tract is broken must be rejected."""
    broken = _square_calls(100.0)[:3]
    legal = LegalDescription(
        calls=_square_calls(100.0),
        tracts=[
            Tract(label="Tract 1", tract_type=TractType.MAIN, role_basis="single", calls=broken),
        ],
    )
    src = tmp_path / "broken_tract.json"
    src.write_text(json.dumps(legal.model_dump(mode="json")), encoding="utf-8")

    out_dir = tmp_path / "out"
    result = review_file(src, output_dir=out_dir)
    assert result["status"] == "error"
    assert result["errors"][0]["code"] == "invalid_input"
    assert not (out_dir / "calls_verified.csv").exists()


def test_json_main_plus_easement_tracts_only_verifies_main_without_easement_legs(
    tmp_path: Path,
) -> None:
    """#2a: main(heading) + easement(heading) in JSON must review/export only main calls."""
    main_calls = _square_calls(100.0)
    easement_calls = _square_calls(25.0)
    legal = LegalDescription(
        calls=[],
        tracts=[
            Tract(
                label="Tract 1",
                tract_type=TractType.MAIN,
                role_basis="heading",
                calls=main_calls,
                stated_area_sq_ft=10000.0,
            ),
            Tract(
                label="Easement 1",
                tract_type=TractType.EASEMENT,
                role_basis="heading",
                calls=easement_calls,
            ),
        ],
    )
    src = tmp_path / "main_and_easement.json"
    src.write_text(json.dumps(legal.model_dump(mode="json")), encoding="utf-8")

    out_dir = tmp_path / "out"
    result = review_file(src, output_dir=out_dir)
    assert result["status"] == "checks_passed", result["errors"]
    assert len(result["calls"]) == 4
    assert (out_dir / "calls_verified.csv").is_file()


def test_json_multiple_non_boundary_tracts_mark_each_call_with_own_tract_type(
    tmp_path: Path,
) -> None:
    """#2a: [easement, exception] must stamp EASEMENT_TRACT_NOTE on easement and EXCEPTION_TRACT_NOTE on exception."""
    easement_calls = _square_calls(50.0)[:2]
    exception_calls = _square_calls(50.0)[2:]
    legal = LegalDescription(
        calls=[],
        tracts=[
            Tract(
                label="Easement 1",
                tract_type=TractType.EASEMENT,
                role_basis="heading",
                calls=easement_calls,
            ),
            Tract(
                label="Exception 1",
                tract_type=TractType.EXCEPTION,
                role_basis="heading",
                calls=exception_calls,
            ),
        ],
    )
    src = tmp_path / "easement_and_exception.json"
    src.write_text(json.dumps(legal.model_dump(mode="json")), encoding="utf-8")

    result = review_file(src)
    assert result["status"] == "needs_review"
    assert len(result["calls"]) == 4
    for call_data in result["calls"][:2]:
        assert EASEMENT_TRACT_NOTE in (call_data.get("notes") or "")
        assert EXCEPTION_TRACT_NOTE not in (call_data.get("notes") or "")
    for call_data in result["calls"][2:]:
        assert EXCEPTION_TRACT_NOTE in (call_data.get("notes") or "")
        assert EASEMENT_TRACT_NOTE not in (call_data.get("notes") or "")


# ---------------------------------------------------------------------------
# #8: Conflicting top-level vs boundary-tract stated_area_sq_ft
# ---------------------------------------------------------------------------


def test_json_conflicting_top_level_and_tract_stated_area_blocks_verified_export(
    tmp_path: Path,
) -> None:
    """#8: Top-level stated_area_sq_ft (10000) vs tract stated_area_sq_ft (50000) must block."""
    legal = LegalDescription(
        calls=[],
        stated_area_sq_ft=10000.0,
        tracts=[
            Tract(
                label="Tract 1",
                tract_type=TractType.MAIN,
                role_basis="single",
                calls=_square_calls(100.0),
                stated_area_sq_ft=50000.0,
            ),
        ],
    )
    src = tmp_path / "conflict_area.json"
    src.write_text(json.dumps(legal.model_dump(mode="json")), encoding="utf-8")

    out_dir = tmp_path / "out"
    result = review_file(src, output_dir=out_dir)
    assert result["status"] == "needs_review"
    assert any(err.get("code") == "conflicting_stated_area" for err in result["errors"])
    assert not (out_dir / "calls_verified.csv").exists()


# ---------------------------------------------------------------------------
# #9a: Non-positive stated area in prose ("containing 0 acres") blocks review
# ---------------------------------------------------------------------------


def test_zero_stated_area_in_prose_blocks_review_and_verified_export(tmp_path: Path) -> None:
    """#9a: 'containing 0 acres' must return needs_review with invalid_stated_area, not checks_passed."""
    text = (
        "BEGINNING at an iron pin; "
        "THENCE N 0°00' E 100.00 feet; "
        "THENCE N 90°00' E 100.00 feet; "
        "THENCE S 0°00' E 100.00 feet; "
        "THENCE N 90°00' W 100.00 feet to the point of beginning, "
        "containing 0 acres, more or less."
    )
    out_dir = tmp_path / "out"
    result = review_text(text, output_dir=out_dir)
    assert result["status"] == "needs_review"
    assert any(err.get("code") == "invalid_stated_area" for err in result["errors"])
    assert not (out_dir / "calls_verified.csv").exists()


# ---------------------------------------------------------------------------
# #14: bool-as-int equality bypass in corpus assertions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("actual_field", "actual_val", "wanted_val"),
    [
        ("is_exception", False, 0),
        ("is_exception", True, 1),
        ("course", 0, False),
        ("distance_ft", 1.0, True),
    ],
)
def test_corpus_assertions_reject_bool_int_cross_type_equality(
    actual_field: str, actual_val: Any, wanted_val: Any
) -> None:
    """#14: False == 0 and True == 1 must never pass corpus assertions."""
    result = {"calls": [{actual_field: actual_val}]}
    checks = _assertions(result, {"selected_calls": [{actual_field: wanted_val}]})
    assert len(checks) == 1
    assert checks[0]["passed"] is False


def test_run_corpus_fails_when_selected_call_uses_int_for_bool_field(tmp_path: Path) -> None:
    """#14: End-to-end run_corpus rejects selected_calls comparing int 0 against bool False."""
    square = tmp_path / "square.txt"
    square.write_text(
        "BEGINNING at an iron pin; "
        "THENCE N 0°00' E 100.00 feet; "
        "THENCE N 90°00' E 100.00 feet; "
        "THENCE S 0°00' E 100.00 feet; "
        "THENCE N 90°00' W 100.00 feet to the point of beginning.",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": "1.0",
        "reviewed_basis": "Regression check for bool/int equality.",
        "cases": [
            {
                "id": "bool-int-bypass",
                "input": {"kind": "text", "path": "square.txt"},
                "expect": {"selected_calls": [{"is_exception": 0}]},
            }
        ],
    }
    manifest_path = tmp_path / "corpus.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = run_corpus(manifest_path)
    assert report["status"] == "failed"
    assert report["cases"][0]["status"] == "failed"
    assert report["cases"][0]["assertions"][0]["passed"] is False
