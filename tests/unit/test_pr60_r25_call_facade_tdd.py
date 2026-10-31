"""PR #60 round 25: the monolith call extractor and text parser are package facades.

``CallExtractor``, ``MonumentClassifier`` and ``TextParser`` delegate to
``mp_parse`` instead of duplicating it. A broad differential runs every sample
deed text and every call-like literal of the parser regression tables through
both implementations and compares the results field by field; spy tests prove
the delegation, including audit and skipped-course recording.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import mp_models
import mp_parse.calls as package_calls
import mp_parse.metadata as package_metadata
import mp_parse.monuments as package_monuments
import mp_parse.normalizer as package_normalizer
import pytest
from structlog.testing import capture_logs

from metesparser import models as monolith_models
from metesparser import text_parser as monolith_text_parser
from metesparser.call_extractor import CallExtractor, MonumentClassifier
from metesparser.text_parser import TextParser
from tests.fixtures.parser_corpus import CALL_PROBES, TEXT_PARSER_PROBES, corpus, probe

# --- Differential: monolith output == package output -------------------------


def _package_flat(text: str, distance_unit: str = "feet", **kwargs: Any) -> Any:
    """The package extraction's flat calls, as the monolith's default (round 58: the one
    split extraction, marked when roles need review; no second, unsplit parse)."""
    return package_calls.extract_calls(text, distance_unit, **kwargs)[0]


def _extras(module: Any, text_fns: Any) -> dict[str, Any]:
    return {
        "is_indefinite_bearing": lambda t: text_fns.is_indefinite_call(t, True),
        "is_indefinite_no_bearing": lambda t: text_fns.is_indefinite_call(t, False),
        "course_lists": lambda t: repr(module.analyze_course_lists(t)),
        "count_mismatches": module.course_list_count_mismatches,
        "inline_enumerators": module.break_inline_course_enumerators,
    }


class _PackageText:
    """Package text functions under the monolith ``TextParser`` names."""

    def __getattr__(self, name: str) -> Any:
        for module in (package_normalizer, package_metadata):
            if hasattr(module, name):
                return getattr(module, name)
        raise AttributeError(name)


def _monolith_probe(text: str, call_text: bool) -> dict[str, Any]:
    return probe(
        text,
        models=monolith_models,
        extract_flat=CallExtractor.extract_calls,
        extract_single=CallExtractor.extract_single_call,
        call_fns={name: getattr(CallExtractor, name) for name in CALL_PROBES}
        | {
            "monument": MonumentClassifier.classify_monument,
            "monument_status": MonumentClassifier.classify_monument_status,
        },
        text_fns={name: getattr(TextParser, name) for name in TEXT_PARSER_PROBES}
        | _extras(monolith_text_parser, TextParser),
        enrich=CallExtractor.enrich_calls_with_azimuths,
        mark_tie_in=CallExtractor.mark_tie_in_calls,
        call_text=call_text,
    )


def _package_probe(text: str, call_text: bool) -> dict[str, Any]:
    package_text = _PackageText()
    return probe(
        text,
        models=mp_models,
        extract_flat=_package_flat,
        extract_single=package_calls.extract_single_call,
        call_fns={name: getattr(package_calls, name) for name in CALL_PROBES}
        | {
            "monument": package_monuments.classify_monument,
            "monument_status": package_monuments.classify_monument_status,
        },
        text_fns={name: getattr(package_text, name) for name in TEXT_PARSER_PROBES}
        | _extras(package_metadata, package_text),
        enrich=package_calls.enrich_calls_with_azimuths,
        mark_tie_in=package_calls.mark_tie_in_calls,
        call_text=call_text,
    )


def _mismatches(texts: tuple[str, ...], *, call_text: bool) -> list[tuple[str, str]]:
    found = []
    with capture_logs():  # thousands of expected skip warnings; keep the run quiet
        for text in texts:
            monolith = _monolith_probe(text, call_text)
            package = _package_probe(text, call_text)
            found.extend((key, text[:80]) for key in monolith if monolith[key] != package[key])
    return found


def test_corpus_is_broad():
    samples, calls = corpus()
    assert len(samples) >= 150
    assert len(calls) >= 800


def test_sample_deeds_match_package_field_by_field():
    samples, _ = corpus()
    assert _mismatches(samples, call_text=False) == []


def test_regression_table_calls_match_package_field_by_field():
    _, calls = corpus()
    assert _mismatches(calls, call_text=True) == []


# --- Delegation spies ----------------------------------------------------------

SQUARE = (
    "BEGINNING at a point; THENCE N 0° E 100.00 feet; THENCE N 90° E 100.00 feet; "
    "THENCE S 0° W 100.00 feet; THENCE S 90° W 100.00 feet to the point of beginning."
)
WITH_BAD_COURSE = (
    "BEGINNING at a point; THENCE N 0° E 100.00 feet; THENCE along a curve to the left; "
    "THENCE S 0° W 100.00 feet to the point of beginning."
)


def _audit_ctx() -> monolith_models.AuditContext:
    m = monolith_models
    return m.AuditContext(
        run_metadata=m.RunMetadata(
            parser_version="t",
            llm_provider="t",
            llm_model="t",
            prompt_hash="t",
            timestamp_utc=datetime.now(UTC),
            source_pdf="t.pdf",
            cache_enabled=False,
        )
    )


def _spy(monkeypatch, module: Any, name: str) -> list[tuple[Any, ...]]:
    seen: list[tuple[Any, ...]] = []
    real = getattr(module, name)

    def spy(*args, **kwargs):
        seen.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(module, name, spy)
    return seen


def test_extract_calls_delegates_and_returns_monolith_models(monkeypatch):
    seen = _spy(monkeypatch, package_calls, "_extract_call")
    ctx = _audit_ctx()
    calls = CallExtractor.extract_calls(SQUARE, audit_context=ctx)

    assert len(seen) == 4
    assert [type(c) for c in calls] == [monolith_models.DeedCall] * 4
    assert [type(a) for a in ctx.call_audits] == [monolith_models.CallAudit] * 4
    assert [a.course for a in ctx.call_audits] == [1, 2, 3, 4]


def test_skipped_courses_are_recorded_once_as_shared_monolith_records(monkeypatch):
    seen = _spy(monkeypatch, package_calls, "_record_skipped_course")
    ctx = _audit_ctx()
    skips: list[monolith_models.SkippedCourse] = []
    calls = CallExtractor.extract_calls(
        WITH_BAD_COURSE, strict=False, audit_context=ctx, skipped_courses=skips
    )

    assert len(seen) == 1
    assert [c.course for c in calls] == [1, 3]
    assert [type(s) for s in skips] == [monolith_models.SkippedCourse]
    assert skips[0].course == 2 and skips[0].tract_label is None
    # Both destinations hold the same record, as when the monolith recorded it itself.
    assert ctx.skipped_courses[0] is skips[0]


def test_strict_failure_keeps_records_made_before_it():
    ctx = _audit_ctx()
    with pytest.raises(ValueError, match="Malformed course 2"):
        CallExtractor.extract_calls(WITH_BAD_COURSE, audit_context=ctx)
    assert [a.course for a in ctx.call_audits] == [1]


def test_unrecorded_skip_raises_as_strict():
    with pytest.raises(ValueError, match="skipped course not recorded"):
        CallExtractor.extract_calls(WITH_BAD_COURSE, strict=False)


def test_single_call_and_helpers_delegate(monkeypatch):
    single = _spy(monkeypatch, package_calls, "_extract_call")
    curve = _spy(monkeypatch, package_calls, "extract_curve_info")
    direction = _spy(monkeypatch, package_calls, "extract_direction")
    monument = _spy(monkeypatch, package_monuments, "classify_monument")

    call = CallExtractor.extract_single_call("THENCE N 10° E 50 feet to an iron pin", 7)
    CallExtractor.extract_curve_info("curve to the right with a radius of 50 feet")
    CallExtractor.extract_direction("N 10° E 50 feet")
    MonumentClassifier.classify_monument("an iron pin")

    assert isinstance(call, monolith_models.DeedCall) and call.course == 7
    assert single and curve and direction and monument


def test_unchanged_calls_are_returned_as_is():
    calls = CallExtractor.extract_calls(SQUARE.removesuffix(" to the point of beginning."))
    assert CallExtractor.mark_tie_in_calls(calls, None) is calls
    assert CallExtractor.mark_tie_in_calls(calls, "a stone") is calls
    enriched = CallExtractor.enrich_calls_with_azimuths(calls)
    assert all(a is b for a, b in zip(enriched, calls, strict=True))


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("normalize_legal_description", ("THENCE N 10 DEG E 50 FT",)),
        ("split_into_calls", ("THENCE N 10° E 50 feet; THENCE S 10° W 50 feet",)),
        ("split_exception_clauses", ("THENCE N 10° E 50 feet EXCEPT THENCE S 1° W 2 feet",)),
        ("extract_distance", ("N 10° E 50 feet",)),
        ("extract_area_statement", ("containing 1.5 acres",)),
    ],
)
def test_text_parser_delegates(monkeypatch, name, args):
    module = package_normalizer if hasattr(package_normalizer, name) else package_metadata
    seen = _spy(monkeypatch, module, name)
    getattr(TextParser, name)(*args)
    assert seen == [args]


def test_text_parser_models_are_monolith_models():
    clauses = TextParser.extract_deed_clauses("SUBJECT TO easements of record.")
    reference = TextParser.extract_subdivision_reference("Lot 5, Block 3 of Oak Hills subdivision")
    assert clauses and all(isinstance(c, monolith_models.DeedClause) for c in clauses)
    assert isinstance(reference, monolith_models.SubdivisionReference)


def test_cardinal_only_patterns_are_the_package_patterns():
    from metesparser import call_extractor

    assert call_extractor._CARDINAL_ONLY_PATTERN is package_calls._CARDINAL_ONLY_PATTERN
    assert TextParser.CARDINAL_ONLY_PATTERN is package_metadata.CARDINAL_ONLY_PATTERN


POB_TIE = (
    "Beginning at a point distant North 2 degrees 56 minutes 20 seconds West 955.85 feet "
    "along the East line of Section and South 87 degrees 03 minutes West 1782.0 feet from "
    "the East 1/4 corner of Section 16, and proceeding thence South 87 degrees 03 minutes "
    "40 seconds West 138.0 feet; thence North 2 degrees 56 minutes 20 seconds West 324.0 "
    "feet; thence North 87 degrees 03 minutes 40 seconds East 138.0 feet; thence South 2 "
    "degrees 56 minutes 20 seconds East 324.0 feet to the Point of Beginning."
)


def test_monolith_does_not_parse_pob_tie_as_a_course():
    calls = CallExtractor.extract_calls(POB_TIE)
    assert [c.distance_ft for c in calls] == [138.0, 324.0, 138.0, 324.0]


def test_package_extract_calls_does_not_parse_pob_tie_as_a_course():
    calls, _ = package_calls.extract_calls(POB_TIE)
    assert [c.distance_ft for c in calls] == [138.0, 324.0, 138.0, 324.0]


def test_monolith_extract_single_call_raises_for_unusable_course_and_none_for_beginning() -> None:
    import pytest

    from metesparser.call_extractor import CallExtractor

    with pytest.raises(ValueError, match="No usable course"):
        CallExtractor.extract_single_call("thence to a point 100 feet", 1)
    assert CallExtractor.extract_single_call("BEGINNING at a point", 1) is None


def test_monolith_extract_single_call_rejects_curve_with_following_course() -> None:
    text = (
        "THENCE along a curve to the right having a radius of 100 feet, "
        "an arc length of 50 feet; THENCE N 20° E 10 feet"
    )
    with pytest.raises(package_calls.MultipleCoursesError):
        CallExtractor.extract_single_call(text, 1)
