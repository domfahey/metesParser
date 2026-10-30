"""Broad parser corpus and probes for monolith/package differential tests.

The corpus is every sample deed text (LlamaParse markdown, ground-truth legal
description and normalized text) plus every call-like string literal in the
parser regression tables. A probe runs one text through every call-extraction and
text-parsing entry point and returns plain data, so two implementations can be
compared field by field.
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DEEDS = ROOT / "sample_deeds"
CLOSING = "; THENCE due South 50 feet; THENCE due West 50 feet to the point of beginning."

_TABLE_GLOBS = (
    "tests/unit/test_pr60_*_tdd.py",
    "tests/unit/test_bugs_*_tdd.py",
    "tests/unit/test_open_bugs_tdd.py",
    "tests/unit/test_call_extractor.py",
    "tests/unit/test_text_parser.py",
    "tests/unit/test_phase*.py",
    "tests/fixtures/sample_deeds.py",
    "packages/mp-parse/tests/test_*.py",
)
_CALL_LIKE = re.compile(
    r"\d.*\b(?:north|south|east|west|[NSEW]|thence|curve|curving|chord|radius|feet|ft|"
    r"poles?|rods?|chains?|beginning|except|tract)\b|"
    r"\b(?:north|south|east|west|[NSEW]|thence|curve|chord|radius)\b.*\d",
    re.IGNORECASE | re.DOTALL,
)

TEXT_PARSER_PROBES = (
    "normalize_legal_description",
    "normalize_dms_symbols",
    "merge_line_wrapped_calls",
    "standardize_cardinal_directions",
    "clean_ocr_errors",
    "expand_assessor_abbreviations",
    "expand_abbreviations",
    "split_into_calls",
    "split_exception_clauses",
    "extract_distance",
    "extract_along_to_fields",
    "detect_meander",
    "extract_pob",
    "extract_poc",
    "extract_poc_and_pob",
    "is_closure_to_pob",
    "extract_area_statement",
    "extract_plss_metadata",
    "extract_basis_of_bearing",
    "extract_surveyor_certification",
    "extract_prior_conveyance",
    "extract_deed_clauses",
    "extract_subdivision_reference",
    "infer_distance_unit",
    "extract_witness_trees",
    "extract_coordinate_system",
)
CALL_PROBES = ("extract_direction", "extract_curve_info", "extract_distance_alternate")


def keyed_sample_texts() -> Iterator[tuple[str, str]]:
    """Yield ``(key, text)`` for every sample deed text.

    Keys are ``<file>.md`` for LlamaParse markdown and ``<deed>::legal`` or
    ``<deed>::normalized`` for the ground-truth legal description and normalized text.
    """
    for path in sorted(SAMPLE_DEEDS.glob("*.md")):
        yield path.name, path.read_text(encoding="utf-8")
    for path in sorted(SAMPLE_DEEDS.glob("*.ground_truth.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        deed = path.name.removesuffix(".ground_truth.json")
        for key, tag in (
            ("expected_legal_description", "legal"),
            ("expected_normalized_text", "normalized"),
        ):
            value = data.get(key)
            if isinstance(value, str) and value:
                yield f"{deed}::{tag}", value


def _sample_texts() -> Iterator[str]:
    for _key, text in keyed_sample_texts():
        yield text


def _table_texts() -> Iterator[str]:
    for pattern in _TABLE_GLOBS:
        for path in sorted(ROOT.glob(pattern)):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and 6 <= len(node.value) <= 20_000
                    and _CALL_LIKE.search(node.value)
                ):
                    yield node.value


@cache
def corpus() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return ``(sample deed texts, call texts)``, each de-duplicated in order."""
    samples = tuple(dict.fromkeys(_sample_texts()))
    calls = tuple(text for text in dict.fromkeys(_table_texts()) if text not in samples)
    return samples, calls


def _plain(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return _plain(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, float):
        return repr(value)
    return value


def _attempt(fn: Callable[[], Any]) -> Any:
    try:
        return {"ok": _plain(fn())}
    except Exception as exc:  # noqa: BLE001 - the error is part of the compared output
        return {"error": type(exc).__name__, "message": str(exc)}


def _audit_context(models: ModuleType) -> Any:
    return models.AuditContext(
        run_metadata=models.RunMetadata(
            parser_version="t",
            llm_provider="t",
            llm_model="t",
            prompt_hash="t",
            timestamp_utc=datetime(2026, 1, 1, tzinfo=UTC),
            source_pdf="t.pdf",
            cache_enabled=False,
        )
    )


def probe(
    text: str,
    *,
    models: ModuleType,
    extract_flat: Callable[..., Any],
    extract_single: Callable[..., Any],
    call_fns: dict[str, Callable[..., Any]],
    text_fns: dict[str, Callable[..., Any]],
    enrich: Callable[[list[Any]], list[Any]],
    mark_tie_in: Callable[[list[Any], str | None], list[Any]],
    call_text: bool = True,
) -> dict[str, Any]:
    """Run ``text`` through every entry point of one implementation.

    For a call text (``call_text``) the per-call entry points also run, and the text
    is extracted again followed by two closing courses, which turns a lone table
    literal into a multi-course description. Whole deeds run the description-level
    entry points only.
    """
    out: dict[str, Any] = {}
    sources = [("", text)] + ([("+closing", text + CLOSING)] if call_text else [])
    for suffix, source in sources:
        out[f"strict{suffix}"] = _attempt(lambda s=source: extract_flat(s, strict=True))
        audit = _audit_context(models)
        skips: list[Any] = []

        def lenient(s: str = source, a: Any = audit, k: list[Any] = skips) -> Any:
            calls = extract_flat(s, strict=False, audit_context=a, skipped_courses=k)
            return {
                "calls": calls,
                "call_audits": a.call_audits,
                "audit_skips": a.skipped_courses,
                "skips": k,
                "enriched": enrich(calls),
                "tie_in": mark_tie_in(calls, "a point of commencement"),
            }

        out[f"lenient{suffix}"] = _attempt(lenient)
    if call_text:
        out["single"] = _attempt(lambda: extract_single(text, 1))
        out["single_poles"] = _attempt(lambda: extract_single(text, 3, "poles"))
    for name, fn in (call_fns | text_fns if call_text else text_fns).items():
        out[name] = _attempt(lambda f=fn: f(text))
    return out
