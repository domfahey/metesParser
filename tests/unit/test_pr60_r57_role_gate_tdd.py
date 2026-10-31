"""PR #60 round 57: one description-role gate, carried by the artifacts it blocks.

The fail-closed role policy (``mp_models.roles_need_review``) is one gate on a
description's tracts and on the role-review mark (``DESCRIPTION_ROLES_NOTE``) its flat
calls carry once their roles need review. The mark survives CSV and JSON round trips,
so the calls of a blocked review stay blocked when re-reviewed or re-verified through
any importer, and verification itself (``_verify_single``) blocks any traverse holding
it. The monolith extracts each description once: its flat calls and its tracts (with
role bases) come from the same ``mp_parse.extract_calls`` call.
"""

from __future__ import annotations

import json
from pathlib import Path

import mp_parse.calls as package_calls
import pytest
from mp_export import export_verified_csv
from mp_export.csv_writer import calls_to_csv, csv_to_calls
from mp_models import (
    DESCRIPTION_ROLES_CHECK,
    DESCRIPTION_ROLES_NOTE,
    FIXED_NOTES,
    DeedCall,
    LegalDescription,
    mark_roles_review,
    roles_need_review,
    split_notes,
)
from mp_parse.calls import extract_calls
from mp_review.api import review_file, review_text
from mp_verify import verify_closure, verify_tract

from metesparser import cli
from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker
from metesparser.csv_builder import CSVBuilder
from metesparser.pdf_processor import PDFProcessor
from tests.unit.test_pr60_r56_role_policy_tdd import PROBES, TWO_UNHEADED

# Every probe whose description roles need review (several descriptions, a guessed role).
BLOCKED = [
    name
    for name, text in PROBES.items()
    if roles_need_review(extract_calls(text, strict=False, skipped_courses=[])[1])
]


def _strictly_parsed(text: str) -> bool:
    try:
        extract_calls(text, strict=True)
    except ValueError:
        return False
    return True


# Text review extracts strictly: a probe with a malformed course is an input error there.
BLOCKED_REVIEWS = [name for name in BLOCKED if _strictly_parsed(PROBES[name])]
# The round-56 re-review bypass: the flat calls of these blocked deeds close alone.
BYPASSED = [
    "close0_easement_after",
    "close1_easement_after",
    "close2_easement_after",
    "close5_easement_after",
    "tie_easement_after",
    "plain_easement_after",
    "second_parcel2_also",
    "second_parcel2_paragraph",
    "second_parcel3_paragraph",
    "second_parcel4_also",
    "second_parcel4_paragraph",
]
EASEMENT_AFTER = PROBES["plain_easement_after"]


def _marked(call: DeedCall | dict) -> bool:
    notes = call["notes"] if isinstance(call, dict) else call.notes
    return DESCRIPTION_ROLES_NOTE in split_notes(notes)


def _codes(result: dict) -> list[str]:
    return [e["code"] for e in result["errors"]]


# --- the mark ---------------------------------------------------------------------------


def test_role_review_note_is_registered_and_idempotent() -> None:
    assert DESCRIPTION_ROLES_NOTE in FIXED_NOTES
    assert "; " not in DESCRIPTION_ROLES_NOTE
    calls, _ = extract_calls(PROBES["plain"], strict=True)
    once = mark_roles_review(calls)
    assert all(_marked(c) for c in once)
    assert mark_roles_review(once) == once
    # A verbatim note before it never swallows it.
    noted = calls[-1].model_copy(update={"notes": "exception not applied: the West 10 feet; x"})
    (marked,) = mark_roles_review([noted])
    assert split_notes(marked.notes)[-1] == DESCRIPTION_ROLES_NOTE


def test_gate_reads_the_mark_when_tracts_are_absent() -> None:
    calls, _ = extract_calls(PROBES["plain"], strict=True)
    assert roles_need_review([], calls) == []
    reasons = roles_need_review([], mark_roles_review(calls))
    assert len(reasons) == 1 and DESCRIPTION_ROLES_NOTE in reasons[0]


# --- parse: the flat calls of a blocked deed carry the mark; tract calls do not -------


@pytest.mark.parametrize("name", BLOCKED)
def test_flat_calls_of_a_blocked_deed_are_marked(name: str) -> None:
    calls, tracts = extract_calls(PROBES[name], strict=False, skipped_courses=[])
    assert calls and all(_marked(c) for c in calls)
    assert not any(_marked(c) for t in tracts for c in t.calls)


@pytest.mark.parametrize("name", ["plain", "mineral_single_parcel", "close0_two_headed_parcels"])
def test_established_roles_leave_calls_unmarked(name: str) -> None:
    calls, _ = extract_calls(PROBES[name], strict=True)
    assert not any(_marked(c) for c in calls)


# --- verification and export: every path consults the gate ----------------------------


@pytest.mark.parametrize("name", BYPASSED)
def test_flat_package_path_is_blocked(name: str, tmp_path: Path) -> None:
    calls, _ = extract_calls(PROBES[name], strict=False, skipped_courses=[])
    result = verify_closure(calls)
    assert any(c.name == DESCRIPTION_ROLES_CHECK and c.status == "blocked" for c in result.checks)
    assert not result.is_fully_verified()
    assert not verify_tract(calls).is_fully_verified()
    with pytest.raises(ValueError, match="description roles need review"):
        export_verified_csv(calls, result, str(tmp_path / "deed.csv"))
    assert list(tmp_path.iterdir()) == []


def test_marked_calls_are_blocked_after_a_csv_round_trip(tmp_path: Path) -> None:
    calls, _ = extract_calls(EASEMENT_AFTER, strict=True)
    calls_to_csv(calls, str(tmp_path / "calls.csv"))
    loaded = csv_to_calls(str(tmp_path / "calls.csv"))
    assert all(_marked(c) for c in loaded)
    assert not verify_closure(loaded).is_fully_verified()
    # Unmarked, the same geometry verifies: only the mark blocks it.
    clean = [c.model_copy(update={"notes": None}) for c in loaded]
    assert verify_closure(clean).is_fully_verified()


def test_tract_verification_reports_one_role_check() -> None:
    calls, tracts = extract_calls(TWO_UNHEADED, strict=True)
    marked_tracts = [t.model_copy(update={"calls": mark_roles_review(t.calls)}) for t in tracts]
    for result in verify_closure(calls, tracts=marked_tracts):
        assert [c.name for c in result.checks].count(DESCRIPTION_ROLES_CHECK) == 1


def test_dashboard_calculation_is_blocked_by_the_mark() -> None:
    from mp_models.dashboard import DashboardBundle
    from mp_verify.dashboard import calculate_dashboard

    fixture = Path(__file__).resolve().parents[2] / "packages/mp-review/tests/fixtures"
    raw = json.loads((fixture / "dashboard-absolute.json").read_text(encoding="utf-8"))
    assert calculate_dashboard(DashboardBundle.model_validate(raw)).calculations[0].engine_verified
    for record in raw["calls"]:
        if record.get("call"):
            record["call"]["notes"] = DESCRIPTION_ROLES_NOTE
    result = calculate_dashboard(DashboardBundle.model_validate(raw)).calculations[0]
    assert result.engine_verified is False
    assert result.verified_export_eligible is False


# --- review: a blocked review's artifacts stay blocked when re-reviewed ----------------


def test_strict_parse_errors_are_the_only_blocked_probes_not_reviewed() -> None:
    assert sorted(set(BLOCKED) - set(BLOCKED_REVIEWS)) == ["running_exception_after"]
    assert review_text(PROBES["running_exception_after"])["status"] == "error"


@pytest.mark.parametrize("name", BLOCKED_REVIEWS)
def test_blocked_review_artifacts_stay_blocked(name: str, tmp_path: Path) -> None:
    first = review_text(PROBES[name], output_dir=tmp_path / "r1")
    assert first["status"] == "needs_review"
    assert "description_roles_inferred" in _codes(first)
    assert first["calls"] and all(_marked(c) for c in first["calls"])
    assert "calls_verified.csv" not in first["artifacts"]
    stored = json.loads((tmp_path / "r1" / "calls.json").read_text(encoding="utf-8"))
    assert all(_marked(c) for c in stored)
    assert all(_marked(c) for c in csv_to_calls(str(tmp_path / "r1" / "calls.csv")))
    for artifact in ("calls.csv", "calls.json"):
        again = review_file(tmp_path / "r1" / artifact, output_dir=tmp_path / f"re-{artifact}")
        assert again["status"] == "needs_review", (artifact, again["errors"])
        assert "description_roles_inferred" in _codes(again)
        assert "calls_verified.csv" not in again["artifacts"]
        # And again: the re-review's own artifacts are still marked.
        third = review_file(
            tmp_path / f"re-{artifact}" / artifact, output_dir=tmp_path / f"re2-{artifact}"
        )
        assert third["status"] == "needs_review"


@pytest.mark.parametrize("name", ["plain", "mineral_single_parcel", "creek_bed_single_parcel"])
def test_unblocked_review_artifacts_still_pass(name: str, tmp_path: Path) -> None:
    first = review_text(PROBES[name], output_dir=tmp_path / "r1")
    assert first["status"] == "checks_passed"
    assert not any(_marked(c) for c in first["calls"])
    for artifact in ("calls.csv", "calls.json"):
        again = review_file(tmp_path / "r1" / artifact, output_dir=tmp_path / f"re-{artifact}")
        assert again["status"] == "checks_passed", (artifact, again["errors"])
        assert "calls_verified.csv" in again["artifacts"]


def test_text_review_records_tracts_with_role_bases(tmp_path: Path) -> None:
    result = review_text(TWO_UNHEADED, output_dir=tmp_path / "r1")
    audit = json.loads((tmp_path / "r1" / "audit.json").read_text(encoding="utf-8"))
    tracts = audit["legal_description"]["tracts"]
    assert [(t["tract_type"], t["role_basis"]) for t in tracts] == [
        ("main", "inferred"),
        ("exception", "inferred"),
    ]
    # The audit's description replayed as JSON is blocked by its tracts.
    path = tmp_path / "legal.json"
    path.write_text(json.dumps(audit["legal_description"]), encoding="utf-8")
    assert review_file(path, output_dir=tmp_path / "replay")["status"] == "needs_review"
    assert result["status"] == "needs_review"


def test_json_review_with_stored_tracts_marks_its_artifacts(tmp_path: Path) -> None:
    _, tracts = extract_calls(EASEMENT_AFTER, strict=True)
    stored = LegalDescription(calls=tracts[0].calls, tracts=tracts)
    path = tmp_path / "deed.json"
    path.write_text(stored.model_dump_json(), encoding="utf-8")
    first = review_file(path, output_dir=tmp_path / "r1")
    assert first["status"] == "needs_review"
    for artifact in ("calls.csv", "calls.json"):
        again = review_file(tmp_path / "r1" / artifact, output_dir=tmp_path / f"re-{artifact}")
        assert again["status"] == "needs_review", artifact


# --- monolith: one extraction, the same gate ------------------------------------------


class _CountingParse:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.extract_calls = 0
        self.texts: list[str] = []
        original_extract = package_calls.extract_calls
        original_text = package_calls._extract_calls_from_text

        def extract(*args, **kwargs):
            self.extract_calls += 1
            return original_extract(*args, **kwargs)

        def from_text(text, *args, **kwargs):
            self.texts.append(text)
            return original_text(text, *args, **kwargs)

        monkeypatch.setattr(package_calls, "extract_calls", extract)
        monkeypatch.setattr(package_calls, "_extract_calls_from_text", from_text)


def _processor(text: str) -> PDFProcessor:
    class _NoLLM:
        pass

    processor = PDFProcessor(client=_NoLLM(), cache=False)
    processor.extract_legal_description = lambda _path: text  # type: ignore[method-assign]
    processor.normalize_legal_description = lambda value: value  # type: ignore[method-assign]
    return processor


@pytest.mark.parametrize(
    ("name", "parses"),
    [("plain", 1), ("plain_easement_after", 2), ("close0_two_headed_parcels", 2)],
)
def test_monolith_parses_each_description_once(
    name: str, parses: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    counter = _CountingParse(monkeypatch)
    legal = _processor(PROBES[name]).process_deed_pdf("deed.pdf")
    assert counter.extract_calls == 1
    # One course parse per description: never a second pass over the whole text.
    assert len(counter.texts) == parses
    flat, tracts = extract_calls(PROBES[name], strict=True)
    assert [(c.course, c.distance_ft, c.notes) for c in legal.calls] == [
        (c.course, c.distance_ft, c.notes) for c in flat
    ]
    assert [(t.label, t.role_basis) for t in legal.tracts] == [
        (t.label, t.role_basis) for t in tracts
    ]


def test_monolith_facade_returns_tracts_from_its_own_extraction() -> None:
    tracts: list = []
    calls = CallExtractor.extract_calls(TWO_UNHEADED, tracts=tracts)
    assert [(t.tract_type.value, t.role_basis) for t in tracts] == [
        ("main", "inferred"),
        ("exception", "inferred"),
    ]
    assert all(_marked(c) for c in calls)
    headed: list = []
    CallExtractor.extract_calls(PROBES["close0_two_headed_parcels"], tracts=headed)
    assert [t.role_basis for t in headed] == ["heading", "heading"]
    single: list = []
    CallExtractor.extract_calls(PROBES["plain"], tracts=single)
    assert single == []


def test_pipeline_parses_once_and_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    from metesparser.pipeline import Pipeline

    counter = _CountingParse(monkeypatch)
    monkeypatch.setattr(
        "metesparser.pipeline.PDFProcessor",
        lambda **_kwargs: _processor(EASEMENT_AFTER),
    )
    results = Pipeline(provider="openai").run(Path("deed.pdf"))
    assert counter.extract_calls == 1
    assert len(counter.texts) == 2  # one course parse per description, nothing more
    assert isinstance(results, list) and len(results) == 2
    assert not any(r.is_fully_verified() for r in results)


def test_cli_extract_writes_a_marked_csv_that_verify_rejects(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "RUNS_DIR", tmp_path / "runs")
    pdf = tmp_path / "deed.pdf"
    pdf.write_bytes(b"%PDF")
    monkeypatch.setattr(
        "metesparser.pdf_processor.PDFProcessor",
        lambda provider=None, **_kwargs: _processor(EASEMENT_AFTER),
    )
    output = tmp_path / "deed.csv"
    cli.extract_command(str(pdf), output=str(output))
    assert output.exists() and not (tmp_path / "deed_verified.csv").exists()
    loaded = CSVBuilder.csv_to_calls(str(output))
    assert loaded and all(_marked(c) for c in loaded)
    assert not ClosureChecker.verify_closure(loaded).is_fully_verified()
    with pytest.raises(SystemExit) as exit_info:
        cli.verify_command(str(output))
    assert exit_info.value.code == 1


def test_cli_extract_still_exports_a_single_description(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "RUNS_DIR", tmp_path / "runs")
    pdf = tmp_path / "deed.pdf"
    pdf.write_bytes(b"%PDF")
    monkeypatch.setattr(
        "metesparser.pdf_processor.PDFProcessor",
        lambda provider=None, **_kwargs: _processor(PROBES["plain"]),
    )
    cli.extract_command(str(pdf), output=str(tmp_path / "deed.csv"))
    assert (tmp_path / "deed_verified.csv").exists()
    cli.verify_command(str(tmp_path / "deed_verified.csv"))


def test_cli_marks_a_hand_built_description_whose_roles_need_review(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from types import SimpleNamespace

    from metesparser import models as monolith

    _, tracts = extract_calls(EASEMENT_AFTER, strict=True)
    legacy = [monolith.Tract.model_validate(t.model_dump()) for t in tracts]
    legal = monolith.LegalDescription(calls=legacy[0].calls, tracts=legacy)
    assert not any(_marked(c) for c in legal.calls)
    monkeypatch.setattr(cli, "RUNS_DIR", tmp_path / "runs")
    pdf = tmp_path / "deed.pdf"
    pdf.write_bytes(b"%PDF")
    monkeypatch.setattr(
        "metesparser.pdf_processor.PDFProcessor",
        lambda provider=None, **_kwargs: SimpleNamespace(process_deed_pdf=lambda _p: legal),
    )
    output = tmp_path / "deed.csv"
    cli.extract_command(str(pdf), output=str(output))
    assert not (tmp_path / "deed_verified.csv").exists()
    assert all(_marked(c) for c in CSVBuilder.csv_to_calls(str(output)))
