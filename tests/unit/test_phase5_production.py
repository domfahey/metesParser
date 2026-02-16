"""Tests for Phase 5 model additions: DeedClause, SubdivisionReference, natural monuments, spiral curves."""

import pytest
from pydantic import ValidationError

from metesparser.models import (
    DeedCall,
    DeedClause,
    LegalDescription,
    SubdivisionReference,
)


class TestPhase5ModelChanges:
    """Tests for Phase 5 model additions."""

    # --- MonumentType: natural monument values ---

    def test_monument_type_accepts_tree(self) -> None:
        call = DeedCall(
            course=1,
            direction_text="N 45 E",
            bearing_quadrant="N 45 E",
            bearing_azimuth_deg_from_north=45.0,
            distance_ft=100.0,
            monument_type="tree",
        )
        assert call.monument_type == "tree"

    def test_monument_type_accepts_rock(self) -> None:
        call = DeedCall(
            course=1,
            direction_text="N 45 E",
            bearing_quadrant="N 45 E",
            bearing_azimuth_deg_from_north=45.0,
            distance_ft=100.0,
            monument_type="rock",
        )
        assert call.monument_type == "rock"

    def test_monument_type_accepts_natural_feature(self) -> None:
        call = DeedCall(
            course=1,
            direction_text="N 45 E",
            bearing_quadrant="N 45 E",
            bearing_azimuth_deg_from_north=45.0,
            distance_ft=100.0,
            monument_type="natural_feature",
        )
        assert call.monument_type == "natural_feature"

    # --- CurveType: spiral ---

    def test_curve_type_accepts_spiral(self) -> None:
        call = DeedCall(
            course=1,
            direction_text="along curve",
            distance_ft=50.0,
            curve_dir="left",
            radius_ft=100.0,
            delta_deg=30.0,
            curve_type="spiral",
        )
        assert call.curve_type == "spiral"

    # --- DeedClause ---

    def test_deed_clause_reservation(self) -> None:
        clause = DeedClause(
            clause_type="reservation",
            text="Reserving unto the grantor a 20-foot easement",
        )
        assert clause.clause_type == "reservation"
        assert clause.text == "Reserving unto the grantor a 20-foot easement"

    def test_deed_clause_subject_to(self) -> None:
        clause = DeedClause(
            clause_type="subject_to",
            text="Subject to existing easements of record",
        )
        assert clause.clause_type == "subject_to"
        assert clause.text == "Subject to existing easements of record"

    def test_deed_clause_together_with(self) -> None:
        clause = DeedClause(
            clause_type="together_with",
            text="Together with a right-of-way over Lot 3",
        )
        assert clause.clause_type == "together_with"
        assert clause.text == "Together with a right-of-way over Lot 3"

    def test_deed_clause_rejects_invalid_clause_type(self) -> None:
        with pytest.raises(ValidationError):
            DeedClause(
                clause_type="invalid_type",
                text="Some clause text",
            )

    def test_deed_clause_forbids_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            DeedClause(
                clause_type="reservation",
                text="Some clause text",
                extra_field="should not be allowed",
            )

    def test_deed_clause_requires_nonempty_text(self) -> None:
        with pytest.raises(ValidationError):
            DeedClause(
                clause_type="reservation",
                text="",
            )

    # --- SubdivisionReference ---

    def test_subdivision_reference_full(self) -> None:
        ref = SubdivisionReference(
            lot="12",
            block="B",
            subdivision_name="Pennbrook Estates",
            plat_book="45",
            plat_page="23",
        )
        assert ref.lot == "12"
        assert ref.block == "B"
        assert ref.subdivision_name == "Pennbrook Estates"
        assert ref.plat_book == "45"
        assert ref.plat_page == "23"

    def test_subdivision_reference_partial(self) -> None:
        ref = SubdivisionReference(
            lot="5",
            subdivision_name="Oak Hills",
        )
        assert ref.lot == "5"
        assert ref.block is None
        assert ref.subdivision_name == "Oak Hills"
        assert ref.plat_book is None
        assert ref.plat_page is None

    def test_subdivision_reference_all_none(self) -> None:
        ref = SubdivisionReference()
        assert ref.lot is None
        assert ref.block is None
        assert ref.subdivision_name is None
        assert ref.plat_book is None
        assert ref.plat_page is None

    def test_subdivision_reference_forbids_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            SubdivisionReference(
                lot="12",
                extra_field="should not be allowed",
            )

    # --- LegalDescription new fields ---

    def test_legal_description_clauses_default_empty(self) -> None:
        ld = LegalDescription()
        assert ld.clauses == []

    def test_legal_description_clauses_populated(self) -> None:
        clauses = [
            DeedClause(clause_type="reservation", text="Reserving a 20-foot easement"),
            DeedClause(clause_type="subject_to", text="Subject to restrictions of record"),
        ]
        ld = LegalDescription(clauses=clauses)
        assert len(ld.clauses) == 2
        assert ld.clauses[0].clause_type == "reservation"
        assert ld.clauses[1].clause_type == "subject_to"

    def test_legal_description_subdivision_ref_default_none(self) -> None:
        ld = LegalDescription()
        assert ld.subdivision_ref is None

    def test_legal_description_subdivision_ref_populated(self) -> None:
        ref = SubdivisionReference(lot="7", block="A", subdivision_name="Green Acres")
        ld = LegalDescription(subdivision_ref=ref)
        assert ld.subdivision_ref is not None
        assert ld.subdivision_ref.lot == "7"
        assert ld.subdivision_ref.block == "A"
        assert ld.subdivision_ref.subdivision_name == "Green Acres"

    def test_legal_description_witness_trees_default_empty(self) -> None:
        ld = LegalDescription()
        assert ld.witness_trees == []

    def test_legal_description_witness_trees_populated(self) -> None:
        trees = ["White Oak 16 in dia bears N 45 E 25 links", "Black Gum 10 in dia bears S 30 W 18 links"]
        ld = LegalDescription(witness_trees=trees)
        assert len(ld.witness_trees) == 2
        assert "White Oak" in ld.witness_trees[0]

    def test_legal_description_coordinate_system_default_none(self) -> None:
        ld = LegalDescription()
        assert ld.coordinate_system is None

    def test_legal_description_coordinate_system_populated(self) -> None:
        ld = LegalDescription(coordinate_system="New Jersey State Plane NAD83")
        assert ld.coordinate_system == "New Jersey State Plane NAD83"

    def test_legal_description_fips_code_default_none(self) -> None:
        ld = LegalDescription()
        assert ld.fips_code is None

    def test_legal_description_fips_code_populated(self) -> None:
        ld = LegalDescription(fips_code="2900")
        assert ld.fips_code == "2900"
