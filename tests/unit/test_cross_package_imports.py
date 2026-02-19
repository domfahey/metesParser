"""Verify cross-package imports work correctly across the workspace."""

from __future__ import annotations


class TestMpModelsImports:
    """mp-models package should export all core types."""

    def test_core_types(self) -> None:
        from mp_models import AuditContext, ClosureResult, DeedCall, LegalDescription, Point

        assert DeedCall is not None
        assert LegalDescription is not None
        assert ClosureResult is not None
        assert Point is not None
        assert AuditContext is not None

    def test_envelope_types(self) -> None:
        from mp_models import RawTextMessage, parse_message, read_jsonl, write_jsonl

        assert RawTextMessage is not None
        assert read_jsonl is not None
        assert write_jsonl is not None
        assert parse_message is not None

    def test_unit_types(self) -> None:
        from mp_models import ConversionFactors, DistanceUnit

        assert ConversionFactors is not None
        assert DistanceUnit is not None

    def test_logging(self) -> None:
        from mp_models import configure_logging, get_log_format

        assert configure_logging is not None
        assert get_log_format is not None


class TestMpBearingImports:
    """mp-bearing package should export azimuth and curve functions."""

    def test_azimuth_functions(self) -> None:
        from mp_bearing import (
            bearing_to_azimuth,
            due_cardinal_to_azimuth,
            parse_quadrant_bearing,
            quadrant_to_azimuth,
        )

        assert quadrant_to_azimuth is not None
        assert parse_quadrant_bearing is not None
        assert bearing_to_azimuth is not None
        assert due_cardinal_to_azimuth is not None

    def test_curve_functions(self) -> None:
        from mp_bearing import calculate_curve_properties, calculate_missing_curve_elements

        assert calculate_curve_properties is not None
        assert calculate_missing_curve_elements is not None

    def test_delta_functions(self) -> None:
        from mp_bearing import calculate_deltas

        assert calculate_deltas is not None


class TestMpParseImports:
    """mp-parse package should export call extraction and monument functions."""

    def test_call_functions(self) -> None:
        from mp_parse import enrich_calls_with_azimuths, extract_calls, mark_tie_in_calls

        assert extract_calls is not None
        assert mark_tie_in_calls is not None
        assert enrich_calls_with_azimuths is not None

    def test_monument_functions(self) -> None:
        from mp_parse import classify_monument, classify_monument_status

        assert classify_monument is not None
        assert classify_monument_status is not None

    def test_normalizer_functions(self) -> None:
        from mp_parse import expand_assessor_abbreviations

        assert expand_assessor_abbreviations is not None

    def test_strip_exception_functions(self) -> None:
        from mp_parse import detect_strip_exceptions, remove_strip_exceptions

        assert detect_strip_exceptions is not None
        assert remove_strip_exceptions is not None

    def test_parcel_functions(self) -> None:
        from mp_parse import (
            ParcelInfo,
            ParcelMarker,
            detect_parcel_markers,
            split_into_parcels,
        )

        assert ParcelInfo is not None
        assert ParcelMarker is not None
        assert detect_parcel_markers is not None
        assert split_into_parcels is not None


class TestMpVerifyImports:
    """mp-verify package should export verification functions."""

    def test_verify_closure(self) -> None:
        from mp_verify import get_closure_summary, verify_closure

        assert verify_closure is not None
        assert get_closure_summary is not None

    def test_confidence_functions(self) -> None:
        from mp_verify import calculate_confidence_score, score_call_quality

        assert calculate_confidence_score is not None
        assert score_call_quality is not None


class TestMpExportImports:
    """mp-export package should export CSV and audit HTML functions."""

    def test_csv_functions(self) -> None:
        from mp_export import FIELDNAMES, calls_to_csv, csv_to_calls, export_verified_csv

        assert calls_to_csv is not None
        assert csv_to_calls is not None
        assert export_verified_csv is not None
        assert FIELDNAMES is not None

    def test_audit_html_functions(self) -> None:
        from mp_export import generate_html, write_report

        assert generate_html is not None
        assert write_report is not None


class TestPipelineImport:
    """metesparser orchestrator should export Pipeline."""

    def test_pipeline_from_package(self) -> None:
        from metesparser import Pipeline

        assert Pipeline is not None

    def test_pipeline_from_module(self) -> None:
        from metesparser.pipeline import Pipeline

        assert Pipeline is not None
