"""PR #60 round 41: record calls through the monolith facade.

The monolith ``CallExtractor`` delegates to ``mp_parse``. Every case of the
package record-call corpus (``packages/mp-parse/tests/test_record_call_roles.py``)
reads exactly as in the package: course values, complete notes, or the same
fail-closed error. ``enrich_calls_with_azimuths`` keeps every note but the
incomplete-bearing one.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from metesparser.call_extractor import CallExtractor
from metesparser.models import DeedCall, SkippedCourse

ROOT = Path(__file__).resolve().parents[2]


def _corpus() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "record_call_corpus", ROOT / "packages" / "mp-parse" / "tests" / "test_record_call_roles.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CORPUS = _corpus()


@pytest.mark.parametrize("name", CORPUS.COURSES)
def test_monolith_single_call(name: str) -> None:
    case = CORPUS.CASES[name]
    CORPUS.assert_course(CallExtractor.extract_single_call(case.fragment, 1), case)


@pytest.mark.parametrize("name", CORPUS.COURSES)
def test_monolith_description(name: str) -> None:
    case = CORPUS.CASES[name]
    calls = CallExtractor.extract_calls(CORPUS.POB + case.fragment + CORPUS.CLOSING)
    assert len(calls) == 2
    CORPUS.assert_course(calls[0], case)


@pytest.mark.parametrize("name", CORPUS.FAILS)
def test_monolith_fails_closed(name: str) -> None:
    case = CORPUS.CASES[name]
    with pytest.raises(case.error, match=case.match):
        CallExtractor.extract_single_call(case.fragment, 1)
    skipped: list[SkippedCourse] = []
    calls = CallExtractor.extract_calls(
        CORPUS.POB + case.fragment + CORPUS.CLOSING, strict=False, skipped_courses=skipped
    )
    assert [s.course for s in skipped] == [1]
    assert case.match in skipped[0].error
    assert [c.course for c in calls] == [2]


def test_monolith_enrichment_keeps_record_notes() -> None:
    notes = f"{CORPUS.CARDINAL}; {CORPUS.RECORD_WITH_SEMICOLON}"
    call = DeedCall(course=1, direction_text="due North", distance_ft=100.0, notes=notes)
    (enriched,) = CallExtractor.enrich_calls_with_azimuths([call])
    assert enriched.bearing_azimuth_deg_from_north == pytest.approx(0.0)
    assert enriched.notes == CORPUS.RECORD_WITH_SEMICOLON
