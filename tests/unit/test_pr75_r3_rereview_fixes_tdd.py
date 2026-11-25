"""Red-Green TDD regression tests for PR #75 Cycle 2 (R2 re-review findings)."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import pytest
from mp_export.csv_writer import export_verified_csv
from mp_models import (
    DeedCall,
    LegalDescription,
    Tract,
    TractType,
    mark_roles_review,
)
from mp_parse.calls import extract_calls
from mp_parse.metadata import extract_plss_metadata
from mp_parse.normalizer import expand_assessor_abbreviations, normalize_legal_description
from mp_parse.numbers import COMMA_NUMBER
from mp_review import replay_review, review_text
from mp_verify import verify_closure

from metesparser.closure_checker import ClosureChecker
from metesparser.csv_builder import CSVBuilder
from metesparser.pdf_processor import PDFProcessor
from metesparser.review_packet import _as_bool, generate_traverse_plot


def _square(size: float = 100.0) -> list[DeedCall]:
    return [
        DeedCall(
            course=i + 1,
            direction_text=f"az {az}",
            bearing_azimuth_deg_from_north=az,
            distance_ft=size,
        )
        for i, az in enumerate((0.0, 90.0, 180.0, 270.0))
    ]


# ---------------------------------------------------------------------------
# Codex P1: D-suffixed curve angles preserved during normalization
# ---------------------------------------------------------------------------


def test_d_suffixed_curve_delta_preserved_and_contradiction_rejected() -> None:
    text = (
        f"BEGINNING at a pin; "
        f"THENCE N 0D E along a curve to the right with a radius of 100 feet "
        f"and a delta of 90D and an arc length of {100 * math.pi:.6f} feet to a point; "
        f"THENCE N 90D W 200 feet to the point of beginning."
    )
    normalized = normalize_legal_description(text)
    calls, _ = extract_calls(normalized)
    assert calls[0].delta_deg == pytest.approx(90.0)

    res = verify_closure(calls)
    assert not res.is_fully_verified()
    assert any("arc length inconsistency" in w for w in res.warnings)
    assert review_text(text)["status"] == "needs_review"

    # Lot / unit / building identifiers must still remain untouched
    assert "LOT 2D" in expand_assessor_abbreviations("LOT 2D, UNIT 3D, BLDG 4D")
    assert "UNIT 3D" in expand_assessor_abbreviations("LOT 2D, UNIT 3D, BLDG 4D")
    assert "BLDG 4D" in expand_assessor_abbreviations("LOT 2D, UNIT 3D, BLDG 4D")


# ---------------------------------------------------------------------------
# Codex P2: Compound cardinal suffixes after TH
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected_fragment"),
    [
        ("BEG TH NORTHEASTERLY 100 FT", "thence NORTHEASTERLY"),
        ("BEG TH SOUTHWESTERLY 100 FT", "thence SOUTHWESTERLY"),
        ("BEG TH NORTHWESTERLY 100 FT", "thence NORTHWESTERLY"),
        ("BEG TH SOUTHEASTWARDLY 100 FT", "thence SOUTHEASTWARDLY"),
    ],
)
def test_th_expands_before_compound_cardinal_suffixes(raw: str, expected_fragment: str) -> None:
    out = expand_assessor_abbreviations(raw)
    assert expected_fragment.lower() in out.lower()


# ---------------------------------------------------------------------------
# Native #1 (CRITICAL): DESCRIPTION_ROLES_NOTE cannot be stripped on JSON review
# ---------------------------------------------------------------------------


def test_json_review_cannot_strip_description_roles_note_via_headed_tract() -> None:
    square = _square(100.0)
    legal = LegalDescription(
        calls=mark_roles_review(square),
        tracts=[
            Tract(
                label="Tract 1",
                tract_type=TractType.MAIN,
                role_basis="heading",
                calls=square,
            )
        ],
    )
    payload = json.dumps(legal.model_dump(mode="json")).encode("utf-8")
    replayed = replay_review(payload, input_kind="json", source_name="crafted.json")
    assert replayed["status"] != "checks_passed"


# ---------------------------------------------------------------------------
# Native #2 (HIGH): Empty ADDITION / EXCEPTION tracts fail closed
# ---------------------------------------------------------------------------


def test_empty_addition_and_exception_tracts_blocked_in_export_and_review(tmp_path: Path) -> None:
    square = _square(100.0)
    closing = verify_closure(square)

    legal_add = LegalDescription(
        calls=square,
        tracts=[
            Tract(label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=square),
            Tract(
                label="Addition 1", tract_type=TractType.ADDITION, role_basis="heading", calls=[]
            ),
        ],
    )
    with pytest.raises(ValueError, match="multiple boundary tracts"):
        export_verified_csv(square, closing, str(tmp_path / "add.csv"), legal_desc=legal_add)

    legal_exc = LegalDescription(
        calls=square,
        tracts=[
            Tract(label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=square),
            Tract(
                label="Exception 1",
                tract_type=TractType.EXCEPTION,
                role_basis="heading",
                calls=[],
                stated_area_sq_ft=2500.0,
            ),
        ],
    )
    with pytest.raises(ValueError, match="exception tracts"):
        export_verified_csv(square, closing, str(tmp_path / "exc.csv"), legal_desc=legal_exc)

    payload = json.dumps(legal_exc.model_dump(mode="json")).encode("utf-8")
    replayed = replay_review(payload, input_kind="json", source_name="empty_exc.json")
    assert replayed["status"] == "needs_review"
    assert any(err["code"] == "incomplete_exception_tract" for err in replayed["errors"])


# ---------------------------------------------------------------------------
# Native #3 (HIGH): Compound-distance allowlist & punctuation/spacing guards
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "clause",
    [
        "THENCE N 45° E 100 feet and 2 stone cubits to a pin.",
        "THENCE N 45° E 100 feet and 2 iron fathoms to a pin.",
        "THENCE N 45° E 100 feet and 2 concrete km to a pin.",
        "THENCE N 45° E 100 ft. and 50 yards to a pin.",
        "THENCE N 45° E 100 feet, and 50 cubits to a pin.",
        "THENCE N 45° E 100 feet and 50cm to a pin.",
        "THENCE N 45° E 100m and 50cm to a pin.",
        "THENCE N 45° E 10 rods 5 ft. and 2 cubits to a pin.",
        "THENCE N 45° E 10 chains 50 links, and 2 cubits to a pin.",
    ],
)
def test_compound_distance_variants_fail_closed(clause: str) -> None:
    normalized = normalize_legal_description(clause)
    with pytest.raises(ValueError):
        extract_calls(normalized, strict=True)


def test_multi_modifier_monument_counts_still_accepted() -> None:
    for clause in (
        "THENCE N 45° E 100 feet and 2 capped iron pins to a corner.",
        "THENCE N 45° E 100 feet and 2 concrete monuments to a corner.",
    ):
        calls, _ = extract_calls(normalize_legal_description(clause), strict=True)
        assert len(calls) == 1
        assert calls[0].distance_ft == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Native #4 (HIGH): Zero stated area blocks verification in PDFProcessor (audit=False)
# ---------------------------------------------------------------------------


def test_pdf_processor_zero_stated_area_blocks_verification_and_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_path = tmp_path / "zero_area.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    processor = PDFProcessor(client=object(), cache=False)  # type: ignore[arg-type]
    prose = (
        "BEGINNING at an iron pin; "
        "THENCE N 0°00'00\" E, 100.00 feet; "
        "THENCE N 90°00'00\" E, 100.00 feet; "
        "THENCE S 0°00'00\" W, 100.00 feet; "
        "THENCE N 90°00'00\" W, 100.00 feet to the point of beginning, "
        "containing 0.00 acres, more or less."
    )
    monkeypatch.setattr(processor, "extract_text_from_pdf", lambda *a, **kw: prose)
    monkeypatch.setattr(processor, "extract_legal_description", lambda *a, **kw: prose)
    monkeypatch.setattr(processor, "normalize_legal_description", lambda *a, **kw: prose)

    legal = processor.process_deed_pdf(str(pdf_path), audit=False)
    assert legal.stated_area_sq_ft is None

    result = ClosureChecker.verify_closure(legal.calls)
    assert not result.is_fully_verified()
    assert any("invalid stated area" in w.lower() for w in result.warnings)

    with pytest.raises(ValueError, match="Cannot export verified CSV"):
        CSVBuilder.export_verified_csv(
            legal.calls, result, str(tmp_path / "out.csv"), legal_desc=legal
        )


# ---------------------------------------------------------------------------
# Native #5 (MEDIUM): Unverified double-entry claim not stamped in .verification.txt
# ---------------------------------------------------------------------------


def test_export_without_double_entry_calls_does_not_stamp_double_entry_pass(tmp_path: Path) -> None:
    calls = _square(100.0)
    de = _square(100.0)
    verified = verify_closure(calls, double_entry_calls=de)

    out_implicit = tmp_path / "implicit" / "deed.csv"
    export_verified_csv(calls, verified, str(out_implicit))
    summary_implicit = (tmp_path / "implicit" / "deed_verified.verification.txt").read_text(
        encoding="utf-8"
    )
    assert "double_entry: PASS" not in summary_implicit
    assert "Independent entries match" not in summary_implicit

    out_explicit = tmp_path / "explicit" / "deed.csv"
    export_verified_csv(calls, verified, str(out_explicit), double_entry_calls=de)
    summary_explicit = (tmp_path / "explicit" / "deed_verified.verification.txt").read_text(
        encoding="utf-8"
    )
    assert "double_entry" in summary_explicit
    assert "Independent entries match" in summary_explicit


# ---------------------------------------------------------------------------
# Native #6 (MEDIUM): COMMA_NUMBER allows sentence period / clause comma
# ---------------------------------------------------------------------------


def test_comma_number_matches_before_sentence_period_or_clause_comma() -> None:
    assert re.findall(COMMA_NUMBER, "300,07.") == ["300,07"]
    assert re.findall(COMMA_NUMBER, "300,07,") == ["300,07"]
    assert re.findall(COMMA_NUMBER, "300,07.5") == []
    assert re.findall(COMMA_NUMBER, "300,07,5") == []


# ---------------------------------------------------------------------------
# Native #7 (MEDIUM): Near-360° SVG arc split and _as_bool alignment
# ---------------------------------------------------------------------------


def test_near_360_svg_arc_splits_instead_of_collapsing_and_as_bool_handles_off_n() -> None:
    gt: dict[str, Any] = {
        "expected_calls": [
            {
                "course": 1,
                "direction_text": "N 0° E near-full circle",
                "bearing_azimuth_deg_from_north": 0.0,
                "distance_ft": 50.0 * math.radians(359.995),
                "curve_dir": "right",
                "radius_ft": 50.0,
                "delta_deg": 359.995,
            }
        ]
    }
    svg = generate_traverse_plot(gt)
    path_match = re.search(r"<path d='([^']+)'", svg)
    assert path_match is not None
    assert len(re.findall(r"\bA\s+", path_match.group(1))) == 2
    assert _as_bool("off") is False
    assert _as_bool("n") is False
    assert _as_bool("on") is True
    assert _as_bool("y") is True


# ---------------------------------------------------------------------------
# Native #8 (MEDIUM): extract_sample_deeds.create_extraction_report on tracts-only
# ---------------------------------------------------------------------------


def test_create_extraction_report_uses_all_calls_on_tracts_only_deed(tmp_path: Path) -> None:
    import importlib.util

    script_path = Path(__file__).resolve().parents[2] / "scripts" / "extract_sample_deeds.py"
    spec = importlib.util.spec_from_file_location("extract_sample_deeds_r3", script_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    from metesparser.models import (
        DeedCall as MonoDeedCall,
    )
    from metesparser.models import (
        LegalDescription as MonoLegal,
    )
    from metesparser.models import (
        Tract as MonoTract,
    )
    from metesparser.models import (
        TractType as MonoTractType,
    )

    mono_calls = [
        MonoDeedCall(
            course=i + 1,
            direction_text=f"az {az}",
            bearing_azimuth_deg_from_north=az,
            distance_ft=100.0,
        )
        for i, az in enumerate((0.0, 90.0, 180.0, 270.0))
    ]
    legal = MonoLegal(
        calls=[],
        tracts=[
            MonoTract(
                label="Tract 1",
                tract_type=MonoTractType.MAIN,
                role_basis="single",
                calls=mono_calls,
            )
        ],
    )
    res = ClosureChecker.verify_closure(mono_calls)
    report_path = tmp_path / "report.txt"
    mod.create_extraction_report(legal, res, report_path)
    content = report_path.read_text(encoding="utf-8")
    assert "EXTRACTED CALLS (4 total)" in content
    assert "CALL #4" in content


# ---------------------------------------------------------------------------
# Native #9 (LOW): PLSS hyphen/in./prime guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Section 12, T3N, R4W; Thence N 1/2-mile to a pin",
        "Section 12, T3N, R4W; Thence N 1/2 in. to a pin",
        "Section 12, T3N, R4W; Thence N 1/2' to a pin",
        'Section 12, T3N, R4W; Thence N 1/2" to a pin',
    ],
)
def test_plss_aliquot_rejects_hyphenated_in_and_prime_units(text: str) -> None:
    assert extract_plss_metadata(text)["aliquot"] is None
