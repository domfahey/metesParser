"""High-signal behavioral tests for advanced mp_parse.calls code paths.

Covers:
- Malformed curve dimensions (negative / scientific-notation elements & lengths)
- Curve geometry variants (spirals without length, tangent+chord, chord > 2R,
  radial-line courses, radius conflicts, DMS degree of curvature, compound curves,
  ambiguous curve lengths, out-of-range delta, compound units on curves)
- Audit trail coverage (computed arc, chord-only, standalone inch, generic
  monument, cardinal-only chord curve, cardinal-chord conflict, meander, spiral)
- Tie-line detection & closure inference (restated POB, COMMENCING closure
  inference with AuditContext, straight-misclosure guards)
- Initial-course prefixes, closing-sentence validation, non-strict skip logging,
  Pydantic validation cleanup, fragment splitting, adjoiner/out-of-range guards
- Invalid stated area propagation (single-tract, per-tract, uncovered gaps,
  dropped empty tracts) and token-level gap alignment across short & long deeds
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest
import structlog.testing
from mp_models import (
    INVALID_STATED_AREA_NOTE_PREFIX,
    SEPARATE_EASEMENT_NOTE_PREFIX,
    AuditContext,
    DeedCall,
    RunMetadata,
    SkippedCourse,
    TractType,
)
from mp_parse.calls import (
    _INFERRED_TIE_REASON,
    ARC_COMPUTED_NOTE,
    ARC_COMPUTED_RULE,
    LENGTH_NOT_DETERMINED_NOTE,
    LENGTH_NOT_DETERMINED_RULE,
    _align_segment_tokens,
    _local_sequence_blocks,
    _notes_by_segment,
    _SourceMap,
    _uncovered_text_gaps,
    _verbatim_note,
    enrich_calls_with_azimuths,
    extract_calls,
    extract_curve_info,
    extract_direction,
    extract_distance_alternate,
    extract_single_call,
)


def _make_audit_context() -> AuditContext:
    return AuditContext(
        run_metadata=RunMetadata(
            parser_version="test",
            llm_provider="none",
            llm_model="none",
            prompt_hash="0" * 64,
            timestamp_utc=datetime(2026, 1, 1, tzinfo=UTC),
            source_pdf="test.pdf",
            cache_enabled=False,
        )
    )


# ---------------------------------------------------------------------------
# 1. Malformed curve elements (fail-closed)
# ---------------------------------------------------------------------------


class TestMalformedCurveElements:
    """Negative or scientific-notation curve dimensions fail closed."""

    @pytest.mark.parametrize(
        ("text", "expected_fragment"),
        [
            (
                "thence along a curve to the right, radius of -100 feet, arc length of 50 feet",
                "radius_ft",
            ),
            (
                "thence along a curve to the right, radius of 100 feet, arc length of -50 feet",
                "arc_length_ft",
            ),
            (
                "thence along a curve to the right, radius of 100 feet, chord length of 1e2 feet",
                "chord_length_ft",
            ),
            (
                "thence along a curve to the right, radius of 100 feet, tangent length of -20 feet, arc length of 50 feet",
                "tangent_length_ft",
            ),
            (
                "thence along a curve to the right, radius of 100 feet, delta angle of -30 degrees",
                "delta_deg",
            ),
            (
                "thence along a curve to the right, degree of curvature of -5 degrees, delta of 20 degrees",
                "degree_of_curvature",
            ),
            (
                "thence along a curve to the right, radius of 100 feet, 1.5e1 degrees",
                "delta_deg",
            ),
            (
                "thence along a curve to the right, radius of 100 feet, -50 feet to a pin",
                "Malformed curve length",
            ),
            (
                "thence along a curve to the right, radius of 100 feet, 1e2 feet to a pin",
                "scientific-notation curve length",
            ),
            (
                "thence along a curve to the right, radius of 100 feet, 1e2' to a pin",
                "scientific-notation curve length",
            ),
        ],
    )
    def test_malformed_curve_elements_raise(self, text: str, expected_fragment: str) -> None:
        with pytest.raises(ValueError, match=expected_fragment):
            extract_single_call(text, 1)


# ---------------------------------------------------------------------------
# 2. Advanced curve geometry, radial lines, conflicts, spirals & audit trail
# ---------------------------------------------------------------------------


class TestAdvancedCurveAndAuditBehaviors:
    """Surveying edge cases for curves, radial lines, directions, and audit records."""

    def test_straight_course_running_along_radial_line_keeps_radial_bearing(self) -> None:
        call = extract_single_call(
            "thence along a radial line bearing N 45°00' E 100.00 feet to an iron pin", 1
        )
        assert call is not None
        assert call.bearing_quadrant == "N 45°00' E"
        assert call.bearing_azimuth_deg_from_north == pytest.approx(45.0)
        assert call.distance_ft == pytest.approx(100.0)

    def test_curve_compound_course_length_and_bearing_token_skip(self) -> None:
        # Compound course length (1 chain and 21 links = 66 + 13.86 = 79.86 ft) on a curve
        call = extract_single_call(
            "thence along a curve to the right, radius of 200 feet, 1 chain and 21 links to a pin",
            1,
        )
        assert call is not None
        assert call.arc_length_ft == pytest.approx(79.86, abs=0.01)

        # Length-like foot mark inside a bearing span is ignored when extracting curve dimensions
        curve = extract_curve_info(
            "thence N 45° 30' E 10° along a curve to the right, radius of 100 feet, arc length of 50 feet"
        )
        assert curve["direction"] == "right"
        assert curve["radius_ft"] == pytest.approx(100.0)
        assert curve["arc_length_ft"] == pytest.approx(50.0)
        assert "chord_length_ft" not in curve

    def test_delta_arc_only_curve_rejects_delta_over_360(self) -> None:
        with pytest.raises(ValueError, match="delta angle out of range"):
            extract_single_call(
                "thence along a curve to the right, delta of 400 degrees, arc length of 100 feet", 1
            )

    def test_spiral_without_length_keeps_none_distance_and_audits_flag(self) -> None:
        audit = _make_audit_context()
        calls, _ = extract_calls(
            "BEGINNING at a pin; thence along a spiral curve to the right, "
            "radius of 500 feet, delta of 10 degrees to a point.",
            audit_context=audit,
        )
        assert len(calls) == 1
        assert calls[0].curve_type == "spiral"
        assert calls[0].distance_ft is None
        assert LENGTH_NOT_DETERMINED_NOTE in (calls[0].notes or "")
        assert len(audit.call_audits) == 1
        assert "distance_not_determined" in audit.call_audits[0].flags
        dist_tx = [t for t in audit.call_audits[0].transformations if t.step == "extract_distance"]
        assert dist_tx[0].rule == LENGTH_NOT_DETERMINED_RULE
        assert dist_tx[0].output == "not determined"

    def test_tangent_and_chord_curve_without_arc_notes_positioning(self) -> None:
        call = extract_single_call(
            "thence N 10°00' E along a curve to the right, radius of 200 feet, "
            "chord bears N 25°00' E 100.00 feet to a pin",
            1,
        )
        assert call is not None
        assert call.bearing_azimuth_deg_from_north == pytest.approx(10.0)
        assert call.distance_ft == pytest.approx(100.0)
        assert "curve positioned by stated tangent and chord; arc not stated" in (call.notes or "")

    def test_chord_exceeding_diameter_flagged_in_notes(self) -> None:
        call = extract_single_call(
            "thence along a curve to the right, radius of 50 feet, "
            "chord bears N 45°00' E 120.00 feet to a pin",
            1,
        )
        assert call is not None
        assert "chord length exceeds twice the radius" in (call.notes or "")

    def test_meander_curve_combines_meander_and_tangent_notes_and_audits_flag(self) -> None:
        audit = _make_audit_context()
        calls, _ = extract_calls(
            "BEGINNING at a pin; thence along the creek along a curve to the right, "
            "radius of 200 feet, delta of 30 degrees, chord bears N 45°00' E 103.53 feet to a point.",
            audit_context=audit,
        )
        assert len(calls) == 1
        assert calls[0].is_meander is True
        assert "meander / approximate" in (calls[0].notes or "")
        assert "tangent bearing not stated" in (calls[0].notes or "")
        assert "meander" in audit.call_audits[0].flags

    def test_radius_conflict_and_radial_bearing_without_length(self) -> None:
        conflict_call = extract_single_call(
            "thence along a curve to the right, radius of 500 feet, "
            "radius point bears N 10°00' E 400 feet, arc length of 100 feet to a pin",
            1,
        )
        assert conflict_call is not None
        assert conflict_call.radius_ft == pytest.approx(500.0)
        assert "radius conflict" in (conflict_call.notes or "")

        no_radial_len = extract_curve_info(
            "curve to the right, radius of 500 feet, radius point bears N 10°00' E, arc length of 100 feet"
        )
        assert no_radial_len["radius_ft"] == pytest.approx(500.0)
        assert no_radial_len["radial_bearing"] == "N 10°00' E"
        assert "radius_conflict_note" not in no_radial_len

    def test_degree_of_curvature_dms_converts_to_radius(self) -> None:
        info = extract_curve_info(
            "curve to the right, degree of curvature of 5° 30' 15\", delta of 20 degrees"
        )
        expected_deg = 5.0 + 30.0 / 60.0 + 15.0 / 3600.0
        expected_radius = 5729.577951308232 / expected_deg
        assert info["radius_ft"] == pytest.approx(expected_radius, rel=1e-4)

    def test_compound_curve_type_extracted_in_single_call(self) -> None:
        call = extract_single_call(
            "thence along a compound curve to the right, radius of 300 feet, "
            "delta of 20 degrees, arc length of 104.72 feet to a pin",
            1,
        )
        assert call is not None
        assert call.curve_type == "compound"

    def test_audit_trail_for_computed_arc_chord_only_inches_monument_and_conflicts(self) -> None:
        audit = _make_audit_context()
        text = (
            "BEGINNING at a stone; "
            "THENCE N 45°00' E along a curve to the right, radius of 100 feet, delta of 90 degrees to a monument; "
            "THENCE along a curve to the right, radius of 200 feet, chord bears N 30°00' E 100 feet to a point; "
            "THENCE N 45°00' E 6 inches to a pin; "
            "THENCE northerly along a curve to the right, radius of 100 feet, delta of 90 degrees, "
            "chord bears N 45°00' E 141.42 feet to a pin; "
            "THENCE southerly along a curve to the right, radius of 200 feet, "
            "chord bears N 10°00' E 100 feet to the point of beginning."
        )
        calls, _ = extract_calls(text, audit_context=audit)
        assert len(calls) == 5
        assert len(audit.call_audits) == 5

        # Call 1: arc computed from R & delta + generic "monument" rule
        assert ARC_COMPUTED_NOTE in (calls[0].notes or "")
        assert any(
            t.step == "extract_distance" and t.rule == ARC_COMPUTED_RULE
            for t in audit.call_audits[0].transformations
        )
        assert any(
            t.step == "classify_monument" and t.output == "other" and t.rule == r"\bmonument\b"
            for t in audit.call_audits[0].transformations
        )

        # Call 2: chord-only curve distance audit
        assert any(
            t.step == "extract_distance" and "chord-only curve" in (t.rule or "")
            for t in audit.call_audits[1].transformations
        )

        # Call 3: standalone inches fallback in _distance_audit_source
        assert calls[2].distance_ft == pytest.approx(0.5)
        assert any(
            t.step == "extract_distance" and "6 inches" in t.input
            for t in audit.call_audits[2].transformations
        )

        # Call 4: cardinal-only chord-positioned curve
        assert "cardinal_only_direction" in audit.call_audits[3].flags

        # Call 5: cardinal direction conflicts with chord bearing
        assert "cardinal_chord_conflict" in audit.call_audits[4].flags

    def test_direction_packed_dms_compound_compass_and_distance_alternate_non_feet(self) -> None:
        # Valid packed DMS with single-digit seconds pads with leading zero
        assert extract_direction("N 45.3005° E") == "N 45°30'05\" E"
        # Invalid packed DMS raises in strict mode, returns verbatim in non-strict mode
        with pytest.raises(ValueError, match=r"Invalid packed DMS: minutes=99 \(must be 0-59\)"):
            extract_direction("N 45.9999° E", strict=True)
        assert extract_direction("N 45.9999° E", strict=False) == "N 45.9999° E"
        # 32-point compound compass point
        assert extract_direction("thence North by East 100 feet") == "north by east"
        # Non-feet unit returns 0.0 from extract_distance_alternate
        assert extract_distance_alternate("10 poles along the fence") == 0.0

    def test_enrich_calls_with_azimuths_preserves_unparseable_quadrant(self) -> None:
        bad_call = DeedCall(
            course=1,
            direction_text="N 95° E",
            bearing_quadrant="N 95° E",
            bearing_azimuth_deg_from_north=None,
            distance_ft=100.0,
        )
        result = enrich_calls_with_azimuths([bad_call])
        assert result[0].bearing_azimuth_deg_from_north is None
        assert result[0].bearing_quadrant == "N 95° E"


# ---------------------------------------------------------------------------
# 3. Tie-line detection, restated POB, and closure-based tie inference
# ---------------------------------------------------------------------------


class TestTieLineDetectionAndInference:
    """Restated POB and closure-inferred tie courses with audit recording."""

    def test_restated_pob_marks_leading_courses_as_tie_lines(self) -> None:
        text = (
            "BEGINNING at a stone corner; "
            "THENCE N 0°00' E 50.00 feet to an iron pin, which last mentioned point is the place of beginning; "
            "THENCE N 90°00' E 100.00 feet; "
            "THENCE S 0°00' E 100.00 feet; "
            "THENCE S 90°00' W 100.00 feet; "
            "THENCE N 0°00' W 100.00 feet to the place of beginning."
        )
        calls, _ = extract_calls(text)
        assert len(calls) == 5
        assert [c.is_tie_in for c in calls] == [True, False, False, False, False]

    def test_inferred_tie_from_closure_marks_course_and_updates_audit_context(self) -> None:
        audit = _make_audit_context()
        text = (
            "COMMENCING at the southwest corner of Lot 1; "
            "THENCE N 0°00' E 50.00 feet to a stake; "
            "THENCE N 90°00' E 100.00 feet to a pin; "
            "THENCE S 0°00' E 100.00 feet to a pin; "
            "THENCE S 90°00' W 100.00 feet to a pin; "
            "THENCE N 0°00' W 100.00 feet to the point of beginning."
        )
        calls, _ = extract_calls(text, audit_context=audit)
        assert len(calls) == 5
        assert [c.is_tie_in for c in calls] == [True, False, False, False, False]
        assert _INFERRED_TIE_REASON in (calls[0].notes or "")
        assert "tie_inferred_from_closure" in audit.call_audits[0].flags
        assert any(
            d.field == "is_tie_in" and d.value == "true" for d in audit.call_audits[0].decisions
        )

    def test_straight_misclosure_and_inferred_tie_guards(self) -> None:
        # Cardinal-only (missing azimuth) course in remainder prevents closure-based tie inference
        cardinal_deed = (
            "COMMENCING at a stone; "
            "THENCE N 0°00' E 50.00 feet to a stake; "
            "THENCE northerly 100.00 feet; "
            "THENCE S 0°00' E 100.00 feet; "
            "THENCE S 90°00' W 100.00 feet; "
            "THENCE N 0°00' W 100.00 feet to the point of beginning."
        )
        cardinal_calls, _ = extract_calls(cardinal_deed)
        assert len(cardinal_calls) == 5
        assert [c.is_tie_in for c in cardinal_calls] == [False, False, False, False, False]

        # Earlier course mentioning "to the point of beginning" suppresses closure inference
        early_pob_deed = (
            "COMMENCING from a stone; "
            "THENCE N 0°00' E 50.00 feet to the point of beginning; "
            "THENCE N 90°00' E 100.00 feet; "
            "THENCE S 0°00' E 100.00 feet; "
            "THENCE S 90°00' W 100.00 feet; "
            "THENCE N 0°00' W 100.00 feet to the point of beginning."
        )
        early_pob_calls, _ = extract_calls(early_pob_deed)
        assert len(early_pob_calls) == 5
        assert [c.is_tie_in for c in early_pob_calls] == [False, False, False, False, False]


# ---------------------------------------------------------------------------
# 4. Prefixes, validation cleanup, skip recording, fragment splitting & guards
# ---------------------------------------------------------------------------


class TestParsingGuardsAndValidationCleanup:
    """Validation error cleanup, skip recording, debug logging, and fragment guards."""

    def test_long_malformed_course_warning_truncates_preview(self) -> None:
        long_bad_course = "THENCE " + "along the northerly line of Oak Street " * 6 + "to a pin"
        deed = (
            "BEGINNING at a pin; "
            "THENCE N 45°00' E 100 feet to a pin; "
            f"{long_bad_course}; "
            "THENCE S 45°00' W 100 feet to the point of beginning."
        )
        skips: list[SkippedCourse] = []
        with structlog.testing.capture_logs() as logs:
            calls, _ = extract_calls(deed, strict=False, skipped_courses=skips)
        assert len(calls) == 2
        assert len(skips) == 1
        assert skips[0].course == 2
        skip_logs = [entry for entry in logs if entry.get("event") == "Skipping malformed call"]
        assert len(skip_logs) == 1
        preview = skip_logs[0]["call_preview"]
        assert len(preview) == 120
        assert preview.endswith("...")

    def test_clean_validation_error_in_single_and_full_extraction(self) -> None:
        # Radius of 0 feet triggers Pydantic ValidationError on DeedCall(radius_ft=0.0)
        bad_curve = (
            "thence along a curve to the right, radius of 0 feet, arc length of 100 feet to a pin"
        )
        with pytest.raises(ValueError, match="radius_ft must be non-zero"):
            extract_single_call(bad_curve, 1)

        with pytest.raises(ValueError, match="Malformed course 1"):
            extract_calls(f"BEGINNING at a pin; {bad_curve}.", strict=True)

    def test_nonstrict_skip_requires_sink_and_logs_in_debug_mode(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        deed = (
            "BEGINNING at a pin; "
            "THENCE N 45°00' E 100 feet to a pin; "
            "THENCE along a curve to the right, radius of -50 feet, arc length of 20 feet to a pin; "
            "THENCE S 45°00' W 100 feet to the point of beginning."
        )
        # Non-strict with neither audit_context nor skipped_courses fails closed
        with pytest.raises(ValueError, match="skipped course not recorded"):
            extract_calls(deed, strict=False)

        # Non-strict with audit_context records skip and logs full call_text under DEBUG
        audit = _make_audit_context()
        with (
            caplog.at_level(logging.DEBUG, logger="mp_parse.calls"),
            structlog.testing.capture_logs() as debug_logs,
        ):
            calls, _ = extract_calls(deed, strict=False, audit_context=audit)
            with pytest.raises(ValueError, match="No usable course"):
                extract_single_call("100.00 feet to a point", 1)
        assert len(calls) == 2
        assert len(audit.skipped_courses) == 1
        assert audit.skipped_courses[0].course == 2
        skip_ev = next(e for e in debug_logs if e.get("event") == "Skipping malformed call")
        assert (
            skip_ev["call_text"]
            == "along a curve to the right, radius of -50 feet, arc length of 20 feet to a pin"
        )
        rej_ev = next(
            e for e in debug_logs if e.get("event") == "Rejecting bearingless non-curve call"
        )
        assert rej_ev["call_text"] == "100.00 feet to a point"

        # Under WARNING level, full call_text is omitted from structured logs
        audit_warn = _make_audit_context()
        with (
            caplog.at_level(logging.WARNING, logger="mp_parse.calls"),
            structlog.testing.capture_logs() as warn_logs,
        ):
            extract_calls(deed, strict=False, audit_context=audit_warn)
            with pytest.raises(ValueError, match="No usable course"):
                extract_single_call("100.00 feet to a point", 1)
        warn_skip = next(e for e in warn_logs if e.get("event") == "Skipping malformed call")
        assert "call_text" not in warn_skip
        warn_rej = next(
            e for e in warn_logs if e.get("event") == "Rejecting bearingless non-curve call"
        )
        assert "call_text" not in warn_rej

    def test_initial_course_prefix_and_packed_dms_edges(self) -> None:
        # Packed DMS course before first THENCE is preserved as Course 1
        packed_calls, _ = extract_calls(
            "N 45.3000° E 100 feet to a pin; THENCE S 45°00' E 100 feet to the point of beginning."
        )
        assert len(packed_calls) == 2
        assert packed_calls[0].bearing_quadrant == "N 45°30' E"
        assert packed_calls[0].distance_ft == pytest.approx(100.0)

        # Curve course before first THENCE is preserved as Course 1
        curve_calls, _ = extract_calls(
            "along a curve to the right, radius of 100 feet, delta of 30 degrees, "
            "arc length of 52.36 feet; THENCE S 45°00' E 100 feet to the point of beginning."
        )
        assert len(curve_calls) == 2
        assert curve_calls[0].curve_dir == "right"
        assert curve_calls[0].radius_ft == pytest.approx(100.0)

        # Leading text with invalid packed DMS is not misread as an initial course prefix
        preamble_calls, _ = extract_calls(
            "along Oak Street N 45.9999° E 100 feet; THENCE S 45°00' E 100 feet to a pin."
        )
        assert len(preamble_calls) == 1
        assert preamble_calls[0].bearing_quadrant == "S 45°00' E"

        # Invalid packed DMS in a THENCE course fails closed
        with pytest.raises(ValueError, match="Malformed course 1: 'N45.9999° E 100 feet to a pin'"):
            extract_calls("BEGINNING at a pin; THENCE N45.9999° E 100 feet to a pin.")

    def test_unsupported_compound_course_distance_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported component in compound course distance"):
            extract_single_call("thence N 45°00' E 10 chains and 5 widgets to a pin", 1)

    def test_multi_course_fragment_splitting_adjoiner_and_record_call_guards(self) -> None:
        # Leading passing call before two courses cannot be split off and fails closed
        with pytest.raises(ValueError, match="fragment contains multiple courses"):
            extract_calls(
                "BEGINNING at a pin; THENCE passing a pipe at 30 feet; "
                "N 45°00' E 100 feet; S 45°00' E 100 feet."
            )

        # Leading descriptive text before two courses prepends to the first split course
        split_calls, _ = extract_calls(
            "BEGINNING at a pin; THENCE along Oak Street; N 45°00' E 100 feet; S 45°00' E 100 feet."
        )
        assert len(split_calls) == 2
        assert split_calls[0].bearing_quadrant == "N 45°00' E"
        assert split_calls[0].along == "Oak Street"
        assert split_calls[1].bearing_quadrant == "S 45°00' E"

        # Adjoiner wording strips course bearing while retaining record-call notes verbatim
        adjoiner_call = extract_single_call(
            "thence along Oak Street (a N 45°00' E public road) N 45°00' E 100.00 feet "
            "(deed N 44°00' E 99.00 feet record) to a pin",
            1,
        )
        assert adjoiner_call.bearing_quadrant == "N 45°00' E"
        assert adjoiner_call.distance_ft == pytest.approx(100.0)
        assert adjoiner_call.along == "Oak Street"
        assert (
            adjoiner_call.notes
            == "record call: (a N 45°00' E public road); record call: (deed N 44°00' E 99.00 feet record)"
        )

        # Non-bearing tokens and >2 angle parts do not false-positive as out-of-range bearings
        non_oor = extract_single_call(
            "thence N 45°00' E 100 feet along N 45° foo bar E and N 45° 10' 20\" 30\" E to a pin",
            1,
        )
        assert non_oor.bearing_quadrant == "N 45°00' E"
        assert non_oor.distance_ft == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# 5. Invalid stated area propagation & uncovered text gap alignment
# ---------------------------------------------------------------------------


class TestInvalidStatedAreaAndGapAlignment:
    """Invalid stated areas fail closed across single-tract, multi-tract, and gaps."""

    def test_single_tract_invalid_stated_area_blocks_all_calls(self) -> None:
        deed = (
            "BEGINNING at a pin; "
            "THENCE N 0°00' E 100.00 feet; "
            "THENCE N 90°00' E 100.00 feet; "
            "THENCE S 0°00' E 100.00 feet; "
            "THENCE S 90°00' W 100.00 feet to the point of beginning. "
            "Containing 0 acres."
        )
        calls, tracts = extract_calls(deed)
        assert tracts == []
        assert len(calls) == 4
        assert all(INVALID_STATED_AREA_NOTE_PREFIX in (c.notes or "") for c in calls)
        assert extract_calls("Containing 0 acres.") == ([], [])

    def test_multi_tract_invalid_area_in_tract_in_gap_and_in_dropped_tract(self) -> None:
        # 1) Invalid stated area inside Tract 2
        in_tract = (
            "TRACT 1: BEGINNING at a pin; THENCE N 0°00' E 100 feet to the point of beginning. "
            "TRACT 2: BEGINNING at a stone; THENCE S 0°00' E 50 feet to the point of beginning. "
            "Containing 0 acres."
        )
        _calls, tracts = extract_calls(in_tract)
        assert len(tracts) == 2
        assert all(INVALID_STATED_AREA_NOTE_PREFIX not in (c.notes or "") for c in tracts[0].calls)
        assert all(INVALID_STATED_AREA_NOTE_PREFIX in (c.notes or "") for c in tracts[1].calls)

        # 2) Invalid stated area in preamble gap before Tract 1 propagates to all tracts
        in_gap = (
            "Schedule A premises containing 0 acres. "
            "TRACT 1: BEGINNING at a pin; THENCE N 0°00' E 100 feet to the point of beginning. "
            "TRACT 2: BEGINNING at a stone; THENCE S 0°00' E 50 feet to the point of beginning."
        )
        calls_gap, tracts_gap = extract_calls(in_gap)
        assert len(tracts_gap) == 2
        assert all(INVALID_STATED_AREA_NOTE_PREFIX in (c.notes or "") for c in calls_gap)
        assert all(
            INVALID_STATED_AREA_NOTE_PREFIX in (c.notes or "") for t in tracts_gap for c in t.calls
        )

        # 3) Invalid stated area inside a dropped empty tract (non-strict) propagates to remaining tracts
        dropped_empty = (
            "TRACT 1: Lot 12 of Sample Plat containing 0 acres. "
            "TRACT 2: BEGINNING at a stone; THENCE S 0°00' E 50 feet to the point of beginning."
        )
        skips: list[SkippedCourse] = []
        calls_drop, tracts_drop = extract_calls(dropped_empty, strict=False, skipped_courses=skips)
        assert len(tracts_drop) == 1
        assert all(INVALID_STATED_AREA_NOTE_PREFIX in (c.notes or "") for c in calls_drop)

    def test_uncovered_text_gaps_short_spliced_and_boundary_shifting(self) -> None:
        # Empty working / empty segments fallback
        assert _uncovered_text_gaps("Containing 0 acres.", [("", "Tract 1", TractType.MAIN)]) == [
            "Containing 0 acres."
        ]

        # Out-of-order exact substring match (working.find fallback)
        working_ooo = "FIRST PART. GAP HERE. SECOND PART."
        gaps_ooo = _uncovered_text_gaps(
            working_ooo,
            [
                ("SECOND PART.", "Tract 2", TractType.MAIN),
                ("FIRST PART.", "Tract 1", TractType.MAIN),
            ],
        )
        assert gaps_ooo == ["GAP HERE."]

        # Spliced interior gap with identical boundary tokens ("Containing 0 acres." before
        # "Containing 10 acres.") shifts left so the gap lands cleanly on the sentence boundary.
        working_shift_left = (
            "BEGINNING at a pin; THENCE N 0° E 100 feet. Containing 0 acres. Containing 10 acres."
        )
        spliced_left = "BEGINNING at a pin; THENCE N 0° E 100 feet. Containing 10 acres."
        gaps_left = _uncovered_text_gaps(
            working_shift_left, [(spliced_left, "Tract 1", TractType.MAIN)]
        )
        assert gaps_left == ["Containing 0 acres."]

        # Right-shift case: SequenceMatcher aligns Block 2 [".", "b1", "b2", "b3"] first,
        # placing the gap at [".", "extra", "text"]; right-shifting across "." moves the gap
        # cleanly onto ["extra", "text", "."] at the sentence boundary.
        work_words = ["a1", "a2", ".", "extra", "text", ".", "b1", "b2", "b3"]
        seg_words = ["a1", "a2", ".", "b1", "b2", "b3"]
        intervals = _align_segment_tokens(work_words, seg_words, 0)
        assert intervals == [(0, 3), (6, 9)]

        # Single-token segment alignment (allow_single=True) & empty edge
        assert _align_segment_tokens(["hello", "world"], ["world"], 0) == [(1, 2)]
        assert _align_segment_tokens(["hello"], [], 0) == []
        assert _local_sequence_blocks(["a"], 1, 1, ["a"], 0, 1) == []

    def test_align_segment_tokens_long_document_all_anchor_paths(self) -> None:
        # Build a >256-token document to exercise k=4 anchor indexing, repeated anchors,
        # leading/interior/trailing local alignment, far-jump lookahead, and block merging.
        base = [f"w{i}" for i in range(340)]
        # Place an anchor ["rep", "a", "b", "c"] three times:
        # 1) before tok_start (index 2)
        # 2) early after tok_start with a short 5-token run (index 20..24)
        # 3) slightly later with a 6-token run (index 40..45) -> tests best_run tracking
        anchor = ["rep", "a", "b", "c"]
        base[2:6] = anchor
        base[20:25] = [*anchor, "x1"]
        base[40:46] = [*anchor, "x1", "x2"]

        # Place a short 4-token anchor far away (> 256 tokens ahead) at index 320,
        # while the next segment tokens match nearby at index 60..69 -> triggers lookahead!
        far_anchor = ["far", "k1", "k2", "k3"]
        base[320:324] = far_anchor
        nearby = ["near", "n1", "n2", "n3", "n4", "n5", "n6", "n7"]
        base[60:68] = nearby

        # Tiny segments (< 4 tokens) on a >256-token document:
        # 1) Exact 2-token match
        assert _align_segment_tokens(base, ["w100", "w101"], 0) == [(100, 102)]
        # 2) 3-token segment where only 2 tokens match (fallback sub-slice)
        assert _align_segment_tokens(base, ["zz", "w100", "w101"], 0) == [(100, 102)]
        # 3) Completely unmatched tiny segment -> []
        assert _align_segment_tokens(base, ["no1", "no2", "no3"], 0) == []

        # Long segment exercising:
        # - leading unmatched token + 2-token local lead match ("w14", "w15")
        # - repeated anchor picking the 6-token best_run at index 40..46
        # - interior 2-token local match ("w50", "w51") between blocks
        # - far-jump anchor ("far", "k1", "k2", "k3") overridden by nearby lookahead ("near", ...)
        # - direct cursor continuation (base[68:76]) merging adjacently with nearby block
        # - unmatched anchor past end of positions (anchor after index 76 -> p_idx >= len(positions))
        # - trailing 2-token local match ("w80", "w81")
        seg = [
            "lead_miss",
            "w14",
            "w15",
            "gap_miss",
            *anchor,
            "x1",
            "x2",
            "mid_miss",
            "w50",
            "w51",
            "mid_miss2",
            *far_anchor,
            *nearby,
            *base[68:76],
            *anchor,  # occurs only before a_cursor=76 -> hits p_idx >= len(positions)
            "tail_miss",
            "w80",
            "w81",
        ]
        intervals = _align_segment_tokens(base, seg, tok_start=10)
        assert (14, 16) in intervals
        assert (40, 46) in intervals
        assert (50, 52) in intervals
        assert (60, 76) in intervals  # nearby + direct continuation merged!
        assert (80, 82) in intervals

        # Contiguous trailing local block (< k tokens) directly following an anchor merges into one span
        contiguous_seg = [*base[100:108], *base[108:110]]
        assert _align_segment_tokens(base, contiguous_seg, tok_start=0) == [(100, 110)]

    def test_uncovered_text_gaps_long_out_of_order_retry_from_zero(self) -> None:
        # >256 tokens so _build_token_index is used inside _uncovered_text_gaps;
        # second segment appears earlier than cursor and is spliced so tok_start > 0 retries from 0.
        part_a = " ".join(f"alpha{i}" for i in range(140))
        gap_txt = "Containing 0 acres."
        part_b = " ".join(f"beta{i}" for i in range(140))
        working = f"{part_a} {gap_txt} {part_b}"
        # Spliced versions (omit one interior word so literal .find fails, forcing token alignment)
        seg_b = " ".join(f"beta{i}" for i in range(140) if i != 70)
        seg_a = " ".join(f"alpha{i}" for i in range(140) if i != 70)
        gaps = _uncovered_text_gaps(
            working,
            [
                (seg_b, "Tract 2", TractType.MAIN),
                (seg_a, "Tract 1", TractType.MAIN),
            ],
        )
        assert any("Containing 0 acres." in g for g in gaps)

    def test_source_map_verbatim_note_and_notes_by_segment_fallbacks(self) -> None:
        # _SourceMap edge cases: missing tract, unmapped span, stretched span
        smap = _SourceMap("N 45° 10' E 100 feet", "N 45°10' E 100 feet")
        assert smap.locate_tract("not present") is None
        assert smap.source_wording(100, 105) is None

        # Stretched source span (> 2*(last-first) + 8) returns None
        padded_source = "start " + " ".join(f"x{i}" for i in range(25)) + " end"
        short_norm = "start end"
        smap_stretch = _SourceMap(padded_source, short_norm)
        assert smap_stretch.source_wording(0, len(short_norm)) is None

        # _verbatim_note restores original casing/whitespace when found once, keeps note when empty
        raw_source = "Easement   over  the  West  10  feet"
        note = SEPARATE_EASEMENT_NOTE_PREFIX + "easement over the west 10 feet"
        assert _verbatim_note(note, raw_source) == SEPARATE_EASEMENT_NOTE_PREFIX + raw_source
        assert (
            _verbatim_note(SEPARATE_EASEMENT_NOTE_PREFIX, raw_source)
            == SEPARATE_EASEMENT_NOTE_PREFIX
        )

        # _notes_by_segment: out-of-order segment head & unlocated easement segment
        norm = "SECOND TRACT TEXT. FIRST TRACT TEXT."
        segments = [
            ("FIRST TRACT TEXT.", "Tract 1", TractType.MAIN),
            ("SECOND TRACT TEXT.", "Tract 2", TractType.MAIN),
            ("unmatched easement wording", "Easement 1", TractType.EASEMENT),
        ]
        notes = _notes_by_segment(norm, segments, [], norm, norm + " Unmatched Easement Wording")
        assert any(SEPARATE_EASEMENT_NOTE_PREFIX in n for group in notes for n in group)
