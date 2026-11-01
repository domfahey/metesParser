"""PR #60 round 23: the verified-export gate re-verifies with every recorded skip."""

from __future__ import annotations

from datetime import UTC, datetime

import mp_models
import pytest
from mp_export import export_verified_csv as package_export
from mp_parse import extract_calls as package_extract
from mp_verify import verify_closure as package_verify

from metesparser import models as monolith_models
from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker
from metesparser.csv_builder import CSVBuilder

SKIPPED = "N 45° E along the line of lands of Smith to a pin"
TRACT_DEED = (
    "Tract 1: BEGINNING at a point; THENCE due North 100.00 feet; THENCE "
    + SKIPPED
    + "; THENCE due East 100.00 feet; THENCE due South 100.00 feet; "
    "THENCE due West 100.00 feet to the point of beginning. "
    "Tract 2: BEGINNING at a point; THENCE due North 50.00 feet; THENCE due East 50.00 feet; "
    "THENCE due South 50.00 feet; THENCE due West 50.00 feet to the point of beginning."
)
SINGLE_DEED = TRACT_DEED.split("Tract 2")[0].replace("Tract 1: ", "")
CLEAN = (
    "BEGINNING at a point; THENCE due North 100.00 feet; THENCE due East 100.00 feet; "
    "THENCE due South 100.00 feet; THENCE due West 100.00 feet to the point of beginning."
)


def _pkg_extract(text, **kw):
    return package_extract(text, **kw)[0]


IMPLS = {
    "package": (mp_models, _pkg_extract, package_verify, package_export),
    "monolith": (
        monolith_models,
        CallExtractor.extract_calls,
        ClosureChecker.verify_closure,
        CSVBuilder.export_verified_csv,
    ),
}


@pytest.fixture(params=sorted(IMPLS))
def impl(request):
    return IMPLS[request.param]


def _ctx(models):
    return models.AuditContext(
        run_metadata=models.RunMetadata(
            parser_version="test",
            llm_provider="test",
            llm_model="test",
            prompt_hash="test",
            timestamp_utc=datetime(2026, 10, 30, tzinfo=UTC),
            source_pdf="test.pdf",
            cache_enabled=False,
        )
    )


def _written(tmp_path):
    return sorted(p.name for p in tmp_path.glob("*_verified*.csv"))


def test_single_tract_audit_context_skip_blocks_export(impl, tmp_path):
    models, extract, verify, export = impl
    ctx = _ctx(models)
    calls = extract(SINGLE_DEED, strict=False, audit_context=ctx)
    assert ctx.skipped_courses
    # Verification computed without the skips looks clean; the exporter must not trust it.
    with pytest.raises(ValueError, match="fresh verification"):
        export(calls, verify(calls), str(tmp_path / "single.csv"), audit_context=ctx)
    assert _written(tmp_path) == []


def test_explicit_skipped_list_blocks_export(impl, tmp_path):
    models, extract, verify, export = impl
    ctx = _ctx(models)
    calls = extract(SINGLE_DEED, strict=False, audit_context=ctx)
    with pytest.raises(ValueError, match="fresh verification"):
        export(
            calls,
            verify(calls),
            str(tmp_path / "single.csv"),
            skipped_courses=list(ctx.skipped_courses),
        )
    assert _written(tmp_path) == []


def test_multi_tract_skipped_course_blocks_export(impl, tmp_path):
    models, extract, verify, export = impl
    sink: list = []
    calls = extract(TRACT_DEED, strict=False, skipped_courses=sink)
    tracts = [
        models.Tract(
            label="Tract 1",
            tract_type="main",
            role_basis="heading",
            calls=calls[:4],
            skipped_courses=sink,
        ),
        models.Tract(label="Tract 2", tract_type="main", role_basis="heading", calls=calls[4:]),
    ]
    # Stale results ignorant of the skip must not export tract 1.
    results = [(t, verify(t.calls)) for t in tracts]
    with pytest.raises(ValueError, match="fresh verification"):
        export(calls, results[0][1], str(tmp_path / "deed.csv"), tract_results=results)
    assert _written(tmp_path) == []


def test_multi_tract_audit_context_skip_blocks_export(impl, tmp_path):
    models, extract, verify, export = impl
    ctx = _ctx(models)
    calls = extract(TRACT_DEED, strict=False, audit_context=ctx)
    tracts = [
        models.Tract(label="Tract 1", tract_type="main", role_basis="heading", calls=calls[:4]),
        models.Tract(label="Tract 2", tract_type="main", role_basis="heading", calls=calls[4:]),
    ]
    results = [(t, verify(t.calls)) for t in tracts]
    with pytest.raises(ValueError, match="fresh verification"):
        export(
            calls,
            results[0][1],
            str(tmp_path / "deed.csv"),
            tract_results=results,
            audit_context=ctx,
        )
    assert _written(tmp_path) == []


def test_clean_deed_still_exports(impl, tmp_path):
    models, extract, verify, export = impl
    ctx = _ctx(models)
    calls = extract(CLEAN, strict=False, audit_context=ctx)
    assert not ctx.skipped_courses
    paths = export(calls, verify(calls), str(tmp_path / "clean.csv"), audit_context=ctx)
    assert [p.name for p in paths] == ["clean_verified.csv"]
