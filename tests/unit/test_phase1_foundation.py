"""Phase 1 TDD tests: Foundation — Units, Models & Monument Types.

Tests for new distance units, monument types, precision_ratio,
and non-tangent curve fields.
"""

import math

import pytest
from pydantic import ValidationError

from metesparser.call_extractor import MonumentClassifier
from metesparser.models import ClosureResult, ConversionFactors, DeedCall


class TestNewDistanceUnits:
    """Test conversion of historical/regional distance units to feet."""

    @pytest.mark.parametrize(
        "value,unit,expected_ft",
        [
            (1.0, "varas", 2.778),
            (100.0, "varas", 277.8),
            (1.0, "arpents", 191.8),
            (2.5, "arpents", 479.5),
            (1.0, "toises", 6.395),
            (10.0, "toises", 63.95),
            (1.0, "furlongs", 660.0),
            (0.5, "furlongs", 330.0),
            (1.0, "meters", 3.28084),
            (100.0, "meters", 328.084),
            (1.0, "miles", 5280.0),
            (0.25, "miles", 1320.0),
            (1.0, "engineer_chains", 100.0),
            (3.5, "engineer_chains", 350.0),
            (1.0, "engineer_links", 1.0),
            (50.0, "engineer_links", 50.0),
        ],
        ids=[
            "1_vara",
            "100_varas",
            "1_arpent",
            "2.5_arpents",
            "1_toise",
            "10_toises",
            "1_furlong",
            "0.5_furlongs",
            "1_meter",
            "100_meters",
            "1_mile",
            "0.25_miles",
            "1_eng_chain",
            "3.5_eng_chains",
            "1_eng_link",
            "50_eng_links",
        ],
    )
    def test_convert_to_feet(self, value, unit, expected_ft):
        result = ConversionFactors.convert_to_feet(value, unit)
        assert math.isclose(result, expected_ft, rel_tol=1e-4)

    def test_unsupported_unit_raises(self):
        with pytest.raises(ValueError, match="Unsupported distance unit"):
            ConversionFactors.convert_to_feet(1.0, "cubits")

    def test_existing_units_still_work(self):
        """Ensure existing conversions are not broken."""
        assert ConversionFactors.convert_to_feet(1.0, "feet") == 1.0
        assert ConversionFactors.convert_to_feet(1.0, "poles") == 16.5
        assert ConversionFactors.convert_to_feet(1.0, "chains") == 66.0
        assert ConversionFactors.convert_to_feet(1.0, "links") == 0.66


class TestDistanceUnitLiteral:
    """Test that new units are accepted by the DistanceUnit Literal."""

    @pytest.mark.parametrize(
        "unit",
        [
            "varas",
            "arpents",
            "toises",
            "furlongs",
            "meters",
            "miles",
            "engineer_chains",
            "engineer_links",
        ],
    )
    def test_legal_description_accepts_new_unit(self, unit):
        from metesparser.models import LegalDescription

        ld = LegalDescription(distance_unit=unit)
        assert ld.distance_unit == unit


class TestNewMonumentTypes:
    """Test that new monument types are accepted by the model."""

    @pytest.mark.parametrize(
        "monument_type",
        [
            "pk_nail",
            "hub_and_tack",
            "monitoring_well",
            "capped_pin",
            "capped_rod",
            "txdot_monument",
        ],
    )
    def test_deedcall_accepts_new_monument_type(self, monument_type):
        call = DeedCall(
            course=1,
            direction_text="N 45° E",
            distance_ft=100.0,
            monument_type=monument_type,
        )
        assert call.monument_type == monument_type


class TestMonumentClassifierNewPatterns:
    """Test MonumentClassifier detects new monument types from text."""

    @pytest.mark.parametrize(
        "text,expected_type",
        [
            ("to a PK nail set", "pk_nail"),
            ("to a PK nail found in the pavement", "pk_nail"),
            ("to a pk nail", "pk_nail"),
            ("to a hub and tack set", "hub_and_tack"),
            ("to a hub & tack", "hub_and_tack"),
            ("to monitoring well MW8-15", "monitoring_well"),
            ("to a point occupied by monitoring well MW-3", "monitoring_well"),
            ("to a capped iron pin set", "capped_pin"),
            ("to a capped iron rod found", "capped_rod"),
            ("to a capped rebar set", "capped_rod"),
            ("to a TxDOT Type I concrete monument found", "txdot_monument"),
            ("to a TxDOT concrete monument", "txdot_monument"),
        ],
        ids=[
            "pk_nail_set",
            "pk_nail_pavement",
            "pk_nail_lower",
            "hub_and_tack",
            "hub_ampersand_tack",
            "monitoring_well_id",
            "monitoring_well_point",
            "capped_iron_pin",
            "capped_iron_rod",
            "capped_rebar",
            "txdot_type_i",
            "txdot_basic",
        ],
    )
    def test_classify_new_monument(self, text, expected_type):
        result = MonumentClassifier.classify_monument(text)
        assert result == expected_type

    def test_existing_monument_types_still_work(self):
        """Ensure existing patterns are not broken."""
        assert MonumentClassifier.classify_monument("iron rod found") == "iron_rod"
        assert MonumentClassifier.classify_monument("iron pin set") == "iron_pin"
        assert MonumentClassifier.classify_monument("concrete monument") == "concrete"
        assert MonumentClassifier.classify_monument("rebar") == "rebar"
        assert MonumentClassifier.classify_monument("railroad spike") == "railroad_spike"
        assert MonumentClassifier.classify_monument("nail in pavement") == "nail"


class TestPrecisionRatio:
    """Test precision_ratio field on ClosureResult."""

    def test_precision_ratio_stored(self):
        result = ClosureResult(
            misclosure_x_ft=0.01,
            misclosure_y_ft=0.01,
            misclosure_ft=0.0141,
            area_sq_ft=7500.0,
            area_acres=0.1722,
            perimeter_ft=350.0,
            closure_passed=True,
            angle_check_passed=True,
            curve_consistency_passed=True,
            precision_ratio=0.0141 / 350.0,
        )
        assert result.precision_ratio is not None
        assert math.isclose(result.precision_ratio, 0.0141 / 350.0, rel_tol=1e-6)

    def test_precision_ratio_defaults_to_none(self):
        result = ClosureResult(
            misclosure_x_ft=0.0,
            misclosure_y_ft=0.0,
            misclosure_ft=0.0,
            area_sq_ft=0.0,
            area_acres=0.0,
            perimeter_ft=0.0,
            closure_passed=True,
            angle_check_passed=True,
            curve_consistency_passed=True,
        )
        assert result.precision_ratio is None

    def test_precision_ratio_rejects_negative(self):
        with pytest.raises(ValidationError):
            ClosureResult(
                misclosure_x_ft=0.0,
                misclosure_y_ft=0.0,
                misclosure_ft=0.0,
                area_sq_ft=0.0,
                area_acres=0.0,
                perimeter_ft=0.0,
                closure_passed=True,
                angle_check_passed=True,
                curve_consistency_passed=True,
                precision_ratio=-0.01,
            )


class TestNonTangentFields:
    """Test non_tangent and radial_bearing fields on DeedCall."""

    def test_non_tangent_defaults_false(self):
        call = DeedCall(
            course=1,
            direction_text="N 45° E",
            distance_ft=100.0,
        )
        assert call.non_tangent is False

    def test_non_tangent_set_true(self):
        call = DeedCall(
            course=1,
            direction_text="N 45° E",
            distance_ft=100.0,
            curve_dir="right",
            radius_ft=356.37,
            delta_deg=41.8,
            non_tangent=True,
            radial_bearing="N 15°22'00\" E",
        )
        assert call.non_tangent is True
        assert call.radial_bearing == "N 15°22'00\" E"

    def test_radial_bearing_defaults_none(self):
        call = DeedCall(
            course=1,
            direction_text="N 45° E",
            distance_ft=100.0,
        )
        assert call.radial_bearing is None

    def test_radial_bearing_without_non_tangent_is_allowed(self):
        """radial_bearing can be set independently for informational purposes."""
        call = DeedCall(
            course=1,
            direction_text="N 45° E",
            distance_ft=100.0,
            radial_bearing="N 15°22' E",
        )
        assert call.radial_bearing == "N 15°22' E"
        assert call.non_tangent is False
