"""Round 8: radial-clause phrasings, single bearing normalization, glued word bearings.

1. Every realistic radial/radius-point/center phrasing is recognised: its bearing is
   recorded as ``radial_bearing`` and never used as the course tangent.
2. Bearing forms in the course text are normalized once per call (not once per
   reference-clause pass, per verbatim candidate and again for the audit).
3. Word bearings whose cardinal is glued to the last marker (``North 45°30'East``)
   are handled by the marked-DMS expansion, so the separate word-symbol pass is gone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import mp_models
import pytest
from mp_parse import calls as package_calls
from mp_parse.calls import extract_single_call as package_single_call

from metesparser import call_extractor as monolith_calls
from metesparser import models as monolith_models
from metesparser.call_extractor import CallExtractor
from tests.fixtures.package_parser import extract_calls as package_extract_calls

CLOSING = "; THENCE due South 50 feet; THENCE due West 50 feet to the point of beginning."


def _via_calls(extract):
    return lambda text: extract(text + CLOSING, strict=True)[0]


def _via_single(extract):
    return lambda text: extract(text, 1)


ENTRY_POINTS = {
    "package-calls": _via_calls(package_extract_calls),
    "monolith-calls": _via_calls(CallExtractor.extract_calls),
    "package-single": _via_single(package_single_call),
    "monolith-single": _via_single(CallExtractor.extract_single_call),
}


@pytest.fixture(params=sorted(ENTRY_POINTS))
def parse(request):
    return ENTRY_POINTS[request.param]


# --- 2. Normalization runs once per call --------------------------------------

STRAIGHT = (
    "BEGINNING at a point; THENCE N 10° W 100.00 feet to a point; "
    "THENCE North 80 degrees 00' East 100.00 feet to a point; "
    "THENCE S 10-00 E 100.00 feet to a point; "
    "THENCE S 80° W 100.00 feet to the point of beginning."
)
IMPLEMENTATIONS = {
    "package": (package_calls, package_extract_calls, mp_models),
    "monolith": (monolith_calls, CallExtractor.extract_calls, monolith_models),
}


def _audit_ctx(models):
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


@pytest.mark.parametrize("impl", sorted(IMPLEMENTATIONS))
def test_bearing_normalization_runs_once_per_call(monkeypatch, impl):
    module, extract, models = IMPLEMENTATIONS[impl]
    original = module._normalize_bearing_forms
    seen: list[str] = []

    def spy(text: str) -> str:
        seen.append(text)
        return original(text)

    monkeypatch.setattr(module, "_normalize_bearing_forms", spy)
    audit = _audit_ctx(models)
    calls = extract(STRAIGHT, audit_context=audit)

    assert len(calls) == 4
    assert [round(c.bearing_azimuth_deg_from_north, 6) for c in calls] == [350, 80, 170, 260]
    assert [c.direction_text for c in calls] == [
        "N 10° W",
        "North 80 degrees 00' East",
        "S 10-00 E",
        "S 80° W",
    ]
    assert len(audit.call_audits) == 4
    assert len(seen) == len(calls)


@pytest.mark.parametrize("impl", sorted(IMPLEMENTATIONS))
def test_segmented_normalization_matches_separate_normalization(impl):
    module = IMPLEMENTATIONS[impl][0]
    segments = [
        "thence Lot N 12-3 E, N 45-30 E 100 feet",
        "N 45-30 E",
        "North 34 degrees 02' 00\" West",
        "N 45.3015 E",
        "S 10d 15m W",
    ]
    assert module._normalize_bearing_segments(segments) == [
        module._normalize_bearing_forms(s) for s in segments
    ]


# --- 3. Glued word bearings -----------------------------------------------------


@dataclass(frozen=True)
class Glued:
    text: str
    expanded: str
    azimuth: float


GLUED = [
    Glued("North 45°East", "N 45° E", 45.0),
    Glued("North 45°30'East", "N 45°30' E", 45.5),
    Glued("South 10° 15' 20\"West", "S 10°15'20\" W", 190 + 15 / 60 + 20 / 3600),
    Glued("south 10°west", "S 10° W", 190.0),
]


@pytest.mark.parametrize("module", [package_calls, monolith_calls], ids=["package", "monolith"])
@pytest.mark.parametrize("case", GLUED, ids=[g.text for g in GLUED])
def test_marked_dms_expands_glued_cardinal_word(module, case):
    assert module._expand_marked_dms(case.text) == case.expanded


@pytest.mark.parametrize("case", GLUED, ids=[g.text for g in GLUED])
def test_glued_word_bearing_parses_with_verbatim_text(parse, case):
    call = parse(f"thence {case.text} 100.00 feet to a point")
    assert call is not None
    assert call.bearing_azimuth_deg_from_north == pytest.approx(case.azimuth)
    assert call.direction_text == case.text


@pytest.mark.parametrize("text", ["North 45°Eighty", "N 45°30'Westerly", "N 45 dEasterly"], ids=str)
def test_marked_dms_does_not_eat_other_words(text):
    for module in (package_calls, monolith_calls):
        assert module._expand_marked_dms(text) == text


def test_word_symbol_pass_is_removed():
    for module in (package_calls, monolith_calls):
        assert not hasattr(module, "_abbreviate_word_bearing")
        assert not hasattr(module, "_WORD_SYMBOL_BEARING")
