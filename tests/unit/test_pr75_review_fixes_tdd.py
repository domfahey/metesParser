"""Red-Green TDD regression tests for PR #75 Codex & adversarial review findings."""

from __future__ import annotations

import json
import re
import sys
import types
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from mp_export.csv_writer import export_verified_csv
from mp_models import (
    DESCRIPTION_ROLES_NOTE,
    AuditContext,
    DeedCall,
    LegalDescription,
    RunMetadata,
    SkippedCourse,
    Tract,
    TractType,
)
from mp_parse.calls import extract_calls
from mp_review import replay_review, review_file
from mp_review.text import prepare_text
from mp_verify import verify_closure

from metesparser import cli
from metesparser.llm_cache import CachedLLMClient
from metesparser.llm_clients import GeminiClient, OpenAIClient
from metesparser.models import ClosureResult as MonoClosureResult
from metesparser.models import Tract as MonoTract
from metesparser.models import TractType as MonoTractType
from metesparser.pdf_processor import PDFProcessor
from metesparser.review_packet import generate_traverse_plot


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
# Codex #1 (P1) & #2 (P2) + Adversarial #2 & #6: tracts-only & non-boundary JSON
# ---------------------------------------------------------------------------


def test_tracts_only_json_preserves_skipped_courses_blocker(tmp_path: Path) -> None:
    """Codex P1: tracts-only JSON with skipped_courses must not return checks_passed."""
    legal = LegalDescription(
        calls=[],
        tracts=[
            Tract(
                label="Tract 1",
                tract_type=TractType.MAIN,
                role_basis="single",
                calls=_square_calls(100.0),
                skipped_courses=[
                    SkippedCourse(
                        course=5,
                        source_course=5,
                        source_excerpt="garbled course",
                        error_type="UnparsedCourse",
                        error="could not parse",
                        tract_label="Tract 1",
                    )
                ],
            )
        ],
    )
    src = tmp_path / "tract_with_skip.json"
    src.write_text(json.dumps(legal.model_dump(mode="json")), encoding="utf-8")

    result = review_file(src, output_dir=tmp_path / "out")
    assert result["status"] == "needs_review"
    assert not (tmp_path / "out" / "calls_verified.csv").exists()
    assert any(
        "Course 5: skipped malformed course 'garbled course' (UnparsedCourse)" in warning
        for warning in result["verification"]["warnings"]
    )


def test_tracts_only_json_preserves_tract_stated_area_blocker(tmp_path: Path) -> None:
    """Codex P1: tracts-only JSON with conflicting tract stated_area_sq_ft must not pass."""
    legal = LegalDescription(
        calls=[],
        tracts=[
            Tract(
                label="Tract 1",
                tract_type=TractType.MAIN,
                role_basis="single",
                calls=_square_calls(100.0),  # 10,000 sq ft
                stated_area_sq_ft=50000.0,  # 5x mismatch
            )
        ],
    )
    src = tmp_path / "tract_bad_area.json"
    src.write_text(json.dumps(legal.model_dump(mode="json")), encoding="utf-8")

    result = review_file(src, output_dir=tmp_path / "out")
    assert result["status"] == "needs_review"
    assert not (tmp_path / "out" / "calls_verified.csv").exists()


def test_tracts_only_json_exports_verified_csv_with_output_dir(tmp_path: Path) -> None:
    """Codex P2: valid tracts-only JSON must synchronize legal.calls and export verified CSV."""
    legal = LegalDescription(
        calls=[],
        tracts=[
            Tract(
                label="Tract 1",
                tract_type=TractType.MAIN,
                role_basis="single",
                calls=_square_calls(100.0),
                stated_area_sq_ft=10000.0,
            )
        ],
    )
    src = tmp_path / "valid_tract.json"
    src.write_text(json.dumps(legal.model_dump(mode="json")), encoding="utf-8")

    out_dir = tmp_path / "out"
    result = review_file(src, output_dir=out_dir)
    assert result["status"] == "checks_passed", result["errors"]
    assert not result["errors"]
    assert (out_dir / "calls_verified.csv").is_file()
    assert "calls_verified.csv" in result["artifacts"]


def test_multi_non_boundary_tracts_with_flat_calls_cannot_bypass_review_or_export(
    tmp_path: Path,
) -> None:
    """Adversarial #2: JSON with unmarked flat calls + only non-boundary tracts must block."""
    calls = _square_calls(100.0)
    legal = LegalDescription(
        calls=calls,
        tracts=[
            Tract(
                label="Easement 1",
                tract_type=TractType.EASEMENT,
                role_basis="heading",
                calls=calls[:2],
            ),
            Tract(
                label="Exception 1",
                tract_type=TractType.EXCEPTION,
                role_basis="heading",
                calls=calls[2:],
            ),
        ],
    )
    src = tmp_path / "non_boundary_only.json"
    src.write_text(json.dumps(legal.model_dump(mode="json")), encoding="utf-8")

    out_dir = tmp_path / "out"
    result = review_file(src, output_dir=out_dir)
    assert result["status"] == "needs_review"
    assert not (out_dir / "calls_verified.csv").exists()

    # Direct export_verified_csv without tract_results must also reject non-boundary-only legal_desc
    closing = verify_closure(calls)
    with pytest.raises(ValueError, match="no parcel boundary tract"):
        export_verified_csv(calls, closing, str(tmp_path / "direct.csv"), legal_desc=legal)


def test_role_review_marks_both_calls_and_tracts_in_audit_json(tmp_path: Path) -> None:
    """Adversarial #6: audit.json must persist DESCRIPTION_ROLES_NOTE on legal.tracts calls too."""
    calls = _square_calls(100.0)
    legal = LegalDescription(
        calls=calls,
        tracts=[
            Tract(
                label="Tract 1",
                tract_type=TractType.MAIN,
                role_basis="inferred",
                calls=calls,
            ),
            Tract(
                label="Easement 1",
                tract_type=TractType.EASEMENT,
                role_basis="inferred",
                calls=_square_calls(50.0),
            ),
        ],
    )
    src = tmp_path / "inferred_roles.json"
    src.write_text(json.dumps(legal.model_dump(mode="json")), encoding="utf-8")

    out_dir = tmp_path / "out"
    result = review_file(src, output_dir=out_dir)
    assert result["status"] == "needs_review"
    audit_data = json.loads((out_dir / "audit.json").read_text(encoding="utf-8"))
    for tract_data in audit_data["legal_description"]["tracts"]:
        for call_data in tract_data["calls"]:
            assert DESCRIPTION_ROLES_NOTE in (call_data.get("notes") or "")


# ---------------------------------------------------------------------------
# Adversarial #1: Multi-tract double_entry_calls length mismatch must block ALL tracts
# ---------------------------------------------------------------------------


def test_multi_tract_double_entry_length_mismatch_blocks_earlier_main_tract() -> None:
    """Adversarial #1: mismatched total double_entry_calls must block tract 1 (main), not only last tract."""
    main_calls = _square_calls(100.0)
    exc_calls = _square_calls(20.0)
    tracts = [
        Tract(label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=main_calls),
        Tract(
            label="Exception 1",
            tract_type=TractType.EXCEPTION,
            role_basis="heading",
            calls=exc_calls,
        ),
    ]
    # Extra call appended (9 vs 8) — previously Tract 1 sliced [0:4] and falsely passed!
    double_entry = [*main_calls, *exc_calls, main_calls[0].model_copy(update={"course": 9})]
    audit = AuditContext(
        run_metadata=RunMetadata(
            parser_version="2.0.0",
            llm_provider="none",
            llm_model="none",
            prompt_hash="",
            timestamp_utc=datetime.now(UTC),
            source_pdf="multi.pdf",
            cache_enabled=False,
        )
    )
    results = verify_closure(
        [*main_calls, *exc_calls],
        tracts=tracts,
        double_entry_calls=double_entry,
        audit_context=audit,
    )
    assert len(results) == 2
    assert results[0].is_fully_verified() is False
    assert any("mismatch" in w.lower() for w in results[0].warnings)
    de_check = next(c for c in results[0].checks if c.name == "double_entry")
    assert de_check.status == "failed"


# ---------------------------------------------------------------------------
# Codex #3 (P2) & Adversarial #5: CLI _unwrap_llm_model and aggregate_tract_closure
# ---------------------------------------------------------------------------


def test_unwrap_llm_model_stops_at_provider_client_with_sdk_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Codex P2: OpenAIClient and GeminiClient own ._client (SDK) — must not unwrap past .model."""
    fake_openai = types.ModuleType("openai")
    fake_openai.OpenAI = lambda api_key: SimpleNamespace(api_key=api_key)  # type: ignore[attr-defined]
    fake_google = types.ModuleType("google")
    fake_genai = types.ModuleType("google.genai")
    fake_genai.Client = lambda api_key: SimpleNamespace(api_key=api_key)  # type: ignore[attr-defined]
    fake_types = types.ModuleType("google.genai.types")
    fake_errors = types.ModuleType("google.genai.errors")
    fake_genai.types = fake_types  # type: ignore[attr-defined]
    fake_genai.errors = fake_errors  # type: ignore[attr-defined]
    fake_google.genai = fake_genai  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)
    monkeypatch.setitem(sys.modules, "google.genai.errors", fake_errors)

    openai_client = OpenAIClient(api_key="test-key", model="gpt-5.2")
    gemini_client = GeminiClient(api_key="test-key", model="gemini-3-flash-preview")
    cache_dir = tmp_path / "unused-cache"
    cached_openai = CachedLLMClient(openai_client, cache_dir=cache_dir)
    cached_gemini = CachedLLMClient(gemini_client, cache_dir=cache_dir)

    class _Proc:
        def __init__(self, client: Any) -> None:
            self.client = client

    assert cli._unwrap_llm_model(_Proc(openai_client)) == "gpt-5.2"
    assert cli._unwrap_llm_model(_Proc(gemini_client)) == "gemini-3-flash-preview"
    assert cli._unwrap_llm_model(_Proc(cached_openai)) == "gpt-5.2"
    assert cli._unwrap_llm_model(_Proc(cached_gemini)) == "gemini-3-flash-preview"


def test_aggregate_tract_closure_preserves_all_warnings_and_handles_empty() -> None:
    """Adversarial #5: 1 main + 1 exception keeps exception warnings; empty list does not pass."""
    main_tract = MonoTract(
        label="Tract 1", tract_type=MonoTractType.MAIN, role_basis="heading", calls=[]
    )
    exc_tract = MonoTract(
        label="Exception 1", tract_type=MonoTractType.EXCEPTION, role_basis="heading", calls=[]
    )
    main_res = MonoClosureResult(
        misclosure_x_ft=0.0,
        misclosure_y_ft=0.0,
        misclosure_ft=0.0,
        area_sq_ft=10000.0,
        area_acres=10000.0 / 43560.0,
        perimeter_ft=400.0,
        closure_passed=True,
        angle_check_passed=False,  # not fully verified!
        curve_consistency_passed=True,
        warnings=[],
    )
    exc_res = MonoClosureResult(
        misclosure_x_ft=0.0,
        misclosure_y_ft=0.0,
        misclosure_ft=0.0,
        area_sq_ft=100.0,
        area_acres=100.0 / 43560.0,
        perimeter_ft=40.0,
        closure_passed=True,
        angle_check_passed=True,
        curve_consistency_passed=True,
        warnings=["Exception tract warning"],
    )

    agg = cli.aggregate_tract_closure([(main_tract, main_res), (exc_tract, exc_res)])
    assert "Exception tract warning" in agg.warnings
    assert agg.closure_passed is True
    assert not agg.is_fully_verified()

    empty_agg = cli.aggregate_tract_closure([])
    assert empty_agg.closure_passed is False
    assert empty_agg.misclosure_available is False


# ---------------------------------------------------------------------------
# Adversarial #3: Zero stated area must not crash LegalDescription construction
# ---------------------------------------------------------------------------


def test_zero_stated_area_does_not_crash_prepare_text_or_pdf_processor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Adversarial #3: 'containing 0 acres' must not raise ValidationError."""
    text = (
        "BEGINNING at an iron pin; "
        "THENCE N 0°00' E 100.00 feet; "
        "THENCE N 90°00' E 100.00 feet; "
        "THENCE S 0°00' E 100.00 feet; "
        "THENCE N 90°00' W 100.00 feet to the point of beginning, "
        "containing 0 acres, more or less."
    )
    prepared = prepare_text(text)
    assert prepared.legal_description.stated_area_sq_ft is None
    assert prepared.legal_description.stated_area_approximate is False

    pdf_path = tmp_path / "zero_area.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    processor = PDFProcessor(client=object(), cache=False)  # type: ignore[arg-type]
    monkeypatch.setattr(processor, "extract_legal_description", lambda _p: text)
    monkeypatch.setattr(processor, "normalize_legal_description", lambda t: t)
    legal_desc = processor.process_deed_pdf(str(pdf_path))
    assert legal_desc.stated_area_sq_ft is None
    assert legal_desc.stated_area_approximate is False


# ---------------------------------------------------------------------------
# Adversarial #4: Invalid packed DMS on BEGINNING clause in non-strict extract_calls
# ---------------------------------------------------------------------------


def test_extract_calls_non_strict_handles_invalid_packed_dms_in_beginning_clause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Adversarial #4: invalid packed DMS in BEGINNING fragment inside course region records skip."""
    monkeypatch.setattr(
        "mp_parse.calls._course_fragments",
        lambda *_a, **_kw: [
            "N 0°00' E 100.00 feet",
            "BEGINNING at a point N 45.7500 E",
            "S 0°00' W 100.00 feet",
        ],
    )
    text = "N 0°00' E 100.00 feet; BEGINNING at a point N 45.7500 E; S 0°00' W 100.00 feet."
    audit = AuditContext(
        run_metadata=RunMetadata(
            parser_version="2.0.0",
            llm_provider="none",
            llm_model="none",
            prompt_hash="",
            timestamp_utc=datetime.now(UTC),
            source_pdf="packed.txt",
            cache_enabled=False,
        )
    )
    calls, _ = extract_calls(text, strict=False, audit_context=audit)
    assert len(calls) == 2
    assert len(audit.skipped_courses) == 1
    assert "45.7500" in audit.skipped_courses[0].source_excerpt


# ---------------------------------------------------------------------------
# Codex #4 (P2): SVG arc bulge normal and extrema on rendered side of chord
# ---------------------------------------------------------------------------


def test_review_packet_arc_bounds_and_label_on_rendered_side_of_chord() -> None:
    """Codex P2: right-hand 180-deg curve north tangent renders at y=-100 (NOT y=+100)."""
    gt = {
        "expected_calls": [
            {
                "course": 1,
                "direction_text": "right semicircle radius 100 ft",
                "bearing_azimuth_deg_from_north": 0.0,
                "distance_ft": 314.159265,
                "curve_dir": "right",
                "radius_ft": 100.0,
                "delta_deg": 180.0,
                "arc_length_ft": 314.159265,
            },
            {
                "course": 2,
                "direction_text": "S 90° W 200 ft",
                "bearing_azimuth_deg_from_north": 270.0,
                "distance_ft": 200.0,
            },
        ]
    }
    svg = generate_traverse_plot(gt)
    vb_match = re.search(r"viewBox='([^']+)'", svg)
    assert vb_match is not None
    vb_x, vb_y, vb_w, vb_h = (float(v) for v in vb_match.group(1).split())
    # Arc goes from (0,0) to (200,0) through SVG (100, -100): viewBox MUST include y=-100!
    assert vb_y <= -100.0
    assert vb_y + vb_h < 90.0  # Must NOT extend down to +100!

    # Label #1 must sit near (100, -100), on the rendered side (y < 0)
    label_match = re.search(r"<text x='([^']+)' y='([^']+)'[^>]*>#1 ", svg)
    assert label_match is not None
    label_x, label_y = float(label_match.group(1)), float(label_match.group(2))
    assert label_x == pytest.approx(100.0, abs=0.01)
    assert label_y == pytest.approx(-100.0, abs=0.01)


def test_review_packet_major_arc_includes_cardinal_extrema_in_viewbox() -> None:
    """Codex P2: 270-deg right-hand major arc starting North must include x=200 and y=-100 extrema."""
    gt = {
        "expected_calls": [
            {
                "course": 1,
                "direction_text": "right 270-deg curve radius 100 ft",
                "bearing_azimuth_deg_from_north": 0.0,
                "distance_ft": 471.238898,
                "curve_dir": "right",
                "radius_ft": 100.0,
                "delta_deg": 270.0,
                "arc_length_ft": 471.238898,
            },
        ]
    }
    svg = generate_traverse_plot(gt)
    vb_match = re.search(r"viewBox='([^']+)'", svg)
    assert vb_match is not None
    vb_x, vb_y, vb_w, vb_h = (float(v) for v in vb_match.group(1).split())
    # Center (100, 0), radius 100, start (0,0) -> (100,-100) -> (200,0) -> (100,100)
    assert vb_x <= 0.0
    assert vb_x + vb_w >= 200.0
    assert vb_y <= -100.0
    assert vb_y + vb_h >= 100.0


def test_review_packet_left_hand_arc_bounds_and_label_on_rendered_side() -> None:
    """Codex P2: left-hand 180-deg curve starting North renders at (-100, -100), not (-100, +100)."""
    gt = {
        "expected_calls": [
            {
                "course": 1,
                "direction_text": "left semicircle radius 100 ft",
                "bearing_azimuth_deg_from_north": 0.0,
                "distance_ft": 314.159265,
                "curve_dir": "left",
                "radius_ft": 100.0,
                "delta_deg": 180.0,
                "arc_length_ft": 314.159265,
            },
            {
                "course": 2,
                "direction_text": "N 90° E 200 ft",
                "bearing_azimuth_deg_from_north": 90.0,
                "distance_ft": 200.0,
            },
        ]
    }
    svg = generate_traverse_plot(gt)
    vb_match = re.search(r"viewBox='([^']+)'", svg)
    assert vb_match is not None
    vb_x, vb_y, vb_w, vb_h = (float(v) for v in vb_match.group(1).split())
    assert vb_x <= -200.0
    assert vb_y <= -100.0
    assert vb_y + vb_h < 90.0

    label_match = re.search(r"<text x='([^']+)' y='([^']+)'[^>]*>#1 ", svg)
    assert label_match is not None
    label_x, label_y = float(label_match.group(1)), float(label_match.group(2))
    assert label_x == pytest.approx(-100.0, abs=0.01)
    assert label_y == pytest.approx(-100.0, abs=0.01)


def test_tracts_only_json_replay_review_matches_recorded_status(tmp_path: Path) -> None:
    """Tracts-only JSON replays identically in memory without artifact writes."""
    legal = LegalDescription(
        calls=[],
        tracts=[
            Tract(
                label="Tract 1",
                tract_type=TractType.MAIN,
                role_basis="single",
                calls=_square_calls(100.0),
                stated_area_sq_ft=10000.0,
            )
        ],
    )
    payload = json.dumps(legal.model_dump(mode="json")).encode("utf-8")
    src = tmp_path / "tract.json"
    src.write_bytes(payload)

    recorded = review_file(src, output_dir=tmp_path / "out")
    replayed = replay_review(payload, input_kind="json", source_name="tract.json")
    assert recorded["status"] == "checks_passed"
    assert replayed["status"] == "checks_passed"
    assert replayed["calls"] == recorded["calls"]
    assert replayed["audit"]["legal_description"]["calls"] == recorded["calls"]
