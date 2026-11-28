"""Verify cross-package imports and core behaviors work across the workspace."""

from __future__ import annotations

import io
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import get_args

import pytest


def _square_calls():
    from mp_models import DeedCall

    return [
        DeedCall(
            course=1,
            direction_text="N 0°00' E",
            bearing_quadrant="N 0°00' E",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=100.0,
        ),
        DeedCall(
            course=2,
            direction_text="S 90°00' E",
            bearing_quadrant="S 90°00' E",
            bearing_azimuth_deg_from_north=90.0,
            distance_ft=100.0,
        ),
        DeedCall(
            course=3,
            direction_text="S 0°00' W",
            bearing_quadrant="S 0°00' W",
            bearing_azimuth_deg_from_north=180.0,
            distance_ft=100.0,
        ),
        DeedCall(
            course=4,
            direction_text="N 90°00' W",
            bearing_quadrant="N 90°00' W",
            bearing_azimuth_deg_from_north=270.0,
            distance_ft=100.0,
        ),
    ]


class TestMpModelsImports:
    """mp-models package should export working core types."""

    def test_core_types(self) -> None:
        from mp_models import (
            AuditContext,
            ClosureResult,
            DeedCall,
            LegalDescription,
            Point,
            RunMetadata,
        )

        call = DeedCall(
            course=1,
            direction_text="N 45°00' E",
            bearing_quadrant="N 45°00' E",
            bearing_azimuth_deg_from_north=45.0,
            distance_ft=100.0,
        )
        desc = LegalDescription(calls=[call], source_doc="sample.pdf")
        pt = Point(x=10.0, y=20.0)
        closure = ClosureResult(
            misclosure_ft=0.0,
            misclosure_x_ft=0.0,
            misclosure_y_ft=0.0,
            area_sq_ft=10000.0,
            area_acres=10000.0 / 43560.0,
            perimeter_ft=400.0,
            closure_passed=True,
            angle_check_passed=True,
            curve_consistency_passed=True,
        )
        ctx = AuditContext(
            run_metadata=RunMetadata(
                parser_version="1.0.0",
                llm_provider="openai",
                llm_model="gpt-5.2",
                prompt_hash="abc",
                timestamp_utc=datetime(2026, 1, 1, tzinfo=UTC),
                source_pdf="sample.pdf",
                cache_enabled=False,
            )
        )

        assert desc.num_calls() == 1
        assert (pt.x, pt.y) == (10.0, 20.0)
        assert closure.closure_passed is True
        assert ctx.run_metadata.source_pdf == "sample.pdf"

    def test_envelope_types(self) -> None:
        from mp_models import RawTextMessage, parse_message, read_jsonl, write_jsonl

        msg = RawTextMessage(
            source="deed.pdf",
            text="BEGINNING at a point;",
            llm_provider="openai",
            llm_model="gpt-5.2",
        )
        buf = io.StringIO()
        write_jsonl(buf, msg)
        line = buf.getvalue().strip()

        assert parse_message(line) == msg
        buf.seek(0)
        assert list(read_jsonl(buf)) == [msg]

    def test_unit_types(self) -> None:
        from mp_models import ConversionFactors, DistanceUnit

        assert ConversionFactors.convert_to_feet(1.0, "chains") == pytest.approx(66.0, abs=1e-6)
        assert ConversionFactors.convert_to_feet(2.0, "rods") == pytest.approx(33.0, abs=1e-6)
        units = get_args(DistanceUnit)
        assert {"feet", "chains", "rods", "varas"}.issubset(set(units))

    def test_tract_types(self) -> None:
        from mp_models import Tract, TractType

        calls = _square_calls()
        tract = Tract(label="Tract 1", tract_type=TractType.MAIN, calls=calls)
        assert TractType.MAIN == "main"
        assert tract.label == "Tract 1"
        assert tract.tract_type is TractType.MAIN
        assert len(tract.calls) == 4

    def test_logging(self) -> None:
        import logging

        import mp_models.logging as mp_logging
        import structlog
        from mp_models import configure_logging, get_log_format

        root_logger = logging.getLogger()
        orig_root_handlers = list(root_logger.handlers)
        orig_root_level = root_logger.level
        orig_pkg_state = {
            name: (
                list(logging.getLogger(name).handlers),
                logging.getLogger(name).level,
                logging.getLogger(name).propagate,
            )
            for name in mp_logging._PACKAGE_LOGGER_NAMES
        }
        orig_structlog_config = dict(structlog.get_config())
        orig_format = mp_logging._CURRENT_FORMAT
        orig_owns_warnings = mp_logging._OWNS_WARNING_CAPTURE
        orig_warnings_captured = getattr(logging, "_warnings_showwarning", None) is not None
        try:
            configure_logging(level="WARNING", log_format="json", stream=io.StringIO())
            assert get_log_format() == "json"
        finally:
            for h in list(root_logger.handlers):
                root_logger.removeHandler(h)
            for h in orig_root_handlers:
                root_logger.addHandler(h)
            root_logger.setLevel(orig_root_level)
            for name, (handlers, level, propagate) in orig_pkg_state.items():
                pkg_logger = logging.getLogger(name)
                for h in list(pkg_logger.handlers):
                    pkg_logger.removeHandler(h)
                for h in handlers:
                    pkg_logger.addHandler(h)
                pkg_logger.setLevel(level)
                pkg_logger.propagate = propagate
            structlog.configure(**orig_structlog_config)
            mp_logging._CURRENT_FORMAT = orig_format
            mp_logging._OWNS_WARNING_CAPTURE = orig_owns_warnings
            logging.captureWarnings(orig_warnings_captured)


class TestMpBearingImports:
    """mp-bearing package should export working azimuth and curve functions."""

    def test_azimuth_functions(self) -> None:
        from mp_bearing import (
            bearing_to_azimuth,
            due_cardinal_to_azimuth,
            parse_quadrant_bearing,
            quadrant_to_azimuth,
        )

        assert quadrant_to_azimuth("N", 45.0, "E") == 45.0
        assert parse_quadrant_bearing("S 56°40'30\" W") == (
            "S",
            pytest.approx(56.675, abs=1e-6),
            "W",
        )
        assert bearing_to_azimuth("S 56°40'30\" W") == pytest.approx(236.675, abs=1e-6)
        assert due_cardinal_to_azimuth("due West") == 270.0

    def test_curve_functions(self) -> None:
        from mp_bearing import calculate_curve_properties, calculate_missing_curve_elements

        props = calculate_curve_properties(100.0, delta_deg=90.0)
        assert props["arc_length_ft"] == pytest.approx(50.0 * math.pi, abs=1e-6)
        assert props["chord_length_ft"] == pytest.approx(100.0 * math.sqrt(2), abs=1e-6)

        solved = calculate_missing_curve_elements(radius_ft=100.0, delta_deg=90.0)
        assert solved["arc_length_ft"] == pytest.approx(50.0 * math.pi, abs=1e-6)
        assert solved["chord_length_ft"] == pytest.approx(100.0 * math.sqrt(2), abs=1e-6)

    def test_delta_functions(self) -> None:
        from mp_bearing import calculate_deltas

        dx, dy = calculate_deltas(90.0, 100.0)
        assert dx == pytest.approx(100.0, abs=1e-9)
        assert dy == pytest.approx(0.0, abs=1e-9)


class TestMpParseImports:
    """mp-parse package should export working call extraction and monument functions."""

    def test_call_functions(self) -> None:
        from mp_models import DeedCall
        from mp_parse import enrich_calls_with_azimuths, extract_calls, mark_tie_in_calls

        calls, tracts = extract_calls(
            "BEGINNING at a point; THENCE N 45°00' E 100.00 feet to an iron pin."
        )
        assert tracts == []
        assert len(calls) == 1
        assert calls[0].bearing_azimuth_deg_from_north == pytest.approx(45.0, abs=1e-6)

        unenriched = [
            DeedCall(
                course=1,
                direction_text="N 45°00' E",
                bearing_quadrant="N 45°00' E",
                distance_ft=50.0,
                to="the point of beginning",
            ),
            DeedCall(
                course=2,
                direction_text="S 45°00' E",
                bearing_quadrant="S 45°00' E",
                distance_ft=100.0,
            ),
        ]
        enriched = enrich_calls_with_azimuths(unenriched)
        assert [c.bearing_azimuth_deg_from_north for c in enriched] == [45.0, 135.0]

        marked = mark_tie_in_calls(enriched, poc_description="NW corner of Section 12")
        assert [c.is_tie_in for c in marked] == [True, False]

    def test_monument_functions(self) -> None:
        from mp_parse import classify_monument, classify_monument_status

        assert classify_monument("iron pin found") == "iron_pin"
        assert classify_monument_status("iron pin found") == "found"

    def test_normalizer_functions(self) -> None:
        from mp_parse import expand_assessor_abbreviations

        assert expand_assessor_abbreviations("N 45 E 100 FT") == "N 45 E 100 feet"

    def test_strip_exception_functions(self) -> None:
        from mp_parse import detect_strip_exceptions, remove_strip_exceptions

        text = (
            "BEGINNING at a point; THENCE N 45 E 100 feet. "
            "LESS AND EXCEPT the east 10 feet thereof."
        )
        strips = detect_strip_exceptions(text)
        assert len(strips) == 1
        assert strips[0]["direction"] == "East"
        assert strips[0]["width_ft"] == 10.0
        assert remove_strip_exceptions(text) == "BEGINNING at a point; THENCE N 45 E 100 feet."

    def test_parcel_functions(self) -> None:
        from mp_parse import (
            ParcelInfo,
            ParcelMarker,
            detect_parcel_markers,
            split_into_parcels,
        )

        text = "Parcel A: BEGINNING at a point. Parcel B: BEGINNING at another point."
        markers: list[ParcelMarker] = detect_parcel_markers(text)
        parcels: list[ParcelInfo] = split_into_parcels(text)

        assert [m["label"] for m in markers] == ["Parcel A", "Parcel B"]
        assert set(markers[0].keys()) == set(ParcelMarker.__annotations__)
        assert [p["label"] for p in parcels] == ["Parcel A", "Parcel B"]
        assert set(parcels[0].keys()) == set(ParcelInfo.__annotations__)

    def test_split_into_tracts(self) -> None:
        from mp_models import TractType
        from mp_parse import split_into_tracts

        text = (
            "TRACT #1: BEGINNING at a point; THENCE N 0° E 100 feet. "
            "TRACT #2: BEGINNING at a point; THENCE S 0° W 50 feet."
        )
        segments = split_into_tracts(text)
        assert [(label, tract_type) for _seg_text, label, tract_type in segments] == [
            ("Tract 1", TractType.MAIN),
            ("Tract 2", TractType.MAIN),
        ]


class TestMpVerifyImports:
    """mp-verify package should export working verification functions."""

    def test_verify_closure(self) -> None:
        from mp_verify import get_closure_summary, verify_closure

        result = verify_closure(_square_calls())
        assert result.closure_passed is True
        assert result.area_sq_ft == pytest.approx(10000.0, abs=1e-6)
        summary = get_closure_summary(result)
        assert "FULLY VERIFIED" in summary

    def test_confidence_functions(self) -> None:
        from mp_verify import calculate_confidence_score, score_call_quality, verify_closure

        calls = _square_calls()
        result = verify_closure(calls)
        assert score_call_quality(calls[0]) == "high"
        assert calculate_confidence_score(result, calls) == pytest.approx(1.0, abs=1e-6)

    def test_verify_tract(self) -> None:
        from mp_models import Tract, TractType
        from mp_verify import verify_tract

        calls = _square_calls()
        tract = Tract(label="Tract 1", tract_type=TractType.MAIN, calls=calls)
        result = verify_tract(calls, tract=tract)
        assert result.closure_passed is True
        assert result.area_sq_ft == pytest.approx(10000.0, abs=1e-6)

    def test_relative_analysis_facade(self) -> None:
        from mp_models import RelativeDescription as PackageDescription
        from mp_verify import analyze_relative as package_analyze

        from metesparser.relative import RelativeDescription, analyze_relative

        assert RelativeDescription is PackageDescription
        assert analyze_relative is package_analyze

    def test_diagnostics_and_source_handoff_facades(self) -> None:
        from mp_models import ClosureDiagnosticRequest, SourceAcquisitionRecord
        from mp_review import diagnose_closure_file, validate_source_bundle
        from mp_verify import diagnose_closure

        from metesparser import diagnostics, source_handoff

        assert diagnostics.ClosureDiagnosticRequest is ClosureDiagnosticRequest
        assert diagnostics.diagnose_closure is diagnose_closure
        assert diagnostics.diagnose_closure_file is diagnose_closure_file
        assert source_handoff.SourceAcquisitionRecord is SourceAcquisitionRecord
        assert source_handoff.validate_source_bundle is validate_source_bundle

    def test_comparison_and_inspection_facades(self) -> None:
        from mp_models import ArtifactInspection, ComparisonRequest
        from mp_review import compare_descriptions_file, inspect_artifacts
        from mp_verify import compare_descriptions

        from metesparser import artifact_inspect, comparison

        assert comparison.ComparisonRequest is ComparisonRequest
        assert comparison.compare_descriptions is compare_descriptions
        assert comparison.compare_descriptions_file is compare_descriptions_file
        assert artifact_inspect.ArtifactInspection is ArtifactInspection
        assert artifact_inspect.inspect_artifacts is inspect_artifacts


class TestMpExportImports:
    """mp-export package should export working CSV and audit HTML functions."""

    def test_revision_facade_preserves_shared_implementations(self) -> None:
        from mp_models import DashboardRevision, revision_template
        from mp_review import import_revision, load_revision, publish_revision

        from metesparser import revisions

        assert revisions.DashboardRevision is DashboardRevision
        assert revisions.revision_template is revision_template
        assert revisions.import_revision is import_revision
        assert revisions.load_revision is load_revision
        assert revisions.publish_revision is publish_revision

    def test_csv_functions(self, tmp_path: Path) -> None:
        from mp_export import FIELDNAMES, calls_to_csv, csv_to_calls, export_verified_csv
        from mp_verify import verify_closure

        assert len(FIELDNAMES) == 22
        assert FIELDNAMES[0] == "course"
        assert FIELDNAMES[-1] == "curve_type"

        calls = _square_calls()
        raw_csv = tmp_path / "square.csv"
        calls_to_csv(calls, str(raw_csv))
        loaded = csv_to_calls(str(raw_csv))
        assert len(loaded) == 4
        assert [c.distance_ft for c in loaded] == [100.0, 100.0, 100.0, 100.0]

        closure = verify_closure(calls)
        written_paths = export_verified_csv(calls, closure, str(tmp_path / "out.csv"))
        assert len(written_paths) == 1
        assert written_paths[0].exists()
        assert len(csv_to_calls(str(written_paths[0]))) == 4

    def test_audit_html_functions(self, tmp_path: Path) -> None:
        from mp_export import generate_html, write_report
        from mp_models import AuditContext, RunMetadata

        ctx = AuditContext(
            run_metadata=RunMetadata(
                parser_version="1.0.0",
                llm_provider="openai",
                llm_model="gpt-5.2",
                prompt_hash="abc123",
                timestamp_utc=datetime(2026, 1, 1, tzinfo=UTC),
                source_pdf="cross_pkg.pdf",
                cache_enabled=False,
            )
        )
        html = generate_html(ctx)
        assert "<!DOCTYPE html>" in html
        assert "cross_pkg.pdf" in html

        report_path = tmp_path / "report.audit.html"
        write_report(ctx, report_path)
        assert report_path.read_text(encoding="utf-8") == html

    def test_dashboard_facade(self) -> None:
        from mp_export import render_dashboard as package_render
        from mp_models import DashboardBundle as PackageBundle
        from mp_review import dashboard_file as package_file
        from mp_review import prepare_dashboard as package_prepare

        from metesparser.dashboard import (
            DashboardBundle,
            dashboard_file,
            prepare_dashboard,
            render_dashboard,
        )

        assert DashboardBundle is PackageBundle
        assert render_dashboard is package_render
        assert prepare_dashboard is package_prepare
        assert dashboard_file is package_file


class TestPipelineImport:
    """metesparser orchestrator should export the same working Pipeline class."""

    def test_pipeline_from_package(self) -> None:
        from metesparser import Pipeline
        from metesparser.pipeline import Pipeline as ModulePipeline

        assert Pipeline is ModulePipeline
        pipe = Pipeline(provider="unsupported_provider", cache=False)
        with pytest.raises(ValueError, match="Unsupported LLM provider 'unsupported_provider'"):
            pipe.run(Path("unused.pdf"))

    def test_pipeline_from_module(self) -> None:
        from metesparser import Pipeline as PackagePipeline
        from metesparser.pipeline import Pipeline

        assert Pipeline is PackagePipeline
        pipe = Pipeline(provider="unsupported_provider", cache=False, audit=True)
        with pytest.raises(ValueError, match="Unsupported LLM provider 'unsupported_provider'"):
            pipe.run(Path("unused.pdf"))

    def test_pipeline_result_exported_from_package(self) -> None:
        import metesparser
        import metesparser.pipeline as pipeline_mod

        assert metesparser.PipelineResult is pipeline_mod.PipelineResult
        assert "PipelineResult" in metesparser.__all__


def test_online_map_facade_uses_package_implementations() -> None:
    from mp_export import render_online_map as package_render
    from mp_models import WebMapRequest as PackageRequest
    from mp_review import prepare_web_map as package_prepare

    from metesparser.dashboard import WebMapRequest, prepare_web_map, render_online_map

    assert render_online_map is package_render
    assert prepare_web_map is package_prepare
    assert WebMapRequest is PackageRequest


def test_mapbox_mcp_facade_uses_package_implementations() -> None:
    from mp_export import build_mapbox_mcp_handoff as package_build
    from mp_review import mapbox_mcp_file as package_file

    from metesparser.dashboard import build_mapbox_mcp_handoff, mapbox_mcp_file

    assert build_mapbox_mcp_handoff is package_build
    assert mapbox_mcp_file is package_file


def test_standalone_online_map_facade_uses_package_implementations() -> None:
    from mp_models import StandaloneWebMapInput as PackageInput
    from mp_review import render_map_file as package_file

    from metesparser.dashboard import StandaloneWebMapInput, render_map_file

    assert StandaloneWebMapInput is PackageInput
    assert render_map_file is package_file


def test_corridor_and_plss_facades_reuse_shared_implementations() -> None:
    from mp_models.corridor import CorridorRequest
    from mp_models.plss import PLSSDerivationRequest
    from mp_review.corridor import analyze_corridor_file
    from mp_review.plss import prepare_plss_file
    from mp_verify.corridor import analyze_corridor
    from mp_verify.plss import derive_plss

    import metesparser.corridor as corridor
    import metesparser.plss as plss

    assert corridor.CorridorRequest is CorridorRequest
    assert corridor.analyze_corridor is analyze_corridor
    assert corridor.analyze_corridor_file is analyze_corridor_file
    assert plss.PLSSDerivationRequest is PLSSDerivationRequest
    assert plss.derive_plss is derive_plss
    assert plss.prepare_plss_file is prepare_plss_file


def test_delivery_facade_reuses_shared_models_and_replay() -> None:
    from mp_models import DeliveryRequest
    from mp_review.delivery import (
        DeliveryReplay,
        DeliveryReplayIncomplete,
        load_delivery,
        publish_delivery,
        replay_delivery,
    )
    from mp_review.revision_view import render_revision_file

    import metesparser.delivery as delivery

    assert delivery.DeliveryRequest is DeliveryRequest
    assert delivery.load_delivery is load_delivery
    assert delivery.publish_delivery is publish_delivery
    assert delivery.replay_delivery is replay_delivery
    assert delivery.DeliveryReplay is DeliveryReplay
    assert delivery.DeliveryReplayIncomplete is DeliveryReplayIncomplete
    assert delivery.render_revision_file is render_revision_file


def test_raster_picker_facade_reuses_shared_adapter() -> None:
    from mp_review.raster_picker import prepare_raster_picker_file

    from metesparser.raster_picker import prepare_raster_picker_file as public

    assert public is prepare_raster_picker_file


def test_mp_ocr_escalation_and_preprocessing_public_exports():
    from mp_ocr import (
        VALID_ESCALATION_POLICIES,
        CourseDisagreement,
        EscalationReport,
        compare_call_readings,
        count_pdf_pages,
        has_legal_measurement_signals,
        parse_located_pages,
        preprocess_pdf_pages_for_ocr,
        render_pdf_pages_to_pngs,
        select_escalation_outcome,
        should_escalate_closure,
        strip_green_watermark_and_crop,
        validate_escalation_policy,
        verify_normalization_integrity,
    )

    assert VALID_ESCALATION_POLICIES == ("never", "closure_failed", "unverified")
    assert callable(validate_escalation_policy)
    assert callable(should_escalate_closure)
    assert callable(compare_call_readings)
    assert callable(select_escalation_outcome)
    assert callable(count_pdf_pages)
    assert callable(render_pdf_pages_to_pngs)
    assert callable(strip_green_watermark_and_crop)
    assert callable(preprocess_pdf_pages_for_ocr)
    assert callable(verify_normalization_integrity)
    assert callable(has_legal_measurement_signals)
    assert callable(parse_located_pages)
    assert CourseDisagreement is not None
    assert EscalationReport is not None
