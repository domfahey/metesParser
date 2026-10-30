"""Normalization is idempotent and the public extractor normalizes exactly once."""

from __future__ import annotations

import pytest
from mp_parse import calls as package_calls
from mp_parse.normalizer import normalize_legal_description

from tests.fixtures.parser_corpus import corpus

SAMPLES, CALL_TEXTS = corpus()

POB_TIE = (
    "Beginning at a point distant North 2 degrees 56 minutes 20 seconds West 955.85 feet "
    "along the East line of Section and South 87 degrees 03 minutes West 1782.0 feet from "
    "the East 1/4 corner of Section 16, and proceeding thence South 87 degrees 03 minutes "
    "40 seconds West 138.0 feet; thence North 2 degrees 56 minutes 20 seconds West 324.0 "
    "feet; thence North 87 degrees 03 minutes 40 seconds East 138.0 feet; thence South 2 "
    "degrees 56 minutes 20 seconds East 324.0 feet to the Point of Beginning."
)


def test_corpus_is_nonempty():
    assert len(SAMPLES) > 10 and len(CALL_TEXTS) > 100


@pytest.mark.parametrize("group", ["samples", "calls"])
def test_normalize_is_idempotent_over_corpus(group):
    texts = SAMPLES if group == "samples" else CALL_TEXTS
    bad = [
        t[:80]
        for t in texts
        if normalize_legal_description(normalize_legal_description(t))
        != normalize_legal_description(t)
    ]
    assert bad == []


def test_pob_tie_and_is_never_rewritten_to_thence():
    once = normalize_legal_description(POB_TIE)
    assert "Section and S 87°03' W" in once
    assert normalize_legal_description(once) == once


def test_and_between_courses_still_becomes_thence_in_one_pass():
    text = "thence N 10°00' E 50.00 feet and S 20°00' W 60.00 feet"
    assert "feet thence S 20°00' W" in normalize_legal_description(text)


def test_public_extract_calls_does_not_parse_pob_tie_as_a_course():
    calls, _ = package_calls.extract_calls(POB_TIE)
    assert [c.distance_ft for c in calls] == [138.0, 324.0, 138.0, 324.0]


def test_public_extract_calls_normalizes_exactly_once(monkeypatch):
    seen: list[str] = []
    real = package_calls.normalize_legal_description
    monkeypatch.setattr(
        package_calls, "normalize_legal_description", lambda t: seen.append(t) or real(t)
    )
    package_calls.extract_calls(POB_TIE)
    assert len(seen) == 1
