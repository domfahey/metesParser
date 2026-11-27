"""Core model validation, coercion, and invariant tests for mp_models."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from mp_models import (
    AuditContext,
    CheckResult,
    ClosureResult,
    ConversionFactors,
    DeedCall,
    LegalDescription,
    Point,
    RunMetadata,
    Tract,
    TractType,
    stated_areas_match,
)
from mp_models.base import coerce_bool_field
from pydantic import ValidationError


class TestBaseHelpers:
    def test_stated_areas_match_tolerance_and_invalid_inputs(self):
        assert stated_areas_match(10000.0, 10000.005) is True
        assert stated_areas_match(0.0, 0.00005) is True
        assert stated_areas_match(10000.0, 10100.0) is False
        assert stated_areas_match(True, 1.0) is False  # type: ignore[arg-type]
        assert stated_areas_match(1.0, False) is False  # type: ignore[arg-type]
        assert stated_areas_match(float("nan"), 1.0) is False
        assert stated_areas_match(1.0, float("inf")) is False

    @pytest.mark.parametrize(
        "raw,expected",
        [
            (True, True),
            (False, False),
            (None, False),
            (0, False),
            (1, True),
            (0.0, False),
            (1.0, True),
            ("", False),
            ("  false ", False),
            ("0", False),
            ("no", False),
            ("n", False),
            ("off", False),
            ("true", True),
            ("1", True),
            ("YES", True),
            ("y", True),
            ("on", True),
        ],
    )
    def test_coerce_bool_field_valid_values(self, raw, expected):
        assert coerce_bool_field(raw) is expected

    @pytest.mark.parametrize("bad", [2, -1, 0.5, "maybe", [], {}])
    def test_coerce_bool_field_rejects_ambiguous_values(self, bad):
        with pytest.raises(ValueError, match="boolean"):
            coerce_bool_field(bad)


class TestDeedCallValidation:
    def test_deed_call_frozen_and_bool_coercion(self):
        call = DeedCall(course=1, direction_text="North", distance_ft=100.0, is_exception="true")
        assert call.course == 1
        assert call.distance_ft == 100.0
        assert call.is_exception is True
        with pytest.raises(ValidationError, match="Instance is frozen"):
            call.course = 2  # type: ignore[misc]

    def test_literal_and_monument_status_normalization_and_errors(self):
        c_found = DeedCall(
            course=1,
            direction_text="N",
            distance_ft=10.0,
            monument_status="  FOUND ",
            monument_type=" IRON_PIN ",
        )
        assert c_found.monument_status == "found"
        assert c_found.monument_type == "iron_pin"

        c_set = DeedCall(course=1, direction_text="N", distance_ft=10.0, monument_status="set")
        assert c_set.monument_status == "set"

        for blank in ("", "none", " NONE "):
            c_none = DeedCall(course=1, direction_text="N", distance_ft=10.0, monument_status=blank)
            assert c_none.monument_status is None

        with pytest.raises(ValidationError, match="monument_status must be a string"):
            DeedCall(course=1, direction_text="N", distance_ft=10.0, monument_status=123)  # type: ignore[arg-type]
        with pytest.raises(ValidationError, match="monument_status must be one of: found, set"):
            DeedCall(course=1, direction_text="N", distance_ft=10.0, monument_status="destroyed")  # type: ignore[arg-type]
        with pytest.raises(ValidationError, match="Curve/monument values must be strings"):
            DeedCall(course=1, direction_text="N", distance_ft=10.0, monument_type=42)  # type: ignore[arg-type]
        with pytest.raises(ValidationError, match="is_meander must be a boolean value"):
            DeedCall(course=1, direction_text="N", distance_ft=10.0, is_meander="sometimes")  # type: ignore[arg-type]

    def test_azimuth_and_radius_validation_and_negative_radius_sign(self):
        # Azimuth wraps 360 -> 0 and rejects bool.
        wrapped = DeedCall(
            course=1, direction_text="N", bearing_azimuth_deg_from_north=360.0, distance_ft=10.0
        )
        assert wrapped.bearing_azimuth_deg_from_north == 0.0
        with pytest.raises(ValidationError, match="not a boolean"):
            DeedCall(
                course=1,
                direction_text="N",
                bearing_azimuth_deg_from_north=True,  # type: ignore[arg-type]
                distance_ft=10.0,
            )
        with pytest.raises(ValidationError, match="not a boolean"):
            DeedCall(
                course=1,
                direction_text="curve",
                distance_ft=10.0,
                curve_dir="left",
                radius_ft=True,  # type: ignore[arg-type]
                delta_deg=10.0,
            )
        with pytest.raises(ValidationError, match="non-zero"):
            DeedCall(
                course=1,
                direction_text="curve",
                distance_ft=10.0,
                curve_dir="left",
                radius_ft=0.0,
                delta_deg=10.0,
            )

        # Negative radius normalized to positive for left curve; rejected for right curve.
        left_neg = DeedCall(
            course=1,
            direction_text="curve",
            distance_ft=50.0,
            curve_dir="left",
            radius_ft=-100.0,
            delta_deg=30.0,
        )
        assert left_neg.radius_ft == 100.0

        with pytest.raises(ValidationError, match="radius_ft sign conflicts with curve_dir"):
            DeedCall(
                course=1,
                direction_text="curve",
                distance_ft=50.0,
                curve_dir="right",
                radius_ft=-100.0,
                delta_deg=30.0,
            )

        # Spiral with arc length and negative radius without curve_dir keeps radius (no conflict).
        spiral_neg = DeedCall(
            course=1,
            direction_text="spiral",
            distance_ft=50.0,
            curve_type="spiral",
            radius_ft=-100.0,
            arc_length_ft=50.0,
        )
        assert spiral_neg.radius_ft == -100.0

    def test_spiral_chord_only_and_undetermined_distance_rules(self):
        # Spiral with only chord_bearing + chord_length_ft (no radius/curve_dir) is valid.
        sp_chord = DeedCall(
            course=1,
            direction_text="spiral",
            distance_ft=50.0,
            curve_type="spiral",
            chord_bearing="N 45° E",
            chord_length_ft=50.0,
        )
        assert sp_chord.is_curve() is True

        # Spiral with curve_dir + radius + delta and no stated arc/chord may have distance_ft=None.
        sp_undetermined = DeedCall(
            course=1,
            direction_text="spiral",
            distance_ft=None,
            curve_type="spiral",
            curve_dir="right",
            radius_ft=200.0,
            delta_deg=15.0,
        )
        assert sp_undetermined.distance_ft is None

        # Straight call or spiral with stated length cannot have distance_ft=None.
        with pytest.raises(ValidationError, match="distance_ft may be None only for a spiral"):
            DeedCall(course=1, direction_text="North", distance_ft=None)
        with pytest.raises(ValidationError, match="distance_ft may be None only for a spiral"):
            DeedCall(
                course=1,
                direction_text="spiral",
                distance_ft=None,
                curve_type="spiral",
                curve_dir="right",
                radius_ft=200.0,
                arc_length_ft=50.0,
            )


class TestLegalDescriptionAndClosureModels:
    def test_legal_description_validation_and_has_incomplete_calls(self):
        ld = LegalDescription(distance_unit="  CHAINS ")
        assert ld.distance_unit == "chains"
        assert ld.has_incomplete_calls() is False

        with pytest.raises(ValidationError, match="distance_unit must be a string"):
            LegalDescription(distance_unit=123)  # type: ignore[arg-type]
        with pytest.raises(ValidationError, match="Input should be 'feet'"):
            LegalDescription(distance_unit=None)  # type: ignore[arg-type]
        with pytest.raises(ValidationError, match="stated_area_approximate must be a boolean"):
            LegalDescription(stated_area_approximate="unsure")  # type: ignore[arg-type]
        with pytest.raises(ValidationError, match="stated_area_sq_ft must be set"):
            LegalDescription(stated_area_approximate=True)

        ld_approx = LegalDescription(stated_area_sq_ft=5000.0, stated_area_approximate="yes")
        assert ld_approx.stated_area_approximate is True

        incomplete_call = DeedCall(course=1, direction_text="northerly", distance_ft=100.0)
        ld_inc = LegalDescription(
            tracts=[Tract(label="T1", tract_type=TractType.MAIN, calls=[incomplete_call])]
        )
        assert ld_inc.has_incomplete_calls() is True

    def test_check_result_legacy_status_and_closure_result_statuses(self):
        # Legacy passed-only payload infers status and synchronizes passed.
        legacy_pass = CheckResult.model_validate({"name": "c", "passed": True, "detail": "ok"})
        assert legacy_pass.status == "passed" and legacy_pass.passed is True
        legacy_fail = CheckResult.model_validate({"name": "c", "passed": False, "detail": "bad"})
        assert legacy_fail.status == "failed" and legacy_fail.passed is False
        explicit = CheckResult.model_validate(
            {"name": "c", "status": "not_applicable", "passed": True, "detail": "na"}
        )
        assert explicit.status == "not_applicable" and explicit.passed is False

        base = {
            "misclosure_x_ft": 0.0,
            "misclosure_y_ft": 0.0,
            "misclosure_ft": 0.002,
            "area_sq_ft": 7500.0,
            "area_acres": 0.172,
            "perimeter_ft": 350.0,
            "closure_passed": True,
            "angle_check_passed": True,
            "curve_consistency_passed": True,
        }
        cr = ClosureResult(**base, source_review_status="complete")
        assert cr.is_fully_verified() is True
        assert cr.source_review_complete is True
        assert cr.get_closure_status() == "EXCELLENT"

        assert ClosureResult(**(base | {"misclosure_ft": 0.05})).get_closure_status() == "GOOD"
        assert ClosureResult(**(base | {"misclosure_ft": 0.5})).get_closure_status() == "ACCEPTABLE"
        assert ClosureResult(**(base | {"misclosure_ft": 2.0})).get_closure_status() == "POOR"
        assert (
            ClosureResult(**(base | {"misclosure_available": False})).get_closure_status()
            == "NOT DETERMINED"
        )
        assert (
            ClosureResult(**(base | {"closure_passed": False})).get_closure_status()
            == "NEEDS REVIEW"
        )
        assert (
            ClosureResult(**(base | {"warnings": ["issue"]})).get_closure_status() == "NEEDS REVIEW"
        )

        with pytest.raises(ValidationError, match="closure_passed must be a boolean value"):
            ClosureResult(**(base | {"closure_passed": "nope"}))  # type: ignore[arg-type]

    def test_point_units_and_audit_context(self):
        assert str(Point(x=1.0, y=2.0)) == "(1.00, 2.00)"
        assert ConversionFactors.convert_to_feet(1.0, "chains") == 66.0
        with pytest.raises(ValueError, match="Unsupported distance unit"):
            ConversionFactors.convert_to_feet(1.0, "leagues")

        rm = RunMetadata(
            parser_version="1.0.0",
            llm_provider="openai",
            llm_model="gpt-5",
            prompt_hash="abc123",
            timestamp_utc=datetime.now(UTC),
            source_pdf="deed.pdf",
            cache_enabled=True,
        )
        ctx = AuditContext(run_metadata=rm)
        assert ctx.call_audits == []
