"""PR #60 round 31: omitted-tract skips and undetermined misclosure status."""

from __future__ import annotations

import mp_models
import pytest
from mp_export import export_verified_csv as package_export
from mp_parse import extract_calls as package_extract
from mp_verify import verify_closure as package_verify

from metesparser import models as monolith_models
from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker
from metesparser.csv_builder import CSVBuilder

TWO_SQUARES = (
    "Tract 1: BEGINNING at a point; THENCE due North 100.00 feet; THENCE due East 100.00 feet; "
    "THENCE due South 100.00 feet; THENCE due West 100.00 feet to the point of beginning. "
    "Tract 2: BEGINNING at a point; THENCE due North 50.00 feet; THENCE due East 50.00 feet; "
    "THENCE due South 50.00 feet; THENCE due West 50.00 feet to the point of beginning."
)

IMPLS = {
    "package": (
        mp_models,
        lambda t: package_extract(t, strict=False)[0],
        package_verify,
        package_export,
    ),
    "monolith": (
        monolith_models,
        lambda t: CallExtractor.extract_calls(t, strict=False),
        ClosureChecker.verify_closure,
        CSVBuilder.export_verified_csv,
    ),
}


@pytest.fixture(params=sorted(IMPLS))
def impl(request):
    return IMPLS[request.param]


def _setup(impl, label):
    models, extract, verify, export = impl
    calls = extract(TWO_SQUARES)
    tracts = [
        models.Tract(label="Tract 1", tract_type="main", calls=calls[:4]),
        models.Tract(label="Tract 2", tract_type="main", calls=calls[4:]),
    ]
    skip = models.SkippedCourse(
        course=5,
        source_course=5,
        source_excerpt="x",
        error_type="E",
        error="e",
        tract_label=label,
    )
    return models, calls, tracts, skip, verify, export


def test_skip_of_omitted_known_tract_does_not_block_exported_tract(impl, tmp_path):
    models, calls, tracts, skip, verify, export = _setup(impl, "Tract 2")
    flags = [r.is_fully_verified() for r in verify(calls, tracts=tracts, skipped_courses=[skip])]
    assert flags == [True, False]
    r1 = verify(tracts[0].calls)
    desc = models.LegalDescription(calls=calls, tracts=tracts)
    paths = export(
        calls,
        r1,
        str(tmp_path / "d.csv"),
        legal_desc=desc,
        tract_results=[(tracts[0], r1)],
        skipped_courses=[skip],
    )
    assert paths


def test_skip_of_unknown_tract_still_blocks(impl, tmp_path):
    models, calls, tracts, skip, verify, export = _setup(impl, "Tract 9")
    r1 = verify(tracts[0].calls)
    desc = models.LegalDescription(calls=calls, tracts=tracts)
    with pytest.raises(ValueError, match="fresh verification"):
        export(
            calls,
            r1,
            str(tmp_path / "d.csv"),
            legal_desc=desc,
            tract_results=[(tracts[0], r1)],
            skipped_courses=[skip],
        )


def test_skip_of_exported_tract_still_blocks(impl, tmp_path):
    models, calls, tracts, skip, verify, export = _setup(impl, "Tract 1")
    r1 = verify(tracts[0].calls)
    desc = models.LegalDescription(calls=calls, tracts=tracts)
    with pytest.raises(ValueError, match="fresh verification"):
        export(
            calls,
            r1,
            str(tmp_path / "d.csv"),
            legal_desc=desc,
            tract_results=[(tracts[0], r1)],
            skipped_courses=[skip],
        )


def test_undetermined_misclosure_is_not_graded_or_verified(impl):
    models = impl[0]
    result = models.ClosureResult(
        closure_passed=True,
        angle_check_passed=True,
        curve_consistency_passed=True,
        misclosure_available=False,
        misclosure_ft=0.0,
        misclosure_x_ft=0.0,
        misclosure_y_ft=0.0,
        area_sq_ft=0.0,
        area_acres=0.0,
        perimeter_ft=0.0,
        confidence_score=1.0,
    )
    assert result.get_closure_status() == "NOT DETERMINED"
    assert not result.is_fully_verified()
