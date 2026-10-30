"""PR #60 round 11: consumers of unavailable closure measurements never read the 0.0 sentinel."""

from __future__ import annotations

import json
from pathlib import Path

import mp_export
import mp_models
import mp_verify
import mp_verify.dashboard as pkg_dashboard
import pytest
from mp_models.dashboard import DashboardBundle
from mp_verify.confidence import calculate_confidence_score as pkg_confidence
from mp_verify.dashboard import calculate_dashboard

from metesparser import csv_builder
from metesparser import models as mono_models
from metesparser.closure_checker import ClosureChecker
from metesparser.review_packet import build_closure_section
from metesparser.run_registry import RunManifest, RunResults, format_comparison_table

FIXTURES = Path(__file__).resolve().parents[2] / "packages/mp-review/tests/fixtures"

IMPLS = {
    "package": (mp_models, mp_verify.verify_closure, mp_export.export_verified_csv),
    "monolith": (
        mono_models,
        ClosureChecker.verify_closure,
        csv_builder.CSVBuilder.export_verified_csv,
    ),
}
SCORES = {
    "package": pkg_confidence,
    "monolith": ClosureChecker.calculate_confidence_score,
}
UNAVAILABLE = {
    "misclosure_ft": 0.0,
    "misclosure_x_ft": 0.0,
    "misclosure_y_ft": 0.0,
    "misclosure_available": False,
    "closure_passed": False,
}


def _square(m, broken=False):
    azimuths = (0.0, 90.0, 180.0, None if broken else 270.0)
    return [
        m.DeedCall(
            course=i + 1,
            direction_text="recorded",
            bearing_azimuth_deg_from_north=a,
            distance_ft=100.0,
        )
        for i, a in enumerate(azimuths)
    ]


@pytest.mark.parametrize("impl", IMPLS)
def test_confidence_does_not_credit_unavailable_misclosure(impl):
    m, verify, _ = IMPLS[impl]
    calls = _square(m)
    ok = verify(calls)
    unavailable = ok.model_copy(update=UNAVAILABLE)
    worst = ok.model_copy(
        update={**UNAVAILABLE, "misclosure_ft": 1e6, "misclosure_available": True}
    )
    score = SCORES[impl]
    assert score(unavailable, calls) == pytest.approx(score(worst, calls))
    # Even an inconsistent "passed" flag cannot earn closure credit without a misclosure.
    passed = unavailable.model_copy(update={"closure_passed": True})
    assert score(passed, calls) == pytest.approx(score(worst, calls))


@pytest.mark.parametrize("impl", IMPLS)
def test_available_confidence_unchanged(impl):
    m, verify, _ = IMPLS[impl]
    result = verify(_square(m))
    assert result.misclosure_available
    assert SCORES[impl](result, _square(m)) == pytest.approx(result.confidence_score)


@pytest.mark.parametrize("impl", IMPLS)
def test_csv_rejection_messages_do_not_print_sentinel(impl, tmp_path):
    m, verify, export = IMPLS[impl]
    calls = _square(m)
    bad = verify(calls).model_copy(update=UNAVAILABLE)
    with pytest.raises(ValueError) as caught:
        export(calls, bad, str(tmp_path / "a.csv"))
    assert "0.0000" not in str(caught.value)
    assert "not determined" in str(caught.value)

    # Fresh verification of the exported calls is what fails here.
    broken = _square(m, broken=True)
    assert not verify(broken).misclosure_available
    with pytest.raises(ValueError) as caught:
        export(broken, verify(calls), str(tmp_path / "b.csv"))
    assert "0.0000" not in str(caught.value)
    assert "not determined" in str(caught.value)


@pytest.mark.parametrize("impl", IMPLS)
def test_tract_summary_does_not_print_sentinel(impl, tmp_path):
    m, verify, export = IMPLS[impl]
    good_calls, bad_calls = _square(m), _square(m, broken=True)
    tracts = [
        (m.Tract(label="Good", tract_type="main", calls=good_calls), verify(good_calls)),
        (m.Tract(label="Bad", tract_type="main", calls=bad_calls), verify(bad_calls)),
    ]
    assert not tracts[1][1].misclosure_available
    export(good_calls, tracts[0][1], str(tmp_path / "d.csv"), tract_results=tracts)
    text = (tmp_path / "d_verified.verification.txt").read_text()
    assert "Bad: misclosure not determined;" in text
    assert "0.0000" not in text.split("Not verified")[1]


def test_dashboard_leaves_unavailable_misclosure_undetermined(monkeypatch):
    original = pkg_dashboard.verify_closure
    monkeypatch.setattr(
        pkg_dashboard,
        "verify_closure",
        lambda *a, **k: original(*a, **k).model_copy(update=UNAVAILABLE),
    )
    raw = json.loads((FIXTURES / "dashboard-absolute.json").read_text())
    result = calculate_dashboard(DashboardBundle.model_validate(raw)).calculations[0]
    assert result.misclosure_ft is None
    assert result.misclosure_x_ft is None and result.misclosure_y_ft is None
    assert result.precision_denominator is None


def test_run_registry_marks_unavailable_misclosure():
    bad = ClosureChecker.verify_closure(_square(mono_models, broken=True))
    assert not bad.misclosure_available
    results = RunResults.from_closure(bad, call_count=4)
    assert results.misclosure_available is False
    manifest = RunManifest(
        run_id="r",
        timestamp_utc="2026-01-01T00:00:00Z",
        source_pdf="x.pdf",
        llm_provider="p",
        llm_model="m",
        cache_enabled=False,
        results=results,
        parser_version="0",
    )
    table = format_comparison_table([manifest])
    assert "0.0000" not in table
    assert "n/d" in table
    good = RunResults.from_closure(ClosureChecker.verify_closure(_square(mono_models)), 4)
    assert good.misclosure_available is True
    assert good.misclosure_ft == pytest.approx(0.0)


def test_review_packet_reports_undetermined_misclosure():
    gt = {"expected_closure": {"misclosure_ft": 0.0, "misclosure_available": False}}
    assert "<th>Misclosure (ft)</th><td>not determined</td>" in build_closure_section(gt)
    available = {"expected_closure": {"misclosure_ft": 0.0}}
    assert "<th>Misclosure (ft)</th><td>0.0</td>" in build_closure_section(available)
