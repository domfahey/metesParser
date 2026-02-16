"""Tests for Phase 5 Step 10: Pipeline Wiring + Final Verification."""

from __future__ import annotations

from pathlib import Path

from metesparser.csv_builder import CSVBuilder
from metesparser.models import DeedCall, DeedClause, LegalDescription, SubdivisionReference


class TestPipelineWiring:
    """Tests for Phase 5 pipeline integration."""

    def test_legal_description_to_csv_includes_new_metadata(self, tmp_path: Path) -> None:
        """New Phase 5 metadata should appear in the metadata file."""
        ld = LegalDescription(
            calls=[
                DeedCall(course=1, direction_text="N 45° E", distance_ft=100.0),
            ],
            distance_unit="feet",
            clauses=[DeedClause(clause_type="reservation", text="RESERVING mineral rights")],
            subdivision_ref=SubdivisionReference(
                lot="15", block="3", subdivision_name="PENNBROOK ESTATES"
            ),
            witness_trees=["a white oak, 14 in dia, bears N 35° W"],
            coordinate_system="State Plane, Texas South Central Zone",
            fips_code="4204",
        )
        output_path = str(tmp_path / "test_output.csv")
        CSVBuilder.legal_description_to_csv(ld, output_path)

        # Read metadata file
        metadata_path = tmp_path / "test_output.metadata.txt"
        assert metadata_path.exists()
        metadata_content = metadata_path.read_text()
        assert "coordinate_system" in metadata_content
        assert "fips_code" in metadata_content
        assert "4204" in metadata_content
        assert "PENNBROOK ESTATES" in metadata_content
        assert "white oak" in metadata_content
        assert "RESERVING mineral rights" in metadata_content

    def test_csv_schema_still_21_fields(self) -> None:
        """CSV schema must remain at 21 fields."""
        assert len(CSVBuilder.FIELDNAMES) == 21

    def test_metadata_without_new_fields(self, tmp_path: Path) -> None:
        """When new fields are None/empty, metadata file should still be valid."""
        ld = LegalDescription(
            calls=[
                DeedCall(course=1, direction_text="N 45° E", distance_ft=100.0),
            ],
            distance_unit="feet",
        )
        output_path = str(tmp_path / "test_basic.csv")
        CSVBuilder.legal_description_to_csv(ld, output_path)

        metadata_path = tmp_path / "test_basic.metadata.txt"
        assert metadata_path.exists()
        content = metadata_path.read_text()
        # Should not crash, and should not contain "None" as text
        assert "None" not in content
