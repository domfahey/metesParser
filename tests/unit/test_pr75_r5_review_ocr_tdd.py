"""Red-Green TDD tests for PR #75 Round 5 Track 3 (mp-review, mp-ocr, monolith OCR)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
import structlog.testing
from mp_models import (
    DESCRIPTION_ROLES_NOTE,
    EASEMENT_TRACT_NOTE,
    EXCEPTION_TRACT_NOTE,
    INVALID_STATED_AREA_NOTE_PREFIX,
    DeedCall,
    LegalDescription,
    SkippedCourse,
    Tract,
    TractType,
    mark_non_boundary,
    split_notes,
)
from mp_ocr.cache import CachedLLMClient as PackageCachedClient
from mp_ocr.clients import GeminiClient as PackageGeminiClient
from mp_ocr.clients import OpenAIClient as PackageOpenAIClient
from mp_ocr.extract import PDFProcessor as PackagePDFProcessor
from mp_review.api import replay_review, review_file, review_text
from mp_review.settings import SettingsError, read_settings
from mp_review.text import prepare_text

from metesparser.closure_checker import ClosureChecker
from metesparser.llm_cache import CachedLLMClient as MonolithCachedClient
from metesparser.llm_clients import GeminiClient as MonolithGeminiClient
from metesparser.llm_clients import OpenAIClient as MonolithOpenAIClient
from metesparser.pdf_processor import PDFProcessor as MonolithPDFProcessor

_SQUARE_TEXT = (
    "BEGINNING at an iron pin; "
    "THENCE N 0°00'00\" E, 100.00 feet; "
    "THENCE N 90°00'00\" E, 100.00 feet; "
    "THENCE S 0°00'00\" W, 100.00 feet; "
    "THENCE N 90°00'00\" W, 100.00 feet to the point of beginning."
)


def _square_calls(side: float = 100.0, *, is_exception: bool = False) -> list[DeedCall]:
    return [
        DeedCall(
            course=1,
            direction_text="N 0° E",
            bearing_quadrant="N 0°00' E",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=side,
            is_exception=is_exception,
        ),
        DeedCall(
            course=2,
            direction_text="N 90° E",
            bearing_quadrant="N 90°00' E",
            bearing_azimuth_deg_from_north=90.0,
            distance_ft=side,
            is_exception=is_exception,
        ),
        DeedCall(
            course=3,
            direction_text="S 0° E",
            bearing_quadrant="S 0°00' E",
            bearing_azimuth_deg_from_north=180.0,
            distance_ft=side,
            is_exception=is_exception,
        ),
        DeedCall(
            course=4,
            direction_text="N 90° W",
            bearing_quadrant="N 90°00' W",
            bearing_azimuth_deg_from_north=270.0,
            distance_ft=side,
            is_exception=is_exception,
        ),
    ]


# ---------------------------------------------------------------------------
# 1. mp-review api.py: bool/non-finite stated_area_sq_ft + manifest safety
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_area",
    [0.0, -5.0, float("nan"), float("inf"), float("-inf"), True, False],
)
def test_review_text_rejects_invalid_and_bool_stated_area_sq_ft(bad_area: Any) -> None:
    result = review_text(_SQUARE_TEXT, stated_area_sq_ft=bad_area)
    assert result["status"] == "error"
    assert result["errors"][0]["code"] == "invalid_input"
    assert "finite and positive" in result["errors"][0]["message"].lower()


@pytest.mark.parametrize(
    "bad_area",
    [0.0, -5.0, float("nan"), float("inf"), float("-inf"), True, False],
)
def test_review_text_invalid_stated_area_rejects_before_creating_output_dir(
    tmp_path: Path, bad_area: Any
) -> None:
    out_dir = tmp_path / "out"
    result = review_text(_SQUARE_TEXT, output_dir=out_dir, stated_area_sq_ft=bad_area)
    assert result["status"] == "error"
    codes = [err["code"] for err in result["errors"]]
    assert codes == ["invalid_input"]
    assert "artifact_error" not in codes
    assert result["artifacts"] == {}
    assert not out_dir.exists()


@pytest.mark.parametrize("bad_area", [0.0, -5.0, float("nan"), True, False])
def test_replay_review_invalid_stated_area_keeps_audit_payload(bad_area: Any) -> None:
    from mp_review.api import replay_review

    result = replay_review(
        _SQUARE_TEXT.encode("utf-8"),
        input_kind="text",
        stated_area_sq_ft=bad_area,
    )
    assert result["status"] == "error"
    assert [err["code"] for err in result["errors"]] == ["invalid_input"]
    assert "audit" in result
    assert result["audit"]["errors"] == result["errors"]


def test_json_inferred_role_tracts_rejects_fabricated_or_mismatched_flat_calls(
    tmp_path: Path,
) -> None:
    """Inferred-role tracts must STILL reject fabricated/mismatched top-level JSON calls."""
    main_calls = _square_calls(100.0)
    exc_calls = _square_calls(20.0, is_exception=True)
    fabricated_calls = _square_calls(50.0)
    inferred_tracts = [
        Tract(
            label="Tract 1",
            tract_type=TractType.MAIN,
            role_basis="inferred",
            calls=main_calls,
        ),
        Tract(
            label="Exception 1",
            tract_type=TractType.EXCEPTION,
            role_basis="inferred",
            calls=exc_calls,
        ),
    ]

    bad = LegalDescription(calls=fabricated_calls, tracts=inferred_tracts)
    bad_src = tmp_path / "inferred_bad.json"
    bad_src.write_text(json.dumps(bad.model_dump(mode="json")), encoding="utf-8")
    bad_result = review_file(bad_src)
    assert bad_result["status"] == "error"
    assert bad_result["errors"][0]["code"] == "invalid_input"
    assert "do not match tracts" in bad_result["errors"][0]["message"]

    # Consistent single-tract slice on inferred-role tracts stays accepted as needs_review.
    slice_ok = LegalDescription(calls=main_calls, tracts=inferred_tracts)
    slice_src = tmp_path / "inferred_slice.json"
    slice_src.write_text(json.dumps(slice_ok.model_dump(mode="json")), encoding="utf-8")
    slice_result = review_file(slice_src)
    assert slice_result["status"] == "needs_review"
    assert "description_roles_inferred" in [e["code"] for e in slice_result["errors"]]


# ---------------------------------------------------------------------------
# 1b. mp-review api.py: JSON TractType.EXCEPTION is_exception=True sync
# ---------------------------------------------------------------------------


def test_json_main_plus_exception_without_is_exception_flag_subtracts_area(
    tmp_path: Path,
) -> None:
    """JSON MAIN (100x100) + EXCEPTION (20x20, calls omitting is_exception) nets 9,600 sq ft."""
    legal = LegalDescription(
        calls=[],
        tracts=[
            Tract(
                label="Tract 1",
                tract_type=TractType.MAIN,
                role_basis="heading",
                calls=_square_calls(100.0),
            ),
            Tract(
                label="Exception 1",
                tract_type=TractType.EXCEPTION,
                role_basis="heading",
                calls=_square_calls(20.0, is_exception=False),
            ),
        ],
    )
    src = tmp_path / "main_and_exc.json"
    src.write_text(json.dumps(legal.model_dump(mode="json")), encoding="utf-8")

    out_dir = tmp_path / "out"
    result = review_file(src, output_dir=out_dir)
    assert result["status"] == "needs_review"
    assert not result["errors"]
    assert not (out_dir / "calls_verified.csv").exists()
    assert result["verification"]["area_sq_ft"] == pytest.approx(9600.0)
    assert not any("intersect" in w.lower() for w in result["verification"]["warnings"])
    assert all(c["is_exception"] is False for c in result["calls"][:4])
    assert all(c["is_exception"] is True for c in result["calls"][4:])
    assert all(EXCEPTION_TRACT_NOTE in (c["notes"] or "") for c in result["calls"][4:])


@pytest.mark.parametrize("variant", ["raw", "note_marked", "synced_and_marked"])
def test_json_accepts_consistent_exception_call_variants(tmp_path: Path, variant: str) -> None:
    """JSON with tracts=[MAIN, EXCEPTION] accepts raw, note-marked, or synced+marked flat calls."""
    main_calls = _square_calls(100.0)
    raw_exc = _square_calls(20.0, is_exception=False)
    if variant == "raw":
        flat_exc = raw_exc
    elif variant == "note_marked":
        flat_exc = mark_non_boundary(raw_exc, TractType.EXCEPTION)
    else:
        synced = [c.model_copy(update={"is_exception": True}) for c in raw_exc]
        flat_exc = mark_non_boundary(synced, TractType.EXCEPTION)

    legal = LegalDescription(
        calls=[*main_calls, *flat_exc],
        tracts=[
            Tract(
                label="Tract 1",
                tract_type=TractType.MAIN,
                role_basis="heading",
                calls=main_calls,
            ),
            Tract(
                label="Exception 1",
                tract_type=TractType.EXCEPTION,
                role_basis="heading",
                calls=raw_exc,
            ),
        ],
    )
    src = tmp_path / f"exc_{variant}.json"
    src.write_text(json.dumps(legal.model_dump(mode="json")), encoding="utf-8")

    result = review_file(src)
    assert result["status"] == "needs_review"
    assert not result["errors"]
    assert result["verification"]["area_sq_ft"] == pytest.approx(9600.0)
    assert all(c["is_exception"] is True for c in result["calls"][4:])


# ---------------------------------------------------------------------------
# 2. Multi-tract tracts[*].calls enrichment/tie-ins & cross-tract area isolation
# ---------------------------------------------------------------------------


def test_prepare_text_synchronizes_tract_calls_azimuths_and_preamble_tie_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """prepare_text must enrich azimuths across all tracts and apply preamble tie-in only on sole-tract deeds."""
    tie_call = DeedCall(
        course=1,
        direction_text="N 0° E",
        bearing_quadrant="N 0°00' E",
        bearing_azimuth_deg_from_north=None,  # deliberately un-enriched
        distance_ft=50.0,
        to="the point of beginning",
    )
    main_boundary = [
        c.model_copy(update={"course": c.course + 1, "bearing_azimuth_deg_from_north": None})
        for c in _square_calls(100.0)
    ]
    main_boundary[-1] = main_boundary[-1].model_copy(update={"to": "the point of beginning"})
    easement_calls = [
        c.model_copy(update={"bearing_azimuth_deg_from_north": None}) for c in _square_calls(20.0)
    ]

    deed = (
        "COMMENCING at a stone monument; "
        "THENCE N 0°00' E 50 feet to the POINT OF BEGINNING; "
        "THENCE N 0°00' E 100 feet to the point of beginning."
    )

    # 1. Multi-tract: enriches azimuths on every tract without blindly applying deed-wide POC.
    multi_tracts = [
        Tract(
            label="Tract 1",
            tract_type=TractType.MAIN,
            role_basis="heading",
            calls=[tie_call, *main_boundary],
        ),
        Tract(
            label="Easement 1",
            tract_type=TractType.EASEMENT,
            role_basis="heading",
            calls=easement_calls,
        ),
    ]
    monkeypatch.setattr(
        "mp_review.text.extract_calls",
        lambda *_a, **_kw: ([tie_call, *main_boundary], multi_tracts),
    )
    prepared_multi = prepare_text(deed)
    ld_multi = prepared_multi.legal_description
    assert len(ld_multi.tracts) == 2
    assert all(c.is_tie_in is False for c in ld_multi.tracts[0].calls)
    assert all(c.bearing_azimuth_deg_from_north is not None for c in ld_multi.tracts[0].calls)
    assert all(c.bearing_azimuth_deg_from_north is not None for c in ld_multi.tracts[1].calls)
    assert all(c.is_tie_in is False for c in ld_multi.tracts[1].calls)
    assert ld_multi.calls == ld_multi.tracts[0].calls

    # 2. Sole-tract preamble POC: enriches azimuths and marks preamble tie-in on tracts[0] and calls.
    sole_tract = [
        Tract(
            label="Tract 1",
            tract_type=TractType.MAIN,
            role_basis="single",
            calls=[tie_call, *main_boundary],
        )
    ]
    monkeypatch.setattr(
        "mp_review.text.extract_calls",
        lambda *_a, **_kw: ([tie_call, *main_boundary], sole_tract),
    )
    prepared_sole = prepare_text(deed)
    ld_sole = prepared_sole.legal_description
    assert len(ld_sole.tracts) == 1
    assert ld_sole.tracts[0].calls[0].is_tie_in is True
    assert ld_sole.calls[0].is_tie_in is True
    assert all(c.bearing_azimuth_deg_from_north is not None for c in ld_sole.tracts[0].calls)
    assert ld_sole.calls == ld_sole.tracts[0].calls


def test_pdf_processor_synchronizes_tract_calls_azimuths_and_per_tract_tie_ins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PDFProcessor must enrich/mark per tract without contaminating Tract 1 from Tract 2 POC."""
    # Case A: Tract 1 has NO POC (closes on call 4), Tract 2 has unresolved COMMENCING.
    # Running mark_tie_in_calls across flat_calls would falsely mark ALL 4 Tract 1 calls as tie-ins!
    deed_tract2_poc = (
        "TRACT 1: BEGINNING at an iron pin; "
        "THENCE N 0°00'00\" E, 100.00 feet; "
        "THENCE N 90°00'00\" E, 100.00 feet; "
        "THENCE S 0°00'00\" W, 100.00 feet; "
        "THENCE N 90°00'00\" W, 100.00 feet to the point of beginning.\n\n"
        "TRACT 2: COMMENCING at a stone monument; "
        "THENCE N 0°00'00\" E, 50.00 feet to a concrete marker; "
        "THENCE N 90°00'00\" E, 50.00 feet; "
        "THENCE S 0°00'00\" W, 50.00 feet; "
        "THENCE N 90°00'00\" W, 50.00 feet to the point of beginning."
    )
    pdf = tmp_path / "multi_poc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    processor = MonolithPDFProcessor(client=object(), cache=False)  # type: ignore[arg-type]
    monkeypatch.setattr(processor, "extract_legal_description", lambda _p: deed_tract2_poc)
    monkeypatch.setattr(processor, "normalize_legal_description", lambda t: t)

    legal_a = processor.process_deed_pdf(str(pdf))
    assert not isinstance(legal_a, tuple)
    assert len(legal_a.tracts) == 2
    assert all(not c.is_tie_in for c in legal_a.tracts[0].calls)
    assert all(not c.is_tie_in for c in legal_a.calls[:4])

    # Case B: Per-tract COMMENCING inside TRACT 1 marks Tract 1 tie-in in BOTH calls and tracts[0].
    deed_tract1_poc = (
        "TRACT 1: COMMENCING at a stone monument; "
        "THENCE N 0°00'00\" E, 50.00 feet to the point of beginning; "
        "THENCE N 0°00'00\" E, 100.00 feet; "
        "THENCE N 90°00'00\" E, 100.00 feet; "
        "THENCE S 0°00'00\" W, 100.00 feet; "
        "THENCE N 90°00'00\" W, 100.00 feet to the point of beginning.\n\n"
        "TRACT 2: BEGINNING at an iron pin; "
        "THENCE N 0°00'00\" E, 50.00 feet; "
        "THENCE N 90°00'00\" E, 50.00 feet; "
        "THENCE S 0°00'00\" W, 50.00 feet; "
        "THENCE N 90°00'00\" W, 50.00 feet to the point of beginning."
    )
    monkeypatch.setattr(processor, "extract_legal_description", lambda _p: deed_tract1_poc)
    legal_b = processor.process_deed_pdf(str(pdf))
    assert not isinstance(legal_b, tuple)
    assert len(legal_b.tracts) == 2
    assert legal_b.tracts[0].calls[0].is_tie_in is True
    assert all(not c.is_tie_in for c in legal_b.tracts[0].calls[1:])
    assert all(not c.is_tie_in for c in legal_b.tracts[1].calls)
    assert legal_b.calls[0].is_tie_in is True
    assert legal_b.calls == [*legal_b.tracts[0].calls, *legal_b.tracts[1].calls]
    assert all(c.bearing_azimuth_deg_from_north is not None for c in legal_b.calls)


def test_pdf_processor_enriches_unpopulated_tract_call_azimuths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stub CallExtractor.extract_calls with azimuth=None to prove PDFProcessor enriches tract calls."""
    from metesparser.call_extractor import CallExtractor
    from metesparser.models import DeedCall as MonolithDeedCall
    from metesparser.models import Tract as MonolithTract
    from metesparser.models import TractType as MonolithTractType

    def _raw_square(side: float) -> list[MonolithDeedCall]:
        return [
            MonolithDeedCall(
                course=1,
                direction_text="N 0° E",
                bearing_quadrant="N 0°00' E",
                bearing_azimuth_deg_from_north=None,
                distance_ft=side,
            ),
            MonolithDeedCall(
                course=2,
                direction_text="N 90° E",
                bearing_quadrant="N 90°00' E",
                bearing_azimuth_deg_from_north=None,
                distance_ft=side,
            ),
            MonolithDeedCall(
                course=3,
                direction_text="S 0° E",
                bearing_quadrant="S 0°00' E",
                bearing_azimuth_deg_from_north=None,
                distance_ft=side,
            ),
            MonolithDeedCall(
                course=4,
                direction_text="N 90° W",
                bearing_quadrant="N 90°00' W",
                bearing_azimuth_deg_from_north=None,
                distance_ft=side,
            ),
        ]

    def fake_extract_calls(
        _text: str,
        *,
        distance_unit: str = "feet",
        audit_context: Any = None,
        tracts: list[MonolithTract] | None = None,
        **_kw: Any,
    ) -> list[MonolithDeedCall]:
        main_calls = _raw_square(100.0)
        easement_calls = _raw_square(20.0)
        if tracts is not None:
            tracts.extend(
                [
                    MonolithTract(
                        label="Tract 1",
                        tract_type=MonolithTractType.MAIN,
                        role_basis="heading",
                        calls=main_calls,
                    ),
                    MonolithTract(
                        label="Easement 1",
                        tract_type=MonolithTractType.EASEMENT,
                        role_basis="heading",
                        calls=easement_calls,
                    ),
                ]
            )
        return main_calls

    monkeypatch.setattr(CallExtractor, "extract_calls", staticmethod(fake_extract_calls))
    pdf = tmp_path / "unenriched.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    processor = MonolithPDFProcessor(client=object(), cache=False)  # type: ignore[arg-type]
    monkeypatch.setattr(processor, "extract_legal_description", lambda _p: _SQUARE_TEXT)
    monkeypatch.setattr(processor, "normalize_legal_description", lambda t: t)

    legal = processor.process_deed_pdf(str(pdf))
    assert not isinstance(legal, tuple)
    assert len(legal.tracts) == 2
    expected_az = [0.0, 90.0, 180.0, 270.0]
    assert [c.bearing_azimuth_deg_from_north for c in legal.tracts[0].calls] == pytest.approx(
        expected_az
    )
    assert [c.bearing_azimuth_deg_from_north for c in legal.tracts[1].calls] == pytest.approx(
        expected_az
    )
    assert [c.bearing_azimuth_deg_from_north for c in legal.calls] == pytest.approx(expected_az)
    assert legal.calls == legal.tracts[0].calls


def test_pdf_processor_multi_tract_first_tract_zero_area_does_not_poison_second_tract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tract 1 containing 0 acres must NOT stamp invalid-area notes onto Tract 2 (10,000 sq ft)."""
    deed = (
        "TRACT 1: BEGINNING at an iron pin; "
        "THENCE N 0°00'00\" E, 100.00 feet; "
        "THENCE N 90°00'00\" E, 100.00 feet; "
        "THENCE S 0°00'00\" W, 100.00 feet; "
        "THENCE N 90°00'00\" W, 100.00 feet to the point of beginning, "
        "containing 0 acres.\n\n"
        "TRACT 2: BEGINNING at a concrete monument; "
        "THENCE N 0°00'00\" E, 100.00 feet; "
        "THENCE N 90°00'00\" E, 100.00 feet; "
        "THENCE S 0°00'00\" W, 100.00 feet; "
        "THENCE N 90°00'00\" W, 100.00 feet to the point of beginning, "
        "containing 10,000 square feet."
    )
    pdf = tmp_path / "tract1_zero.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    processor = MonolithPDFProcessor(client=object(), cache=False)  # type: ignore[arg-type]
    monkeypatch.setattr(processor, "extract_legal_description", lambda _p: deed)
    monkeypatch.setattr(processor, "normalize_legal_description", lambda t: t)

    with structlog.testing.capture_logs() as cap_logs:
        legal, audit_ctx = processor.process_deed_pdf(str(pdf), audit=True)

    assert len(legal.tracts) == 2
    assert legal.tracts[0].stated_area_sq_ft is None
    assert any(INVALID_STATED_AREA_NOTE_PREFIX in (c.notes or "") for c in legal.tracts[0].calls)
    assert legal.tracts[1].stated_area_sq_ft == pytest.approx(10000.0)
    assert not any(
        INVALID_STATED_AREA_NOTE_PREFIX in (c.notes or "") for c in legal.tracts[1].calls
    )

    tract_results = ClosureChecker.verify_closure([], tracts=legal.tracts)
    assert isinstance(tract_results, list)
    assert not tract_results[0].is_fully_verified()
    assert tract_results[1].is_fully_verified()

    assert any(
        entry.get("log_level") == "warning" and "stated area" in str(entry.get("event", "")).lower()
        for entry in cap_logs
    )
    assert audit_ctx.extraction_record is not None
    assert audit_ctx.extraction_record.confidence_signals.get("valid_stated_area") is False


def test_pdf_processor_multi_tract_second_tract_zero_area_warns_and_sets_audit_signal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tract 2 containing 0 acres must warn and flag valid_stated_area=False symmetrically."""
    deed = (
        "TRACT 1: BEGINNING at an iron pin; "
        "THENCE N 0°00'00\" E, 100.00 feet; "
        "THENCE N 90°00'00\" E, 100.00 feet; "
        "THENCE S 0°00'00\" W, 100.00 feet; "
        "THENCE N 90°00'00\" W, 100.00 feet to the point of beginning, "
        "containing 10,000 square feet.\n\n"
        "TRACT 2: BEGINNING at a concrete monument; "
        "THENCE N 0°00'00\" E, 100.00 feet; "
        "THENCE N 90°00'00\" E, 100.00 feet; "
        "THENCE S 0°00'00\" W, 100.00 feet; "
        "THENCE N 90°00'00\" W, 100.00 feet to the point of beginning, "
        "containing 0 acres."
    )
    pdf = tmp_path / "tract2_zero.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    processor = MonolithPDFProcessor(client=object(), cache=False)  # type: ignore[arg-type]
    monkeypatch.setattr(processor, "extract_legal_description", lambda _p: deed)
    monkeypatch.setattr(processor, "normalize_legal_description", lambda t: t)

    with structlog.testing.capture_logs() as cap_logs:
        legal, audit_ctx = processor.process_deed_pdf(str(pdf), audit=True)

    assert len(legal.tracts) == 2
    assert legal.tracts[0].stated_area_sq_ft == pytest.approx(10000.0)
    assert not any(
        INVALID_STATED_AREA_NOTE_PREFIX in (c.notes or "") for c in legal.tracts[0].calls
    )
    assert legal.tracts[1].stated_area_sq_ft is None
    assert any(INVALID_STATED_AREA_NOTE_PREFIX in (c.notes or "") for c in legal.tracts[1].calls)

    assert any(
        entry.get("log_level") == "warning" and "stated area" in str(entry.get("event", "")).lower()
        for entry in cap_logs
    )
    assert audit_ctx.extraction_record is not None
    assert audit_ctx.extraction_record.confidence_signals.get("valid_stated_area") is False


def test_prepare_text_zero_area_on_easement_or_main_does_not_contaminate_other_tract() -> None:
    """Zero area on one tract must be reported without contaminating the other tract's calls."""
    main_valid_easement_zero = (
        "TRACT 1: BEGINNING at an iron pin; "
        "THENCE N 0°00'00\" E, 100.00 feet; "
        "THENCE N 90°00'00\" E, 100.00 feet; "
        "THENCE S 0°00'00\" W, 100.00 feet; "
        "THENCE N 90°00'00\" W, 100.00 feet to the point of beginning, "
        "containing 10,000 square feet.\n\n"
        "TRACT 2: A non-exclusive easement for ingress and egress described as follows: "
        "BEGINNING at a stake; "
        "THENCE N 0°00'00\" E, 20.00 feet; "
        "THENCE N 90°00'00\" E, 20.00 feet; "
        "THENCE S 0°00'00\" W, 20.00 feet; "
        "THENCE N 90°00'00\" W, 20.00 feet to the point of beginning, "
        "containing 0 acres."
    )
    prep1 = prepare_text(main_valid_easement_zero)
    assert prep1.invalid_stated_area is not None
    assert "0.0 sq ft (acres)" in prep1.invalid_stated_area
    assert len(prep1.legal_description.tracts) == 2
    assert prep1.legal_description.stated_area_sq_ft == pytest.approx(10000.0)
    assert not any(
        INVALID_STATED_AREA_NOTE_PREFIX in (c.notes or "")
        for c in prep1.legal_description.tracts[0].calls
    )
    assert any(
        INVALID_STATED_AREA_NOTE_PREFIX in (c.notes or "")
        for c in prep1.legal_description.tracts[1].calls
    )

    main_zero_easement_valid = (
        "TRACT 1: BEGINNING at an iron pin; "
        "THENCE N 0°00'00\" E, 100.00 feet; "
        "THENCE N 90°00'00\" E, 100.00 feet; "
        "THENCE S 0°00'00\" W, 100.00 feet; "
        "THENCE N 90°00'00\" W, 100.00 feet to the point of beginning, "
        "containing 0 acres.\n\n"
        "TRACT 2: A non-exclusive easement for ingress and egress described as follows: "
        "BEGINNING at a stake; "
        "THENCE N 0°00'00\" E, 20.00 feet; "
        "THENCE N 90°00'00\" E, 20.00 feet; "
        "THENCE S 0°00'00\" W, 20.00 feet; "
        "THENCE N 90°00'00\" W, 20.00 feet to the point of beginning, "
        "containing 400 square feet."
    )
    prep2 = prepare_text(main_zero_easement_valid)
    assert prep2.invalid_stated_area is not None
    assert prep2.legal_description.stated_area_sq_ft is None
    assert any(
        INVALID_STATED_AREA_NOTE_PREFIX in (c.notes or "")
        for c in prep2.legal_description.tracts[0].calls
    )
    assert not any(
        INVALID_STATED_AREA_NOTE_PREFIX in (c.notes or "")
        for c in prep2.legal_description.tracts[1].calls
    )


def test_prepare_text_never_leaks_easement_or_exception_area_onto_legal_description() -> None:
    """When MAIN omits stated area, an easement or exception stated area must NOT leak onto LegalDescription."""
    main_no_area_easement_400 = (
        "TRACT 1: BEGINNING at an iron pin; "
        "THENCE N 0°00'00\" E, 100.00 feet; "
        "THENCE N 90°00'00\" E, 100.00 feet; "
        "THENCE S 0°00'00\" W, 100.00 feet; "
        "THENCE N 90°00'00\" W, 100.00 feet to the point of beginning.\n\n"
        "TRACT 2: A non-exclusive easement for ingress and egress described as follows: "
        "BEGINNING at a stake; "
        "THENCE N 0°00'00\" E, 20.00 feet; "
        "THENCE N 90°00'00\" E, 20.00 feet; "
        "THENCE S 0°00'00\" W, 20.00 feet; "
        "THENCE N 90°00'00\" W, 20.00 feet to the point of beginning, "
        "containing 400 square feet, more or less."
    )
    prep_ease = prepare_text(main_no_area_easement_400)
    assert len(prep_ease.legal_description.tracts) == 2
    assert prep_ease.legal_description.tracts[0].stated_area_sq_ft is None
    assert prep_ease.legal_description.tracts[1].stated_area_sq_ft == pytest.approx(400.0)
    assert prep_ease.legal_description.stated_area_sq_ft is None
    assert prep_ease.legal_description.stated_area_approximate is False

    main_no_area_exception_400 = (
        "TRACT 1: BEGINNING at an iron pin; "
        "THENCE N 0°00'00\" E, 100.00 feet; "
        "THENCE N 90°00'00\" E, 100.00 feet; "
        "THENCE S 0°00'00\" W, 100.00 feet; "
        "THENCE N 90°00'00\" W, 100.00 feet to the point of beginning.\n\n"
        "TRACT 2: EXCEPTING THEREFROM the following described parcel: "
        "BEGINNING at a stake; "
        "THENCE N 0°00'00\" E, 20.00 feet; "
        "THENCE N 90°00'00\" E, 20.00 feet; "
        "THENCE S 0°00'00\" W, 20.00 feet; "
        "THENCE N 90°00'00\" W, 20.00 feet to the point of beginning, "
        "containing 400 square feet, more or less."
    )
    prep_exc = prepare_text(main_no_area_exception_400)
    assert len(prep_exc.legal_description.tracts) == 2
    assert prep_exc.legal_description.tracts[0].stated_area_sq_ft is None
    assert prep_exc.legal_description.tracts[1].stated_area_sq_ft == pytest.approx(400.0)
    assert prep_exc.legal_description.stated_area_sq_ft is None
    assert prep_exc.legal_description.stated_area_approximate is False

    easement_only = (
        "A non-exclusive easement for ingress and egress described as follows: "
        "BEGINNING at a stake; "
        "THENCE N 0°00'00\" E, 20.00 feet; "
        "THENCE N 90°00'00\" E, 20.00 feet; "
        "THENCE S 0°00'00\" W, 20.00 feet; "
        "THENCE N 90°00'00\" W, 20.00 feet to the point of beginning, "
        "containing 400 square feet."
    )
    prep_only = prepare_text(easement_only)
    assert prep_only.legal_description.stated_area_sq_ft is None
    assert prep_only.legal_description.stated_area_approximate is False


def test_prepare_text_surfaces_invalid_stated_area_when_tracts_have_all_empty_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deeds whose tracts have all calls skipped/empty must still surface invalid_stated_area."""
    empty_tracts = [
        Tract(label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=[]),
    ]
    monkeypatch.setattr("mp_review.text.extract_calls", lambda *_a, **_kw: ([], empty_tracts))
    prepared = prepare_text("TRACT 1: BEGINNING at a pin, containing 0 acres.")
    assert prepared.invalid_stated_area is not None
    assert "0.0 sq ft (acres)" in prepared.invalid_stated_area
    assert prepared.legal_description.stated_area_sq_ft is None
    assert prepared.legal_description.stated_area_approximate is False


def test_pdf_processor_never_leaks_easement_or_exception_area_onto_legal_description(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Monolith PDFProcessor must apply tract-scoped stated_area_sq_ft rules when tracts exist."""
    pdf = tmp_path / "area_leak.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    processor = MonolithPDFProcessor(client=object(), cache=False)  # type: ignore[arg-type]
    monkeypatch.setattr(processor, "normalize_legal_description", lambda t: t)

    # 1. MAIN (no area) + EASEMENT (400 sq ft, more or less) -> None / False
    deed_main_none_ease_400 = (
        "TRACT 1: BEGINNING at an iron pin; "
        "THENCE N 0°00'00\" E, 100.00 feet; "
        "THENCE N 90°00'00\" E, 100.00 feet; "
        "THENCE S 0°00'00\" W, 100.00 feet; "
        "THENCE N 90°00'00\" W, 100.00 feet to the point of beginning.\n\n"
        "TRACT 2: A non-exclusive easement for ingress and egress described as follows: "
        "BEGINNING at a stake; "
        "THENCE N 0°00'00\" E, 20.00 feet; "
        "THENCE N 90°00'00\" E, 20.00 feet; "
        "THENCE S 0°00'00\" W, 20.00 feet; "
        "THENCE N 90°00'00\" W, 20.00 feet to the point of beginning, "
        "containing 400 square feet, more or less."
    )
    monkeypatch.setattr(processor, "extract_legal_description", lambda _p: deed_main_none_ease_400)
    legal1 = processor.process_deed_pdf(str(pdf))
    assert not isinstance(legal1, tuple)
    assert len(legal1.tracts) == 2
    assert legal1.stated_area_sq_ft is None
    assert legal1.stated_area_approximate is False

    # 2. MAIN (10,000 sq ft) + EASEMENT (0 acres) -> 10,000.0 / False
    deed_main_10k_ease_zero = (
        "TRACT 1: BEGINNING at an iron pin; "
        "THENCE N 0°00'00\" E, 100.00 feet; "
        "THENCE N 90°00'00\" E, 100.00 feet; "
        "THENCE S 0°00'00\" W, 100.00 feet; "
        "THENCE N 90°00'00\" W, 100.00 feet to the point of beginning, "
        "containing 10,000 square feet.\n\n"
        "TRACT 2: A non-exclusive easement for ingress and egress described as follows: "
        "BEGINNING at a stake; "
        "THENCE N 0°00'00\" E, 20.00 feet; "
        "THENCE N 90°00'00\" E, 20.00 feet; "
        "THENCE S 0°00'00\" W, 20.00 feet; "
        "THENCE N 90°00'00\" W, 20.00 feet to the point of beginning, "
        "containing 0 acres."
    )
    monkeypatch.setattr(processor, "extract_legal_description", lambda _p: deed_main_10k_ease_zero)
    legal2 = processor.process_deed_pdf(str(pdf))
    assert not isinstance(legal2, tuple)
    assert legal2.stated_area_sq_ft == pytest.approx(10000.0)
    assert legal2.stated_area_approximate is False

    # 3. EASEMENT-only (400 sq ft) -> None / False
    deed_ease_only = (
        "A non-exclusive easement for ingress and egress described as follows: "
        "BEGINNING at a stake; "
        "THENCE N 0°00'00\" E, 20.00 feet; "
        "THENCE N 90°00'00\" E, 20.00 feet; "
        "THENCE S 0°00'00\" W, 20.00 feet; "
        "THENCE N 90°00'00\" W, 20.00 feet to the point of beginning, "
        "containing 400 square feet."
    )
    monkeypatch.setattr(processor, "extract_legal_description", lambda _p: deed_ease_only)
    legal3 = processor.process_deed_pdf(str(pdf))
    assert not isinstance(legal3, tuple)
    assert legal3.stated_area_sq_ft is None
    assert legal3.stated_area_approximate is False

    # 4. MAIN (no area) + EXCEPTION (400 sq ft) -> None / False
    deed_main_none_exc_400 = (
        "TRACT 1: BEGINNING at an iron pin; "
        "THENCE N 0°00'00\" E, 100.00 feet; "
        "THENCE N 90°00'00\" E, 100.00 feet; "
        "THENCE S 0°00'00\" W, 100.00 feet; "
        "THENCE N 90°00'00\" W, 100.00 feet to the point of beginning.\n\n"
        "TRACT 2: EXCEPTING THEREFROM the following described parcel: "
        "BEGINNING at a stake; "
        "THENCE N 0°00'00\" E, 20.00 feet; "
        "THENCE N 90°00'00\" E, 20.00 feet; "
        "THENCE S 0°00'00\" W, 20.00 feet; "
        "THENCE N 90°00'00\" W, 20.00 feet to the point of beginning, "
        "containing 400 square feet."
    )
    monkeypatch.setattr(processor, "extract_legal_description", lambda _p: deed_main_none_exc_400)
    legal4 = processor.process_deed_pdf(str(pdf))
    assert not isinstance(legal4, tuple)
    assert len(legal4.tracts) == 2
    assert legal4.tracts[0].stated_area_sq_ft is None
    assert legal4.tracts[1].stated_area_sq_ft == pytest.approx(400.0)
    assert legal4.stated_area_sq_ft is None
    assert legal4.stated_area_approximate is False


# ---------------------------------------------------------------------------
# 3. Cache-key collision across custom DI providers + public model_name
# ---------------------------------------------------------------------------


def _make_custom_client_a():
    class Client:
        model = "same-model"

        def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
            return "from-a"

        def generate_text_with_pdf(
            self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
        ) -> str:
            return "pdf-a"

    return Client()


def _make_custom_client_b():
    class Client:
        model = "same-model"

        def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
            return "from-b"

        def generate_text_with_pdf(
            self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
        ) -> str:
            return "pdf-b"

    return Client()


@pytest.mark.parametrize("cache_cls", [PackageCachedClient, MonolithCachedClient])
def test_cached_client_separates_custom_di_clients_with_same_class_name(
    cache_cls: Any, tmp_path: Path
) -> None:
    cache_dir = tmp_path / "shared_cache"
    cached_a = cache_cls(_make_custom_client_a(), cache_dir=cache_dir)
    cached_b = cache_cls(_make_custom_client_b(), cache_dir=cache_dir)

    assert cached_a._cache_key("prompt", None) != cached_b._cache_key("prompt", None)
    assert cached_a.generate_text("prompt") == "from-a"
    assert cached_b.generate_text("prompt") == "from-b"


def test_cached_client_builtin_aliases_still_share_keys_across_impls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    openai_mod = ModuleType("openai")
    openai_mod.OpenAI = lambda api_key: SimpleNamespace(responses=SimpleNamespace())  # type: ignore[attr-defined]
    google_mod = ModuleType("google")
    genai_mod = ModuleType("google.genai")
    errors_mod = ModuleType("google.genai.errors")
    types_mod = ModuleType("google.genai.types")
    genai_mod.Client = lambda api_key: SimpleNamespace(models=SimpleNamespace())  # type: ignore[attr-defined]
    genai_mod.errors = errors_mod  # type: ignore[attr-defined]
    genai_mod.types = types_mod  # type: ignore[attr-defined]
    google_mod.genai = genai_mod  # type: ignore[attr-defined]
    google_mod.__path__ = []  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", openai_mod)
    monkeypatch.setitem(sys.modules, "google", google_mod)
    monkeypatch.setitem(sys.modules, "google.genai", genai_mod)
    monkeypatch.setitem(sys.modules, "google.genai.errors", errors_mod)
    monkeypatch.setitem(sys.modules, "google.genai.types", types_mod)

    assert PackageCachedClient(PackageOpenAIClient(api_key="k"), tmp_path / "c")._cache_key(
        "p", None
    ) == MonolithCachedClient(MonolithOpenAIClient(api_key="k"), tmp_path / "c")._cache_key(
        "p", None
    )
    assert PackageCachedClient(PackageGeminiClient(api_key="k"), tmp_path / "c")._cache_key(
        "p", None
    ) == MonolithCachedClient(MonolithGeminiClient(api_key="k"), tmp_path / "c")._cache_key(
        "p", None
    )


@pytest.mark.parametrize(
    ("cache_cls", "proc_cls"),
    [
        (PackageCachedClient, PackagePDFProcessor),
        (MonolithCachedClient, MonolithPDFProcessor),
    ],
)
def test_public_model_name_property_on_cached_client_and_pdf_processor(
    cache_cls: Any, proc_cls: Any, tmp_path: Path
) -> None:
    class ModelClient:
        model = "custom-model-v1"

        def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
            return ""

        def generate_text_with_pdf(
            self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
        ) -> str:
            return ""

    class NamelessClient:
        def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
            return ""

        def generate_text_with_pdf(
            self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
        ) -> str:
            return ""

    cached = cache_cls(ModelClient(), cache_dir=tmp_path / "c1")
    assert cached.model_name == "custom-model-v1"
    cached_nameless = cache_cls(NamelessClient(), cache_dir=tmp_path / "c2")
    assert cached_nameless.model_name is None

    proc_uncached = proc_cls(client=ModelClient(), cache=False)
    assert proc_uncached.model_name == "custom-model-v1"
    proc_cached = proc_cls(client=ModelClient(), cache=True, cache_dir=tmp_path / "c3")
    assert proc_cached.model_name == "custom-model-v1"
    proc_nameless = proc_cls(client=NamelessClient(), cache=False)
    assert proc_nameless.model_name is None


@pytest.mark.parametrize(
    ("outer_cache", "inner_cache", "proc_cls"),
    [
        (PackageCachedClient, PackageCachedClient, PackagePDFProcessor),
        (PackageCachedClient, MonolithCachedClient, PackagePDFProcessor),
        (MonolithCachedClient, PackageCachedClient, MonolithPDFProcessor),
        (MonolithCachedClient, MonolithCachedClient, MonolithPDFProcessor),
    ],
)
def test_nested_and_cross_module_cache_unwrapping_model_name_and_stage_provenance(
    outer_cache: Any, inner_cache: Any, proc_cls: Any, tmp_path: Path
) -> None:
    """Nested/cross-module caches must unwrap cleanly, preserve distinct keys, and populate stage model."""

    class ModelNameOnlyClient:
        def __init__(self, name: str) -> None:
            self.model_name = name

        def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
            return f"resp:{self.model_name}"

        def generate_text_with_pdf(
            self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
        ) -> str:
            return f"pdf:{self.model_name}"

    class ModelAttrClient:
        def __init__(self, model: str) -> None:
            self.model = model

        def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
            return f"resp:{self.model}"

        def generate_text_with_pdf(
            self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
        ) -> str:
            return f"pdf:{self.model}"

    # 1. Nested caches on ModelAttrClient preserve distinct keys for different models
    c_a = outer_cache(
        inner_cache(ModelAttrClient("model-alpha"), cache_dir=tmp_path / "in_a"),
        cache_dir=tmp_path / "out_a",
    )
    c_b = outer_cache(
        inner_cache(ModelAttrClient("model-beta"), cache_dir=tmp_path / "in_b"),
        cache_dir=tmp_path / "out_b",
    )
    assert c_a.model_name == "model-alpha"
    assert c_b.model_name == "model-beta"
    assert c_a._cache_key("same-prompt", None) != c_b._cache_key("same-prompt", None)
    assert c_a._cache_key("same-prompt", None) == outer_cache(
        ModelAttrClient("model-alpha"), cache_dir=tmp_path / "single_a"
    )._cache_key("same-prompt", None)

    # 2. CachedLLMClient.model_name reads inner client's model_name (not only .model)
    name_only = ModelNameOnlyClient("custom-model-name-only")
    nested_name_only = outer_cache(
        inner_cache(name_only, cache_dir=tmp_path / "in_n"),
        cache_dir=tmp_path / "out_n",
    )
    assert nested_name_only.model_name == "custom-model-name-only"

    # 3. PDFProcessor._unwrap_client recursively unwraps cross-module nested caches
    proc = proc_cls(client=nested_name_only, cache=True, cache_dir=tmp_path / "proc_c")
    assert proc._unwrap_client(proc.client) is name_only
    assert proc.model_name == "custom-model-name-only"

    # 4. _record_llm_stage uses _get_model_name() (not raw getattr(inner, "model"))
    proc._audit_stage_records = []
    proc._record_llm_stage("normalize_text", "prompt", "response")
    assert len(proc._audit_stage_records) == 1
    assert proc._audit_stage_records[0].model == "custom-model-name-only"

    # 5. Cycle guard and MagicMock safety in _unwrap_client and model_name
    from unittest.mock import MagicMock

    cyclic = outer_cache(ModelAttrClient("cycle-m"), cache_dir=tmp_path / "cyc")
    cyclic._client = cyclic
    assert cyclic.model_name is None
    assert proc_cls._unwrap_client(cyclic) is cyclic
    mock_client = MagicMock()
    assert proc_cls._unwrap_client(mock_client) is mock_client


# ---------------------------------------------------------------------------
# 4. UTF-8 prompt reads & normalize_legal_description _audit_stage_records reset
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("proc_cls", [PackagePDFProcessor, MonolithPDFProcessor])
def test_load_prompt_uses_explicit_utf8_encoding(
    proc_cls: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "utf8_sample.yaml").write_text(
        'system_prompt: "Check 45°30′ — utf8"\nuser_prompt_template: "Prompt"\n',
        encoding="utf-8",
    )

    seen_encodings: list[str | None] = []
    real_read_text = Path.read_text

    def spy_read_text(self: Path, encoding: str | None = None, errors: str | None = None) -> str:
        if self.name == "utf8_sample.yaml":
            seen_encodings.append(encoding)
        return real_read_text(self, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, "read_text", spy_read_text)

    processor = proc_cls(client=object(), cache=False)
    processor.prompts_dir = prompt_dir
    cfg = processor._load_prompt("utf8_sample")
    assert "45°30′" in cfg["system_prompt"]
    assert seen_encodings == ["utf-8"]


def test_package_normalize_legal_description_resets_audit_stages_on_repeated_standalone_calls() -> (
    None
):
    class RecordingClient:
        model = "test-model"

        def __init__(self) -> None:
            self.n = 0

        def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
            self.n += 1
            return f"NORMALIZED-{self.n}"

        def generate_text_with_pdf(
            self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
        ) -> str:
            return "OCR"

    processor = PackagePDFProcessor(client=RecordingClient(), cache=False)
    assert processor.normalize_legal_description("first", audit=True) == "NORMALIZED-1"
    assert processor._audit_stage_records is not None
    assert len(processor._audit_stage_records) == 1

    assert processor.normalize_legal_description("second", audit=True) == "NORMALIZED-2"
    assert processor._audit_stage_records is not None
    assert len(processor._audit_stage_records) == 1
    assert processor._audit_stage_records[0].response == "NORMALIZED-2"


# ---------------------------------------------------------------------------
# 5. mp-review settings.py: _find_project_root symlink anchoring
# ---------------------------------------------------------------------------


def test_read_settings_symlink_in_claude_dir_anchors_to_logical_project_root(
    tmp_path: Path,
) -> None:
    external = tmp_path / "external_shared"
    external.mkdir()
    shared = external / "shared.local.md"
    shared.write_text('---\noutput_dir: "reviews"\n---\n', encoding="utf-8")

    project = tmp_path / "project"
    claude_dir = project / ".claude"
    claude_dir.mkdir(parents=True)
    linked_settings = claude_dir / "metesparser.local.md"
    linked_settings.symlink_to(shared)

    parsed = read_settings(linked_settings)
    assert parsed["output_dir"] == (project / "reviews").resolve()
    assert not parsed["output_dir"].is_relative_to(external.resolve())

    shared.write_text('---\noutput_dir: "../escape"\n---\n', encoding="utf-8")
    with pytest.raises(SettingsError, match="within the project directory"):
        read_settings(linked_settings)


def test_read_settings_find_project_root_all_symlink_and_dotdot_cases(tmp_path: Path) -> None:
    """_find_project_root must resolve settings_path.parent safely across all 4 symlink cases."""
    # Case 1: Real proj/.claude/metesparser.local.md -> root /real/proj
    proj1 = tmp_path / "proj1"
    (proj1 / ".claude").mkdir(parents=True)
    real_settings = proj1 / ".claude" / "metesparser.local.md"
    real_settings.write_text('---\noutput_dir: "reviews"\n---\n', encoding="utf-8")
    assert read_settings(real_settings)["output_dir"] == (proj1 / "reviews").resolve()

    # Case 2: Symlinked file proj2/.claude/metesparser.local.md -> /external/shared.local.md -> root /real/proj2
    external2 = tmp_path / "external2"
    external2.mkdir()
    shared2 = external2 / "shared.local.md"
    shared2.write_text('---\noutput_dir: "reviews"\n---\n', encoding="utf-8")
    proj2 = tmp_path / "proj2"
    (proj2 / ".claude").mkdir(parents=True)
    linked_file = proj2 / ".claude" / "metesparser.local.md"
    linked_file.symlink_to(shared2)
    assert read_settings(linked_file)["output_dir"] == (proj2 / "reviews").resolve()
    assert not read_settings(linked_file)["output_dir"].is_relative_to(external2.resolve())

    # Case 3: Symlinked subdir + .. : proj3/sub/../.claude/settings.md where proj3/sub -> /outside3/sub
    # OS resolves this to /outside3/.claude/settings.md, so root MUST be /outside3 (NOT proj3!).
    outside3 = tmp_path / "outside3"
    (outside3 / "sub").mkdir(parents=True)
    (outside3 / ".claude").mkdir(parents=True)
    outside3_settings = outside3 / ".claude" / "settings.md"
    outside3_settings.write_text('---\noutput_dir: "reviews"\n---\n', encoding="utf-8")
    proj3 = tmp_path / "proj3"
    proj3.mkdir()
    (proj3 / "sub").symlink_to(outside3 / "sub")
    dotdot_settings = proj3 / "sub" / ".." / ".claude" / "settings.md"
    parsed3 = read_settings(dotdot_settings)
    assert parsed3["output_dir"] == (outside3 / "reviews").resolve()
    assert not parsed3["output_dir"].is_relative_to(proj3.resolve())

    # Case 4: Symlinked .claude dir: proj4/.claude -> /outside4 -> root /real/outside4 (NOT proj4!)
    outside4 = tmp_path / "outside4"
    outside4.mkdir()
    (outside4 / "metesparser.local.md").write_text(
        '---\noutput_dir: "reviews"\n---\n', encoding="utf-8"
    )
    proj4 = tmp_path / "proj4"
    proj4.mkdir()
    (proj4 / ".claude").symlink_to(outside4)
    linked_dir_settings = proj4 / ".claude" / "metesparser.local.md"
    parsed4 = read_settings(linked_dir_settings)
    assert parsed4["output_dir"] == (outside4 / "reviews").resolve()
    assert not parsed4["output_dir"].is_relative_to(proj4.resolve())


# ---------------------------------------------------------------------------
# 6. Cycle 3 Track 3: C6 (part 2), C8 (part 2), M6, M5, M11+A4
# ---------------------------------------------------------------------------


def test_c6_stated_area_override_syncs_single_boundary_tract_and_clears_approximate(
    tmp_path: Path,
) -> None:
    """Explicit stated_area_sq_ft override updates boundary tract and clears approximate flag."""
    legal = LegalDescription(
        calls=[],
        stated_area_sq_ft=10200.0,
        stated_area_approximate=True,
        tracts=[
            Tract(
                label="Tract 1",
                tract_type=TractType.MAIN,
                role_basis="heading",
                stated_area_sq_ft=10200.0,
                calls=_square_calls(100.0),
            ),
            Tract(
                label="Easement 1",
                tract_type=TractType.EASEMENT,
                role_basis="heading",
                stated_area_sq_ft=400.0,
                calls=_square_calls(20.0),
            ),
        ],
    )
    raw = json.dumps(legal.model_dump(mode="json")).encode("utf-8")
    src = tmp_path / "tract_area_override.json"
    src.write_bytes(raw)

    replayed = replay_review(raw, input_kind="json", stated_area_sq_ft=10000.0)
    assert replayed["status"] == "checks_passed", replayed["errors"]
    assert replayed["errors"] == []
    replay_ld = replayed["audit"]["legal_description"]
    assert replay_ld["stated_area_sq_ft"] == pytest.approx(10000.0)
    assert replay_ld["stated_area_approximate"] is False
    assert replay_ld["tracts"][0]["stated_area_sq_ft"] == pytest.approx(10000.0)
    assert replay_ld["tracts"][1]["stated_area_sq_ft"] == pytest.approx(400.0)

    out_dir = tmp_path / "out"
    disk = review_file(src, output_dir=out_dir, stated_area_sq_ft=10000.0)
    assert disk["status"] == "checks_passed", disk["errors"]
    assert disk["errors"] == []
    assert (out_dir / "calls_verified.csv").exists()
    disk_audit = json.loads((out_dir / "audit.json").read_text(encoding="utf-8"))
    disk_ld = disk_audit["legal_description"]
    assert disk_ld["stated_area_sq_ft"] == pytest.approx(10000.0)
    assert disk_ld["stated_area_approximate"] is False
    assert disk_ld["tracts"][0]["stated_area_sq_ft"] == pytest.approx(10000.0)
    assert disk_ld["tracts"][1]["stated_area_sq_ft"] == pytest.approx(400.0)


def test_c6_stated_area_tolerance_parity_between_replay_and_disk_export(
    tmp_path: Path,
) -> None:
    """Top-level 10000.0 vs boundary tract 10000.005 matches via shared stated_areas_match."""
    legal = LegalDescription(
        calls=[],
        stated_area_sq_ft=10000.0,
        tracts=[
            Tract(
                label="Tract 1",
                tract_type=TractType.MAIN,
                role_basis="heading",
                stated_area_sq_ft=10000.005,
                calls=_square_calls(100.0),
            ),
        ],
    )
    raw = json.dumps(legal.model_dump(mode="json")).encode("utf-8")
    src = tmp_path / "tol_parity.json"
    src.write_bytes(raw)

    replayed = replay_review(raw, input_kind="json")
    assert replayed["status"] == "checks_passed", replayed["errors"]

    out_dir = tmp_path / "out"
    disk = review_file(src, output_dir=out_dir)
    assert disk["status"] == "checks_passed", disk["errors"]
    assert (out_dir / "calls_verified.csv").exists()


@pytest.mark.parametrize(
    ("deed_level_area_phrase", "main_area_phrase", "expected_area", "expected_approx"),
    [
        # Within STATED_AREA_REL_TOL (1e-6 * 10000.005 ≈ 0.01 > 0.005 > STATED_AREA_ABS_TOL)
        ("10,000.005 square feet, more or less", "10,000 square feet", 10000.0, True),
        # Outside STATED_AREA_REL_TOL (0.05 > 0.01000005)
        ("10,000.05 square feet, more or less", "10,000 square feet", 10000.0, False),
        # Within STATED_AREA_ABS_TOL (5e-5 <= 1e-4, even though > 1e-6 * 1.00005)
        ("1.00005 square feet, more or less", "1.0 square feet", 1.0, True),
        # Outside STATED_AREA_ABS_TOL (5e-4 > 1e-4)
        ("1.0005 square feet, more or less", "1.0 square feet", 1.0, False),
        # Distinct easement approximate area vs exact MAIN area must not propagate approximate
        ("400 square feet, more or less", "10,000 square feet", 10000.0, False),
    ],
)
def test_c6_prepare_text_and_pdf_processor_stated_area_approximate_tolerance_behavior(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    deed_level_area_phrase: str,
    main_area_phrase: str,
    expected_area: float,
    expected_approx: bool,
) -> None:
    """Both prepare_text and MonolithPDFProcessor propagate approximate iff areas match within tolerance."""
    # Tract 1 (EASEMENT) supplies the deed-level first positive area statement (approximate=True),
    # while Tract 2 (MAIN) is the sole boundary tract whose stated_area_sq_ft is compared against it.
    deed = (
        "TRACT 1: A non-exclusive easement for ingress and egress described as follows: "
        "BEGINNING at a stake; "
        "THENCE N 0°00'00\" E, 20.00 feet; "
        "THENCE N 90°00'00\" E, 20.00 feet; "
        "THENCE S 0°00'00\" W, 20.00 feet; "
        "THENCE N 90°00'00\" W, 20.00 feet to the point of beginning, "
        f"containing {deed_level_area_phrase}.\n\n"
        "TRACT 2: BEGINNING at an iron pin; "
        "THENCE N 0°00'00\" E, 100.00 feet; "
        "THENCE N 90°00'00\" E, 100.00 feet; "
        "THENCE S 0°00'00\" W, 100.00 feet; "
        "THENCE N 90°00'00\" W, 100.00 feet to the point of beginning, "
        f"containing {main_area_phrase}."
    )

    prepared = prepare_text(deed)
    ld = prepared.legal_description
    assert len(ld.tracts) == 2
    assert ld.tracts[0].tract_type == TractType.EASEMENT
    assert ld.tracts[1].tract_type == TractType.MAIN
    assert ld.stated_area_sq_ft == pytest.approx(expected_area)
    assert ld.stated_area_approximate is expected_approx

    pdf = tmp_path / "stated_area_tol.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    processor = MonolithPDFProcessor(client=object(), cache=False)  # type: ignore[arg-type]
    monkeypatch.setattr(processor, "extract_legal_description", lambda _p: deed)
    monkeypatch.setattr(processor, "normalize_legal_description", lambda t: t)
    mono_ld = processor.process_deed_pdf(str(pdf))
    assert not isinstance(mono_ld, tuple)
    assert len(mono_ld.tracts) == 2
    assert mono_ld.stated_area_sq_ft == pytest.approx(expected_area)
    assert mono_ld.stated_area_approximate is expected_approx


def test_c8_easement_poc_never_marks_main_boundary_or_triggers_unresolved_poc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An easement POC must never mark MAIN boundary calls as tie-ins or leak into legal.poc_description."""
    deed_pob_wording_in_main = (
        "TRACT 1: BEGINNING at an iron pin; "
        "THENCE N 0°00'00\" E, 100.00 feet to the point of beginning of Lot 2; "
        "THENCE N 90°00'00\" E, 100.00 feet; "
        "THENCE S 0°00'00\" W, 100.00 feet; "
        "THENCE N 90°00'00\" W, 100.00 feet to the point of beginning.\n\n"
        "TRACT 2: A non-exclusive easement for ingress and egress described as follows: "
        "COMMENCING at a stone monument; "
        "THENCE N 0°00'00\" E, 10.00 feet to the point of beginning; "
        "THENCE N 0°00'00\" E, 20.00 feet; "
        "THENCE N 90°00'00\" E, 20.00 feet; "
        "THENCE S 0°00'00\" W, 20.00 feet; "
        "THENCE N 90°00'00\" W, 20.00 feet to the point of beginning."
    )
    prepared = prepare_text(deed_pob_wording_in_main)
    ld = prepared.legal_description
    assert len(ld.tracts) == 2
    assert all(not c.is_tie_in for c in ld.tracts[0].calls)
    assert all(not c.is_tie_in for c in ld.calls)
    assert ld.tracts[1].calls[0].is_tie_in is True
    assert ld.poc_description is None
    assert prepared.unresolved_commencement is False

    reviewed = review_text(deed_pob_wording_in_main)
    assert "unresolved_poc" not in [e["code"] for e in reviewed["errors"]]
    assert reviewed["verification"] is not None
    assert reviewed["verification"]["closure_passed"] is True
    assert reviewed["verification"]["area_sq_ft"] == pytest.approx(10000.0)

    pdf = tmp_path / "easement_poc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    processor = MonolithPDFProcessor(client=object(), cache=False)  # type: ignore[arg-type]
    monkeypatch.setattr(processor, "extract_legal_description", lambda _p: deed_pob_wording_in_main)
    monkeypatch.setattr(processor, "normalize_legal_description", lambda t: t)
    mono_ld = processor.process_deed_pdf(str(pdf))
    assert not isinstance(mono_ld, tuple)
    assert len(mono_ld.tracts) == 2
    assert all(not c.is_tie_in for c in mono_ld.tracts[0].calls)
    assert all(not c.is_tie_in for c in mono_ld.calls)
    assert mono_ld.tracts[1].calls[0].is_tie_in is True
    assert mono_ld.poc_description is None

    # Bug 2: MAIN without mid-traverse POB wording + Easement with POC must not emit unresolved_poc.
    deed_clean_main_easement_poc = deed_pob_wording_in_main.replace(
        " to the point of beginning of Lot 2", ""
    )
    reviewed2 = review_text(deed_clean_main_easement_poc)
    assert "unresolved_poc" not in [e["code"] for e in reviewed2["errors"]]
    assert prepare_text(deed_clean_main_easement_poc).legal_description.poc_description is None

    monkeypatch.setattr(
        processor, "extract_legal_description", lambda _p: deed_clean_main_easement_poc
    )
    mono_ld2 = processor.process_deed_pdf(str(pdf))
    assert not isinstance(mono_ld2, tuple)
    assert mono_ld2.poc_description is None


def test_c8_sole_tract_preamble_poc_fallback_and_active_tract_poc_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sole-tract preamble POC applies only without skips; multi-tract uses active tract poc_description."""
    from metesparser.call_extractor import CallExtractor
    from metesparser.models import DeedCall as MonolithDeedCall
    from metesparser.models import SkippedCourse as MonolithSkippedCourse
    from metesparser.models import Tract as MonolithTract
    from metesparser.models import TractType as MonolithTractType

    tie_call = DeedCall(
        course=1,
        direction_text="N 0° E",
        bearing_quadrant="N 0°00' E",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=50.0,
        to="the point of beginning",
    )
    boundary = [c.model_copy(update={"course": c.course + 1}) for c in _square_calls(100.0)]
    boundary[-1] = boundary[-1].model_copy(update={"to": "the point of beginning"})
    preamble_deed = (
        "COMMENCING at a stone monument; "
        "THENCE N 0°00' E 50 feet to the POINT OF BEGINNING; "
        "THENCE N 0°00' E 100 feet to the point of beginning."
    )

    # 1. Sole tract with NO skips and poc_description=None -> applies preamble fallback.
    sole_clean = [
        Tract(
            label="Tract 1",
            tract_type=TractType.MAIN,
            role_basis="single",
            calls=[tie_call, *boundary],
        )
    ]
    monkeypatch.setattr(
        "mp_review.text.extract_calls", lambda *_a, **_kw: ([tie_call, *boundary], sole_clean)
    )
    prep_clean = prepare_text(preamble_deed)
    assert prep_clean.legal_description.tracts[0].calls[0].is_tie_in is True
    assert prep_clean.legal_description.calls[0].is_tie_in is True
    assert prep_clean.legal_description.poc_description is not None

    # 2. Sole tract WITH skipped_courses -> refuses to guess tie-ins, still records POC.
    sole_skipped = [
        Tract(
            label="Tract 1",
            tract_type=TractType.MAIN,
            role_basis="single",
            calls=[tie_call, *boundary],
            skipped_courses=[
                SkippedCourse(
                    course=1,
                    source_course=1,
                    source_excerpt="THENCE garbled",
                    error_type="ValueError",
                    error="unparsed",
                    tract_label="Tract 1",
                )
            ],
        )
    ]
    monkeypatch.setattr(
        "mp_review.text.extract_calls", lambda *_a, **_kw: ([tie_call, *boundary], sole_skipped)
    )
    prep_skip = prepare_text(preamble_deed)
    assert all(not c.is_tie_in for c in prep_skip.legal_description.tracts[0].calls)
    assert all(not c.is_tie_in for c in prep_skip.legal_description.calls)
    assert prep_skip.legal_description.poc_description is not None

    # 3. Multi-tract: uses active tract's poc_description (not easement's).
    multi_tracts = [
        Tract(
            label="Tract 1",
            tract_type=TractType.MAIN,
            role_basis="heading",
            poc_description="NE corner of Section 1",
            calls=[tie_call.model_copy(update={"is_tie_in": True}), *boundary],
        ),
        Tract(
            label="Easement 1",
            tract_type=TractType.EASEMENT,
            role_basis="heading",
            poc_description="a stone monument",
            calls=_square_calls(20.0),
        ),
    ]
    monkeypatch.setattr(
        "mp_review.text.extract_calls",
        lambda *_a, **_kw: (multi_tracts[0].calls, multi_tracts),
    )
    prep_multi = prepare_text(preamble_deed)
    assert prep_multi.legal_description.poc_description == "NE corner of Section 1"

    # 4. Monolith PDFProcessor mirrors sole-tract skipped_courses refusal and active tract POC.
    mono_tie = MonolithDeedCall.model_validate(tie_call.model_dump())
    mono_boundary = [MonolithDeedCall.model_validate(c.model_dump()) for c in boundary]

    def fake_skipped_extract(_text: str, *, tracts: list[MonolithTract] | None = None, **_kw: Any):
        if tracts is not None:
            tracts.append(
                MonolithTract(
                    label="Tract 1",
                    tract_type=MonolithTractType.MAIN,
                    role_basis="single",
                    calls=[mono_tie, *mono_boundary],
                    skipped_courses=[
                        MonolithSkippedCourse(
                            course=1,
                            source_course=1,
                            source_excerpt="THENCE garbled",
                            error_type="ValueError",
                            error="unparsed",
                            tract_label="Tract 1",
                        )
                    ],
                )
            )
        return [mono_tie, *mono_boundary]

    pdf = tmp_path / "sole_skip.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    processor = MonolithPDFProcessor(client=object(), cache=False)  # type: ignore[arg-type]
    monkeypatch.setattr(processor, "extract_legal_description", lambda _p: preamble_deed)
    monkeypatch.setattr(processor, "normalize_legal_description", lambda t: t)
    monkeypatch.setattr(CallExtractor, "extract_calls", staticmethod(fake_skipped_extract))
    mono_skip = processor.process_deed_pdf(str(pdf))
    assert not isinstance(mono_skip, tuple)
    assert all(not c.is_tie_in for c in mono_skip.tracts[0].calls)
    assert all(not c.is_tie_in for c in mono_skip.calls)
    assert mono_skip.poc_description is not None


def test_m6_easement_only_deed_text_json_and_pdf_processor_parity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Easement-only deeds retain blocked easement calls across prepare_text, JSON replay, and PDFProcessor."""
    easement_only = (
        "A non-exclusive easement for ingress and egress described as follows: "
        "BEGINNING at a stake; "
        "THENCE N 0°00'00\" E, 20.00 feet; "
        "THENCE N 90°00'00\" E, 20.00 feet; "
        "THENCE S 0°00'00\" W, 20.00 feet; "
        "THENCE N 90°00'00\" W, 20.00 feet to the point of beginning."
    )
    text_out = tmp_path / "text_out"
    text_res = review_text(easement_only, output_dir=text_out)
    assert text_res["status"] == "needs_review"
    assert "no_calls" not in [e["code"] for e in text_res["errors"]]
    assert len(text_res["calls"]) == 4
    assert all(EASEMENT_TRACT_NOTE in split_notes(c["notes"]) for c in text_res["calls"])
    assert all(DESCRIPTION_ROLES_NOTE in split_notes(c["notes"]) for c in text_res["calls"])
    assert text_res["verification"] is not None
    assert any(
        chk["name"] == "non_boundary_tract" and chk["status"] == "blocked"
        for chk in text_res["verification"]["checks"]
    )
    assert not (text_out / "calls_verified.csv").exists()

    audit_payload = json.loads((text_out / "audit.json").read_text(encoding="utf-8"))
    legal_json = tmp_path / "easement_legal.json"
    legal_json.write_text(json.dumps(audit_payload["legal_description"]), encoding="utf-8")
    json_out = tmp_path / "json_out"
    json_res = review_file(legal_json, output_dir=json_out)
    assert json_res["status"] == text_res["status"] == "needs_review"
    assert json_res["calls"] == text_res["calls"]
    assert [e["code"] for e in json_res["errors"]] == [e["code"] for e in text_res["errors"]]
    assert json_res["verification"]["checks"] == text_res["verification"]["checks"]
    assert not (json_out / "calls_verified.csv").exists()

    # Monolith PDFProcessor parity on easement-only deed
    pdf = tmp_path / "easement_only.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    processor = MonolithPDFProcessor(client=object(), cache=False)  # type: ignore[arg-type]
    monkeypatch.setattr(processor, "extract_legal_description", lambda _p: easement_only)
    monkeypatch.setattr(processor, "normalize_legal_description", lambda t: t)
    mono_ld = processor.process_deed_pdf(str(pdf))
    assert not isinstance(mono_ld, tuple)
    assert len(mono_ld.tracts) == 1
    assert len(mono_ld.calls) == 4
    assert all(EASEMENT_TRACT_NOTE in split_notes(c.notes) for c in mono_ld.calls)
    assert all(DESCRIPTION_ROLES_NOTE in split_notes(c.notes) for c in mono_ld.calls)


@pytest.mark.parametrize("cache_cls", [PackageCachedClient, MonolithCachedClient])
def test_m5_cached_client_separates_model_name_only_clients(cache_cls: Any, tmp_path: Path) -> None:
    """Two instances of a model_name-only client class with distinct model_name must not collide."""

    class ModelNameOnlyClient:
        def __init__(self, name: str) -> None:
            self.model_name = name

        def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
            return f"resp:{self.model_name}"

        def generate_text_with_pdf(
            self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
        ) -> str:
            return f"pdf:{self.model_name}"

    cache_dir = tmp_path / "model_name_cache"
    alpha = cache_cls(ModelNameOnlyClient("alpha"), cache_dir=cache_dir)
    beta = cache_cls(ModelNameOnlyClient("beta"), cache_dir=cache_dir)

    assert alpha._cache_key("prompt", None) != beta._cache_key("prompt", None)
    assert alpha.generate_text("prompt") == "resp:alpha"
    assert beta.generate_text("prompt") == "resp:beta"

    nested_alpha = cache_cls(
        cache_cls(ModelNameOnlyClient("alpha"), cache_dir=tmp_path / "inner"),
        cache_dir=cache_dir,
    )
    assert nested_alpha._cache_key("prompt", None) == alpha._cache_key("prompt", None)
    assert nested_alpha._cache_key("prompt", None) != beta._cache_key("prompt", None)


def test_m11_replay_review_invalid_stated_area_preserves_decoded_source(tmp_path: Path) -> None:
    """Invalid stated_area_sq_ft must preserve decoded UTF-8 source in audit without creating output_dir."""
    valid_bytes = b"BEGINNING at a pin;"
    res = replay_review(valid_bytes, input_kind="text", stated_area_sq_ft=-1.0)
    assert res["status"] == "error"
    assert [e["code"] for e in res["errors"]] == ["invalid_input"]
    assert res["audit"]["original_source"] == "BEGINNING at a pin;"
    assert res["audit"]["source_encoding"] == "utf-8"
    assert res["audit"]["errors"] == res["errors"]

    bom_res = replay_review(
        "\ufeffBEGINNING at a pin;".encode(), input_kind="text", stated_area_sq_ft=0.0
    )
    assert bom_res["audit"]["original_source"] == "BEGINNING at a pin;"
    assert bom_res["audit"]["source_encoding"] == "utf-8"

    empty_res = replay_review(b"", input_kind="text", stated_area_sq_ft=-1.0)
    assert empty_res["audit"]["original_source"] == ""
    assert empty_res["audit"]["source_encoding"] == "unavailable or empty"

    bad_utf8_res = replay_review(
        b"\xff\xfeN 0 E 100 feet", input_kind="text", stated_area_sq_ft=-1.0
    )
    assert bad_utf8_res["status"] == "error"
    assert [e["code"] for e in bad_utf8_res["errors"]] == ["invalid_input"]
    assert bad_utf8_res["audit"]["original_source"] == ""
    assert bad_utf8_res["audit"]["source_encoding"] == "unavailable or empty"

    # output_dir must still not be created when stated_area_sq_ft is invalid
    src = tmp_path / "deed.txt"
    src.write_bytes(valid_bytes)
    out_dir = tmp_path / "never_created"
    disk_err = review_file(src, output_dir=out_dir, stated_area_sq_ft=-1.0)
    assert disk_err["status"] == "error"
    assert [e["code"] for e in disk_err["errors"]] == ["invalid_input"]
    assert not out_dir.exists()


# ---------------------------------------------------------------------------
# 7. Cycle 3 Follow-up Track 3: #3/#13, #15, #12
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "lead",
    [
        "POC: NW corner of Section 4; ",
        "COMMENCING from the NW corner of Section 4; ",
    ],
)
def test_unresolved_commencement_single_tract_fails_closed_in_review_text(
    tmp_path: Path, lead: str
) -> None:
    """Unresolved commencement clauses with poc_description=None must fail closed in review_text."""
    deed = (
        lead + "THENCE N 0°00'00\" E, 100.00 feet; "
        "THENCE N 90°00'00\" E, 100.00 feet; "
        "THENCE S 0°00'00\" W, 100.00 feet; "
        "THENCE N 90°00'00\" W, 100.00 feet to the point of beginning."
    )
    prepared = prepare_text(deed)
    assert prepared.legal_description.poc_description is None
    assert prepared.unresolved_commencement is True

    out_dir = tmp_path / "review_out"
    reviewed = review_text(deed, output_dir=out_dir)
    assert reviewed["status"] == "needs_review"
    assert "unresolved_poc" in [e["code"] for e in reviewed["errors"]]
    assert not (out_dir / "calls_verified.csv").exists()


def test_unresolved_commencement_multi_tract_main_with_easement_fails_closed(
    tmp_path: Path,
) -> None:
    """Multi-tract deed with unresolved COMMENCING on MAIN + EASEMENT must fail closed."""
    deed = (
        "TRACT 1: COMMENCING at the NW corner of Section 4; "
        "THENCE N 0°00'00\" E, 100.00 feet; "
        "THENCE N 90°00'00\" E, 100.00 feet; "
        "THENCE S 0°00'00\" W, 100.00 feet; "
        "THENCE N 90°00'00\" W, 100.00 feet to the point of beginning.\n\n"
        "TRACT 2: A non-exclusive easement for ingress and egress described as follows: "
        "BEGINNING at a stake; "
        "THENCE N 0°00'00\" E, 20.00 feet; "
        "THENCE N 90°00'00\" E, 20.00 feet; "
        "THENCE S 0°00'00\" W, 20.00 feet; "
        "THENCE N 90°00'00\" W, 20.00 feet to the point of beginning."
    )
    prepared = prepare_text(deed)
    assert len(prepared.legal_description.tracts) == 2
    assert prepared.unresolved_commencement is True

    out_dir = tmp_path / "multi_unresolved_out"
    reviewed = review_text(deed, output_dir=out_dir)
    assert reviewed["status"] == "needs_review"
    assert "unresolved_poc" in [e["code"] for e in reviewed["errors"]]
    assert not (out_dir / "calls_verified.csv").exists()


def test_exception_plus_easement_text_and_json_replay_parity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EXCEPTION + EASEMENT deeds (no boundary tract) retain all 8 calls across text, JSON, and PDFProcessor."""
    exc_plus_ease_text = (
        "TRACT 1: EXCEPTING THEREFROM the following described parcel: "
        "BEGINNING at an iron pin; "
        "THENCE N 0°00'00\" E, 20.00 feet; "
        "THENCE N 90°00'00\" E, 20.00 feet; "
        "THENCE S 0°00'00\" W, 20.00 feet; "
        "THENCE N 90°00'00\" W, 20.00 feet to the point of beginning.\n\n"
        "TRACT 2: A non-exclusive easement for ingress and egress described as follows: "
        "BEGINNING at a stake; "
        "THENCE N 0°00'00\" E, 10.00 feet; "
        "THENCE N 90°00'00\" E, 10.00 feet; "
        "THENCE S 0°00'00\" W, 10.00 feet; "
        "THENCE N 90°00'00\" W, 10.00 feet to the point of beginning."
    )
    text_res = review_text(exc_plus_ease_text)
    prepared_json = prepare_text(exc_plus_ease_text).legal_description.model_dump_json().encode()
    json_res = replay_review(prepared_json, input_kind="json")

    assert text_res["status"] == "needs_review"
    assert json_res["status"] == "needs_review"
    assert len(text_res["calls"]) == 8
    assert all(
        c["is_exception"] is True and EXCEPTION_TRACT_NOTE in split_notes(c["notes"])
        for c in text_res["calls"][:4]
    )
    assert all(
        c["is_exception"] is False and EASEMENT_TRACT_NOTE in split_notes(c["notes"])
        for c in text_res["calls"][4:]
    )
    assert json_res["calls"] == text_res["calls"]

    # Monolith PDFProcessor parity on EXCEPTION + EASEMENT deed
    pdf = tmp_path / "exc_plus_ease.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    processor = MonolithPDFProcessor(client=object(), cache=False)  # type: ignore[arg-type]
    monkeypatch.setattr(processor, "extract_legal_description", lambda _p: exc_plus_ease_text)
    monkeypatch.setattr(processor, "normalize_legal_description", lambda t: t)
    mono_ld = processor.process_deed_pdf(str(pdf))
    assert not isinstance(mono_ld, tuple)
    assert len(mono_ld.tracts) == 2
    assert len(mono_ld.calls) == 8
    assert all(
        c.is_exception is True and EXCEPTION_TRACT_NOTE in split_notes(c.notes)
        for c in mono_ld.calls[:4]
    )
    assert all(
        c.is_exception is False and EASEMENT_TRACT_NOTE in split_notes(c.notes)
        for c in mono_ld.calls[4:]
    )


def test_sole_tract_preamble_poc_monolith_happy_path_and_all_tie_in_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Monolith sole-tract preamble POC happy path marks tie-ins; all-tie-in guard keeps calls unmarked."""
    from metesparser.call_extractor import CallExtractor
    from metesparser.models import DeedCall as MonolithDeedCall
    from metesparser.models import Tract as MonolithTract
    from metesparser.models import TractType as MonolithTractType

    tie_call = DeedCall(
        course=1,
        direction_text="N 0° E",
        bearing_quadrant="N 0°00' E",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=50.0,
        to="the point of beginning",
    )
    boundary = [c.model_copy(update={"course": c.course + 1}) for c in _square_calls(100.0)]
    boundary[-1] = boundary[-1].model_copy(update={"to": "the point of beginning"})
    preamble_deed = (
        "COMMENCING at a stone monument; "
        "THENCE N 0°00' E 50 feet to the POINT OF BEGINNING; "
        "THENCE N 0°00' E 100 feet to the point of beginning."
    )

    mono_tie = MonolithDeedCall.model_validate(tie_call.model_dump())
    mono_boundary = [MonolithDeedCall.model_validate(c.model_dump()) for c in boundary]

    def fake_clean_extract(_text: str, *, tracts: list[MonolithTract] | None = None, **_kw: Any):
        if tracts is not None:
            tracts.append(
                MonolithTract(
                    label="Tract 1",
                    tract_type=MonolithTractType.MAIN,
                    role_basis="single",
                    calls=[mono_tie, *mono_boundary],
                    skipped_courses=[],
                )
            )
        return [mono_tie, *mono_boundary]

    pdf = tmp_path / "sole_happy.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    processor = MonolithPDFProcessor(client=object(), cache=False)  # type: ignore[arg-type]
    monkeypatch.setattr(processor, "extract_legal_description", lambda _p: preamble_deed)
    monkeypatch.setattr(processor, "normalize_legal_description", lambda t: t)
    monkeypatch.setattr(CallExtractor, "extract_calls", staticmethod(fake_clean_extract))

    # 1. Monolith sole-tract preamble POC happy path (skipped_courses=[])
    mono_clean = processor.process_deed_pdf(str(pdf))
    assert not isinstance(mono_clean, tuple)
    assert len(mono_clean.tracts) == 1
    assert mono_clean.tracts[0].calls[0].is_tie_in is True
    assert mono_clean.calls[0].is_tie_in is True
    assert all(not c.is_tie_in for c in mono_clean.tracts[0].calls[1:])
    assert all(not c.is_tie_in for c in mono_clean.calls[1:])
    assert mono_clean.poc_description is not None

    # 2. All-tie-in guard on MonolithPDFProcessor: if mark_tie_in_calls marks every call, keep unmarked
    monkeypatch.setattr(
        CallExtractor,
        "mark_tie_in_calls",
        staticmethod(
            lambda calls, poc_description=None: [
                c.model_copy(update={"is_tie_in": True}) for c in calls
            ]
        ),
    )
    mono_all_tie = processor.process_deed_pdf(str(pdf))
    assert not isinstance(mono_all_tie, tuple)
    assert not any(c.is_tie_in for c in mono_all_tie.tracts[0].calls)
    assert not any(c.is_tie_in for c in mono_all_tie.calls)

    # 3. All-tie-in guard on mp_review.text.prepare_text
    sole_clean = [
        Tract(
            label="Tract 1",
            tract_type=TractType.MAIN,
            role_basis="single",
            calls=[tie_call, *boundary],
            skipped_courses=[],
        )
    ]
    monkeypatch.setattr(
        "mp_review.text.extract_calls", lambda *_a, **_kw: ([tie_call, *boundary], sole_clean)
    )
    monkeypatch.setattr(
        "mp_review.text.mark_tie_in_calls",
        lambda calls, _poc=None: [c.model_copy(update={"is_tie_in": True}) for c in calls],
    )
    prep_all_tie = prepare_text(preamble_deed)
    assert not any(c.is_tie_in for c in prep_all_tie.legal_description.tracts[0].calls)
    assert not any(c.is_tie_in for c in prep_all_tie.legal_description.calls)
    assert prep_all_tie.unresolved_commencement is True
