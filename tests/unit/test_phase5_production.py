"""Tests for Phase 5 model additions: DeedClause, SubdivisionReference, natural monuments, spiral curves."""

import pytest
from pydantic import ValidationError

from metesparser.bearing_converter import BearingConverter
from metesparser.call_extractor import CallExtractor
from metesparser.models import (
    DeedCall,
    DeedClause,
    LegalDescription,
    SubdivisionReference,
)


class TestPhase5ModelChanges:
    """Schema constraints and serialization round-trip for Phase 5 models."""

    @pytest.mark.parametrize("monument_type", ["tree", "rock", "natural_feature"])
    def test_monument_type_accepts_natural_monuments(self, monument_type: str) -> None:
        call = DeedCall(
            course=1,
            direction_text="N 45 E",
            bearing_quadrant="N 45 E",
            bearing_azimuth_deg_from_north=45.0,
            distance_ft=100.0,
            monument_type=monument_type,  # type: ignore[arg-type]
        )
        assert call.monument_type == monument_type

    @pytest.mark.parametrize("clause_type", ["reservation", "subject_to", "together_with"])
    def test_deed_clause_accepts_valid_types(self, clause_type: str) -> None:
        clause = DeedClause(clause_type=clause_type, text="Clause text")  # type: ignore[arg-type]
        assert clause.clause_type == clause_type

    def test_deed_clause_rejects_invalid_clause_type(self) -> None:
        with pytest.raises(ValidationError, match="clause_type"):
            DeedClause(clause_type="invalid_type", text="Some clause text")

    def test_deed_clause_forbids_extra_fields(self) -> None:
        with pytest.raises(ValidationError, match="extra_forbidden"):
            DeedClause(
                clause_type="reservation",
                text="Some clause text",
                extra_field="should not be allowed",
            )

    def test_deed_clause_requires_nonempty_text(self) -> None:
        with pytest.raises(ValidationError, match="string_too_short"):
            DeedClause(clause_type="reservation", text="")

    def test_subdivision_reference_forbids_extra_fields(self) -> None:
        with pytest.raises(ValidationError, match="extra_forbidden"):
            SubdivisionReference(lot="12", extra_field="should not be allowed")

    def test_legal_description_phase5_fields_json_roundtrip(self) -> None:
        ld = LegalDescription(
            clauses=[
                DeedClause(clause_type="reservation", text="Reserving a 20-foot easement"),
                DeedClause(clause_type="subject_to", text="Subject to restrictions of record"),
            ],
            subdivision_ref=SubdivisionReference(
                lot="12",
                block="B",
                subdivision_name="Pennbrook Estates",
                plat_book="45",
                plat_page="23",
            ),
            witness_trees=[
                "White Oak 16 in dia bears N 45 E 25 links",
                "Black Gum 10 in dia bears S 30 W 18 links",
            ],
            coordinate_system="New Jersey State Plane NAD83",
            fips_code="2900",
        )
        restored = LegalDescription.model_validate_json(ld.model_dump_json())
        assert restored == ld


class TestDegreeOfCurvature:
    """Tests for degree of curvature parsing."""

    def test_degree_of_curvature_to_radius_5_degrees(self) -> None:
        radius = BearingConverter.degree_of_curvature_to_radius(5.0)
        assert radius == pytest.approx(5729.578 / 5.0, rel=1e-6)

    def test_degree_of_curvature_to_radius_1_degree(self) -> None:
        radius = BearingConverter.degree_of_curvature_to_radius(1.0)
        assert radius == pytest.approx(5729.578 / 1.0, rel=1e-6)

    def test_degree_of_curvature_to_radius_10_degrees(self) -> None:
        radius = BearingConverter.degree_of_curvature_to_radius(10.0)
        assert radius == pytest.approx(5729.578 / 10.0, rel=1e-6)

    def test_degree_of_curvature_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="non-zero"):
            BearingConverter.degree_of_curvature_to_radius(0.0)

    def test_degree_of_curvature_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            BearingConverter.degree_of_curvature_to_radius(-5.0)

    def test_extract_curve_info_degree_of_curve(self) -> None:
        text = (
            "along a curve to the right having a degree of curve of 5°00'00\", "
            "a delta angle of 30°00'00\", an arc length of 600.00 feet"
        )
        info = CallExtractor.extract_curve_info(text)
        assert info.get("direction") == "right"
        assert info.get("radius_ft") == pytest.approx(5729.578 / 5.0, rel=1e-6)

    def test_extract_curve_info_degree_of_curvature_variant(self) -> None:
        text = (
            "along a curve to the left having a degree of curvature of 2°30', "
            "a delta angle of 15°, an arc distance of 200.00 feet"
        )
        info = CallExtractor.extract_curve_info(text)
        assert info.get("direction") == "left"
        assert info.get("radius_ft") == pytest.approx(5729.578 / 2.5, rel=1e-6)
