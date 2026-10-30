"""Round 16: the extract_distance audit step records the value's actual source."""

from __future__ import annotations

from datetime import UTC, datetime

import mp_models
import pytest

from metesparser import models as monolith_models
from metesparser.call_extractor import CallExtractor
from tests.fixtures.package_parser import extract_calls as package_extract_calls

CLOSING = "; THENCE due South 50 feet; THENCE due West 50 feet to the point of beginning."
IMPLS = {
    "package": (package_extract_calls, mp_models),
    "monolith": (CallExtractor.extract_calls, monolith_models),
}


def _ctx(models):
    return models.AuditContext(
        run_metadata=models.RunMetadata(
            parser_version="t",
            llm_provider="t",
            llm_model="t",
            prompt_hash="t",
            timestamp_utc=datetime.now(UTC),
            source_pdf="t.pdf",
            cache_enabled=False,
        )
    )


def _first(impl, text):
    extract, models = IMPLS[impl]
    ctx = _ctx(models)
    calls = extract(text + CLOSING, audit_context=ctx, strict=True)
    step = next(t for t in ctx.call_audits[0].transformations if t.step == "extract_distance")
    return calls[0], step


@pytest.mark.parametrize("impl", sorted(IMPLS))
def test_chord_only_audit_input_is_the_stated_chord(impl):
    call, step = _first(
        impl,
        "THENCE along a curve to the left having a radius of 100.00 feet, "
        "the chord of which bears N 45° E 51.76 feet",
    )
    assert call.is_chord_only_curve()
    assert step.input == "51.76 feet"
    assert step.output == str(call.distance_ft) == "51.76"
    assert step.rule == "chord-only curve: distance is the stated chord length"


@pytest.mark.parametrize("impl", sorted(IMPLS))
def test_radius_delta_audit_inputs_are_radius_and_delta(impl):
    call, step = _first(
        impl,
        "THENCE along a curve to the right having a radius of 100.00 feet "
        "and a delta of 14°21'36\", to a point",
    )
    assert "radius 100.0 feet" in step.input
    assert f"delta {call.delta_deg}" in step.input
    assert step.output == str(call.distance_ft)
    assert step.rule is not None and "computed from the stated radius and delta" in step.rule


@pytest.mark.parametrize("impl", sorted(IMPLS))
def test_radius_arc_audit_input_is_the_arc_length(impl):
    call, step = _first(
        impl,
        "THENCE along a curve to the right having a radius of 100.00 feet "
        "and an arc length of 25.00 feet, to a point",
    )
    assert call.distance_ft == 25.0
    assert step.input == "25.0 feet"
    assert step.output == "25.0"


@pytest.mark.parametrize("impl", sorted(IMPLS))
def test_straight_course_audit_unchanged(impl):
    call, step = _first(impl, "THENCE N 45° E 51.76 feet to an iron pin")
    assert step.input == "51.76 feet"
    assert step.output == "51.76"
    assert step.rule is None
